import pytest

from app.tasks.schemas import TaskStatus
from app.tasks.service import TaskService


@pytest.fixture()
def service() -> TaskService:
    return TaskService()


def test_task_with_no_dependencies_is_immediately_runnable(service: TaskService):
    task = service.create_task(project_id="proj-1", name="Product validation", capability="market_validation")

    runnable = service.get_runnable_tasks("proj-1")

    assert [t.id for t in runnable] == [task.id]


def test_task_with_unmet_dependency_is_not_runnable(service: TaskService):
    parent = service.create_task(project_id="proj-1", name="Product validation", capability="market_validation")
    child = service.create_task(project_id="proj-1", name="Finance validation", capability="financial_validation")
    service.add_dependency(parent_id=parent.id, child_id=child.id)

    runnable_ids = {t.id for t in service.get_runnable_tasks("proj-1")}

    assert parent.id in runnable_ids
    assert child.id not in runnable_ids


def test_completing_dependency_unlocks_child_task(service: TaskService):
    parent = service.create_task(project_id="proj-1", name="Product validation", capability="market_validation")
    child = service.create_task(project_id="proj-1", name="Finance validation", capability="financial_validation")
    service.add_dependency(parent_id=parent.id, child_id=child.id)

    service.mark_running(parent.id)
    service.mark_completed(parent.id, output={"score": 0.8})

    runnable_ids = {t.id for t in service.get_runnable_tasks("proj-1")}
    assert child.id in runnable_ids

    completed_parent = service.get_task(parent.id)
    assert completed_parent.status == TaskStatus.COMPLETED
    assert completed_parent.output == {"score": 0.8}


def test_mark_failed_records_error_and_status(service: TaskService):
    task = service.create_task(project_id="proj-1", name="Legal validation", capability="legal_validation")

    service.mark_running(task.id)
    service.mark_failed(task.id, error="provider timeout")

    failed = service.get_task(task.id)
    assert failed.status == TaskStatus.FAILED
    assert failed.error == "provider timeout"
    assert failed.id not in {t.id for t in service.get_runnable_tasks("proj-1")}


def test_mark_failed_with_no_max_retries_fails_immediately(service: TaskService):
    task = service.create_task(project_id="proj-1", name="Legal validation", capability="legal_validation")
    service.mark_running(task.id)

    result = service.mark_failed(task.id, error="boom")

    assert result.status == TaskStatus.FAILED
    assert result.retry_count == 0


def test_mark_failed_retries_up_to_the_bound_then_fails(service: TaskService):
    task = service.create_task(project_id="proj-1", name="Legal validation", capability="legal_validation")

    service.mark_running(task.id)
    first = service.mark_failed(task.id, error="boom-1", max_retries=2)
    assert first.status == TaskStatus.PENDING
    assert first.retry_count == 1
    assert task.id in {t.id for t in service.get_runnable_tasks("proj-1")}

    service.mark_running(task.id)
    second = service.mark_failed(task.id, error="boom-2", max_retries=2)
    assert second.status == TaskStatus.PENDING
    assert second.retry_count == 2

    service.mark_running(task.id)
    third = service.mark_failed(task.id, error="boom-3", max_retries=2)
    assert third.status == TaskStatus.FAILED
    assert third.retry_count == 2
    assert task.id not in {t.id for t in service.get_runnable_tasks("proj-1")}


def test_a_task_with_multiple_dependencies_requires_all_to_complete(service: TaskService):
    supplier = service.create_task(project_id="proj-1", name="Supplier sourcing", capability="supplier_sourcing")
    legal = service.create_task(project_id="proj-1", name="Legal validation", capability="legal_validation")
    decision = service.create_task(project_id="proj-1", name="Decision synthesis", capability="decision_synthesis")
    service.add_dependency(parent_id=supplier.id, child_id=decision.id)
    service.add_dependency(parent_id=legal.id, child_id=decision.id)

    service.mark_running(supplier.id)
    service.mark_completed(supplier.id, output={})

    assert decision.id not in {t.id for t in service.get_runnable_tasks("proj-1")}

    service.mark_running(legal.id)
    service.mark_completed(legal.id, output={})

    assert decision.id in {t.id for t in service.get_runnable_tasks("proj-1")}


def test_get_runnable_tasks_only_returns_tasks_for_the_given_project(service: TaskService):
    service.create_task(project_id="proj-1", name="A", capability="market_validation")
    other = service.create_task(project_id="proj-2", name="B", capability="market_validation")

    runnable_ids = {t.id for t in service.get_runnable_tasks("proj-1")}

    assert other.id not in runnable_ids
