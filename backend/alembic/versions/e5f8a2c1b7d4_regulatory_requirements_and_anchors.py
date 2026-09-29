"""regulatory requirements, anchors and compliance evidence

Milestone 41 (ADR 0019). Legal deja de ser un fixture. Tres tablas, una por cada
cuestión que hasta aquí viajaba mezclada y que **no se puede rellenar una con
otra**:

- `regulatory_requirements`: la **aplicabilidad**. Una persona declara que una
  norma (por su número CELEX) se aplica a un alcance de producto en una
  jurisdicción. Ninguna fuente pública lo dice.
- `regulatory_anchors`: la **existencia y vigencia**. Lo que EUR-Lex dijo de esa
  norma y cuándo se le preguntó. Una comprobación nueva es una fila nueva.
- `compliance_evidence`: la **evidencia de cumplimiento** de un producto concreto
  ante un requisito concreto.

## Lo que NO se toca

`legal_analyses` no cambia. El resultado del análisis real vive en su columna
`data` (JSON, ya existente) y las filas anteriores —del mock— siguen exactamente
como estaban. No se rellena nada retroactivamente: ningún análisis anterior se
convierte en `PASS`, `UNKNOWN` ni nada parecido, porque se hizo sobre un fixture.

## Bajar

Es aditiva y no modifica datos existentes, así que bajar solo elimina las tres
tablas y lo que hubiera en ellas: requisitos declarados, comprobaciones y
evidencia. Es información que solo existe ahí; hay que exportarla antes si
importa.

Revision ID: e5f8a2c1b7d4
Revises: d8b4c1e70a29
Create Date: 2026-09-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f8a2c1b7d4"
down_revision: str | Sequence[str] | None = "d8b4c1e70a29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "regulatory_requirements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("product_scope", sa.String(length=128), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("jurisdiction", sa.String(length=16), nullable=False),
        sa.Column("celex", sa.String(length=16), nullable=False),
        sa.Column("regulation", sa.String(length=255), nullable=False),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("requirement", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("applicability_provenance", sa.String(length=32), nullable=False),
        sa.Column("applicability_source", sa.String(length=255), nullable=True),
        sa.Column("declared_by", sa.String(length=255), nullable=False),
        sa.Column("transposition_reference", sa.String(length=255), nullable=True),
        sa.Column("transposition_provenance", sa.String(length=32), nullable=True),
        sa.Column("transposition_source", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_regulatory_requirements_scope",
        "regulatory_requirements",
        ["scope_key", "jurisdiction"],
    )
    op.create_index("ix_regulatory_requirements_celex", "regulatory_requirements", ["celex"])

    op.create_table(
        "regulatory_anchors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("celex", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column(
            "provenance",
            sa.String(length=32),
            nullable=False,
            server_default="third_party_verified",
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recheck_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False),
        sa.Column("in_force", sa.Boolean(), nullable=True),
        sa.Column("act_type", sa.String(length=16), nullable=False),
        sa.Column("act_type_code", sa.String(length=32), nullable=True),
        sa.Column("eli", sa.String(length=255), nullable=True),
        sa.Column("document_date", sa.String(length=10), nullable=True),
        sa.Column("source_effective_from", sa.JSON(), nullable=True),
        sa.Column("source_effective_to", sa.String(length=10), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_regulatory_anchors_celex_verified", "regulatory_anchors", ["celex", "verified_at"]
    )

    op.create_table(
        "compliance_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("product_id", sa.String(length=36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column(
            "requirement_id",
            sa.String(length=36),
            sa.ForeignKey("regulatory_requirements.id"),
            nullable=False,
        ),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("declared_by", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_compliance_evidence_product_id", "compliance_evidence", ["product_id"])
    op.create_index(
        "ix_compliance_evidence_requirement_id", "compliance_evidence", ["requirement_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_evidence_requirement_id", table_name="compliance_evidence")
    op.drop_index("ix_compliance_evidence_product_id", table_name="compliance_evidence")
    op.drop_table("compliance_evidence")

    op.drop_index("ix_regulatory_anchors_celex_verified", table_name="regulatory_anchors")
    op.drop_table("regulatory_anchors")

    op.drop_index("ix_regulatory_requirements_celex", table_name="regulatory_requirements")
    op.drop_index("ix_regulatory_requirements_scope", table_name="regulatory_requirements")
    op.drop_table("regulatory_requirements")
