import heapq

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from proto.task_message_pb2 import TaskRequest, Task, TaskStatus

@dataclass
class TaskInfo:
    """数据类定义任务信息结构"""
    task_name: str
    model_name: str
    priority: int
    params: Dict[str, str] = field(default_factory=dict)
    status: str = "PENDING"
    error_message: Optional[str] = None

@dataclass(order=True)
class PrioritizedTask:
    priority: int
    task: TaskInfo = field(compare=False)

@dataclass
class TaskQueue:
    tasks: List[PrioritizedTask] = field(default_factory=list)

    def enqueue(self, task: TaskInfo, priority: int) -> None:
        heapq.heappush(self.tasks, PrioritizedTask(priority, task))

    def dequeue(self) -> Optional[TaskInfo]:
        if not self.tasks:
            return None
        return heapq.heappop(self.tasks).task

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
