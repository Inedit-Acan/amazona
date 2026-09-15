import pytest

from app.budgets.engine import BudgetEngine, BudgetLimitExceededError, BudgetState


@pytest.fixture()
def engine() -> BudgetEngine:
    return BudgetEngine()


def test_authorize_approves_a_request_within_the_hard_limit(engine: BudgetEngine):
    state = BudgetState(hard_limit=1000.0)

    decision = engine.authorize(amount=200.0, state=state)

    assert decision.approved is True


def test_authorize_blocks_a_request_over_the_hard_limit(engine: BudgetEngine):
    state = BudgetState(hard_limit=1000.0)

    decision = engine.authorize(amount=1200.0, state=state)

    assert decision.approved is False
    assert "hard limit" in decision.reason.lower()


def test_authorize_warns_when_crossing_the_soft_limit_but_still_approves(engine: BudgetEngine):
    state = BudgetState(hard_limit=1000.0, soft_limit=500.0)

    decision = engine.authorize(amount=600.0, state=state)

    assert decision.approved is True
    assert decision.warning is not None


def test_authorize_enforces_the_single_action_limit(engine: BudgetEngine):
    state = BudgetState(hard_limit=1000.0, single_action_limit=100.0)

    decision = engine.authorize(amount=150.0, state=state)

    assert decision.approved is False
    assert "single-action" in decision.reason.lower()


def test_committed_funds_reduce_available_budget(engine: BudgetEngine):
    state = BudgetState(hard_limit=1000.0)

    engine.reserve(state, 400.0)
    engine.commit(state, 400.0)

    assert state.committed == 400.0
    assert state.available == 600.0

    decision = engine.authorize(amount=700.0, state=state)
    assert decision.approved is False


def test_locked_funds_are_never_available_for_authorization(engine: BudgetEngine):
    state = BudgetState(hard_limit=1000.0, locked=300.0)

    assert state.available == 700.0
    decision = engine.authorize(amount=800.0, state=state)
    assert decision.approved is False


def test_release_returns_reserved_funds_to_available(engine: BudgetEngine):
    state = BudgetState(hard_limit=1000.0)

    engine.reserve(state, 500.0)
    assert state.available == 500.0

    engine.release(state, 500.0)
    assert state.available == 1000.0


def test_repeated_rapid_reservations_cannot_exceed_the_hard_limit(engine: BudgetEngine):
    state = BudgetState(hard_limit=1000.0)

    successes = 0
    for _ in range(20):
        try:
            engine.reserve(state, 100.0)
            successes += 1
        except BudgetLimitExceededError:
            pass

    assert successes == 10
    assert state.reserved == 1000.0
    assert state.available == 0.0

    with pytest.raises(BudgetLimitExceededError):
        engine.reserve(state, 1.0)


def test_reserve_raises_when_authorization_is_denied(engine: BudgetEngine):
    state = BudgetState(hard_limit=100.0)

    with pytest.raises(BudgetLimitExceededError):
        engine.reserve(state, 150.0)
