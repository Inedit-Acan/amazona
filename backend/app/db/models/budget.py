from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Budget(IdMixin, TimestampMixin, Base):
    __tablename__ = "budgets"
    #: Hay **un** presupuesto por nombre: lo garantiza la base de datos (ADR 0026), no solo el lock del que autoriza.
    __table_args__ = (UniqueConstraint("name", name="uq_budgets_name"),)

    name: Mapped[str] = mapped_column(String(255))
    hard_limit: Mapped[float] = mapped_column(Numeric(12, 2))
    soft_limit: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    period: Mapped[str] = mapped_column(String(32), default="monthly")


class BudgetAllocation(IdMixin, TimestampMixin, Base):
    __tablename__ = "budget_allocations"
    #: Un presupuesto, un saldo. Con dos filas, cada comprobación de límite miraría la suya y el techo se partiría.
    __table_args__ = (UniqueConstraint("budget_id", name="uq_budget_allocations_budget_id"),)

    budget_id: Mapped[str] = mapped_column(ForeignKey("budgets.id"))
    reserved: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    committed: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    spent: Mapped[float] = mapped_column(Numeric(12, 2), default=0)


class FinancialEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "financial_events"
    #: La identidad de un movimiento (ADR 0026): una `reference` se reserva **una** vez y se liquida (compromete o
    #: libera) **una** vez. Dos liquidaciones de la misma reserva contarían el dinero dos veces.
    __table_args__ = (
        Index(
            "uq_financial_events_one_reserve_per_reference",
            "reference",
            unique=True,
            postgresql_where=text("type = 'RESERVE'"),
            sqlite_where=text("type = 'RESERVE'"),
        ),
        Index(
            "uq_financial_events_one_settlement_per_reference",
            "reference",
            unique=True,
            postgresql_where=text("type IN ('COMMIT', 'RELEASE')"),
            sqlite_where=text("type IN ('COMMIT', 'RELEASE')"),
        ),
    )

    budget_id: Mapped[str | None] = mapped_column(ForeignKey("budgets.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
