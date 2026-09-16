import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.role import Role
from app.db.models.user import User
from app.permissions.roles import RoleService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_role_for_returns_the_assigned_role_name(db_session: Session):
    role = Role(name="owner")
    db_session.add(role)
    db_session.flush()
    user = User(email="owner@amazona.local", role_id=role.id)
    db_session.add(user)
    db_session.commit()

    service = RoleService(db_session)

    assert service.role_for(user.id) == "owner"


def test_role_for_returns_none_for_a_user_with_no_role_assigned(db_session: Session):
    user = User(email="nobody@amazona.local")
    db_session.add(user)
    db_session.commit()

    service = RoleService(db_session)

    assert service.role_for(user.id) is None


def test_role_for_returns_none_for_an_unknown_user_id(db_session: Session):
    service = RoleService(db_session)

    assert service.role_for("does-not-exist") is None
