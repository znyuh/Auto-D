import openai
import logging
import json

from multiprocessing import Queue

from utils.prompt_space import RequirementAnalysisStatus, PromptSpace

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RequirementUnderstandingLayer:
    def __init__(self, api_key: str, llm_server_url: str, llm_server_config: dict, ru_config: dict):
        # Initialize any necessary components or data structures
        self.llm_client = openai.OpenAI(base_url=llm_server_url, api_key=api_key)
        self.input_queue = Queue(maxsize=20)  # Queue for receiving user input
        self.prompt_space = PromptSpace()
        self.llm_config = llm_server_config
        self.ru_config = ru_config
        self.dialogs = []

    def receive_user_input(self, user_input: str):

        if not self.input_queue.full():
            self.input_queue.put(user_input)
        else:
            print("Input queue is full. Please try again later.")

    def process_queue(self):
        while True:
            if not self.input_queue.empty():
                user_input = self.input_queue.get()
                # user_input = self.process_input(user_input) # 输入预处理
                processed_data = self.send_to_llm(user_input)
                print(f"Processed Data: {processed_data}")
                # Here you can add logic to handle the processed data, e.g., store it or send it to another component

    def send_to_llm(self, user_input: str) -> dict:
        retry_times = self.ru_config.get('retry_times', 5)
        while retry_times > 0:
            except_info = None
            format_error = False
            try:
                if except_info is not None:
                    self.dialogs.append({"role": "user", "content": except_info})
                else:
                    self.dialogs.append({"role": "user", "content": user_input})
                response = self.llm_client.chat.completions.create(
                    model=self.llm_config.get('model_name', 'Qwen/QVQ-72B-Preview'),
                    messages=self.dialogs,
                    max_tokens=self.llm_config.get('max_tokens', 1024),
                    temperature=self.llm_config.get('temperature', 0.7),
                    top_p=self.llm_config.get('top_p', 0.7),
                    top_k=self.llm_config.get('top_k', 50),
                    frequency_penalty=self.llm_config.get('frequency_penalty', 0.5),
                    n=self.llm_config.get('n', 1),
                    stop=self.llm_config.get('stop', ['null']),
                    stream=self.llm_config.get('stream', False)
                )
                formated_response =  response.choices[0].message.content.strip()
            except Exception as e:
                print(f"Error communicating with LLM: {e}")
                continue
            try:
                response_data = json.loads(formated_response)
                required_keys = self.ru_config.get('required_keys', ["intent", "details", "clarifications"])
                missing_keys = [key for key in required_keys if key not in response_data]
                if missing_keys:
                    except_info = self.prompt_space.get_prompts("exception_handling_format").get("Missing_Key_In_Parsing_Info").format(missing_keys)
                    retry_times -= 1
                else:
                    break
            except json.JSONDecodeError as e:
                logger.error(f"Response format error: {e}")
                except_info = self.prompt_space.get_prompts("exception_handling_format").get("response_format_error").format(e)
                retry_times -= 1
                
        return formated_response
