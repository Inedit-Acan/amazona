# Milestone 8 Demo

**Ticket:** IVA-56 (Linear).

Plan completo:
[`docs/superpowers/plans/2026-09-16-amazona-milestone-8.md`](../superpowers/plans/2026-09-16-amazona-milestone-8.md).
Arquitectura:
[ADR 0003](../architecture/adr-0003-rls-deny-by-default.md)
(RLS deny-by-default — `marketing_campaigns` nace ya con RLS activado)
y [ADR 0004](../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
(convención de capacidades, aplicada como estilo — sin contraparte de
Milestone 1, igual que los Agentes 5 y 6).

## Hallazgo clave: el mecanismo de aprobación de gasto ya existía desde Milestone 1

Al revisar `app/ceo/orchestrator.py` antes de diseñar este agente se
encontró que el flujo `requests_simulated_spend` /
`spend_action` / `spend_amount` (que dispara `BudgetEngine.authorize()`
y crea una fila `Approval` pendiente de un humano) **ya existía desde
Milestone 1**, con un valor de ejemplo hardcodeado literalmente
`spend_action: "launch_marketing_campaign"`, `spend_amount: 150.0` — un
placeholder inventado a falta de un agente real de marketing. Este
milestone cierra ese hueco exactamente igual que Milestone 5 cerró el
de `restricted_category`: el Agente 7 calcula un presupuesto diario
real recomendado, y el puente "Validate this campaign" hacia la página
CEO precarga `spend_amount` con ese valor real — sin tocar el motor de
presupuesto ni `decision_engine.py`.

## Decisión de alcance (enunciado ambiguo, interpretación documentada)

- **Diseñar campañas (Meta, Google, etc.)** → propuesta determinista
  por producto×mercado×plataforma — no se crea ninguna campaña real, no
  hay credenciales de Meta/Google/TikTok Ads.
- **Segmentar audiencias** → 2-3 segmentos deterministas derivados de
  categoría/competencia real (Agente 1).
- **Generar creatividades (texto/imagen)** → copy de anuncio
  determinista **y un brief de imagen en texto** (descripción, estilo,
  dimensiones) — no se genera ninguna imagen real; es una
  especificación para un humano o una herramienta de diseño.
- **Analizar rendimiento (ROI)** → estimación determinista de
  CTR/CPC/conversión/ROAS, marcada `data_origin:
  "simulated_ad_performance_estimate"` — sin integración real con
  ninguna API de Ads.
- **Optimizar presupuesto** → recomendación determinista
  (subir/mantener/bajar) basada en el ROAS proyectado real — sin
  optimizador multi-plataforma en este milestone.
- **Presupuesto/gasto:** siempre simulado; si se valida la campaña,
  entra al mecanismo de aprobación humana ya existente desde
  Milestone 1 — nunca se ejecuta un cargo real.

## Flujo completo: Investigación → ... → Marketing → Validación (Fase 3, Agentes 1-7)

```bash
# 1-6. Investigar, sourcear, economía, legal, tienda, listing (sin cambios desde Milestone 2-7)
curl -s -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" -d '{"category": "home", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/sourcing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "category": "home", "destination_region": "mexico", "max_results": 5}'
curl -s -X POST http://localhost:8000/api/economics/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "supplier_quote_id": "<quote_id>", "sale_price": 50.0}'
curl -s -X POST http://localhost:8000/api/legal/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us", "certification_available": true}'
curl -s -X POST http://localhost:8000/api/ecommerce/runs \
  -H "Content-Type: application/json" -d '{"product_id": "<product_id>", "market": "us"}'
curl -s -X POST http://localhost:8000/api/marketplace/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us", "platform": "amazon"}'

# 7. Diseñar la campaña de marketing (Fase 3, Agente 7)
curl -s -X POST http://localhost:8000/api/marketing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "market": "us", "platform": "google", "daily_budget": 20.0}'
# -> {"correlation_id": "...", "campaign_status": "READY|NEEDS_REVIEW|BLOCKED",
#     "daily_budget": 20.0, "data": {"audience_segments": [...], "ad_creative":
#     {"image_brief": "..."}, "performance_estimate": {..., "data_origin":
#     "simulated_ad_performance_estimate", "projected_roas": 2.27},
#     "budget_recommendation": "..."}}

# 8. Validar el conjunto completo — spend_amount usa el presupuesto REAL recomendado
curl -s -X POST http://localhost:8000/api/objectives \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Validate <candidate> full chain",
    "created_by": "owner@amazona.local",
    "context": {
      "product_validation": {...}, "supplier_sourcing": {...},
      "finance_validation": {...}, "legal_validation": {...},
      "requests_simulated_spend": true,
      "spend_action": "launch_marketing_campaign",
      "spend_amount": 20.0
    }
  }'
curl -s -X POST http://localhost:8000/api/objectives/<objective_id>/run
# -> decision.status == "HUMAN_APPROVAL"; GET /api/approvals muestra una fila
#    pendiente con amount=20.0 (no 150.0)
```

O desde el Control Center: **Research** → ... → **Marketplace** → *Plan
marketing campaign* → **Marketing** → ver la propuesta (creatividad,
segmentos, rendimiento simulado, recomendación de presupuesto) →
*Validate this campaign* → salta a **CEO** con `spend_amount` real
precargado → *Create & run objective* → decisión `HUMAN_APPROVAL`.

Los siete runs de agentes + la validación tienen ocho `correlation_id`
distintos, todos reconstruibles vía `GET /api/audit?correlation_id=` —
cubierto por
`backend/tests/e2e/test_marketing_campaign_to_validation_flow.py`, que
verifica el camino sano completo hasta `HUMAN_APPROVAL` con el
`Approval.amount` real (no `150.0`), y el camino bloqueado por un ROAS
proyectado débil (`accessories` a precio bajo en `meta`).

**Verificado manualmente en el navegador** (Control Center + backend
contra una base SQLite local de desarrollo): con `home` a $50 de precio
de venta, el pipeline completo de 7 agentes produjo una campaña `READY`
con ROAS proyectado de 2.27x, y al validar, la decisión del CEO llegó a
`HUMAN_APPROVAL` con una fila `Approval` pendiente confirmada vía
`GET /api/approvals` con `amount: 20.0` — el presupuesto real
recomendado, no el `150.0` de Milestone 1. Verificado también a 375px
de ancho (mobile).

## Base de datos: tabla `marketing_campaigns`

`marketing_campaigns` vincula un `Product` (y, opcionalmente, un
`MarketplaceListing` del mismo mercado) a una propuesta de campaña por
mercado×plataforma. RLS activado en su propia migración
(`e739124893e2_add_marketing_campaigns_table.py`), mismo patrón que las
tablas de los milestones anteriores.

**Verificado contra Supabase real.** `alembic upgrade head` se ejecutó
contra el proyecto `amazona` (`bcad811a07e4 → e739124893e2`), y
`SELECT relrowsecurity FROM pg_class WHERE relname = 'marketing_campaigns'`
confirma `true`. `get_advisors` (linter de seguridad de Supabase)
reporta **0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 369 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```
