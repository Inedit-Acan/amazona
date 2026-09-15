from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Budget(IdMixin, TimestampMixin, Base):
    __tablename__ = "budgets"

    name: Mapped[str] = mapped_column(String(255))
    hard_limit: Mapped[float] = mapped_column(Numeric(12, 2))
    soft_limit: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    period: Mapped[str] = mapped_column(String(32), default="monthly")


class BudgetAllocation(IdMixin, TimestampMixin, Base):
    __tablename__ = "budget_allocations"

    budget_id: Mapped[str] = mapped_column(ForeignKey("budgets.id"))
    reserved: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    committed: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    spent: Mapped[float] = mapped_column(Numeric(12, 2), default=0)


class FinancialEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "financial_events"

    budget_id: Mapped[str | None] = mapped_column(ForeignKey("budgets.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
