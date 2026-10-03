"""Los comandos del operador para las acciones externas (hardening pre-M44, ADR 0024).

Cerrar una operación de resultado desconocido es un acto humano y queda escrito: quién, cuándo y por qué. El
CLI es la única vía (no hay endpoint que lo haga), y exige `AMAZONA_BOOTSTRAP=1` como el resto de comandos
que cambian estado.
"""

import datetime

import pytest
from action_test_support import FakeProviderAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import cli
from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService
from app.budgets.service import BudgetLedgerService
from app.core.errors import ExternalOutcomeUnknownError
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.budget import BudgetAllocation
from app.db.models.external_action import ExternalAction

PAYLOAD = {"platform": "meta"}


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def open_action(db: Session, reference: str, behaviors: list[str]) -> ExternalAction:
    BudgetLedgerService(db).authorise_budget(hard_limit=1_000.0, actor="owner@amazona.local")
    adapter = FakeProviderAdapter(supports_idempotency=False, behaviors=behaviors)
    service = ExternalActionService(db)
    action = service.open(
        reference=reference,
        adapter=adapter,
        operation="activate_ads",
        amount=100.0,
        payload=PAYLOAD,
        correlation_id="c",
    )
    service.reserve(action)
    db.commit()
    if behaviors:
        with pytest.raises(ExternalOutcomeUnknownError):
            service.execute(action, adapter, PAYLOAD)
    return action


def reserved(db: Session) -> float:
    db.expire_all()
    return float(db.query(BudgetAllocation).one().reserved)


def test_show_actions_lists_only_the_open_ones_when_asked(db: Session):
    unknown = open_action(db, "ref-1", ["timeout_after"])
    cli.resolve_action(db, action_id=unknown.id, succeeded=False, reason="no campaign exists")

    assert [a.id for a in cli.list_actions(db)] == [unknown.id]
    assert cli.list_actions(db, only_open=True) == []


def test_resolving_an_unknown_outcome_commits_it_and_leaves_who_and_why(db: Session):
    action = open_action(db, "ref-1", ["timeout_after"])

    closed = cli.resolve_action(db, action_id=action.id, succeeded=True, reason="seen in the ads console")

    assert closed.status == ActionStatus.SUCCEEDED.value
    assert closed.resolved_by is not None and closed.resolved_by.startswith("cli:")
    entry = db.query(AuditLog).filter_by(action="external_action.resolve").one()
    assert entry.after["why"] == "seen in the ads console"


def test_resolving_as_failed_releases_the_reservation(db: Session):
    action = open_action(db, "ref-1", ["timeout_after"])
    assert reserved(db) == 100.0

    cli.resolve_action(db, action_id=action.id, succeeded=False, reason="no campaign exists")

    assert reserved(db) == 0.0


def test_the_cli_refuses_an_unknown_id_a_blank_reason_and_a_second_resolution(db: Session):
    action = open_action(db, "ref-1", ["timeout_after"])

    with pytest.raises(cli.BootstrapError, match="not found"):
        cli.resolve_action(db, action_id="nope", succeeded=True, reason="x")
    with pytest.raises(cli.BootstrapError, match="reason"):
        cli.resolve_action(db, action_id=action.id, succeeded=True, reason=" ")
    cli.resolve_action(db, action_id=action.id, succeeded=True, reason="seen")
    with pytest.raises(cli.BootstrapError):
        cli.resolve_action(db, action_id=action.id, succeeded=False, reason="changed my mind")


def test_reconcile_actions_releases_what_never_left_and_marks_the_rest_unknown(db: Session):
    never_sent = open_action(db, "ref-1", [])
    ExternalActionService(db).begin_call(open_action(db, "ref-2", []))  # CALLING y el proceso muere

    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=3)
    db.query(ExternalAction).update({"updated_at": old})
    # Una acción `CALLING` se mide desde que **empezó la llamada** (ADR 0029 §3), no desde su última escritura.
    db.query(ExternalAction).filter(ExternalAction.status == "CALLING").update({"call_started_at": old})
    db.commit()
    swept = cli.reconcile_actions(db, older_than_minutes=60)

    assert swept["released"] == [never_sent.id]
    assert len(swept["unknown"]) == 1
    assert reserved(db) == 100.0  # solo se liberó la que no salió


def test_reconcile_actions_needs_a_sensible_threshold(db: Session):
    with pytest.raises(cli.BootstrapError):
        cli.reconcile_actions(db, older_than_minutes=0)


@pytest.mark.parametrize(
    "argv",
    [
        ["resolve-action", "--id", "x", "--succeeded", "--reason", "r"],
        ["reconcile-actions"],
    ],
)
def test_the_state_changing_commands_need_the_bootstrap_flag(monkeypatch, capsys, argv):
    monkeypatch.delenv(cli.BOOTSTRAP_ENV, raising=False)

    assert cli.main(argv) == 2
    assert "AMAZONA_BOOTSTRAP=1" in capsys.readouterr().err


def test_resolve_action_requires_exactly_one_outcome():
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["resolve-action", "--id", "x", "--reason", "r"])
    with pytest.raises(SystemExit):
        parser.parse_args(["resolve-action", "--id", "x", "--succeeded", "--failed", "--reason", "r"])
