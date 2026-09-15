import uuid

from app.core.ids import new_correlation_id, new_id


def test_new_id_is_a_valid_uuid4_string():
    value = new_id()

    parsed = uuid.UUID(value)
    assert parsed.version == 4
    assert str(parsed) == value


def test_new_id_generates_unique_values():
    values = {new_id() for _ in range(1000)}

    assert len(values) == 1000


def test_new_correlation_id_is_a_valid_uuid4_string():
    value = new_correlation_id()

    parsed = uuid.UUID(value)
    assert parsed.version == 4


def test_new_correlation_id_generates_unique_values():
    values = {new_correlation_id() for _ in range(1000)}

    assert len(values) == 1000
