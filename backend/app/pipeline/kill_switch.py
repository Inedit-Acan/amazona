from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.db.models.audit import AuditLog
from app.db.models.pipeline_kill_switch import PipelineKillSwitch

DEFAULT_KILL_SWITCH_NAME = "pipeline-default"
KILL_SWITCH_ACTOR = "pipeline-kill-switch"


class PipelineKillSwitchService:
    """Get-or-create a single canonical PipelineKillSwitch row (same
    pattern as BudgetLedgerService's canonical Budget row) gating whether
    PipelineOrchestrator may start a new run. Enabled by default — a
    missing row means "no operator has ever disabled it", not "disabled"."""

    def __init__(self, db: Session, *, name: str = DEFAULT_KILL_SWITCH_NAME) -> None:
        self._db = db
        self._name = name

    def is_enabled(self) -> bool:
        return self._get_or_create().enabled

    def get_state(self) -> PipelineKillSwitch:
        return self._get_or_create()

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

    def _get_or_create(self) -> PipelineKillSwitch:
        switch = self._db.query(PipelineKillSwitch).filter_by(name=self._name).first()
        if switch is None:
            switch = PipelineKillSwitch(name=self._name, enabled=True)
            self._db.add(switch)
            self._db.flush()
        return switch
