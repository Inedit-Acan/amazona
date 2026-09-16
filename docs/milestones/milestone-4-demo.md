# Milestone 4 Demo

**Ticket:** IVA-52 (Linear).

Plan completo:
[`docs/superpowers/plans/2026-09-16-amazona-milestone-4.md`](../superpowers/plans/2026-09-16-amazona-milestone-4.md).
Arquitectura:
[ADR 0003](../architecture/adr-0003-rls-deny-by-default.md)
(RLS deny-by-default — `economic_analyses` nace ya con RLS activado) y
[ADR 0004](../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
(pares de capacidades "validar uno" vs "descubrir muchos").

## Flujo completo: Investigación → Sourcing → Análisis Económico → Validación (Fase 3, Agentes 1 + 2 + 3)

```bash
# 1. Investigar una categoría (Fase 3, Agente 1 — sin cambios desde Milestone 2)
curl -s -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" \
  -d '{"category": "electronics", "max_results": 5}'
# -> {"correlation_id": "...", "candidates": [{"product_id": ..., "name": ...,
#     "opportunity_score": ..., "data": {"demand_signal": ..., "competition_level": ...}}]}

# 2. Buscar proveedores para el candidato mejor puntuado (Fase 3, Agente 2 — sin cambios desde Milestone 3)
curl -s -X POST http://localhost:8000/api/sourcing/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "category": "electronics", "destination_region": "mexico", "max_results": 5}'
# -> {"correlation_id": "...", "quotes": [{"id": ..., "supplier_id": ..., "unit_price": ...,
#     "moq": ..., "lead_time_days": ..., "verified": ..., "reliability_score": ...,
#     "logistics_cost_per_unit": ..., "total_landed_cost_per_unit": ...}]}

# 3. Analizar viabilidad económica del producto + proveedor elegidos (Fase 3, Agente 3)
curl -s -X POST http://localhost:8000/api/economics/runs \
  -H "Content-Type: application/json" \
  -d '{"product_id": "<product_id>", "supplier_quote_id": "<quote_id>", "sale_price": 20.0}'
# -> {"correlation_id": "...", "margin_percent": ..., "recommendation": "GO|REVIEW|NO_GO",
#     "confidence": ..., "data": {"scenarios": {"conservative": {...}, "base": {...},
#     "optimistic": {...}}, "risks": [...], "evidence": [...]}}
# el coste aterrizado real (Agente 2) y la señal de demanda real (Agente 1) alimentan
# el cálculo — no hay datos de ejemplo hardcodeados en este paso.

# 4. Validar el trío producto + proveedor + análisis a través del flujo CEO de Milestone 1
curl -s -X POST http://localhost:8000/api/objectives \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Validate <candidate> with <supplier> economics",
    "created_by": "owner@amazona.local",
    "context": {
      "product_validation": {"estimated_monthly_searches": <demand_signal*15000>, "competition_level": "<competition_level>"},
      "supplier_sourcing": {"unit_cost": <unit_landed_cost>, "lead_time_days": <lead_time_days>, "supplier_verified": <verified>},
      "finance_validation": {"unit_cost": <unit_landed_cost>, "sale_price": <sale_price>, "monthly_unit_sales": <base.monthly_unit_sales>, "monthly_fixed_costs": <monthly_fixed_costs>},
      "legal_validation": {"restricted_category": false}
    }
  }'

curl -s -X POST http://localhost:8000/api/objectives/<objective_id>/run
```

O desde el Control Center: página **Research** → *Run research* → *Find
suppliers* en el candidato deseado → salta a **Sourcing** con el
`product_id`/categoría ya rellenados → *Run sourcing* → *Analyze
economics* en el proveedor deseado → salta a **Economics** con
`product_id`/`supplier_quote_id` ya rellenados → *Run analysis* → ver
el informe de viabilidad (tres escenarios + riesgos + recomendación) →
*Validate this analysis* → salta a **CEO** con `finance_validation`
(y `supplier_sourcing.unit_cost`) precargado desde los números reales
del análisis → *Create & run objective*.

Los cuatro runs (investigación, sourcing, análisis económico y
validación) tienen `correlation_id` distintos y son los cuatro 100%
reconstruibles vía `GET /api/audit?correlation_id=` — cubierto por
`backend/tests/e2e/test_economic_analysis_to_validation_flow.py`.

**Verificado manualmente en el navegador** (Control Center + backend
contra una base SQLite local de desarrollo, para no escribir datos de
prueba en el proyecto Supabase real): el flujo completo Research → Find
suppliers → Run sourcing → Analyze economics → Validate this analysis →
Create & run objective produjo un informe de viabilidad con margen
71.1%, escenario base de 244 unidades/mes con profit 2968.07, y una
decisión final `HUMAN_APPROVAL` cuya evidencia de `finance_validation`
(margen 71.15%, profit 2972.12) coincide con el informe económico — no
valores de ejemplo. Verificado también a 375px de ancho (mobile).

## Cómo encaja el Agente 3 (ADR 0004 aplicada, no una decisión nueva)

- `FinanceAgent` (Milestone 1, capability `financial_validation`):
  valida UN escenario financiero ya dado dentro del grafo de tareas de
  un objetivo — sin cambios en este milestone.
- `EconomicAnalysisAgent` (Milestone 4, capability
  `economic_risk_analysis`): calcula tres escenarios deterministas
  (conservador/base/optimista) y riesgos para un producto+proveedor ya
  reales, a través de su propio flujo (`/api/economics`, página
  "Economics"). Variante del patrón de ADR 0004: en vez de rankear N
  candidatos de un directorio (como hacen los Agentes 1 y 2), calcula N
  *escenarios* para una única combinación — mismo espíritu: vive fuera
  del grafo fijo del planner/`decision_engine.py`, nunca sustituye la
  aprobación humana.
- **Diferencia clave con los Agentes 1 y 2:** el Agente 3 no tiene su
  propio *mock provider* de mercado — consume `ProductAnalysis`
  (`analysis_type="research"`) y `SupplierQuote`
  (`analysis_type="sourcing"`) ya reales, persistidas por los Agentes 1
  y 2. Los únicos supuestos simulados son la conversión demanda→ventas
  y los factores de los tres escenarios (`backend/app/economics/scenarios.py`),
  documentados explícitamente como placeholders — igual estándar que
  `MockTrendsProvider`/`estimate_logistics_cost`.

Ambos coexisten registrados en `build_default_agent_manager()` (7
agentes en total tras este milestone).

## Base de datos: tabla `economic_analyses`

`economic_analyses` vincula un `Product` y un `SupplierQuote` a un
informe de viabilidad (precio de venta, margen base, recomendación,
desglose completo de escenarios + riesgos + evidencia en `data`). RLS
activado en su propia migración
(`5264d502182d_add_economic_analyses_table.py`), mismo patrón que
`supplier_quotes` (Milestone 3).

**Verificado contra Supabase real.** `alembic upgrade head` se ejecutó
contra el proyecto `amazona` (`60efd4316cac → 5264d502182d`), y
`SELECT relrowsecurity FROM pg_class WHERE relname = 'economic_analyses'`
confirma `true`. `get_advisors` (linter de seguridad de Supabase)
reporta **0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 244 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```
