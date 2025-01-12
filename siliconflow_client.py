import os
import json
import time
import yaml
import copy
import asyncio
import logging
import websockets

import openai
from enum import Enum
from multiprocessing import Process, Queue
from typing import List, Optional, Any

from utils.visualizer_tool import cprint, ctext
from utils.parse_proto import TaskQueue, TaskInfo,TaskStatus
from proto.task_message_pb2 import TaskRequest

URL = "https://api.siliconflow.cn/v1/chat/completions"

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RequirementAnalysisStatus(Enum):
    NO_INFO = 0
    INFO_INCOMPLETE = 1
    INFO_COMPLETE = 2
    
class PromptSpace:
    def __init__(self):
        self.prompts = {
            "Prologue": {
                "role_play": """
You are an intelligent assistant specializing in analyzing user text input to identify and process task-related intents. 
Your primary responsibility is to deeply analyze user input, understand their true intent, and map it to one of the following supported intent categories:
1. Create a new task request(Create_Tasks): The user wants to initiate a new task. You need to extract the task name, the associated model name, and all necessary parameters.
2. Supplement an existing task request(Supplement_Tasks): The user wants to add or update parameters for an existing task. You need to identify the task and correctly add or update the relevant parameters.
3. Interrupt a specific task(Interrupt_Tasks): The user wants to stop an ongoing task. You need to identify the task ID and generate the corresponding interruption request.
4. Query task status(Query_Tasks): The user wants to know the status of a specific task or all tasks. You need to extract the task ID (if provided) and return the relevant status information.
""",
                "role_cot": """
To improve your accuracy and reliability, use the following step-by-step reasoning process when analyzing user input:
1. Read the user input carefully: Analyze the text for keywords or phrases that indicate the user's intent.
2. Determine the primary intent: Identify the category that best matches the user's request. If multiple intents are implied, prioritize the primary action requested.
3. Extract task-related details:
    3.1 For new tasks, extract the task name, model name, and any additional parameters provided.
    3.2 For existing tasks, identify the task ID and any parameters to be updated or added.
    3.3 For interrupting a task, ensure the task ID is explicitly extracted.
    3.4 For querying task status, look for the task ID or determine if the query is for all tasks.
4. Verify completeness: Check if all required fields for the identified intent are present in the user input. If any critical detail is missing, formulate a clarifying question to ask the user.
5. Generate the structured output: Organize the parsed information into the predefined JSON structure. If the user input is ambiguous, include a flag in the output to indicate incomplete information.
6. If the user input lacks required details, such as task ID or parameters, clearly specify what information is missing and why it's needed.
""",
                "role_rule": """
Here are some rules for you to follow:
1. Perform semantic understanding of the user's input to accurately classify it into one of the above intent categories.
2. Extract the necessary task details, including but not limited to: task name, model name, parameter information, and task ID.
3. Ensure responses are clear and precise, fulfilling the user's requirements.
4. If the user input is incomplete or ambiguous, proactively ask clarifying questions to gather more details.
5. You should structure the analyzed result as follows, using the JSON format:
{
  "intent": "<Intent Category>",  // e.g., "Create_Tasks", "Supplement_Tasks", "Interrupt_Tasks", "Query_Tasks"
  "details": {
    "task_name": "<Task Name>",  // e.g., "Evaluate_model", "Finetune_model", "Infer_model"
    "model_name": "<Model Name>",  // e.g., yolov5s, yolov8n, ... that models should be supported by the system
    "parameters": { "<Parameter Key>": "<Parameter Value>" },  // Variable-length parameters as needed
    "task_id": "<Task ID>"  // Mandatory for supplementing or interrupting a task
  },
  "clarifications": "<Any clarifications to be requested>"
}
""",
            },

            "Requirement_Analysis": {
                RequirementAnalysisStatus.NO_INFO: "",
                RequirementAnalysisStatus.INFO_INCOMPLETE: "",
                RequirementAnalysisStatus.INFO_COMPLETE: ""
            },
            "chat_format":{
                "chat_before": "",
                "response_format_error": "",
                "backlink": ""
            }
        }

    def get_prompts(self, category: str):
        return self.prompts.get(category)



