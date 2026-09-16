from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog
from app.db.models.memory_record import MemoryRecord


class MemoryService:
    """Shared, durable memory scoped by entity (e.g. a product or an
    objective) so agents/CEO don't repeat work across separate runs on the
    same entity. Distinct from `tasks`/`decision_evidence`, which are the
    execution log of one run: this is "what we currently know" about an
    entity, and the latest write always wins per (scope, scope_id, key).
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def remember(self, *, scope: str, scope_id: str, key: str, value: dict, correlation_id: str) -> MemoryRecord:
        existing = (
            self._db.query(MemoryRecord)
            .filter_by(scope=scope, scope_id=scope_id, key=key)
            .one_or_none()
        )
        before = dict(existing.value) if existing else None

        if existing is not None:
            existing.value = value
            record = existing
        else:
            record = MemoryRecord(scope=scope, scope_id=scope_id, key=key, value=value)
            self._db.add(record)

        self._db.flush()
        self._db.add(
            AuditLog(
                actor="memory",
                action="memory.remember",
                resource=f"memory:{scope}:{scope_id}:{key}",
                before=before,
                after=value,
                correlation_id=correlation_id,
            )
        )
        return record

    def recall(self, *, scope: str, scope_id: str, key: str) -> MemoryRecord | None:
        return self._db.query(MemoryRecord).filter_by(scope=scope, scope_id=scope_id, key=key).one_or_none()

    def recall_all(self, *, scope: str, scope_id: str) -> list[MemoryRecord]:
        return self._db.query(MemoryRecord).filter_by(scope=scope, scope_id=scope_id).all()
