# AMAZONA Milestone 3 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1 y 2.

**Objetivo:** continuar la Fase 3 del roadmap con el segundo agente
operativo: **Agente 2, Proveedores y Sourcing**. Dado un producto ya
validado (o candidato) por el Agente 1 (Investigación de Productos,
Milestone 2), encuentra los mejores proveedores a nivel global, compara
precios, evalúa fiabilidad, calcula costes logísticos estimados, y
produce una lista de proveedores válidos con condiciones completas
(precio, MOQ, lead time, fiabilidad, coste logístico estimado).

**Depende de:** Milestone 2 completo (tag `milestone-2`, commit
`c29410a`), [ADR 0001](../../architecture/adr-0001-orchestrator-vs-ceo.md)
(capas Orquestador/CEO), [ADR 0002](../../architecture/adr-0002-agent-messaging-protocol.md)
(protocolo `AgentMessage` y validación de esquema por capability), y
[ADR 0003](../../architecture/adr-0003-rls-deny-by-default.md) (RLS
deny-by-default — toda tabla nueva debe nacer con RLS activado, no
retrofiteado después).

**Patrón heredado de Milestone 2 (no es una decisión nueva):** el Agente
1 introdujo el patrón "descubre y rankea N candidatos, expón un puente a
validación" (`ProductResearchAgent` + `ResearchService` +
`/api/research/runs` + página "Research" con botón "Validar este
producto" que precarga `/ceo?...`). El Agente 2 sigue exactamente el
mismo patrón para proveedores: `SupplierSourcingAgent` +
`SourcingService` + `/api/sourcing/runs` + página "Sourcing" con puente
a validación. No se integra en el grafo de tareas fijo del planner ni en
`decision_engine.py` — es, igual que la investigación de productos, un
flujo de descubrimiento independiente cuyo resultado un humano (o un
futuro objetivo de validación) consume después.

## Restricciones globales (heredadas de Milestone 1 + 2)

- Sin dinero real, pedidos, proveedores ni impuestos reales.
- El Agente 2 usa **fuentes simuladas/mock** únicamente en este
  milestone — sin llamadas reales a Alibaba, Made-in-China, ni APIs de
  comercio exterior/logística. Si en el futuro se decide integrar una
  fuente real, se documenta esa decisión en una ADR nueva antes de
  construirla (no se asume tácitamente).
- Toda acción relevante sigue auditada (tabla `audit_log` +
  `AuditService`, igual patrón que `ResearchService`).
- Cualquier acción simulada de alto impacto (gasto, publicación, cambio
  de política) sigue requiriendo aprobación humana explícita. El Agente
  2 nunca ejecuta gasto ni compromete un pedido — solo produce
  recomendaciones de sourcing; comprometerse con un proveedor sigue
  pasando por el flujo de validación/aprobación ya existente.
- El núcleo de decisión determinista (`decision_engine.py`,
  `permissions/engine.py`, `budgets/engine.py`) no se toca — el Agente 2
  no se cablea en el grafo de tareas del planner ni en la síntesis
  GO/REVIEW/NO_GO/HUMAN_APPROVAL en este milestone (ver ADR 0004).
- Toda tabla nueva se crea con RLS activado y política deny-all
  (`anon`, `authenticated`) en la misma migración que la crea — no se
  añade a una lista aparte después, a diferencia de la migración
  retroactiva 0003. Al terminar, `get_advisors` (linter de seguridad de
  Supabase) debe seguir en verde, sin nuevas tablas sin RLS.
- Tests antes que implementación para todo comportamiento determinista
  nuevo. Commit por tarea completada.
- Ningún test de Milestone 1 o 2 cambia de resultado.

---

## Estructura de archivos (adiciones sobre Milestone 2)

