from app.core.errors import NotFoundError
from app.tasks.schemas import Task, TaskStatus

_RUNNABLE_STATUSES = {TaskStatus.PENDING, TaskStatus.QUEUED}


class TaskService:
    """In-memory task dependency graph for a running orchestration.

    Persistence to the `tasks`/`task_dependencies` tables happens at the
    orchestrator boundary; this service owns only the deterministic DAG
    logic used to decide what can run next.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def create_task(
        self,
        *,
        project_id: str,
        name: str,
        capability: str,
        input: dict | None = None,
        depends_on: list[str] | None = None,
    ) -> Task:
        task = Task(
            project_id=project_id,
            name=name,
            capability=capability,
            input=input or {},
            depends_on=list(depends_on or []),
        )
        self._tasks[task.id] = task
        return task

    def add_dependency(self, *, parent_id: str, child_id: str) -> None:
        child = self.get_task(child_id)
        self.get_task(parent_id)  # validate parent exists
        if parent_id not in child.depends_on:
            child.depends_on.append(parent_id)

    def get_task(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"task {task_id} not found")
        return task

    def mark_running(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        task.status = TaskStatus.RUNNING
        return task

    def mark_completed(self, task_id: str, output: dict) -> Task:
        task = self.get_task(task_id)
        task.status = TaskStatus.COMPLETED
        task.output = output
        return task

    def mark_failed(self, task_id: str, error: str) -> Task:
        task = self.get_task(task_id)
        task.status = TaskStatus.FAILED
        task.error = error
        return task

    def get_runnable_tasks(self, project_id: str) -> list[Task]:
        return [
            task
            for task in self._tasks.values()
            if task.project_id == project_id
            and task.status in _RUNNABLE_STATUSES
            and self._dependencies_met(task)
        ]

    def _dependencies_met(self, task: Task) -> bool:
        return all(self.get_task(dep_id).status == TaskStatus.COMPLETED for dep_id in task.depends_on)
