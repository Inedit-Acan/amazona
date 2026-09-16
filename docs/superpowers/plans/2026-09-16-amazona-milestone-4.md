# AMAZONA Milestone 4 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1, 2 y 3.

**Ticket:** IVA-52 (Linear).

**Objetivo:** continuar la Fase 3 del roadmap con el tercer agente
operativo: **Agente 3, Análisis Económico y de Riesgo**. Dado un producto
ya investigado (Agente 1, Milestone 2) y un proveedor ya sourceado
(Agente 2, Milestone 3) — ambos ya persistidos en la base de datos, no
inventados de nuevo — calcula el coste total aterrizado, estima
márgenes, analiza tres escenarios (conservador/base/optimista) y evalúa
riesgos, produciendo un informe de viabilidad económica.

**Depende de:** Milestone 3 completo, [ADR 0001](../../architecture/adr-0001-orchestrator-vs-ceo.md),
[ADR 0002](../../architecture/adr-0002-agent-messaging-protocol.md),
[ADR 0003](../../architecture/adr-0003-rls-deny-by-default.md), y
[ADR 0004](../../architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md)
(pares de capacidades "validar uno" vs "descubrir muchos").

## Cómo encaja con lo ya construido (Agentes 1 y 2)

Antes de escribir código se revisó cómo se integraron los Agentes 1 y 2:

- **Fuente de datos:** a diferencia de `ProductResearchAgent` y
  `SupplierSourcingAgent` (que necesitaban un *mock provider* propio
  porque no había datos previos de los que partir), el Agente 3 consume
  datos **ya reales dentro del sistema** — la `ProductAnalysis`
  (`analysis_type="research"`) y el `SupplierQuote`
  (`analysis_type="sourcing"`) que Milestone 2 y 3 ya persisten. No
  necesita su propio *mock provider* de mercado; solo necesita
  supuestos deterministas y documentados para las dos cosas que ningún
  agente anterior calculó todavía: conversión de señal de demanda a
  ventas mensuales estimadas, y los factores de los tres escenarios.
- **Patrón agente/servicio:** igual que `ResearchService`/
  `SourcingService`, el `Agent` en sí (`EconomicAnalysisAgent`) es
  puro/sin DB — recibe un `dict` con valores ya resueltos (coste
  aterrizado, precio de venta, señal de demanda, etc.), nunca IDs de
  base de datos. Un `EconomicAnalysisService` nuevo hace el trabajo de
  resolver `product_id`/`supplier_quote_id` → filas reales → `dict` de
  entrada → invoca al agente → persiste el resultado — mismo reparto de
  responsabilidades que en Milestone 2/3.
- **API + auditoría + `correlation_id`:** mismo patrón que
  `/api/research` y `/api/sourcing` (`POST .../runs`,
  `GET .../runs/{correlation_id}`, endpoint de listado por producto,
  fila en `audit_log` con `correlation_id`).
- **Capability, ADR 0004:** `FinanceAgent` (Milestone 1, capability
  `financial_validation`) sigue validando UN escenario financiero ya
  dado dentro del grafo de tareas de un objetivo — sin cambios. El
  Agente 3 es la contraparte "descubre/analiza muchos" para el dominio
  financiero: capability nueva `economic_risk_analysis`. Es una
  variante del patrón de ADR 0004 (en vez de rankear N candidatos de un
  directorio, calcula N *escenarios* deterministas para una única
  combinación producto+proveedor) — mismo espíritu: vive fuera del
  grafo fijo del planner/`decision_engine.py`, expone su propio flujo
  de discovery, y nunca sustituye la aprobación humana. No hace falta
  una ADR nueva — es una aplicación directa de ADR 0004, documentada
  aquí y en el demo doc de cierre.
- **E2E:** se extiende
  `test_supplier_sourcing_to_validation_flow.py` a un cuarto paso
  (Análisis Económico) en un test nuevo, en vez de modificar el
  existente — Milestone 3 sigue siendo válido tal cual.

## Restricciones globales (heredadas)

- Sin dinero real, pedidos, proveedores ni impuestos reales.
- Los supuestos de conversión (demanda → ventas estimadas) y los
  factores de escenario (conservador/base/optimista) son deterministas
  y están documentados explícitamente como *placeholders* — mismo
  estándar que `MockTrendsProvider`/`estimate_logistics_cost`.
- El Agente 3 nunca ejecuta gasto ni compromete un pedido; es
  puramente informativo. Comprometerse con un producto/proveedor sigue
  pasando por el flujo de validación/aprobación existente.