```text
backend/
├── app/
│   ├── ai/
│   │   └── mock_supplier_directory.py   # fuente mock de proveedores por categoría
│   ├── sourcing/
│   │   ├── logistics.py                 # calculadora determinista de coste logístico
│   │   └── service.py                   # SourcingService (persiste cotizaciones)
│   ├── agents/
│   │   └── supplier_sourcing.py         # Agente 2 — capability supplier_sourcing_research
│   ├── api/
│   │   └── sourcing.py
│   └── db/models/
│       └── supplier_quote.py            # tabla supplier_quotes
├── alembic/versions/                    # nueva migración incremental
└── tests/
    ├── unit/
    │   ├── test_mock_supplier_directory.py
    │   ├── test_logistics_calculator.py
    │   └── test_supplier_sourcing_agent.py
    ├── integration/
    │   ├── test_supplier_quote_model.py
    │   └── test_sourcing_api.py
    └── e2e/
        └── test_supplier_sourcing_to_validation_flow.py

apps/control-center/
├── app/
│   └── sourcing/page.tsx        # candidatos de proveedores + puente a validación
├── lib/
│   └── api.ts                   # +createSourcingRun, tipos ResearchCandidate-like
└── components/
    └── nav-items.ts             # +"Sourcing"

docs/
├── architecture/
│   └── adr-0004-agent-capability-pairs-validate-vs-discover.md
└── milestones/
    └── milestone-3-demo.md
```

---

## Sección A — Fuentes mock: directorio de proveedores + coste logístico

### Tarea 1: `MockSupplierDirectory` — proveedores globales por categoría

**Files:**
- Create: `backend/app/ai/mock_supplier_directory.py`
- Create: `backend/tests/unit/test_mock_supplier_directory.py`

**Produces:** fuente de datos determinista y fixture-driven (sin red),
en el mismo espíritu que `MockTrendsProvider` (Milestone 2, Agente 1),
que simula un directorio de proveedores globales por categoría de
producto: nombre, región/país, precio unitario, MOQ, lead time en días,
si está verificado, y un `reliability_score` base.

- [ ] Test: misma consulta (categoría) → mismo resultado (determinista).
- [ ] Test: categorías distintas producen conjuntos de proveedores
      distintos (no todo es una constante disfrazada).
- [ ] Test: cada proveedor del fixture tiene región, precio unitario,
      MOQ, lead time y `reliability_score` — ningún campo obligatorio
      queda vacío en el dataset embebido.
- [ ] Implementar con un dataset fixture embebido (dict Python), cubriendo
      al menos las mismas categorías que `MockTrendsProvider`
      (`electronics`, `home`, `accessories`) con 2-4 proveedores de
      regiones distintas cada una (p. ej. China, Vietnam, México, UE) para
      que la comparación de coste logístico tenga sentido.
- [ ] Commit: `feat: add mock global supplier directory provider`

**Acceptance:** cero llamadas de red — verificable inspeccionando el
código, no solo confiando en la documentación.

---

### Tarea 2: Calculadora determinista de coste logístico estimado

**Files:**
- Create: `backend/app/sourcing/logistics.py`
- Create: `backend/tests/unit/test_logistics_calculator.py`

**Produces:** función pura `estimate_logistics_cost(origin_region: str,
destination_region: str, unit_cost: float, moq: int) -> LogisticsEstimate`
que calcula un coste logístico estimado por envío, usando una tabla de
factores fijos por par de regiones (origen→destino) — sin depender de
tarifas reales de ningún transportista, documentado explícitamente como
placeholder hasta que exista un proveedor de tarifas real.

```python
class LogisticsEstimate(BaseModel):
    shipping_cost_per_unit: float
    customs_factor: float          # multiplicador simulado, no arancel real
    estimated_total_logistics_cost: float
    notes: str
```

- [ ] Test: mismo par de regiones + mismos costes → mismo resultado
      (determinista).
- [ ] Test: pares de regiones más lejanos/con peor conectividad
      simulada producen un coste por unidad mayor que pares cercanos
      (la tabla de factores no es plana).
- [ ] Test: región de origen o destino desconocida en la tabla usa un
      factor conservador por defecto documentado, no lanza excepción.
