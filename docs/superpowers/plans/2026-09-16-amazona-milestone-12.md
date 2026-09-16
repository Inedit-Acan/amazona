# AMAZONA Milestone 12 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1-11.

**Tickets:** IVA-29 (Fase 4.1, "Integrar agentes en entorno común") +
IVA-30 (Fase 4.2, "Pruebas individuales y de flujo completo") — Linear,
proyecto "Fase 4 — Integración y pruebas".

**Objetivo:** construir un `PipelineOrchestrator` que encadene
automáticamente los 9 pasos de Fase 3 (Research → Sourcing → Economics →
Legal Compliance → Ecommerce → Marketplace → Marketing → Operations →
CFO) en una sola ejecución, sustituyendo el recorrido manual de 9
páginas documentado como pendiente en el cierre de Fase 3
(`milestone-9-demo.md`). Se entrega junto con los tests de flujo
completo que verifican la nueva orquestación interna (a diferencia de
los tests e2e existentes, que verifican la cadena orquestándola ellos
mismos por HTTP).

**Depende de:** ADR 0001, ADR 0003, ADR 0004, y el nuevo
[ADR 0005](../../architecture/adr-0005-fase-3-pipeline-orchestrator.md)
(decisión de diseño de este milestone).

**Investigación previa:** confirmado en el código (no solo inferido)
que ni `orchestrator.py` ni `planner.py` invocan ninguno de los 9
agentes de Fase 3/CFO — `SPECIALIST_TASK_NAMES` solo cubre los 4
agentes "validar-uno" de Milestone 1. Los 9 servicios de Fase 3 ya
resuelven su propia data ascendente por `product_id`(+`market`) más
reciente — el pipeline solo necesita invocarlos en orden con los IDs
correctos, no reimplementar su lógica de resolución.

## Decisión de alcance

- El pipeline **nunca detiene la cadena** por un `NO_GO`/`BLOCKED`
  intermedio — mismo comportamiento que ya existe hoy entre servicios
  (ver ADR 0005). Solo se marca `PARTIAL` si un paso no puede ejecutarse
  en absoluto (p. ej. research sin candidatos para la categoría).
- El pipeline **no reemplaza** las 9 páginas/APIs individuales — siguen
  existiendo para uso independiente y depuración; el pipeline es una
  nueva forma de invocarlas todas juntas.
- `planner.py`/`decision_engine.py`/`CEOOrchestrator` no se tocan.
- Selección determinista: mejor candidato de research por
  `opportunity_score` descendente; mejor cotización de sourcing por
  `total_landed_cost_per_unit` ascendente — mismo criterio que cada
  agente ya usa internamente.
- `sale_price` sigue siendo una entrada de negocio explícita (no se
  deriva de nada) — igual que hoy en `EconomicAnalysisService`.
- CFO se ejecuta como último paso del pipeline (catálogo completo, no
  solo el producto de esta ejecución) — cierra el recorrido "detectar
  oportunidad → ... → CFO" tal como se describe en el objetivo de Fase 4.

## Restricciones globales (heredadas)

- Toda tabla nueva nace con RLS activado en su propia migración (ADR 0003).
- Tests antes que implementación. Commit por tarea completada.
- Ningún test de Milestone 1-11 cambia de resultado (salvo el conteo de
  agentes registrados, que no cambia — el pipeline no es un agente
  nuevo, es un orquestador que reutiliza los 9 existentes).

---

## Estructura de archivos

```text
backend/
├── app/
│   ├── pipeline/
│   │   ├── __init__.py
│   │   └── service.py              # PipelineOrchestrator
│   ├── api/
│   │   └── pipeline.py
│   └── db/models/
│       └── pipeline_run.py         # tabla pipeline_runs
├── alembic/versions/                 # nueva migración incremental
└── tests/
    ├── unit/
    │   └── test_pipeline_orchestrator_selection.py   # mejor candidato/cotización
    ├── integration/
    │   ├── test_pipeline_run_model.py
    │   ├── test_pipeline_orchestrator_service.py
    │   └── test_pipeline_api.py
    └── e2e/
        └── test_full_pipeline_internal_orchestration_flow.py

apps/control-center/
├── app/
│   └── pipeline/page.tsx           # un formulario, un botón, todo el recorrido
├── lib/api.ts                      # +createPipelineRun, tipos
└── components/nav-items.ts         # +"Pipeline"
```

---

## Sección A — Persistencia

### Tarea 1: Tabla `pipeline_runs` (con RLS desde su propia migración)

