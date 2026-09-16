from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="CANDIDATE")
    created_by: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), default="manual")