- [ ] Implementar con una tabla de factores fija (dict), documentando en
      un comentario corto que es un placeholder simulado.
- [ ] Commit: `feat: add deterministic logistics cost estimator`

**Acceptance:** la función es pura (mismo input → mismo output, sin
efectos secundarios), reutilizable independientemente del agente que la
invoque.

---

## Sección B — Agente 2: descubrimiento y ranking de proveedores

### Tarea 3: ADR 0004 — pares de capacidades "validar uno" vs "descubrir muchos"

**Files:**
- Create: `docs/architecture/adr-0004-agent-capability-pairs-validate-vs-discover.md`

**Produces:** formaliza como convención general de Fase 3 (no solo para
este agente) el patrón que ya apareció implícitamente en Milestone 2:
`ProductAgent` (`product`, valida UN producto ya elegido, capability
`product`) vs `ProductResearchAgent` (`product_research`, descubre y
rankea VARIOS candidatos). El Agente 2 repite el mismo fork:
`SupplierAgent` (Milestone 1, capability `supplier_sourcing`, valida
la cotización de UN proveedor ya elegido) vs `SupplierSourcingAgent`
(nuevo, capability `supplier_sourcing_research`, descubre y rankea
VARIOS proveedores).

**Decisión a documentar:** cada vez que Fase 3 necesite tanto "validar
una opción dada" como "descubrir/rankear N opciones" para la misma
entidad de dominio (producto, proveedor, y previsiblemente más adelante
canal de venta, campaña, etc.), se modelan como **dos agentes con dos
capabilities distintas**, no como un único agente con un flag de modo.
Regla de nombrado: `<dominio>` para validar-uno, `<dominio>_research`
para descubrir-muchos. El de "descubrir-muchos" es el que se expone en
un flujo de discovery propio (API + página Control Center) con puente
hacia el flujo de validación existente; el de "validar-uno" sigue
siendo el que consume el planner/`decision_engine.py` dentro del grafo
de tareas de un objetivo.

**Razonamiento (a incluir en el ADR):**
1. Los dos modos tienen contratos de entrada/salida distintos (uno
   recibe los datos de UNA opción concreta y devuelve GO/REVIEW/NO_GO
   sobre ella; el otro recibe criterios de búsqueda y devuelve una
   lista rankeada) — forzarlos a un solo agente con un `mode: str`
   ensuciaría `input_schema`/`output_schema` (ADR 0002) con unión de
   dos formas incompatibles.
2. Mantiene intacto el contrato que el planner/`decision_engine.py` ya
   asume para los 4 agentes de Milestone 1 — el agente de "validar-uno"
   nunca cambia de forma.
3. Consistente con cómo Milestone 2 ya resolvió esto para productos sin
   necesidad de una ADR explícita en su momento; esta ADR cierra ese
   hueco retroactivamente y deja la regla escrita para los Agentes 3-8.

- [ ] Escribir el ADR con el formato de ADR 0001-0003 (Contexto,
      Decisión, Razonamiento, Consecuencias).
- [ ] Commit: `docs: add adr for validate-vs-discover agent capability pairs`

**Acceptance:** el ADR es citable por los Agentes 3-8 sin tener que
volver a discutir esta decisión.

---

### Tarea 4: `SupplierSourcingAgent` — capability `supplier_sourcing_research`

**Files:**
- Create: `backend/app/agents/supplier_sourcing.py`
- Create: `backend/tests/unit/test_supplier_sourcing_agent.py`
- Modify: `backend/app/agents/registry.py` (`build_default_agent_manager`)

**Produces:** dado un input de sourcing (categoría o `product_id`,
región de destino, `max_results`), devuelve una lista rankeada de
proveedores con condiciones completas — precio, MOQ, lead time,
fiabilidad, coste logístico estimado, y un coste total aterrizado
(`unit_cost + logistics per unit`) usado para el ranking.

