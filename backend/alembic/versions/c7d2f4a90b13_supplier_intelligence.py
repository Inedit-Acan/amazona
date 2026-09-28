"""supplier intelligence

Milestone 39 (ADR 0017). Los hechos sobre un proveedor pasan a decir quién los
sostiene, y lo que nadie ha dicho deja de valer cero.

## Lo que se quita

`suppliers.verified` y `supplier_quotes.verified`, los dos booleanos. El plan
maestro §10 pide cuatro niveles —supplier claim, third-party verified, AMAZONA
estimate, unknown— y dice literalmente «no marcar un proveedor como "verified"
sin explicar qué significa». Un `bool` no puede explicarlo.

`supplier_quotes.reliability_score` también se va: la fiabilidad es un hecho
sobre la **empresa**, no sobre una tarifa, y estaba copiada en las dos tablas.

## Lo que se rellena, y lo que no

Se rellena `verification = 'simulated'` en todos los proveedores y
`provenance = 'simulated'` en todas las cotizaciones, y no depende del booleano
anterior. El motivo es comprobable: el único proveedor que el dominio SUPPLIERS
ha tenido nunca es `MockSupplierDirectory`, así que **todas** las filas
existentes salen de un fichero de fixtures. El `verified = true` que había en
algunas era una propiedad del fixture, no una verificación; convertirlo en
`third_party_verified` habría ascendido a hecho comprobado algo que nadie
comprobó, que es exactamente lo que esta migración existe para impedir.

Se rellena `logistics_provenance = 'amazona_estimate'` donde hay coste
logístico, porque lo calculó `app/sourcing/logistics.py` y eso sí consta.

**No se rellena la moneda.** Las filas existentes se quedan en `NULL`, que
significa «nadie dijo en qué moneda estaba este precio». Poner `USD` sería
atribuirle a una fila de hace meses una convención que el fixture no declaraba
cuando la escribió. Un precio sin moneda no se compara, y eso es correcto: son
precios inventados.

**No se rellena el mercado de destino.** El destino era un parámetro de la
ejecución y nunca se guardó; no se puede recuperar y no se inventa.

`reliability_score = 0` pasa a `NULL`. Ningún valor del fixture es cero, así
que un cero solo puede venir del `default=0.0` de la columna: es el caso exacto
de «ausencia disfrazada de dato» que la ADR 0017 cierra.

## La identidad

`identity_key` se rellena con la misma transformación determinista que usa
`app.sourcing.identity`, copiada aquí porque una migración tiene que poder
ejecutarse sin importar código de la aplicación —que cambia— y porque así queda
fijado qué hizo **esta** migración el día que se ejecutó. Sin este relleno, cada
proveedor existente sería invisible para la reutilización y el primer sourcing
posterior crearía un duplicado de cada uno.

Revision ID: c7d2f4a90b13
Revises: a4b8e1f60c37
Create Date: 2026-09-28

"""

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7d2f4a90b13"
down_revision: str | Sequence[str] | None = "a4b8e1f60c37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PARENTHETICAL = re.compile(r"\([^)]*\)")


def fold(name: str) -> str:
    """Copia congelada de `app.core.text.fold`. Ver la nota de arriba."""
    without_notes = _PARENTHETICAL.sub(" ", name)
    decomposed = unicodedata.normalize("NFKD", without_notes)
    unaccented = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = unaccented.casefold()
    words = "".join(ch if ch.isalnum() else " " for ch in lowered).split()
    if not words:
        return " ".join(name.split())
    return " ".join(words)


def identity_key(name: str, country: str | None, region: str | None) -> str:
    """Copia congelada de `app.sourcing.identity.resolve`, sin catálogo de alias
    porque el catálogo está vacío el día de esta migración."""
    if (country or "").strip():
        kind, place = "country", fold(country or "")
    elif (region or "").strip():
        kind, place = "region", fold(region or "")
    else:
        kind, place = "nowhere", ""
    return f"{fold(name)}|{kind}:{place}"


