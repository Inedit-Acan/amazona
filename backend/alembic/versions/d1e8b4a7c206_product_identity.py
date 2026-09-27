"""product identity

Milestone 36 (ADR 0014). Una columna en una tabla que ya existía y una tabla
nueva.

- products.identity_key: quién es este producto, independientemente de cómo se
  escribiera su nombre. Nulable y **no** única: en esta tabla también hay
  productos dados de alta a mano, y una restricción única impediría crear dos
  cosas que la normalización colapse.
- product_identity_aliases: con qué otros nombres llegó, y por qué vía se
  resolvió cada uno. Una fusión sin motivo escrito es indistinguible de un error.

## El relleno de la columna usa solo la normalización, no el catálogo de alias

`fold()` está copiado aquí a propósito. Una migración tiene que poder ejecutarse
dentro de tres años contra el código de entonces, así que no importa de
`app.integrations`: lo que hizo cuando se aplicó queda congelado.

Lo que **no** se copia es el catálogo de alias. Una lista escrita a mano cambia
—para eso tiene versión— y congelar la v1 aquí solo daría la ilusión de estar al
día. Consecuencia, escrita para que no sorprenda: una fila anterior al milestone
que se llame `airfryer` recibe la clave `airfryer`, no `air fryer`, y la primera
investigación que mida `Air fryer` creará su propia fila. Ese duplicado
preexistente no se resuelve solo.

Revision ID: d1e8b4a7c206
Revises: a5f1c62d87e4
Create Date: 2026-09-27

"""

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e8b4a7c206"
down_revision: str | Sequence[str] | None = "a5f1c62d87e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARENTHETICAL = re.compile(r"\([^)]*\)")


def fold(name: str) -> str:
    """Copia congelada de `app.integrations.product_intelligence.identity.fold`.

    Si alguna vez las dos dejan de coincidir, la que manda es la de la aplicación
    y esta describe lo que se rellenó el día que se aplicó la migración. Hay un
    test que comprueba que hoy coinciden.
    """
    without_notes = _PARENTHETICAL.sub(" ", name)
    decomposed = unicodedata.normalize("NFKD", without_notes)
    unaccented = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = unaccented.casefold()
    words = "".join(ch if ch.isalnum() else " " for ch in lowered).split()
    if not words:
        return " ".join(name.split())
    return " ".join(words)


def upgrade() -> None:
    op.add_column("products", sa.Column("identity_key", sa.String(length=255), nullable=True))

    # Las filas que ya existían tienen identidad: la que se deduce de su nombre.
    # Dejarlas a NULL haría que la primera investigación las duplicara todas.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, name FROM products")).fetchall()
    for row in rows:
        bind.execute(
            sa.text("UPDATE products SET identity_key = :key WHERE id = :id"),
            {"key": fold(row.name), "id": row.id},
        )

    op.create_index("ix_products_identity_key", "products", ["identity_key"])
    op.create_index("ix_products_identity_category", "products", ["identity_key", "category"])

    op.create_table(
        "product_identity_aliases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("identity_key", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_identity_aliases_product_id", "product_identity_aliases", ["product_id"]
    )
    op.create_index(
        "ix_product_identity_aliases_product_alias",
        "product_identity_aliases",
        ["product_id", "alias"],
    )
    op.create_index(
        "ix_product_identity_aliases_key", "product_identity_aliases", ["identity_key"]
    )

    # RLS deny-by-default en toda tabla pública, desde su propia migración
    # (ADR 0003). El backend entra con la clave de servicio y no le afecta.
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE product_identity_aliases ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE product_identity_aliases FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_product_identity_aliases_key", table_name="product_identity_aliases")
    op.drop_index(
        "ix_product_identity_aliases_product_alias", table_name="product_identity_aliases"
    )
    op.drop_index("ix_product_identity_aliases_product_id", table_name="product_identity_aliases")
    op.drop_table("product_identity_aliases")

    op.drop_index("ix_products_identity_category", table_name="products")
    op.drop_index("ix_products_identity_key", table_name="products")
    op.drop_column("products", "identity_key")
