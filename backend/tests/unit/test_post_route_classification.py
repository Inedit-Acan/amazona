"""Ninguna ruta `POST` queda sin clasificar (hardening pre-M44, ADR 0025 §6).

Una ruta con efecto que nace sin que nadie se pregunte «¿qué pasa si esto se repite?» es exactamente el hueco que
cerró la fase 2. Esta guarda obliga a responderlo: añadir un `POST` sin clasificarlo falla, y clasificar una
ruta como protegida exige que de verdad declare la cabecera `Idempotency-Key` (si no, el documento y el código
divergirían).

Las clases:

- `GENERIC`: idempotencia genérica (`app.idempotency`); declara `Idempotency-Key`.
- `OWN_KEY`: su recurso ya tiene clave y la usa (trabajos, ejecuciones del pipeline): la cabecera o el cuerpo.
- `STATE`: una transición de estado con compare-and-set; repetirla es un 409 o un no-op.
- `DRAFT`: escribe un registro propio sin efecto fuera del sistema; un duplicado es un registro más. Cuando una de estas
  rutas pase a tocar un proveedor real deja de ser un borrador y tiene que pasar a `GENERIC` o a `ExternalAction`.
- `EXTERNAL_WRITE` (Milestone 44, ADR 0028): una operación con efecto fuera del sistema (abrir un cobro, reembolsar,
  comprar al proveedor, enviar). Declara `Idempotency-Key` **y** pasa por `ExternalAction` y el ActionGate: dos
  mecanismos distintos, a propósito (la clave del cliente identifica la intención; la clave hacia el proveedor, la
  operación).
- `WEBHOOK` (Milestone 44): un hecho que cuenta un proveedor. No lleva el token de nadie ni `Idempotency-Key`: se
  autentica por la firma del cuerpo y se deduplica por el identificador del evento del proveedor.
"""

import pytest

from app.main import app

GENERIC = "GENERIC"
OWN_KEY = "OWN_KEY"
STATE = "STATE"
DRAFT = "DRAFT"
EXTERNAL_WRITE = "EXTERNAL_WRITE"
WEBHOOK = "WEBHOOK"

CLASSIFICATION: dict[str, str] = {
    # Salen a una fuente externa, reservan presupuesto o escriben análisis: idempotencia genérica.
    "/api/exchange-rates/backfill": GENERIC,
    "/api/exchange-rates/refresh": GENERIC,
    "/api/legal/runs": GENERIC,
    "/api/national-transpositions/{transposition_id}/verify": GENERIC,
    "/api/objectives/{objective_id}/run": GENERIC,
    # Un pedido (Milestone 44): la clave es obligatoria siempre, también en simulación.
    "/api/orders": GENERIC,
    "/api/orders/{order_id}/payments": EXTERNAL_WRITE,
    "/api/orders/{order_id}/refunds": EXTERNAL_WRITE,
    "/api/orders/{order_id}/fulfillments": GENERIC,
    "/api/fulfillments/{fulfillment_id}/purchase": EXTERNAL_WRITE,
    "/api/fulfillments/{fulfillment_id}/ship": EXTERNAL_WRITE,
    "/api/payments/webhooks/{provider}": WEBHOOK,
    "/api/regulatory-requirements/{requirement_id}/verify": GENERIC,
    "/api/research/comparisons": GENERIC,
    "/api/research/runs": GENERIC,
    # Su recurso ya tiene clave.
    "/api/pipeline/runs": OWN_KEY,
    "/api/jobs": OWN_KEY,
    # Transiciones de estado con compare-and-set.
    "/api/approvals/{approval_id}/approve": STATE,
    "/api/approvals/{approval_id}/reject": STATE,
    "/api/incidents/{incident_id}/resolve": STATE,
    "/api/jobs/{job_id}/cancel": STATE,
    "/api/jobs/{job_id}/requeue": STATE,
    "/api/orders/{order_id}/cancel": STATE,
    "/api/fulfillments/{fulfillment_id}/complete": STATE,
    "/api/fulfillments/{fulfillment_id}/cancel": STATE,
    "/api/fulfillments/{fulfillment_id}/fail": STATE,
    "/api/national-transpositions/{transposition_id}/withdraw": STATE,
    "/api/pipeline/kill-switch": STATE,
    "/api/pipeline/reviews/{review_id}/approve": STATE,
    "/api/pipeline/reviews/{review_id}/reject": STATE,
    "/api/pipeline/runs/{correlation_id}/cancel": STATE,
    "/api/pipeline/runs/{correlation_id}/resume": STATE,
    "/api/regulatory-requirements/{requirement_id}/supersede": STATE,
    "/api/regulatory-requirements/{requirement_id}/withdraw": STATE,
    # Registros propios, sin efecto fuera del sistema.
    "/api/cfo/runs": DRAFT,
    "/api/ecommerce/runs": DRAFT,
    "/api/economics/runs": DRAFT,
    "/api/exchange-rates": DRAFT,
    "/api/incidents": DRAFT,
    "/api/marketing/runs": DRAFT,
    "/api/marketplace/runs": DRAFT,
    "/api/objectives": DRAFT,
    "/api/operations/runs": DRAFT,
    "/api/products/{product_id}/compliance-evidence": DRAFT,
    "/api/regulatory-requirements": DRAFT,
    "/api/regulatory-requirements/{requirement_id}/national-transpositions": DRAFT,
    "/api/sourcing/runs": DRAFT,
    "/api/suppliers": DRAFT,
    "/api/suppliers/{supplier_id}/capabilities": DRAFT,
    "/api/suppliers/{supplier_id}/quotes": DRAFT,
}