- El núcleo de decisión determinista (`decision_engine.py`,
  `permissions/engine.py`, `budgets/engine.py`) no se toca — el Agente
  3 no se cablea en el grafo de tareas del planner en este milestone.
- Toda tabla nueva nace con RLS activado en su propia migración (ADR 0003).
- Tests antes que implementación. Commit por tarea completada.
- Ningún test de Milestone 1, 2 o 3 cambia de resultado.

---

## Estructura de archivos (adiciones sobre Milestone 3)

```text
backend/
├── app/
│   ├── economics/
│   │   ├── scenarios.py         # conversión demanda->ventas + factores de escenario (puro)
│   │   └── service.py           # EconomicAnalysisService
│   ├── agents/
│   │   └── economic_analysis.py # Agente 3 — capability economic_risk_analysis
│   ├── api/
│   │   └── economics.py
│   └── db/models/
│       └── economic_analysis.py # tabla economic_analyses
├── alembic/versions/             # nueva migración incremental
└── tests/
    ├── unit/
    │   ├── test_scenario_calculator.py
    │   └── test_economic_analysis_agent.py
    ├── integration/
    │   ├── test_economic_analysis_model.py
    │   ├── test_economic_analysis_service.py
    │   └── test_economics_api.py
    └── e2e/
        └── test_economic_analysis_to_validation_flow.py

apps/control-center/
├── app/
│   └── economics/page.tsx       # informe de viabilidad + puente a validación
├── lib/api.ts                   # +createEconomicAnalysisRun, tipos
└── components/nav-items.ts      # +"Economics"

docs/
└── milestones/
    └── milestone-4-demo.md
```

---

## Sección A — Supuestos deterministas de escenario

### Tarea 1: `scenarios.py` — conversión de demanda y factores de escenario

**Files:**
- Create: `backend/app/economics/scenarios.py`
- Create: `backend/tests/unit/test_scenario_calculator.py`

**Produces:** dos funciones puras:

```python
def estimate_monthly_unit_sales(demand_signal: float) -> float:
    """demand_signal (0-1, misma escala que MockTrendsProvider) -> ventas
    mensuales estimadas, vía una tasa de conversión fija documentada como
    placeholder (no un dato de mercado real)."""

def build_scenarios(
    *, unit_landed_cost: float, sale_price: float, monthly_unit_sales_base: float,
    monthly_fixed_costs: float,
) -> dict[str, ScenarioResult]:
    """Devuelve {"conservative": ..., "base": ..., "optimistic": ...} con
    factores fijos documentados (p. ej. 0.7 / 1.0 / 1.3) aplicados a
    monthly_unit_sales_base, cada uno con margin_percent, monthly_revenue,
    monthly_profit."""
```

- [ ] Test: `estimate_monthly_unit_sales` es determinista (mismo input →
      mismo output) y monótona creciente en `demand_signal`.
- [ ] Test: `build_scenarios` devuelve las tres claves esperadas, con
      `optimistic.monthly_profit > base.monthly_profit >
      conservative.monthly_profit` para un caso con margen positivo.
- [ ] Test: `margin_percent` es igual en los tres escenarios (el margen
      unitario no cambia con el volumen; lo que cambia es el volumen y
      por tanto el profit total) — evita el bug de recalcular mal el
      margen por escenario.
- [ ] Test: coste aterrizado ≥ precio de venta ⇒ margen negativo en los
      tres escenarios (no se oculta un margen negativo con optimismo de
      volumen).
- [ ] Implementar.
- [ ] Commit: `feat: add deterministic demand-to-sales and scenario calculators`

**Acceptance:** funciones puras, sin acceso a DB ni red, con los
supuestos documentados en un comentario corto explicando que son
placeholders.

---

## Sección B — Agente 3

### Tarea 2: `EconomicAnalysisAgent` — capability `economic_risk_analysis`

**Files:**
- Create: `backend/app/agents/economic_analysis.py`
- Create: `backend/tests/unit/test_economic_analysis_agent.py`
- Modify: `backend/app/agents/registry.py`

**Produces:** dado un input ya resuelto (coste aterrizado, precio de
venta, señal de demanda, fiabilidad/verificación del proveedor, lead
time, nivel de competencia — todos valores, no IDs), calcula margen,
tres escenarios, y evalúa riesgos.

```python
class EconomicAnalysisInput(BaseModel):
    unit_landed_cost: float
    sale_price: float
    demand_signal: float | None = None       # de la investigación (Agente 1), si existe
    monthly_unit_sales_base: float | None = None  # override manual, si no hay demand_signal
    monthly_fixed_costs: float = 500.0
    supplier_verified: bool | None = None
    lead_time_days: int | None = None
    competition_level: str | None = None
```

