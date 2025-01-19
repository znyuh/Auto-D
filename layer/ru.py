import openai
import logging
import json
import sqlite3
import os
import copy
import spacy

from typing import List, Dict
from multiprocessing import Queue
from utils.prompt_space import RequirementAnalysisStatus, PromptSpace

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RequirementUnderstandingLayer:
    def __init__(self, api_key: str, llm_server_url: str, llm_server_config: dict, ru_config: dict):
        # Initialize any necessary components or data structures
        self.llm_client = openai.OpenAI(base_url=llm_server_url, api_key=api_key)
        self.input_queue = Queue(maxsize=20)
        self.prompt_space = PromptSpace()
        self.llm_config = llm_server_config
        self.ru_config = ru_config
        self.prologue_info: List = []
        self.dialogs: List = []
        self.tdd: List = []
        self.db_connection = self.connect_to_db()
        self.ru_prerequisites()
        # self.nlp = spacy.load("en_core_web_sm")

    def ru_prerequisites(self):
        """
        Set up several specialized roles in advance to solve problems.
        """
        prompts_plg = self.prompt_space.rul_prompt.get("Prologue")
        num_dialogs = 0
        for prologue_phase, prologue_phase_content in prompts_plg.items():
            self.dialogs.append([])
            for prompt_effect, prompt_content in prologue_phase_content.items():
                logger.info(f"Prologue_rul phase: {prompt_effect}\n")
                self.dialogs[num_dialogs].append({"role": "System", "content": prompt_content})
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
                self.dialogs[num_dialogs].append({"role": "assisstant", "content": response.choices[0].message.content.strip()})
            self.prologue_info.append([self.dialogs[num_dialogs], copy.deepcopy(self.dialogs[num_dialogs])])
            num_dialogs += 1
    
    def connect_to_db(self):
        db_path = os.path.join('database', 'knowledge_base.db')
        conn = sqlite3.connect(db_path)
        self.initialize_db(conn)
        return conn

    def initialize_db(self, conn):
        """TODO: 初始化是否必要？初始化内容的格式以及默认值？
        Initialize the database with necessary tables.
        """
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT NOT NULL,
                details TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_input TEXT NOT NULL,
                llm_response TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    def load_knowledge_base(self):
        """TODO: 该函数的定位？
        Load initial data into the knowledge base.
        """
        cursor = self.db_connection.cursor()
        # Example data insertion
        cursor.execute("INSERT INTO tasks (task, details) VALUES (?, ?)", ("data analysis", "Use Python and pandas for data analysis."))
        cursor.execute("INSERT INTO tasks (task, details) VALUES (?, ?)", ("web development", "Use React and Node.js for web development."))
        self.db_connection.commit()

    def query_knowledge_base(self, user_input: str, dialogs_id: int):
        """TODO: 待完善：
        1. 使用更高级的逻辑查询知识库（是否启用大模型）
        2. 使用spacy进行关键词提取（确认spacy库的作用，以及当前代码的作用）
        3. 该函数功能目前定位为从知识库中查询与用户输入相关的历史任务信息，用来给大模型做参考
        Query the knowledge base for relevant information using more advanced logic.
        """
        
        # doc = self.nlp(user_input)
        # keywords = [token.text for token in doc if token.is_alpha and not token.is_stop]
        # cursor = self.db_connection.cursor()
        # query = "SELECT * FROM tasks WHERE " + " OR ".join(["task LIKE ?"] * len(keywords))
        # cursor.execute(query, tuple('%' + keyword + '%' for keyword in keywords))
        # return cursor.fetchall()
        return None
    
    def enhance_task_description(self, llm_output: str, knowledge_data: list) -> str:
        """
        Enhance the task description using knowledge base data.
        """
        enhanced_description = llm_output
        for entry in knowledge_data:
            enhanced_description += f"\nRelated Task: {entry[1]}, Details: {entry[2]}"
        return enhanced_description
    
    def process_queue(self):
        
        while True:
            if not self.input_queue.empty():
                user_input = self.input_queue.get()
                processed_data = self.send_to_llm(user_input, 0)
                knowledge_data = self.query_knowledge_base(user_input, 1)
                if knowledge_data is not None:
                    processed_data = self.enhance_task_description(processed_data, knowledge_data)
                
                self.log_interaction(user_input, processed_data)
                self.tdd.append(self.create_tdd(processed_data, knowledge_data))


    def create_tdd(self, llm_output: str, knowledge_data: list) -> dict:
        """TODO: 待完善：1. tdd的格式以及内容需要再次确认，2. 将tdd每个完整任务信息保存到数据库
        Create a Task Description Document (TDD) using the processed data and knowledge base information.
        """
        tdd = {
            "intent": llm_output.get("intent", ""),
            "details": llm_output.get("details", ""),
            "related_tasks": [entry[1] for entry in knowledge_data],
            "clarifications": llm_output.get("clarifications", "")
        }
        print(f"Task Description Document: {tdd}")
        return tdd

    def get_tdd(self) -> dict:
        """TODO: 该函数的功能目前定位不清晰，还需要确认如何修改或者删除
        Get the current Task Description Document (TDD) in memory.
        """
        return self.tdd

    def send_to_llm(self, user_input: str, dialogs_id: int) -> dict:
        retry_times = self.ru_config.get('retry_times', 5)
        while retry_times > 0:
            except_info = None
            try:
                if except_info is not None:
                    self.dialogs[dialogs_id].append({"role": "user", "content": except_info})
                else:
                    self.dialogs[dialogs_id].append({"role": "user", "content": user_input})
                response = self.llm_client.chat.completions.create(
                    model=self.llm_config.get('model_name', 'Qwen/QVQ-72B-Preview'),
                    messages=self.dialogs[dialogs_id],
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
                    return response_data
            except json.JSONDecodeError as e:
                logger.error(f"Response format error: {e}")
                except_info = self.prompt_space.get_prompts("exception_handling_format").get("response_format_error").format(e)
                retry_times -= 1
                
        # TODO: 需要给用户反馈当前输入失败的情况
        
        return {}

    def log_interaction(self, user_input: str, llm_response: str):
        """
        Log the user interaction and LLM response to the database.
        """
        cursor = self.db_connection.cursor()
        cursor.execute("INSERT INTO interactions (user_input, llm_response) VALUES (?, ?)", (user_input, llm_response))
        self.db_connection.commit()
        
    def log_task_info(self, task_info: dict):
        """
        Log the task information to the database.
        """
        cursor = self.db_connection.cursor()
        cursor.execute("INSERT INTO tasks (task, details) VALUES (?, ?)", (task_info["task"], task_info["details"]))
        self.db_connection.commit()
