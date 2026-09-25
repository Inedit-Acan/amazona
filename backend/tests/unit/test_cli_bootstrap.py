"""The bootstrap path: how the very first OWNER comes to exist (Milestone 29).

It is the one way to grant a role, so its refusals matter as much as its
successes.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.actor import ActorSource, RoleName
from app.cli import BOOTSTRAP_ENV, BootstrapError, grant_role, main, role_name_of
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.role import Role
from app.db.models.user import User


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    for role in RoleName:
        session.add(Role(id=f"role-{role.value.lower()}", name=role.value))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_grant_role_creates_the_user_when_it_does_not_exist(db):
    user = grant_role(db, email="owner@amazona.local", role_name="OWNER")

    assert user.email == "owner@amazona.local"
    assert role_name_of(db, user) == "OWNER"
    # Not linked to any session yet: the first verified login claims it.
    assert user.subject is None


def test_grant_role_is_audited_as_a_cli_action(db):
    grant_role(db, email="owner@amazona.local", role_name="OWNER")

    entry = db.query(AuditLog).filter_by(action="user.grant_role").one()
    assert entry.actor_source == ActorSource.CLI
    assert entry.after["role"] == "OWNER"


def test_grant_role_updates_an_existing_user(db):
    grant_role(db, email="someone@amazona.local", role_name="VIEWER")
    user = grant_role(db, email="someone@amazona.local", role_name="OPERATOR")

    assert role_name_of(db, user) == "OPERATOR"
    assert db.query(User).count() == 1


def test_grant_role_rejects_an_unknown_role(db):
    with pytest.raises(BootstrapError, match="unknown role"):
        grant_role(db, email="x@amazona.local", role_name="SUPERUSER")


def test_a_second_owner_needs_force(db):
    grant_role(db, email="first@amazona.local", role_name="OWNER")

    with pytest.raises(BootstrapError, match="already OWNER"):
        grant_role(db, email="second@amazona.local", role_name="OWNER")

    second = grant_role(db, email="second@amazona.local", role_name="OWNER", force=True)
    assert role_name_of(db, second) == "OWNER"


def test_regranting_owner_to_the_same_person_is_not_a_second_owner(db):
    grant_role(db, email="first@amazona.local", role_name="OWNER")

    again = grant_role(db, email="first@amazona.local", role_name="OWNER")
    assert role_name_of(db, again) == "OWNER"


def test_grant_role_refuses_without_the_bootstrap_flag(monkeypatch, capsys):
    monkeypatch.delenv(BOOTSTRAP_ENV, raising=False)

    exit_code = main(["grant-role", "--email", "x@amazona.local", "--role", "OWNER"])

    assert exit_code == 2
    assert BOOTSTRAP_ENV in capsys.readouterr().err