- [ ] Test: margen negativo en el escenario base ⇒
      `recommendation="NO_GO"` (mismo veto que `FinanceAgent`, aplicado
      aquí a un informe multi-escenario en vez de a un único veredicto).
- [ ] Test: margen positivo pero escenario conservador con profit
      negativo ⇒ `recommendation="REVIEW"`.
- [ ] Test: margen saludable en los tres escenarios y sin riesgos
      adicionales ⇒ `recommendation="GO"`.
- [ ] Test: proveedor no verificado / lead time > 45 días / competencia
      alta generan riesgos explícitos en `risks` (reutilizando los
      mismos umbrales que `SupplierAgent`/`SupplierSourcingAgent` —
      no se inventan umbrales nuevos sin motivo).
- [ ] Test: sin `demand_signal` ni `monthly_unit_sales_base` ⇒
      `AgentResultStatus.COMPLETED` con `recommendation="REVIEW"` y un
      riesgo explícito de datos insuficientes (mismo patrón que
      `ProductResearchAgent`/`SupplierSourcingAgent` sin datos).
- [ ] Implementar reutilizando `app/economics/scenarios.py`.
- [ ] Registrar en `build_default_agent_manager()` como
      `agent-economic-analysis-1`, capability `economic_risk_analysis`
      — **sin tocar** `agent-finance-1` (`financial_validation`).
- [ ] Commit: `feat: add economic analysis and risk agent`

**Acceptance:** `AgentResult` válido (mismo contrato de ADR 0002); los
6 agentes existentes siguen pasando sus tests sin modificarse.

---

## Sección C — Persistencia y API

### Tarea 3: Tabla `economic_analyses` (con RLS desde su propia migración)

