# Milestone 12 Demo

**Tickets:** IVA-29 (Fase 4.1) + IVA-30 (Fase 4.2) — Linear, proyecto
"Fase 4 — Integración y pruebas".

Arquitectura: [ADR 0005](../architecture/adr-0005-fase-3-pipeline-orchestrator.md)
(nuevo orquestador de pipeline, separado de `CEOOrchestrator`/`planner.py`/
`decision_engine.py`). Plan completo:
[`docs/superpowers/plans/2026-09-16-amazona-milestone-12.md`](../superpowers/plans/2026-09-16-amazona-milestone-12.md).

## Investigación previa (resumen)

Antes de escribir código se verificó en el código, no solo se infirió,
que `CEOOrchestrator.run_objective()`/`plan_product_validation()`
(`backend/app/ceo/`) solo encadenan los 4 agentes "validar-uno" de
Milestone 1 (`market_validation`, `supplier_sourcing`,
`financial_validation`, `legal_validation`). Los 9 pasos de Fase 3
(research, sourcing, economics, legal_compliance, ecommerce,
marketplace, marketing, operations, CFO) existen cada uno con su propio
servicio + API + página, pero ninguno se invoca desde el orquestador —
confirmado por grep, cero referencias cruzadas. El cierre de Fase 3
(`milestone-9-demo.md`) ya documentaba esto como "manual hoy" y ADR 0004
reserva explícitamente cualquier encadenado automático para una ADR
nueva. Este milestone es esa ADR y esa implementación.

## Decisión de alcance

- Nuevo componente `PipelineOrchestrator` (`backend/app/pipeline/`),
  totalmente separado de `planner.py`/`decision_engine.py`/
  `CEOOrchestrator`, que no se tocan.
- Selección determinista: mejor candidato de research por
  `opportunity_score` descendente; mejor cotización de sourcing por
  `total_landed_cost_per_unit` ascendente — mismo criterio que cada
  agente ya usa internamente.
- Ningún paso detiene la cadena por `NO_GO`/`BLOCKED` — se registra en
  `steps` y se sigue adelante, igual que ya ocurre hoy entre servicios.
  El pipeline solo queda `PARTIAL` si un paso no puede producir ningún
  resultado (research sin candidatos para la categoría, o sourcing sin
  cotizaciones).
- CFO se ejecuta como noveno y último paso, cerrando el recorrido
  "detectar oportunidad → ... → CFO" tal como pide el objetivo de Fase 4.
- Las 9 páginas/APIs individuales de Fase 3 siguen existiendo sin
  cambios, para uso independiente y depuración.

## Flujo completo

```bash
curl -s -X POST http://localhost:8000/api/pipeline/runs \
  -H "Content-Type: application/json" \
  -d '{"category": "home", "sale_price": 50.0, "destination_region": "mexico",
       "market": "us", "marketplace_platform": "amazon",
       "marketing_platform": "google", "daily_budget": 20.0}'
# -> {"correlation_id": "...", "product_id": "...", "status": "COMPLETED",
#     "steps": {"research": {...}, "sourcing": {...}, "economics": {...},
#     "legal": {...}, "ecommerce": {...}, "marketplace": {...},
#     "marketing": {...}, "operations": {...}, "cfo": {...}}}

curl -s http://localhost:8000/api/pipeline/runs/<correlation_id>
curl -s http://localhost:8000/api/pipeline/runs
```

O desde el Control Center: **Pipeline** (nueva página, primera en el
menú) → un solo formulario (categoría, mercado, región de destino,
precio de venta, presupuesto diario) → *Run full pipeline* → ver los 9
pasos con su recomendación/estado, en una sola ejecución.

**Verificado manualmente en el navegador**: con `category=home`,
`sale_price=50`, `destination_region=mexico`, un solo clic produjo
`COMPLETED` con los 9 pasos: 3 candidatos de research, 3 cotizaciones de
sourcing, economics `GO`, legal `GO`, ecommerce/marketplace/marketing/
operations `READY`, CFO `HEALTHY` — sin ningún ID copiado a mano.
Verificado también a 375px de ancho (mobile).

Cada paso conserva su propio `correlation_id` — 10 en total por
ejecución completa (9 pasos + el del pipeline), todos reconstruibles vía
`GET /api/audit?correlation_id=` — cubierto por
`backend/tests/e2e/test_full_pipeline_internal_orchestration_flow.py`,
que verifica el camino sano (con los IDs reales enhebrados
automáticamente — p. ej. `operations.marketing_campaign_id` apunta
exactamente a la campaña que este mismo pipeline creó), el camino
`NO_GO` en economics **sin detener la cadena**, y el camino `PARTIAL`
cuando research no encuentra candidatos para la categoría.

## Base de datos: tabla `pipeline_runs`

`pipeline_runs` vincula opcionalmente un `Product` (nulo en un run
`PARTIAL` que nunca llegó a elegir uno) a un resumen de los 9 pasos
(`steps`, JSON) más `status`/`failed_step`. RLS activado en su propia
migración (`81219be53fb3_add_pipeline_runs_table.py`), mismo patrón que
las tablas de los milestones anteriores.

**Verificado contra Supabase real.** La migración se aplicó contra el
proyecto `amazona` (`0f533b205aef → 81219be53fb3`), y
`SELECT relrowsecurity FROM pg_class WHERE relname = 'pipeline_runs'`
confirma `true`. `get_advisors` (linter de seguridad de Supabase)
reporta **0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 445 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

## Qué queda para el resto de Fase 4

- **IVA-31 + IVA-32 (Milestone 13):** validar el pipeline con casos de
  producto realistas (no solo las categorías de fixture) y ajustar
  errores/rendimiento que surjan de esa validación.
- **IVA-33 (Milestone 14):** controles humanos críticos sobre el
  pipeline ya automatizado — hoy nada impide que un `NO_GO`/`BLOCKED`
  agregado pase desapercibido si nadie revisa `steps` manualmente; este
  milestone formaliza dónde y cómo un humano debe intervenir.
- **IVA-34 (Milestone 15):** documentación completa del sistema, cierre
  de Fase 4.