**Files:**
- Create: `backend/app/db/models/pipeline_run.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration
- Create: `backend/tests/integration/test_pipeline_run_model.py`

**Esquema:** id, product_id (FK `products.id`, nullable — puede ser
`None` en un `PARTIAL` si research no llegó a producir un candidato),
category, market, status (`COMPLETED`/`PARTIAL`), failed_step
(nullable), steps (JSON — por paso: `correlation_id`, `entity_id`,
`status`/`recommendation`), correlation_id, created_at/updated_at.

- [ ] Test: crear con `product_id` válido y `product_id=None`, verificar
      persistencia de ambos.
- [ ] Implementar modelo + migración; aplicar a Supabase real y
      confirmar `relrowsecurity=true` + `get_advisors` en 0 vía MCP.
- [ ] Commit: `feat: add pipeline runs table with rls enabled`

---

## Sección B — Orquestador

### Tarea 2: `PipelineOrchestrator` — selección de mejor candidato/cotización

**Files:**
- Create: `backend/app/pipeline/service.py`
- Create: `backend/tests/unit/test_pipeline_orchestrator_selection.py`

- [ ] Test: dado un `ResearchService.run_research` con varios
      candidatos, el pipeline elige el de `opportunity_score` más alto.
- [ ] Test: dado un `SourcingService.run_sourcing` con varias
      cotizaciones, el pipeline elige la de `total_landed_cost_per_unit`
      más bajo.
- [ ] Implementar `_pick_best_candidate`/`_pick_best_quote` como
      funciones puras testeables por separado del flujo completo.
- [ ] Commit: `feat: add pipeline orchestrator candidate and quote selection`

### Tarea 3: `PipelineOrchestrator.run_pipeline` — encadena los 9 pasos

**Files:**
- Modify: `backend/app/pipeline/service.py`
- Create: `backend/tests/integration/test_pipeline_orchestrator_service.py`

- [ ] Test: con datos que producen resultados sanos en cada paso, el
      pipeline queda `COMPLETED` y `pipeline_runs.steps` tiene los 9
      pasos con sus `correlation_id`/IDs de entidad reales.
- [ ] Test: cuando economics devuelve `NO_GO`, el pipeline **continúa**
      hasta el final (no se detiene) y lo refleja en `steps`.
- [ ] Test: si research no produce ningún candidato para la categoría,
      el pipeline queda `PARTIAL` con `failed_step="research"`, sin
      excepción sin capturar.
- [ ] Test: CFO se ejecuta como último paso y su reporte incluye el
      producto de esta ejecución.
- [ ] Commit: `feat: add pipeline orchestrator chaining all nine fase 3 steps`

---

## Sección C — API

### Tarea 4: API de pipeline

**Files:**
- Create: `backend/app/api/pipeline.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_pipeline_api.py`

**Produces:**
- `POST /api/pipeline/runs` → `{category, market?, destination_region?,
  sale_price, platform_marketplace?, platform_marketing?,
  daily_budget?, certification_available?, max_results?}`, ejecuta y
  persiste, devuelve el resultado completo (los 9 pasos).
- `GET /api/pipeline/runs/{correlation_id}` → reconstruido desde DB.
- `GET /api/pipeline/runs` → listado, más reciente primero.

- [ ] Test: creación exitosa devuelve los 9 pasos con sus
      `recommendation`/`status`.
- [ ] Test: reconstrucción por `correlation_id` idéntica.
- [ ] Test: `PARTIAL` (sin candidatos) devuelve 201 igualmente (es un
      resultado válido, no un error HTTP) con `status="PARTIAL"`.
- [ ] Commit: `feat: add pipeline api`

---

## Sección D — Control Center

### Tarea 5: Página "Pipeline"

**Files:**
- Create: `apps/control-center/app/pipeline/page.tsx`
- Modify: `apps/control-center/lib/api.ts`
- Modify: `apps/control-center/components/nav-items.ts`

**Produces:** un formulario (categoría, mercado, precio de venta,
presupuesto diario, plataformas) que dispara el pipeline completo y
pinta los 9 pasos con su estado, más un enlace a cada entidad creada
(producto, cotización, etc.) para depuración.

- [ ] Verificar en navegador (desktop + mobile) con datos reales del
      backend.
- [ ] Commit: `feat: add pipeline page`

---

## Sección E — Verificación end-to-end

### Tarea 6: E2E interno + doc de cierre

**Files:**
- Create: `backend/tests/e2e/test_full_pipeline_internal_orchestration_flow.py`
- Create: `docs/milestones/milestone-12-demo.md`

**Escenario:** UNA sola llamada `POST /api/pipeline/runs` (a diferencia
de `test_operations_to_full_chain_flow.py`, que hace 8 llamadas
manuales) produce los 9 registros esperados, con IDs correctamente
enhebrados, verificable vía `GET /api/pipeline/runs/{correlation_id}` y
`GET /api/audit?correlation_id=` para cada paso.

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar en `docs/milestones/milestone-12-demo.md` (mismo
      formato que milestones anteriores).
- [ ] Ejecutar `get_advisors` (seguridad) contra el proyecto Supabase
      real tras la migración de la Tarea 1, documentar 0 hallazgos.
- [ ] Commit: `test: verify full pipeline orchestration end to end`

---

## Definition of Done — Milestone 12

1. `pipeline_runs` es una tabla real, con RLS activado desde su propia
   migración, verificada contra Supabase real.
2. `PipelineOrchestrator` encadena los 9 pasos de Fase 3 en una sola
   invocación, sin modificar `planner.py`/`decision_engine.py`/`CEOOrchestrator`.
3. Existe una API de pipeline auditada con `correlation_id` propio, que
   no sustituye los `correlation_id` individuales de cada paso.
4. El Control Center tiene una página "Pipeline" que ejecuta el
   recorrido completo con un solo formulario.
5. El flujo E2E demuestra `COMPLETED` con los 9 pasos reales y
   `PARTIAL` cuando research no encuentra candidatos.
6. El linter de seguridad de Supabase sigue en verde tras la migración.
7. `docs/milestones/milestone-12-demo.md` documenta el milestone.
8. Ningún test de Milestone 1-11 cambia de resultado.
