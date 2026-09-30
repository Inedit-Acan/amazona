"""national transpositions and anchors

Milestone 43 (ADR 0021). Derecho nacional: una persona declara qué norma española
traspone una directiva de un requisito, y el BOE la verifica y la ancla. Dos tablas,
una por cada capa que **no se rellena con otra**:

- `national_transpositions`: la **norma declarada**. Quién la afirmó. El sistema no
  infiere qué ley traspone qué directiva.
- `national_anchors`: lo que el BOE dijo en una comprobación concreta: metadatos y
  relaciones **verbatim**, el estado de la publicación oficial (comprobación
  auxiliar), y —siempre— que la consolidación y el análisis son informativos, con el
  aviso y la atribución que exige la licencia. No se guarda el texto de la norma.

## Lo que NO se toca

`regulatory_requirements`, `regulatory_anchors`, `compliance_evidence` y
`legal_analyses` no cambian. La columna `transposition_reference` de M41 (texto
libre) **se conserva**: sigue siendo la declaración humana y la pista de auditoría.
No se rellena nada retroactivamente.

## RLS desde su propia migración

Las dos tablas activan Row Level Security aquí, con el patrón de la ADR 0003 (y de
`9f2b6c0a1d47`, que cerró el mismo hueco en M39–M41): `ENABLE ROW LEVEL SECURITY` y,
solo en Supabase, la política `deny_all_anon_authenticated`. Sin `FORCE`: el backend es
el dueño y no debe verse afectado.

## Bajar

Es aditiva y no modifica datos existentes: bajar solo elimina las dos tablas y lo que
hubiera en ellas (transposiciones declaradas y comprobaciones). Es información que
solo existe ahí; hay que exportarla antes si importa.

Revision ID: b6d2f8a41c93
Revises: 9f2b6c0a1d47
Create Date: 2026-09-30

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6d2f8a41c93"
down_revision: str | Sequence[str] | None = "9f2b6c0a1d47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "national_transpositions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "requirement_id",
            sa.String(length=36),
            sa.ForeignKey("regulatory_requirements.id"),
            nullable=False,
        ),
        sa.Column("national_id", sa.String(length=32), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("declared_by", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_national_transpositions_requirement_id", "national_transpositions", ["requirement_id"]
    )
    op.create_index(
        "ix_national_transpositions_national_id", "national_transpositions", ["national_id"]
    )

    op.create_table(
        "national_anchors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("national_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recheck_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consolidated", sa.Boolean(), nullable=False),
        sa.Column("informational", sa.Boolean(), nullable=False),
        sa.Column("notice", sa.Text(), nullable=False),
        sa.Column("attribution", sa.String(length=255), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=True),
        sa.Column("source_updated_at", sa.String(length=20), nullable=True),
        sa.Column("relations", sa.JSON(), nullable=True),
        sa.Column("publication_state", sa.String(length=24), nullable=False),
        sa.Column("publication_detail", sa.Text(), nullable=True),
        sa.Column("publication_url", sa.Text(), nullable=True),
        sa.Column("source_urls", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_national_anchors_id_verified", "national_anchors", ["national_id", "verified_at"]
    )


    _enable_rls()


def _enable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with_policy = (
        bind.execute(
            sa.text("SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
        ).scalar()
        == 2
    )
    for table in ("national_transpositions", "national_anchors"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        if with_policy:
            op.execute(
                f"CREATE POLICY deny_all_anon_authenticated ON public.{table} "
                "AS PERMISSIVE FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("national_anchors", "national_transpositions"):
            op.execute(f"DROP POLICY IF EXISTS deny_all_anon_authenticated ON public.{table}")
    op.drop_index("ix_national_anchors_id_verified", table_name="national_anchors")
    op.drop_table("national_anchors")

    op.drop_index("ix_national_transpositions_national_id", table_name="national_transpositions")
    op.drop_index(
        "ix_national_transpositions_requirement_id", table_name="national_transpositions"
    )
    op.drop_table("national_transpositions")
