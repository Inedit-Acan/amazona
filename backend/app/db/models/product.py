from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        # Por aquí se pregunta desde el Milestone 36: «¿ya tengo este producto en
        # esta categoría?», antes de crear otra fila para el mismo objeto.
        Index("ix_products_identity_category", "identity_key", "category"),
    )

    name: Mapped[str] = mapped_column(String(255))
    #: Quién es este producto, independientemente de cómo se escribiera su nombre
    #: (Milestone 36, ADR 0014). Se calcula con `identity.resolve()`, nunca a
    #: mano. Nulable porque las filas anteriores al milestone existen y su clave
    #: se rellenó en la migración a partir del nombre.
    #:
    #: **No es único a propósito.** Aquí también viven productos dados de alta a
    #: mano, y una restricción única impediría crear dos cosas que la
    #: normalización colapse — decidir que son la misma es del catálogo de alias,
    #: no de la base de datos.
    identity_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="CANDIDATE")
    created_by: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), default="manual")