@pytest.fixture(scope="module")
def post_routes() -> dict[str, list[str]]:
    spec = app.openapi()
    return {
        path: [parameter["name"] for parameter in item["post"].get("parameters", [])]
        for path, item in spec["paths"].items()
        if "post" in item
    }


def test_every_post_route_is_classified(post_routes):
    unclassified = sorted(set(post_routes) - set(CLASSIFICATION))

    assert unclassified == [], (
        f"new POST routes with no idempotency classification: {unclassified}. "
        "Decide what happens when the request is repeated and add them to CLASSIFICATION (ADR 0025 §6)."
    )


def test_no_classified_route_has_disappeared(post_routes):
    assert sorted(set(CLASSIFICATION) - set(post_routes)) == []


@pytest.mark.parametrize("path", sorted(p for p, kind in CLASSIFICATION.items() if kind == GENERIC))
def test_a_generic_route_declares_the_idempotency_header(post_routes, path):
    assert "Idempotency-Key" in post_routes[path]


def test_the_pipeline_run_declares_its_own_header(post_routes):
    assert "Idempotency-Key" in post_routes["/api/pipeline/runs"]


@pytest.mark.parametrize("path", sorted(p for p, kind in CLASSIFICATION.items() if kind in (STATE, DRAFT, WEBHOOK)))
def test_a_state_draft_or_webhook_route_does_not_pretend_to_be_idempotent(post_routes, path):
    assert "Idempotency-Key" not in post_routes[path]


@pytest.mark.parametrize("path", sorted(p for p, kind in CLASSIFICATION.items() if kind == EXTERNAL_WRITE))
def test_an_external_write_declares_the_idempotency_header(post_routes, path):
    assert "Idempotency-Key" in post_routes[path]


def test_every_route_that_moves_orders_or_money_is_classified_by_what_it_does():
    """Una ruta nueva bajo pedidos o pagos no puede ser un borrador: o es una transición con compare-and-set, o una
    operación externa gobernada, o un webhook (ADR 0028)."""
    allowed = {GENERIC, STATE, EXTERNAL_WRITE, WEBHOOK}
    for path, kind in CLASSIFICATION.items():
        if path.startswith(("/api/orders", "/api/payments", "/api/fulfillments")):
            assert kind in allowed, f"{path} is {kind}"