```python
class SupplierSourcingInput(BaseModel):
    category: str
    destination_region: str
    max_results: int = Field(default=5, ge=1, le=20)

class RankedSupplierCandidate(BaseModel):
    name: str
    region: str
    unit_price: float
    moq: int
    lead_time_days: int
    verified: bool
    reliability_score: float
    logistics_cost_per_unit: float
    total_landed_cost_per_unit: float
    notes: str

class SupplierSourcingResult(AgentResult):
    # data["candidates"]: list[RankedSupplierCandidate] (serializado)
```

- [ ] Test: input con categoría conocida + región de destino devuelve
      `max_results` proveedores ordenados por `total_landed_cost_per_unit`
      ascendente (menor coste total gana, no solo menor precio de
      lista — un proveedor barato pero lejano puede perder frente a uno
      más caro pero cercano).
- [ ] Test: proveedores no verificados generan un riesgo explícito en
      `risks` (mismo principio que `SupplierAgent` de Milestone 1:
      `verified=False` nunca se oculta detrás de un buen precio).
- [ ] Test: categoría sin datos en el directorio mock devuelve
      `AgentResultStatus.COMPLETED` con `recommendation="REVIEW"`,
      `data.candidates=[]` y un riesgo explícito — igual patrón que
      `ProductResearchAgent` cuando no hay datos de tendencias.
- [ ] Implementar reutilizando `MockSupplierDirectory` (Tarea 1) +
      `estimate_logistics_cost` (Tarea 2).
- [ ] Registrar en `build_default_agent_manager()` como
      `agent-supplier-sourcing-1`, capability `supplier_sourcing_research`
      — **sin tocar** el `agent-supplier-1` (`supplier_sourcing`)
      existente de Milestone 1.
- [ ] Commit: `feat: add supplier sourcing research agent`

**Acceptance:** `AgentResult` válido (mismo contrato de Milestone
1/ADR 0002); los 4 agentes de Milestone 1 y `ProductResearchAgent`
siguen pasando sus tests sin modificarse.

---

## Sección C — Persistencia y API de sourcing

### Tarea 5: Tabla `supplier_quotes` (cotización de un proveedor para un producto)

