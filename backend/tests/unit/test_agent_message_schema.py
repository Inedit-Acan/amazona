import pytest
from pydantic import ValidationError

from app.messaging.schemas import SUPPORTED_SCHEMA_VERSIONS, AgentMessage


def make_message(**overrides) -> dict:
    defaults = dict(
        message_id="msg-1",
        correlation_id="corr-1",
        sender="ceo",
        recipient="agent-product-1",
        capability="market_validation",
        payload={"estimated_monthly_searches": 12000},
    )
    defaults.update(overrides)
    return defaults


def test_valid_message_constructs_with_default_schema_version():
    message = AgentMessage(**make_message())

    assert message.schema_version == "1.0"
    assert message.sent_at is not None


def test_message_serializes_to_a_plain_dict():
    message = AgentMessage(**make_message())

    dumped = message.model_dump()
    assert dumped["capability"] == "market_validation"
    assert dumped["payload"] == {"estimated_monthly_searches": 12000}


def test_unsupported_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        AgentMessage(**make_message(schema_version="99.0"))


def test_supported_schema_versions_includes_the_default():
    assert "1.0" in SUPPORTED_SCHEMA_VERSIONS


def test_message_requires_a_capability():
    payload = make_message()
    del payload["capability"]

    with pytest.raises(ValidationError):
        AgentMessage(**payload)
