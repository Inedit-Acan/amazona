import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.ids import new_id


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_id)
    actor: str
    action: str
    resource: str
    before: dict | None = None
    after: dict | None = None
    correlation_id: str
    timestamp: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


class AuditService:
    """Append-only audit trail. There is intentionally no way to update or
    delete an entry: the full simulated workflow must be reconstructable
    from what was recorded."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def record(
        self,
        *,
        actor: str,
        action: str,
        resource: str,
        before: dict | None,
        after: dict | None,
        correlation_id: str,
    ) -> AuditEntry:
        entry = AuditEntry(
            actor=actor,
            action=action,
            resource=resource,
            before=before,
            after=after,
            correlation_id=correlation_id,
        )
        self._entries.append(entry)
        return entry

    def list_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.correlation_id == correlation_id]

    def list_all(self) -> list[AuditEntry]:
        return list(self._entries)