def _supplier_columns() -> tuple[sa.Column, ...]:
    """Columnas nuevas de `suppliers`. Una función y no una constante porque un
    objeto `Column` se consume al añadirlo y no se puede reutilizar."""
    return (
        sa.Column("identity_key", sa.String(length=320), nullable=True),
        sa.Column("identity_method", sa.String(length=32), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("verification", sa.String(length=32), nullable=True),
        sa.Column("verified_by", sa.String(length=255), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reliability_provenance", sa.String(length=32), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )

def _quote_columns() -> tuple[sa.Column, ...]:
    """Columnas nuevas de `supplier_quotes`."""
    return (
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("quoted_unit", sa.String(length=32), nullable=True),
        sa.Column("quoted_quantity", sa.Integer(), nullable=True),
        sa.Column("transit_days", sa.Integer(), nullable=True),
        sa.Column("transport_mode", sa.String(length=32), nullable=True),
        sa.Column("incoterm", sa.String(length=3), nullable=True),
        sa.Column("payment_terms", sa.String(length=255), nullable=True),
        sa.Column("destination_market", sa.String(length=32), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provenance", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column("logistics_provenance", sa.String(length=32), nullable=True),
    )

#: Las columnas de `supplier_quotes` que dejan de ser obligatorias. Un número
#: que nadie ha dicho tiene que poder faltar; si no, el modelo obliga a
#: inventarlo.
_QUOTE_NULLABLE = (
    ("unit_price", sa.Float()),
    ("moq", sa.Integer()),
    ("lead_time_days", sa.Integer()),
    ("logistics_cost_per_unit", sa.Float()),
    ("total_landed_cost_per_unit", sa.Float()),
)


def upgrade() -> None:
    for column in _supplier_columns():
        op.add_column("suppliers", column)
    for column in _quote_columns():
        op.add_column("supplier_quotes", column)

    connection = op.get_bind()

    # Todo lo que hay salió del mock. No se deduce del booleano anterior.
    connection.execute(sa.text("UPDATE suppliers SET verification = 'simulated'"))
    connection.execute(
        sa.text(
            "UPDATE suppliers SET reliability_provenance = 'simulated' "
            "WHERE reliability_score IS NOT NULL AND reliability_score <> 0"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE supplier_quotes SET provenance = 'simulated', "
            "source = 'fixtures:mock-supplier-directory'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE supplier_quotes SET logistics_provenance = 'amazona_estimate' "
            "WHERE logistics_cost_per_unit IS NOT NULL"
        )
    )

    for row in connection.execute(
        sa.text("SELECT id, name, region FROM suppliers")
    ).fetchall():
        connection.execute(
            sa.text(
                "UPDATE suppliers SET identity_key = :key, identity_method = 'normalised' "
                "WHERE id = :id"
            ),
            {"key": identity_key(row.name, None, row.region), "id": row.id},
        )

    op.create_index("ix_suppliers_identity_key", "suppliers", ["identity_key"])
    op.create_index("ix_suppliers_verification", "suppliers", ["verification"])
    op.create_index("ix_supplier_quotes_provenance", "supplier_quotes", ["provenance"])
    op.create_index(
        "ix_supplier_quotes_destination_market", "supplier_quotes", ["destination_market"]
    )

    # `batch_alter_table` porque SQLite no sabe cambiar la nulabilidad de una
    # columna con ALTER: recrea la tabla. En PostgreSQL usa el ALTER directo.
    with op.batch_alter_table("suppliers") as batch:
        batch.alter_column("reliability_score", existing_type=sa.Float(), nullable=True)
        batch.drop_column("verified")

    # Después de quitar el NOT NULL, no antes: un cero solo puede venir del
    # `default=0.0` porque ningún valor del fixture vale cero, y es la ausencia
    # disfrazada de dato que este milestone cierra.
    connection.execute(
        sa.text("UPDATE suppliers SET reliability_score = NULL WHERE reliability_score = 0")
    )

    with op.batch_alter_table("supplier_quotes") as batch:
        for name, type_ in _QUOTE_NULLABLE:
            batch.alter_column(name, existing_type=type_, nullable=True)
        batch.drop_column("verified")
        batch.drop_column("reliability_score")

    op.create_table(
        "supplier_capabilities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("supplier_id", sa.String(length=36), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_supplier_capabilities_supplier_id", "supplier_capabilities", ["supplier_id"])
    op.create_index("ix_supplier_capabilities_product_id", "supplier_capabilities", ["product_id"])
    op.create_index("ix_supplier_capabilities_provenance", "supplier_capabilities", ["provenance"])
    op.create_index(
        "ix_supplier_capabilities_supplier_capability",
        "supplier_capabilities",
        ["supplier_id", "capability"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_supplier_capabilities_supplier_capability", table_name="supplier_capabilities"
    )
    op.drop_index("ix_supplier_capabilities_provenance", table_name="supplier_capabilities")
    op.drop_index("ix_supplier_capabilities_product_id", table_name="supplier_capabilities")
    op.drop_index("ix_supplier_capabilities_supplier_id", table_name="supplier_capabilities")
    op.drop_table("supplier_capabilities")

    # El booleano vuelve con el único significado que se puede reconstruir:
    # verificado es lo que un tercero verificó. Lo simulado vuelve a `false`,
    # que es lo que era antes de que alguien lo llamara `true` sin motivo.
    op.add_column(
        "suppliers",
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "supplier_quotes",
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "supplier_quotes",
        sa.Column("reliability_score", sa.Float(), nullable=False, server_default="0"),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE suppliers SET verified = TRUE WHERE verification = 'third_party_verified'")
    )
    connection.execute(
        sa.text(
            "UPDATE supplier_quotes SET verified = TRUE WHERE provenance = 'third_party_verified'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE supplier_quotes SET reliability_score = COALESCE("
            "(SELECT s.reliability_score FROM suppliers s WHERE s.id = supplier_quotes.supplier_id)"
            ", 0)"
        )
    )
    connection.execute(
        sa.text("UPDATE suppliers SET reliability_score = 0 WHERE reliability_score IS NULL")
    )
    # Bajar cuesta información, y conviene decirlo: el esquema anterior no sabe
    # representar «no se sabe», así que todo lo desconocido vuelve a valer cero.
    # Es la razón por la que esta migración existe, vista del revés.
    for column, _type in _QUOTE_NULLABLE:
        connection.execute(
            sa.text(f"UPDATE supplier_quotes SET {column} = 0 WHERE {column} IS NULL")
        )

    with op.batch_alter_table("supplier_quotes") as batch:
        for name, type_ in _QUOTE_NULLABLE:
            batch.alter_column(name, existing_type=type_, nullable=False)
    with op.batch_alter_table("suppliers") as batch:
        batch.alter_column("reliability_score", existing_type=sa.Float(), nullable=False)

    op.drop_index("ix_supplier_quotes_destination_market", table_name="supplier_quotes")
    op.drop_index("ix_supplier_quotes_provenance", table_name="supplier_quotes")
    op.drop_index("ix_suppliers_verification", table_name="suppliers")
    op.drop_index("ix_suppliers_identity_key", table_name="suppliers")

    for column in _quote_columns():
        op.drop_column("supplier_quotes", column.name)
    for column in _supplier_columns():
        op.drop_column("suppliers", column.name)
