from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_id: Mapped[str | None] = mapped_column(ForeignKey("roles.id"), nullable=True)
    #: `sub` of the access token that owns this account. Nullable because the
    #: owner seeds a user by email before that person has ever signed in; the
    #: first verified login claims the row (Milestone 29).
    subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
