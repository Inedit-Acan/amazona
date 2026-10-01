from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.db.models.audit import AuditLog
from app.db.models.pipeline_kill_switch import PipelineKillSwitch

DEFAULT_KILL_SWITCH_NAME = "pipeline-default"
KILL_SWITCH_ACTOR = "pipeline-kill-switch"


@dataclass(frozen=True)
class KillSwitchState:
    """What a read of the kill switch says. Never a database row: a read must not
    create one. `persisted` is False when no operator has ever touched the switch,
    which is the default state (enabled) and not a missing answer."""

    enabled: bool = True
    reason: str | None = None
    updated_by: str | None = None
    persisted: bool = False


class PipelineKillSwitchService:
    """A single canonical PipelineKillSwitch row gating whether
    PipelineOrchestrator may start a new run. Enabled by default — a missing row
    means "no operator has ever disabled it", not "disabled".

    Reading and writing are separate on purpose: `is_enabled()` and `get_state()`
    never write (a GET must not insert), and only `enable()`/`disable()` create the
    row, the first time an operator uses them (same canonical-row idea as
    BudgetLedgerService's Budget row, but without creating it on read)."""

    def __init__(self, db: Session, *, name: str = DEFAULT_KILL_SWITCH_NAME) -> None:
        self._db = db
        self._name = name

    def is_enabled(self) -> bool:
        row = self._find()
        return True if row is None else row.enabled

    def get_state(self) -> KillSwitchState:
        row = self._find()
        if row is None:
            return KillSwitchState()
        return KillSwitchState(enabled=row.enabled, reason=row.reason, updated_by=row.updated_by, persisted=True)

    def disable(
        self, *, reason: str, actor: str, correlation_id: str, identity: Actor | None = None
    ) -> PipelineKillSwitch:
        return self._set_enabled(False, reason=reason, actor=actor, correlation_id=correlation_id, identity=identity)

    def enable(self, *, actor: str, correlation_id: str, identity: Actor | None = None) -> PipelineKillSwitch:
        return self._set_enabled(True, reason=None, actor=actor, correlation_id=correlation_id, identity=identity)

    def _set_enabled(
        self,
        enabled: bool,
        *,
        reason: str | None,
        actor: str,
        correlation_id: str,
        identity: Actor | None = None,
    ) -> PipelineKillSwitch:
        switch = self._get_or_create()
        before = {"enabled": switch.enabled, "reason": switch.reason}
        switch.enabled = enabled
        switch.reason = reason
        switch.updated_by = actor
        self._db.add(
            AuditLog(
                actor=actor,
                actor_role=identity.role if identity else None,
                actor_source=identity.source if identity else None,
                action="pipeline_kill_switch.enable" if enabled else "pipeline_kill_switch.disable",
                resource=f"pipeline_kill_switch:{switch.id}",
                before=before,
                after={"enabled": switch.enabled, "reason": switch.reason},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return switch

    def _find(self) -> PipelineKillSwitch | None:
        """Read only. The name is unique in the database (ADR 0026), so there is at
        most one row; the ordering is only a deterministic tie-break that cannot
        matter."""
        return (
            self._db.query(PipelineKillSwitch)
            .filter_by(name=self._name)
            .order_by(PipelineKillSwitch.created_at, PipelineKillSwitch.id)
            .first()
        )

    def _get_or_create(self) -> PipelineKillSwitch:
        """Only for an explicit mutation. On PostgreSQL the creation is serialised
        per switch name with a transaction-scoped advisory lock and looked up again
        once the lock is held, so two first mutations at the same time cannot both
        insert. The lock is released by the commit in `_set_enabled`."""
        switch = self._find()
        if switch is None:
            if self._db.get_bind().dialect.name == "postgresql":
                self._db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"pipeline_kill_switch:{self._name}"},
                )
                switch = self._find()
            if switch is None:
                switch = PipelineKillSwitch(name=self._name, enabled=True)
                self._db.add(switch)
                self._db.flush()
        return switch