**Files:**
- Create: `backend/app/db/models/economic_analysis.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration (incluye `ENABLE ROW LEVEL SECURITY` +
  política deny-all, mismo patrón que `60efd4316cac`)
- Create: `backend/tests/integration/test_economic_analysis_model.py`

**Esquema:**
- id, product_id (FK `products.id`), supplier_quote_id (FK
  `supplier_quotes.id`), analysis_type (default `"economic_risk"`),
  sale_price, monthly_fixed_costs, margin_percent (del escenario base),
  recommendation, confidence, data (JSON — escenarios completos +
  riesgos), correlation_id, created_at/updated_at.

- [ ] Test: crear con `product_id`/`supplier_quote_id` válidos, verificar
      persistencia.
- [ ] Test: FK inválida en cualquiera de los dos campos levanta
      `IntegrityError`.
- [ ] Implementar modelo + migración.
- [ ] Commit: `feat: add economic analyses table with rls enabled`

**Acceptance:** `alembic upgrade head` desde limpio crea la tabla sin
pasos manuales, en SQLite (dev) y Postgres (CI/Supabase).

---

### Tarea 4: `EconomicAnalysisService` — resuelve datos reales y persiste

**Files:**
- Create: `backend/app/economics/service.py`
- Create: `backend/tests/integration/test_economic_analysis_service.py`

**Produces:** dado `product_id` + `supplier_quote_id` + `sale_price`
(+ `monthly_fixed_costs` opcional), busca la `ProductAnalysis`
(`analysis_type="research"`) más reciente del producto para extraer
`demand_signal`/`competition_level`, busca el `SupplierQuote` por id
para extraer coste aterrizado/verificación/lead time, arma el
`task_input`, invoca al agente, persiste `EconomicAnalysis`, audita.

- [ ] Test: con investigación y sourcing previos para el mismo
      producto, el análisis usa `demand_signal`/`competition_level`
      reales de la `ProductAnalysis` (no un valor por defecto).
- [ ] Test: `product_id` o `supplier_quote_id` inexistentes ⇒
      `NotFoundError`.
- [ ] Test: `supplier_quote_id` que pertenece a OTRO producto ⇒
      `NotFoundError` explícito (no se cruzan datos de productos
      distintos silenciosamente).
- [ ] Test: auditoría con `correlation_id` (acción `economics.run`).
- [ ] Implementar.
- [ ] Commit: `feat: add economic analysis service resolving real research and sourcing data`

**Acceptance:** un análisis es 100% reconstruible desde DB; nunca
mezcla datos de un producto/proveedor con los de otro.

---

### Tarea 5: API de análisis económico

**Files:**
- Create: `backend/app/api/economics.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_economics_api.py`

**Produces:**
- `POST /api/economics/runs` → `{product_id, supplier_quote_id,
  sale_price, monthly_fixed_costs?}`, ejecuta y persiste, devuelve el
  informe completo (escenarios + riesgos + recomendación).
- `GET /api/economics/runs/{correlation_id}` → reconstruido desde DB.
- `GET /api/products/{product_id}/economics` → historial de análisis
  para un producto.

- [ ] Test: creación exitosa devuelve los tres escenarios y
      `recommendation`.
- [ ] Test: reconstrucción por `correlation_id` idéntica a la
      respuesta original.
- [ ] Test: 404 claro para producto o cotización inexistentes.
- [ ] Implementar.
- [ ] Commit: `feat: add economic analysis api`

**Acceptance:** mismo estándar de reconstruibilidad y manejo de
errores que `/api/research` y `/api/sourcing`.

---

## Sección D — Control Center

### Tarea 6: Página "Economics" + puente a validación

**Files:**
- Create: `apps/control-center/app/economics/page.tsx`
- Modify: `apps/control-center/lib/api.ts`
- Modify: `apps/control-center/components/nav-items.ts`
- Modify: `apps/control-center/app/sourcing/page.tsx` (botón "Analyze
  economics" junto a "Validate with this supplier")
- Modify: `apps/control-center/app/ceo/page.tsx` (aceptar
  `sale_price`/`monthly_fixed_costs`/margen precalculado vía query
  params, igual patrón que los handoffs anteriores)

**Produces:** formulario (producto + cotización de proveedor + precio
de venta) que dispara el análisis y pinta los tres escenarios con
riesgos y recomendación; botón "Validate this analysis" que salta a
CEO con `finance_validation` precargado desde el escenario base real.

- [ ] Verificar en navegador (desktop + mobile) con datos reales del
      backend, como en Milestone 1/2/3.
- [ ] Commit: `feat: add economics page and validation handoff`

**Acceptance:** desde "Sourcing" se puede pasar a "Economics", ver el
informe de viabilidad, y pasar a validación sin retipear datos —
cerrando el loop Investigación → Sourcing → Análisis Económico →
Validación.

---

## Sección E — Verificación end-to-end

### Tarea 7: E2E — flujo completo de 4 pasos + doc de cierre

**Files:**
- Create: `backend/tests/e2e/test_economic_analysis_to_validation_flow.py`
- Create: `docs/milestones/milestone-4-demo.md`

**Escenario:** Research → Sourcing → Economic Analysis → Validation,
verificando 4 `correlation_id` distintos, cada uno reconstruible, y
que la evidencia de `financial_validation` en la decisión final refleja
los números reales del análisis económico (no valores de ejemplo).

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar el flujo completo en `docs/milestones/milestone-4-demo.md`
      (mismo formato que Milestone 2/3: flujo con curl, patrón de
      capacidades, fuentes/supuestos simulados, tabla nueva y su
      verificación de RLS, comando de verificación local).
- [ ] Ejecutar `get_advisors` (seguridad) contra el proyecto Supabase
      real tras aplicar la migración de la Tarea 3, y documentar el
      resultado.
- [ ] Commit: `test: verify economic analysis to validation flow end to end`

**Acceptance:** el flujo completo Fase 3 (Agentes 1+2+3) es
reproducible desde un entorno limpio, con o sin Supabase real
configurado, y documentado igual que los milestones anteriores.

---

## Definition of Done — Milestone 4

1. `economic_analyses` es una tabla real, con RLS activado desde su
   propia migración.
2. El Agente 3 (`EconomicAnalysisAgent`, capability
   `economic_risk_analysis`) calcula coste aterrizado, margen, tres
   escenarios y riesgos a partir de datos reales de investigación y
   sourcing ya persistidos — sin tocar `FinanceAgent`.
3. `EconomicAnalysisService` resuelve `product_id`/`supplier_quote_id`
   a datos reales, nunca cruza datos entre productos distintos, y
   persiste de forma reconstruible.
4. Existe una API de análisis económico auditada con `correlation_id`.
5. El Control Center tiene una página "Economics" que conecta
   Investigación → Sourcing → Análisis Económico → Validación.
6. El flujo E2E de 4 pasos es reproducible y trazable.
7. El linter de seguridad de Supabase sigue en verde tras la migración.
8. `docs/milestones/milestone-4-demo.md` documenta el milestone en el
   mismo formato que Milestone 2/3.
9. Ningún test de Milestone 1, 2 o 3 cambia de resultado.
