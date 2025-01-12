import heapq
import json

from enum import Enum
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from proto.task_message_pb2 import TaskRequest

class TaskStatus(Enum):
    REPLENISHING = 0
    PENDING = 1
    RUNNING = 2
    COMPLETED = 3
    FAILED = 4

@dataclass
class TaskInfo:
    """数据类定义任务信息结构"""
    task_name: str
    model_name: str
    status: TaskStatus = TaskStatus.REPLENISHING
    params: Dict[str, str] = field(default_factory=dict)
    error_message: Optional[str] = None

    def base_info_add(self, new_info: Dict):
        self.task_name = new_info["task_name"]
        self.model_name = new_info["model_name"]
        for key, value in new_info["parameters"].items():
            self.params[key] = value
        
        self.task_id = new_info["task_id"] if "task_id" in new_info else -1
        # self.priority = new_info["priority"] if "priority" in new_info else 0
    
    def params_add(self, new_info: Dict):
        pass
    
    def necessary_info_check(self):
        # TODO: 不同任务下的基本必要信息校验函数
        pass 
    
@dataclass(order=True)
class PrioritizedTask:
    priority: int
    task: TaskInfo = field(compare=False)

@dataclass
class TaskQueue:
    tasks: List[PrioritizedTask] = field(default_factory=list)
    task_map: Dict[str, PrioritizedTask] = field(default_factory=dict)

    def enqueue(self, task: TaskInfo, priority: int) -> None:
        prioritized_task = PrioritizedTask(priority, task)
        heapq.heappush(self.tasks, prioritized_task)
        self.task_map[task.task_name] = prioritized_task

    def dequeue(self) -> Optional[TaskInfo]:
        if not self.tasks:
            return None
        prioritized_task = heapq.heappop(self.tasks)
        self.task_map.pop(prioritized_task.task.task_name)  # 从映射中移除
        return prioritized_task.task

    def get_task_by_name(self, task_name: str) -> Optional[TaskInfo]:
        prioritized_task = self.task_map.get(task_name)
        return prioritized_task.task if prioritized_task else None

    def is_empty(self) -> bool:
        return len(self.tasks) == 0

    def size(self) -> int:
        return len(self.tasks)

    def peek(self) -> Optional[TaskInfo]:
        if not self.tasks:
            return None
        return self.tasks[0].task

def task_enqueue(serialized_data: bytes, task_queue: TaskQueue) -> List[TaskInfo]:
    task_request = TaskRequest()
    task_request.ParseFromString(serialized_data)
    
    for task in task_request.tasks:
        task_queue.enqueue(TaskInfo(
            task_name=task.task_name,
            model_name=task.model_name,
            params=dict(task.params),
            priority=task.priority,
            status=TaskStatus.Name(task.status),
            error_message=task.error_message if task.status == TaskStatus.FAILURE else None
        ), int(task.priority))
    return


class JSONParser():
    def parse(self, data: str):
        return json.loads(data)

    def dynamic_parameter_handling(self, parsed_data, key_to_check):
        if key_to_check in parsed_data:
            if parsed_data[key_to_check] == 'type1':
                return parsed_data.get('param1'), parsed_data.get('param2')
            elif parsed_data[key_to_check] == 'type2':
                return parsed_data.get('param3'), parsed_data.get('param4')

# 示例数据
def create_sample_data():
    # 构造一个 TaskRequest 示例
    task_request = TaskRequest()
    task1 = task_request.tasks.add()
    task1.task_name = "text_generation"
    task1.model_name = "gpt-4"
    task1.priority = 1
    task1.params["input_text"] = "Write a story about a brave knight"
    task1.params["max_length"] = "200"
    task1.status = TaskStatus.SUCCESS

    # 添加第二个任务
    task2 = task_request.tasks.add()
    task2.task_name = "image_captioning"
    task2.model_name = "blip-2"
    task2.priority = 2
    task2.params["image_path"] = "/path/to/image.jpg"
    task2.params["language"] = "en"
    task2.status = TaskStatus.FAILURE
    task2.error_message = "Model not found"

    # 序列化为二进制数据
    return task_request.SerializeToString()

def test():
    # 创建示例序列化数据
    serialized_data = create_sample_data()
    task_queue = TaskQueue()
    # 解析序列化数据
    task_enqueue(serialized_data, task_queue)

    print("Parsed Task Data:")
    for i in range(task_queue.size()):
        print(task_queue.dequeue())

if __name__ == "__main__":
    test()
