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
from utils.parse_proto import TaskQueue, TaskInfo, TaskCommand, TaskFeedback, TaskStatus, CommandType
from proto.task_message_pb2 import TaskRequest
from utils.prompt_space import RequirementAnalysisStatus, PromptSpace
from layer.ru import RequirementUnderstandingLayer

URL = "https://api.siliconflow.cn/v1/chat/completions"

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def user_interface(uri: str, llm_config: str):
    # uri = "ws://your_websocket_server_url"  # Replace with your WebSocket server URL
    # uri = "ws://localhost:8765"  # Local WebSocket server URL for inter-process communication

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

        dialogs[0].append({"role": "System", "content": prompt_content})
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
            
            retry_times = 5
            
            request_msg = user_mq.get()

            logger.info(f"Received message: {request_msg}")

            if "END_OF_CONVERSATION" in request_msg:
                logging.info("End of conversation detected. Exiting loop.")
                break

            message = chat_template.format(request_msg)
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
            while retry_times > 0:
                except_info = None
                format_error = False
                try:
                    response_data = json.loads(response)
                    required_keys = ["intent", "details", "clarifications"]
                    missing_keys = [key for key in required_keys if key not in response_data]
                    if missing_keys:
                        except_info = prompt_space.get_prompts("exception_handling_format").get("Missing_Key_In_Parsing_Info").format(missing_keys)
                        format_error = True
                except json.JSONDecodeError as e:
                    logger.error(f"Response format error: {e}")
                    except_info = prompt_space.get_prompts("exception_handling_format").get("response_format_error").format(e)
                    format_error = True

                if format_error:
                    retry_times -= 1
                    dialogs[0].append({"role": "System", "content": except_info})
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

            if "Create" in response_data["intent"]:
                task_request = TaskRequest()
                task = task_request.tasks.add()
                task.base_info_add(response_data["details"])
                task.necessary_info_check()
            elif "Supply" in response_data["intent"]:
                # TODO: 功能完善：补充任务功能
                task_info = task_queue.get_task_by_name(response_data["details"]["task_name"])
                if task_info is not None:
                    if task_info.status == TaskStatus.REPLENISHING or task_info.status == TaskStatus.FAILED:
                        task_info.base_info_update(response_data["details"])
                        task_info.necessary_info_check()
                    else:
                        logger.info("Task is not in replenishing or failed status, no need to supply.")
                else:
                    # TODO: 异常处理：补充任务无法检索的情况
                    except_info = prompt_space.get_prompts("exception_handling_format").get("task_not_found").format(response_data["details"]["task_name"])
                    cprint(f"[Supply] Task not found: {response_data['details']['task_name']}. Please check the task name.") 
                    logger.error(f"[Supply] Task not found: {response_data['details']['task_name']}")

            elif "Interrupt" in response_data["intent"]:
                task_info = task_queue.get_task_by_name(response_data["details"]["task_name"])
                if task_info is not None and task_info.status == TaskStatus.RUNNING:

                    task_command = TaskCommand()
                    task_command.command_filling(CommandType.STOP, response_data["details"])
                elif task_info is not None:
                    except_info = prompt_space.get_prompts("exception_handling_format").get("task_not_found").format(response_data["details"]["task_name"])
                    cprint(f"[Interrupt] Task not found: {response_data['details']['task_name']}. Please check the task name.") 
                    logger.error(f"[Interrupt] Task not found: {response_data['details']['task_name']}")
                else:
                    cprint(f"[Interrupt] Task not Running: {response_data['details']['task_name']}. Please check the task status.") 
                    logger.warning(f"[Interrupt] Task not Running: {response_data['details']['task_name']}. Please check the task status.")

            elif "Query" in response_data["intent"]:
                task_info = task_queue.get_task_by_name(response_data["details"]["task_name"])
                if task_info is not None:
                    task_info.info_query()
                else:
                    except_info = prompt_space.get_prompts("exception_handling_format").get("task_not_found").format(response_data["details"]["task_name"])
                    cprint(f"[Query] Task not found: {response_data['details']['task_name']}. Please check the task name.") 
                    logger.error(f"[Query] Task not found: {response_data['details']['task_name']}")
            else:
                # TODO: 异常处理：其他命令处理
                except_info = prompt_space.get_prompts("exception_handling_format").get("Error_Intent").format(response_data["intent"])
                cprint(f"[Error] Unknown intent: {response_data['intent']}. Please check the intent.") 
                logger.error(f"[Error] Unknown intent: {response_data['intent']}")

            # TODO: 给用户输入进行反馈

            # TODO: 保留正确的对话内容，进行下一次对话
            dialogs[0].append({"role": "assisstant", "content": response})



def main():
    pass

# if __name__ == "__main__":
#     fire.Fire(main)