def user_interface(uri: str, llm_config: str):
    # uri = "ws://your_websocket_server_url"  # Replace with your WebSocket server URL
    # uri = "ws://localhost:8765"  # Local WebSocket server URL for inter-process communication
    # Load LLM configuration from the YAML file directly into a dictionary

    user_mq = Queue(maxsize=20)
    dialogs: List = [
        []
    ]
    task_queue = TaskQueue()
    prompt_space = PromptSpace()
    
    chat_template = "{}"
    
    with open(llm_config, 'r') as file:
        llm_params = yaml.safe_load(file)
        
    async def websocket_listener():
        async with websockets.connect(uri) as websocket:
            while True:
                message = await websocket.recv()
                user_mq.put(message)

    asyncio.run(websocket_listener())

    # llm client
    logger.info("Initializing OpenAI client.")
    client = openai.OpenAI(base_url=URL, 
                           api_key=os.environ.get('SILICONCLOUD_API_KEY_AML'))
    # prologue
    prompts_plg = prompt_space.get_prompts("Prologue")
    for prompt_effect, prompt_content in prompts_plg.items():
        logger.info(f"Prologue phase: {prompt_effect}\n")

        dialogs[0].append({"role": "Narrator", "content": prompt_content})
        response = client.chat.completions.create(
            model=llm_params.get('model_name', 'Qwen/QVQ-72B-Preview'),
            messages=dialogs[0],
            max_tokens=llm_params.get('max_tokens', 1024),
            temperature=llm_params.get('temperature', 0.7),
            top_p=llm_params.get('top_p', 0.7),
            top_k=llm_params.get('top_k', 50),
            frequency_penalty=llm_params.get('frequency_penalty', 0.5),
            n=llm_params.get('n', 1),
            stop=llm_params.get('stop', ['null']),
            stream=llm_params.get('stream', False)
        )
        dialogs[0].append({"role": "assisstant", "content": response})
        logger.info(f"Prologue response: {response}")
        
    prologue_len = len(dialogs[0])
    prologue_context = copy.deepcopy(dialogs[0])

    while True:
        if not user_mq.empty():
            request_msg = user_mq.get()

            logger.info(f"Received message: {request_msg}")

            if "END_OF_CONVERSATION" in request_msg:
                logging.info("End of conversation detected. Exiting loop.")
                break
            # Add your message processing logic here
            # 主要是格式化输出，再加一点小的prompt trick
            message = chat_template.format(request_msg) # TODO:  wait to insert into template
            dialogs[0].append({"role": "user", "content": message})

            response = client.chat.completions.create(
                model=llm_params.get('model_name', 'default-model'),
                messages=dialogs[0],
                max_tokens=llm_params.get('max_tokens', 1024),
                temperature=llm_params.get('temperature', 0.7),
                top_p=llm_params.get('top_p', 0.7),
                top_k=llm_params.get('top_k', 50),
                frequency_penalty=llm_params.get('frequency_penalty', 0.5),
                n=llm_params.get('n', 1),
                stop=llm_params.get('stop', ['null']),
                stream=llm_params.get('stream', False)
            )
            # 判断回答是否是规范化的，不是则要求重新回答
            try:
                # TODO: 对大模型的回答进行解析
                response_data = json.loads(response)
                if not all(key in response_data for key in ["intent", "details", "clarifications"]):
                    raise ValueError("Response JSON does not contain all required keys.")
                if not all(key in response_data["details"] for key in ["task_name", "model_name", "parameters", "task_id"]):
                    raise ValueError("Response JSON 'details' does not contain all required keys.")
            except (json.JSONDecodeError, ValueError) as e:
                # TODO: 异常处理：大模型回答格式错误处理
                logger.error(f"Response format error: {e}")
                # Optionally, you can request a re-evaluation or handle the error as needed
                continue
            
            if "Create" in response_data["intent"]:
                # 填写任务需求单
                is_completed = False
                task_request = TaskRequest()
                task = task_request.tasks.add()
                task.base_info_add(response_data["details"])
                
                task.necessary_info_check()
            elif "Supplement" in response_data["intent"]:
                # TODO: 功能完善：补充任务功能
                task_info = task_queue.get_task_by_name(response_data["details"]["task_name"])
                if task_info is not None and task_info.status == TaskStatus.REPLENISHING:
                    task_info.params[response_data["details"]["parameter_name"]] = response_data["details"]["parameter_value"]
                elif task_info is not None and task_info.status == TaskStatus.FAILED:
                    task_info.status = TaskStatus.REPLENISHING
                else:
                    # TODO: 异常处理：补充任务无法检索的情况
                    logger.error(f"Task not found: {response_data['details']['task_name']}")
                task.necessary_info_check()
            elif "Interrupt" in response_data["intent"]:
                # TODO: 功能补充：中断任务功能
                pass
            elif "Query" in response_data["intent"]:
                # TODO: 功能补充：查询任务功能
                pass
            else:
                # TODO: 异常处理：其他命令处理
                logger.info(f"Unknown intent: {response_data['intent']}")

            # TODO: 给用户输入进行反馈

            # TODO: 保留正确的对话内容，进行下一次对话
            dialogs[0].append({"role": "assisstant", "content": response})

def main():
    pass

# if __name__ == "__main__":
#     fire.Fire(main)