**Files:**
- Create: `backend/app/db/models/supplier_quote.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration (incluye `ENABLE ROW LEVEL SECURITY` +
  política deny-all para la tabla nueva, ver ADR 0003 — no se pospone a
  una migración de limpieza posterior)
- Create: `backend/tests/integration/test_supplier_quote_model.py`

**Produces:** persistencia de primera clase para cada cotización
rankeada de un run de sourcing, vinculando `Supplier` (entidad
reutilizable, ya existe desde Milestone 2) con `Product` y con el run
que la generó.

**Esquema `supplier_quotes`:**
- id, product_id (FK `products.id`), supplier_id (FK `suppliers.id`),
  unit_price, moq, lead_time_days, reliability_score,
  logistics_cost_per_unit, total_landed_cost_per_unit,
  analysis_type (`sourcing`, para dejar hueco a otros tipos futuros),
  data (JSON — misma forma que `AgentResult.data` por candidato),
  correlation_id, created_at.

- [ ] Test: crear un `SupplierQuote` con `product_id`/`supplier_id`
      válidos, verificar persistencia y campos.
- [ ] Test: `SupplierQuote` requiere `product_id` y `supplier_id`
      válidos (FK).
- [ ] Test: la migración deja `supplier_quotes` con RLS activado (mismo
      test de humo que ya existe para las tablas de ADR 0003, extendido
      a esta tabla).
- [ ] Implementar modelo + migración.
- [ ] Commit: `feat: add supplier quotes table with rls enabled`

**Acceptance:** `alembic upgrade head` desde limpio crea la tabla sin
pasos manuales, en SQLite (dev) y Postgres (CI/Supabase), con RLS ya
activado desde su primera migración.

---

### Tarea 6: `SourcingService` — ejecuta el agente, deduplica proveedores, persiste cotizaciones

**Files:**
- Create: `backend/app/sourcing/service.py`
- Create: `backend/tests/integration/test_sourcing_service.py`

**Produces:** ejecuta `SupplierSourcingAgent`, y por cada candidato:
reutiliza un `Supplier` existente si ya existe uno con el mismo
`(name, region)` (evita duplicar el mismo proveedor en cada run), o crea
uno nuevo; crea siempre una fila `SupplierQuote` nueva (la cotización sí
es específica de este run); audita el run completo.

- [ ] Test: un run sobre una categoría nueva crea N `Supplier` + N
      `SupplierQuote`, auditado con `correlation_id`.
- [ ] Test: correr sourcing dos veces para la misma categoría reutiliza
      los `Supplier` ya existentes (no duplica proveedores), pero crea
      `SupplierQuote` nuevas en cada run (el precio/lead time pudo
      cambiar).
- [ ] Implementar.
- [ ] Commit: `feat: add sourcing service with supplier deduplication`

**Acceptance:** un run de sourcing es 100% reconstruible desde la base
de datos después de reiniciar el proceso — mismo estándar que
`ResearchService`.

---

### Tarea 7: API de sourcing

**Files:**
- Create: `backend/app/api/sourcing.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_sourcing_api.py`

**Produces:**
- `POST /api/sourcing/runs` → `{product_id, category, destination_region,
  max_results}`, dispara `SupplierSourcingAgent`, persiste vía
  `SourcingService`, devuelve las cotizaciones rankeadas.
- `GET /api/sourcing/runs/{correlation_id}` → resultado reconstruido
  desde DB.
- `GET /api/products/{product_id}/suppliers` → cotizaciones existentes
  para un producto (para que la página "Sourcing" pueda listar sin
  disparar un run nuevo).

- [ ] Test: `POST /api/sourcing/runs` crea las filas esperadas y
      responde con las cotizaciones ordenadas por
      `total_landed_cost_per_unit`.
- [ ] Test: `GET /api/sourcing/runs/{correlation_id}` reconstruye el
      resultado desde DB, no desde estado en memoria.
- [ ] Test: `product_id` inexistente → 404 claro, no 500.
- [ ] Implementar.
- [ ] Commit: `feat: add supplier sourcing api`

**Acceptance:** mismo estándar de reconstruibilidad y manejo de errores
que `/api/research`.

---

## Sección D — Control Center: página "Sourcing" + puente a validación

### Tarea 8: Página "Sourcing" en el Control Center

**Files:**
- Create: `apps/control-center/app/sourcing/page.tsx`
- Modify: `apps/control-center/lib/api.ts` (+`createSourcingRun`,
  +`listProductSuppliers`, tipos `SupplierQuoteCandidate`/`SourcingRun`)
- Modify: `apps/control-center/components/nav-items.ts` (+`"Sourcing"`)
- Modify: `apps/control-center/app/research/page.tsx` (botón "Buscar
  proveedores" junto a "Validar este producto", que navega a
  `/sourcing?product_id=...&category=...`)

**Produces:** formulario (producto/categoría + región de destino) que
dispara un run de sourcing y pinta la lista de proveedores rankeados
con precio, MOQ, lead time, fiabilidad y coste logístico estimado; cada
fila tiene un botón "Validar con este proveedor" que navega a `/ceo`
con el `context` precargado (producto + proveedor elegido), igual
patrón que la Tarea 19 de Milestone 2.

- [ ] Verificar en navegador (desktop + mobile) con datos reales del
      backend, como en Milestone 1/2.
- [ ] Commit: `feat: add sourcing page and validation handoff`

**Acceptance:** desde "Research" se puede pasar un candidato a
"Sourcing", ver proveedores rankeados, y pasar uno a validación sin
retipear datos — cerrando el loop Investigación → Sourcing → Validación.

---

## Sección E — Verificación end-to-end y seguridad

### Tarea 9: E2E — flujo completo Investigación → Sourcing → Validación

**Files:**
- Create: `backend/tests/e2e/test_supplier_sourcing_to_validation_flow.py`
- Update: `docs/milestones/milestone-3-demo.md`

**Escenario:**
1. `POST /api/research/runs` con una categoría → candidatos rankeados
   (Milestone 2, sin cambios).
2. Tomar el candidato mejor puntuado → `POST /api/sourcing/runs` con su
   `product_id` → proveedores rankeados por coste total aterrizado.
3. Tomar el proveedor mejor puntuado → crear un `Objective` cuyo
   `context` deriva de ambos runs (producto + proveedor).
4. `POST /api/objectives/{id}/run` → decisión determinista, igual que
   Milestone 1/2.
5. Verificar trazabilidad completa por `correlation_id` a través de los
   tres runs (investigación + sourcing + validación) vía `/api/audit`.

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar el flujo en `docs/milestones/milestone-3-demo.md`
      (mismo estilo que Milestone 1/2).
- [ ] Commit: `test: verify research to sourcing to validation flow end to end`

**Acceptance:** el flujo completo de Fase 3 (Agente 1 + Agente 2) es
reproducible desde un entorno limpio, con o sin Supabase real
configurado.

---

### Tarea 10: Verificación del linter de seguridad de Supabase

**Files:** ninguno (verificación, no código) — usar
`mcp__supabase__get_advisors` (categoría `security`) contra el proyecto
real, y documentar el resultado en `docs/milestones/milestone-3-demo.md`.

- [ ] Ejecutar el advisor de seguridad tras aplicar la migración de la
      Tarea 5.
- [ ] Confirmar 0 hallazgos nuevos de "RLS Disabled in Public" — la
      tabla `supplier_quotes` debe aparecer con RLS activado desde su
      propia migración, no requerir una migración de limpieza como
      ADR 0003 tuvo que hacer retroactivamente.
- [ ] Si aparece cualquier hallazgo nuevo, corregirlo antes de cerrar el
      milestone.
- [ ] Commit (si hace falta algún ajuste): `fix: address supabase security advisor findings`

**Acceptance:** el linter de seguridad de Supabase sigue en verde, sin
tablas públicas nuevas sin RLS.

---

## Definition of Done — Milestone 3

1. `supplier_quotes` es una tabla real, poblada por el flujo de
   sourcing, con RLS activado desde su propia migración.
2. El Agente 2 (`SupplierSourcingAgent`, capability
   `supplier_sourcing_research`) descubre y rankea proveedores globales
   por coste total aterrizado (precio + logística estimada), usando
   solo fuentes simuladas, sin tocar el `SupplierAgent` de Milestone 1.
3. `SourcingService` persiste cada run de forma reconstruible desde DB,
   deduplicando proveedores reutilizables entre runs.
4. Existe una API de sourcing (`POST /api/sourcing/runs`,
   `GET /api/sourcing/runs/{id}`, `GET /api/products/{id}/suppliers`)
   auditada con `correlation_id`.
5. El Control Center tiene una página "Sourcing" que conecta
   Investigación → Sourcing → Validación sin retipear datos.
6. ADR 0004 documenta la convención "validar-uno vs descubrir-muchos"
   para que los Agentes 3-8 la reutilicen sin volver a discutirla.
7. El flujo E2E Investigación → Sourcing → Validación es reproducible y
   trazable por `correlation_id`.
8. El linter de seguridad de Supabase sigue en verde — ninguna tabla
   nueva sin RLS.
9. Ningún test de Milestone 1 o 2 cambia de resultado — todo lo nuevo
   es aditivo.

## Después de Milestone 3

Fase 3 continúa con los Agentes 3-8 (análisis económico, legal,
e-commerce, marketplaces, marketing, atención al cliente), siguiendo
ADR 0004 para decidir si cada uno necesita el fork validar-uno/
descubrir-muchos, y el mismo patrón de persistencia + API + página +
puente a validación que Agentes 1 y 2. Las llamadas a APIs externas
reales (directorios de proveedores reales, tarifas de logística reales)
quedan para cuando el roadmap lo indique explícitamente — no antes.
