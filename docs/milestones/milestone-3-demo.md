# Milestone 3 Demo

Plan completo:
[`docs/superpowers/plans/2026-09-16-amazona-milestone-3.md`](../superpowers/plans/2026-09-16-amazona-milestone-3.md).
Arquitectura:
[ADR 0003](../architecture/adr-0003-rls-deny-by-default.md)
(RLS deny-by-default — `supplier_quotes` nace ya con RLS activado) y
[ADR 0004](../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
(pares de capacidades "validar uno" vs "descubrir muchos").

## Flujo completo: Investigación → Sourcing → Validación (Fase 3, Agentes 1 + 2)

```bash
# 1. Investigar una categoría (Fase 3, Agente 1 — sin cambios desde Milestone 2)
curl -s -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" \
  -d '{"category": "electronics", "max_results": 5}'
# -> {"correlation_id": "...", "candidates": [{"product_id": ..., "name": ...,
#     "opportunity_score": ..., "data": {"demand_signal": ..., "competition_level": ...}}]}

# 2. Buscar proveedores para el candidato mejor puntuado (Fase 3, Agente 2)
curl -s -X POST http://localhost:8000/api/sourcing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "category": "electronics", "destination_region": "mexico", "max_results": 5}'
# -> {"correlation_id": "...", "quotes": [{"supplier_id": ..., "unit_price": ...,
#     "moq": ..., "lead_time_days": ..., "verified": ..., "reliability_score": ...,
#     "logistics_cost_per_unit": ..., "total_landed_cost_per_unit": ...}]}
# ordenado por total_landed_cost_per_unit ascendente — el primero es el mejor
# coste total aterrizado, no necesariamente el precio unitario más bajo.

# 3. Validar el producto + proveedor elegidos a través del flujo CEO de Milestone 1
curl -s -X POST http://localhost:8000/api/objectives \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Validate <candidate> with <supplier>",
    "created_by": "owner@amazona.local",
    "context": {
      "product_validation": {"estimated_monthly_searches": <demand_signal*15000>, "competition_level": "<competition_level>"},
      "supplier_sourcing": {"unit_cost": <unit_price>, "lead_time_days": <lead_time_days>, "supplier_verified": <verified>},
      "finance_validation": {"unit_cost": <unit_price>, "sale_price": 20.0, "monthly_unit_sales": 300, "monthly_fixed_costs": 500.0},
      "legal_validation": {"restricted_category": false}
    }
  }'

curl -s -X POST http://localhost:8000/api/objectives/<objective_id>/run
```

O desde el Control Center: página **Research** → *Run research* → *Find
suppliers* en el candidato deseado → salta a **Sourcing** con el
`product_id`/categoría ya rellenados → *Run sourcing* → *Validate with
this supplier* en el proveedor deseado → salta a **CEO** con
`supplier_sourcing` (unit_cost/lead_time_days/supplier_verified) ya
rellenado → *Create & run objective*.

Los tres runs (investigación, sourcing y validación) tienen
`correlation_id` distintos y son los tres 100% reconstruibles vía
`GET /api/audit?correlation_id=` — cubierto por
`backend/tests/e2e/test_supplier_sourcing_to_validation_flow.py`.

**Verificado manualmente en el navegador** (Control Center + backend
contra una base SQLite local de desarrollo, ver nota de conectividad
más abajo): el flujo completo Research → Find suppliers → Run sourcing
→ Validate with this supplier → Create & run objective termina en una
decisión `HUMAN_APPROVAL` con `opportunity_score=0.72`,
`confidence=0.85`, usando el `unit_cost`/`lead_time_days` reales del
proveedor elegido (no valores de ejemplo hardcodeados) en la evidencia
de `supplier_sourcing`. Verificado también a 375px de ancho (mobile).

## Dos agentes de proveedores, dos capacidades (ADR 0004)

- `SupplierAgent` (Milestone 1, capability `supplier_sourcing`): valida
  UNA cotización de proveedor ya elegida dentro del grafo de tareas de
  un objetivo — sin cambios en este milestone.
- `SupplierSourcingAgent` (Milestone 3, capability
  `supplier_sourcing_research`): descubre y rankea VARIOS proveedores
  globales por coste total aterrizado (precio unitario + logística
  estimada), a través de su propio flujo (`/api/sourcing`, página
  "Sourcing").

Ambos coexisten registrados en `build_default_agent_manager()` (6
agentes en total tras este milestone). Ver
[ADR 0004](../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
para la convención general que sigue este patrón de cara a los Agentes
3-8.

## Fuentes simuladas

- `MockSupplierDirectory` (`backend/app/ai/mock_supplier_directory.py`):
  directorio determinista de proveedores por categoría (China, Vietnam,
  México, UE), sin llamadas de red.
- `estimate_logistics_cost` (`backend/app/sourcing/logistics.py`):
  calculadora determinista de coste logístico (flete simulado + factor
  de aduana simulado por par de regiones), documentada explícitamente
  como placeholder hasta que exista un proveedor de tarifas real.

## Base de datos: tabla `supplier_quotes`

`supplier_quotes` vincula un `Product` con un `Supplier` para una
cotización de un run de sourcing concreto (precio, MOQ, lead time,
fiabilidad, coste logístico, coste total aterrizado). A diferencia de
las 24 tablas de Milestone 1/2 (que necesitaron una migración
retroactiva para activar RLS, ver ADR 0003), `supplier_quotes` nace con
RLS activado en su propia migración
(`60efd4316cac_add_supplier_quotes_table.py`).

**Verificación pendiente contra Postgres real:** este entorno de
desarrollo no tiene Postgres local disponible (sin Docker), así que la
migración se verificó por compilación/sintaxis (`alembic heads`,
`py_compile`) y por su reutilización literal del patrón `DO $$ ...
ENABLE ROW LEVEL SECURITY ... $$` ya probado en vivo por ADR 0003 — no
se ha podido ejecutar `alembic upgrade head` localmente en este
milestone. Queda verificada por el job de CI (Postgres efímero) en el
pull request, y pendiente de confirmación manual con
`get_advisors`/dashboard contra el proyecto Supabase real.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 210 tests, ~14s
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```
