import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.ids import new_id

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


class AgentMessage(BaseModel):
    """Versioned contract for every CEO <-> specialist-agent exchange.

    Replaces the untyped `dict` that crossed the CEO/agent boundary in
    Milestone 1 (task_input in, AgentResult out) with an explicit envelope,
    so a schema drift is caught here instead of surfacing as a confusing
    KeyError three steps downstream. See ADR 0002 for why this protocol is
    scoped to CEO <-> specialist agents and not Orchestrator <-> CEO.
    """

    schema_version: str = "1.0"
    message_id: str = Field(default_factory=new_id)
    correlation_id: str
    sender: str
    recipient: str
    capability: str
    payload: dict = Field(default_factory=dict)
    sent_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported AgentMessage schema_version {value!r}; supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return value
