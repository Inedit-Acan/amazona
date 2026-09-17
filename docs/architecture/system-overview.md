# AMAZONA — Visión general del sistema

Este documento es el punto de entrada para entender AMAZONA sin leer los
14 `docs/milestones/milestone-N-demo.md` uno a uno. Explica qué existe,
cómo encajan las piezas, y dónde profundizar (cada sección enlaza a la
ADR y al milestone que la construyó). Escrito al cierre de Fase 4
(Milestone 15, IVA-34).

## 1. Qué es AMAZONA

Un backend (FastAPI + SQLAlchemy + Alembic sobre PostgreSQL/Supabase) y
un Control Center (Next.js) que simulan, de principio a fin, la
operación de un negocio de e-commerce dirigido por agentes de IA
deterministas (sin LLM en el camino de decisión): desde detectar una
oportunidad de producto hasta operarlo y controlar su salud financiera
agregada — con controles humanos obligatorios en los puntos donde el
sistema decide algo de riesgo o gasta presupuesto. **No hay dinero real,
pedidos, proveedores, ni impuestos reales** — todo dato de negocio es
simulado y está documentado como tal en el propio código de cada agente.

## 2. Las dos capas de orquestación (la idea arquitectónica central)

El sistema tiene **dos orquestadores paralelos, deliberadamente
separados**, que nunca se llaman entre sí. Confundirlos es el error más
común al leer el código por primera vez:

### 2.1 `CEOOrchestrator` — el grafo de validación de Milestone 1

Vive en `backend/app/ceo/orchestrator.py`. Dado un `Objective` (un
contexto de negocio arbitrario — no necesariamente un producto real del
catálogo), ejecuta un grafo de tareas **fijo de 4 pasos**
(`SPECIALIST_TASK_NAMES`), sintetiza una decisión determinista, y aplica
permisos/presupuesto antes de pedir aprobación humana si hace falta:

```
Objective → planner.py (grafo de 4 tareas) → 4 agentes "validar-uno"
                                                    │
                                                    ▼
                                          decision_engine.py
                                    (GO | REVIEW | NO_GO | HUMAN_APPROVAL)
                                                    │
                                    HUMAN_APPROVAL → PermissionEngine +
                                    BudgetEngine (reserva) → Approval (PENDING)
                                                    │
                                    humano aprueba/rechaza → BudgetLedgerService
                                    (commit/release real en budget_allocations)
```

Por diseño (**[ADR 0001](adr-0001-orchestrator-vs-ceo.md)**), "Orquestador"
(Agente 9) y "CEO" son **dos capas del mismo proceso Python, no dos
agentes independientes**: el Orquestador es el runtime (grafo de tareas,
persistencia, eventos, auditoría — `orchestrator.py`); el CEO es la
política/el cerebro (`planner.py` + `decision_engine.py`), invocado por
el Orquestador como funciones puras. Ninguno de los 9 agentes de Fase 3
(sección 3) se despacha desde aquí.

### 2.2 `PipelineOrchestrator` — la cadena de descubrimiento de Fase 3

Vive en `backend/app/pipeline/service.py` (Milestone 12,
**[ADR 0005](adr-0005-fase-3-pipeline-orchestrator.md)**). Dado
`category` + parámetros de negocio (precio de venta, mercado,
plataformas...), encadena automáticamente los 9 agentes "descubrir-muchos"
de Fase 3 sobre entidades de catálogo reales:

```
category → Research → Sourcing → Economics → Legal → Ecommerce
         → Marketplace → Marketing → Operations → CFO
         (9 pasos, un Product real elegido en el paso 1, sus datos
          reales enhebrados automáticamente hasta el final)
```

Reemplaza el recorrido manual de 9 páginas del Control Center (copiar
IDs de la salida de un paso al formulario del siguiente) que Milestone 9
dejó documentado como pendiente. **Ningún paso detiene la cadena** ante
un `NO_GO`/`BLOCKED` intermedio — cada paso se registra igual y la
ejecución sigue hasta el final (razonamiento completo en ADR 0005); el
control humano sobre resultados de riesgo es post-hoc, ver sección 5.

**Por qué están separados y no es un único orquestador:** los dos
dominios tienen contratos incompatibles — el CEO valida un `Objective`
abstracto (puede no tener ningún `Product` real detrás), mientras que el
pipeline descubre y encadena entidades de catálogo concretas
(`Product`, `SupplierQuote`, ...). Fusionarlos tocaría el núcleo de
decisión GO/NO-GO ya estable desde Milestone 1. Ver ADR 0005 §
"Alternativas consideradas".

## 3. Catálogo de agentes (13 en total)

Cada fila enlaza a la capability real registrada en
`backend/app/agents/registry.py::build_default_agent_manager()`. La
columna "Patrón" sigue **[ADR 0004](adr-0004-agent-capability-pairs-validate-vs-discover.md)**:
`validar-uno` = invocado dentro del grafo de `CEOOrchestrator`;
`descubrir-muchos` = invocado por su propio servicio (manualmente vía su
página del Control Center, o encadenado por `PipelineOrchestrator`).

| # | Agente | Capability | Patrón | Tabla | API |
|---|---|---|---|---|---|
| 1 | Product (validar) | `market_validation` | validar-uno | — (Task/Decision) | vía `/api/objectives/{id}/run` |
| 2 | Supplier (validar) | `supplier_sourcing` | validar-uno | — (Task/Decision) | vía `/api/objectives/{id}/run` |
| 3 | Finance (validar) | `financial_validation` | validar-uno | — (Task/Decision) | vía `/api/objectives/{id}/run` |
| 4 | Legal (validar) | `legal_validation` | validar-uno | — (Task/Decision) | vía `/api/objectives/{id}/run` |
| 5 | Product Research (Fase 3, Agente 1) | `product_research` | descubrir-muchos | `products` + `product_analyses` | `/api/research/runs` |
| 6 | Supplier Sourcing Research (Fase 3, Agente 2) | `supplier_sourcing_research` | descubrir-muchos | `supplier_quotes` | `/api/sourcing/runs` |
| 7 | Economic Analysis (Fase 3, Agente 3) | `economic_risk_analysis` | descubrir-muchos | `economic_analyses` | `/api/economics/runs` |
| 8 | Legal Compliance (Fase 3, Agente 4) | `legal_compliance_analysis` | descubrir-muchos | `legal_analyses` | `/api/legal/runs` |
| 9 | Ecommerce Storefront (Fase 3, Agente 5) | `ecommerce_storefront_generation` | descubrir-muchos | `storefronts` | `/api/ecommerce/runs` |
| 10 | Marketplace Listing (Fase 3, Agente 6) | `marketplace_listing_optimization` | descubrir-muchos | `marketplace_listings` | `/api/marketplace/runs` |
| 11 | Marketing Campaign (Fase 3, Agente 7) | `marketing_campaign_planning` | descubrir-muchos | `marketing_campaigns` | `/api/marketing/runs` |
| 12 | Operations (Fase 3, Agente 8) | `operations_fulfillment_management` | descubrir-muchos | `operations_records` | `/api/operations/runs` |
| 13 | CFO | `cfo_financial_health_report` | descubrir-muchos, catálogo-completo | `cfo_reports` | `/api/cfo/runs` |

Los 4 primeros son Milestone 1 ("validar-uno"); los 9 siguientes son
Fase 3 ("descubrir-muchos", Milestones 2-10). Cada agente Fase 3 resuelve
la salida real del agente inmediatamente anterior (por `product_id` y,
donde aplica, `market`) — nunca inventa datos que otro agente ya generó.
Todos los 13 están registrados en `AgentRegistry` (introspección vía
`GET /api/agents`), pero solo los 4 primeros son alcanzables desde
`CEOOrchestrator` — el resto solo se invoca vía su propio servicio o
`PipelineOrchestrator`.

**Ejecutores de nivel superior** (no son agentes propios, son las dos
capas de orquestación de la sección 2): **Agente 9 — Orquestador**
(`CEOOrchestrator`) y **Agente CEO** (`planner.py` + `decision_engine.py`).
Ninguno de los dos se ha promovido a agente direccionable independiente
— ADR 0001 fija la condición para hacerlo (autonomía real), que ningún
milestone ha requerido todavía.

**Restricción permanente del Agente CFO:** nunca emite facturas propias
— es agregación de solo lectura. Facturación real, si el proyecto la
aborda, debe pasar por un software certificado Verifactu externo.

## 4. Modelo de datos (por dominio)

- **Milestone 1 (grafo CEO):** `objectives`, `projects`, `tasks`,
  `task_dependencies`, `decisions`, `decision_evidence`, `approvals`.
- **Fase 3 (catálogo, un registro por ejecución de cada agente,
  histórico conservado):** `products`, `product_analyses`,
  `supplier_quotes`, `economic_analyses`, `legal_analyses`,
  `storefronts`, `marketplace_listings`, `marketing_campaigns`,
  `operations_records`, `cfo_reports`.
- **Presupuesto (Milestone 1 + 11):** `budgets`, `budget_allocations`,
  `financial_events` — escritas por `BudgetLedgerService`
  (`backend/app/budgets/service.py`) a medida que el Orquestador reserva
  y la API de aprobaciones comprometen/liberan, no por el
  `BudgetEngine` en memoria (que solo autoriza).
- **Pipeline (Milestone 12/14):** `pipeline_runs`, `pipeline_reviews`,
  `pipeline_kill_switch`.
- **Transversal:** `audit_log` (append-only, toda transición relevante
  del sistema pasa por aquí), `agent_execution_log`, `users`/`roles`
  (auth opcional), `memory_records`, `events`, `incidents`,
  `agent`/`agent_capabilities` (introspección), `policies` (scaffold sin
  usar todavía, ver ADR 0006 § alternativas).

Cada tabla de Fase 3/Pipeline tiene índices explícitos en `product_id`
(y `audit_log.correlation_id`) desde Milestone 13 — antes de eso, cada
consulta "última fila para este producto" era un full table scan.

## 5. Controles humanos críticos

Dos mecanismos independientes, en dos capas distintas, cada uno resuelto
en su propio milestone:

### 5.1 Aprobación de gasto (Milestone 1, dentro del grafo CEO)

Cuando una decisión llega a `HUMAN_APPROVAL`, `PermissionEngine`
autoriza y `BudgetEngine` reserva presupuesto en memoria; se crea una
fila `Approval` (`PENDING`, expira a las 24h). Un humano resuelve vía
`POST /api/approvals/{id}/approve|reject`. Desde Milestone 11,
`BudgetLedgerService` persiste esa reserva/compromiso/liberación en
`budget_allocations`/`financial_events` — antes de eso, el `CFOReport`
siempre mostraba presupuesto en cero, aunque el Orquestador sí aplicara
límites.

### 5.2 Revisión de ejecuciones de riesgo + kill switch (Milestone 14, sobre el pipeline)

**[ADR 0006](adr-0006-pipeline-human-controls.md)** — ver también
sección 2.2: el pipeline nunca pausa a mitad de ejecución, así que el
control humano es post-hoc y pre-hoc, no una pausa intermedia:

- **Post-hoc:** `assess_pipeline_run()` (`backend/app/pipeline/review.py`,
  función pura) marca una ejecución como necesitando revisión si
  `status="PARTIAL"`, `economics`/`legal` en `NO_GO`, cualquier paso
  downstream en `BLOCKED`, o el `CFOReport` en `AT_RISK`/`CRITICAL`. Si
  aplica, crea una `PipelineReview` (`PENDING`) — un humano resuelve vía
  `POST /api/pipeline/reviews/{id}/approve|reject`.
- **Pre-hoc:** `PipelineKillSwitch` — una fila canónica que un operador
  activa/desactiva vía `POST /api/pipeline/kill-switch`. Deshabilitado,
  cualquier intento de `POST /api/pipeline/runs` devuelve `423 Locked`
  sin ningún efecto secundario. Es el primer kill-switch del sistema.

Ambos mecanismos son nuevos modelos (`PipelineReview`,
`PipelineKillSwitch`), no reutilizan `Approval` — su FK `decision_id` es
obligatoria y específica del dominio `Decision` de Milestone 1.

## 6. Seguridad

**RLS deny-by-default** (**[ADR 0003](adr-0003-rls-deny-by-default.md)**):
toda tabla nace con Row Level Security activado en su propia migración,
con una política explícita `deny_all_anon_authenticated` para los roles
`anon`/`authenticated` que usa PostgREST. El backend conecta como
`postgres` (dueño de las tablas) y nunca se ve afectado — esto cierra el
acceso público por completo, sin definir todavía un modelo de acceso por
usuario (fuera de alcance hasta que algún cliente necesite llamar a
PostgREST directamente).

**Auth** es opcional (`Settings.require_auth`, `False` por defecto). Con
auth desactivada — el valor por defecto de despliegue — cualquier campo
"quién aprobó/resolvió esto" (`Approval.resolved_by`,
`PipelineReview.resolved_by`) es texto libre suministrado por quien
llama a la API, no una identidad verificada. Activar `require_auth`
respalda esos campos con identidad real de Supabase.

## 7. Protocolo de mensajería entre agentes

**[ADR 0002](adr-0002-agent-messaging-protocol.md)**: la frontera real
del sistema es `AgentManager.execute()` invocando `Agent.run(task_input)`
sobre implementaciones independientes descubiertas por capability
(`AgentRegistry`). Cada `Agent` puede declarar `input_schema`/
`output_schema` (Pydantic) que `AgentManager` valida antes/después de
ejecutar — aditivo, los 4 agentes de Milestone 1 no lo declaran y siguen
funcionando igual. `AgentMessage` (`backend/app/messaging/schemas.py`)
es el sobre versionado ya diseñado para si algún día el transporte deja
de ser una llamada de función Python directa (agentes en procesos
separados, colas) — no se usa activamente hoy.

## 8. Índice de ADRs

| ADR | Decisión |
|---|---|
| [0001](adr-0001-orchestrator-vs-ceo.md) | Orquestador y CEO son dos capas del mismo proceso, no dos agentes independientes |
| [0002](adr-0002-agent-messaging-protocol.md) | `AgentMessage` + validación de esquema opcional en la frontera CEO↔especialistas |
| [0003](adr-0003-rls-deny-by-default.md) | RLS activado con deny-all explícito en las 24 tablas públicas |
| [0004](adr-0004-agent-capability-pairs-validate-vs-discover.md) | Convención "validar-uno" vs "descubrir-muchos" para pares de agentes |
| [0005](adr-0005-fase-3-pipeline-orchestrator.md) | `PipelineOrchestrator` nuevo y separado, nunca detiene la cadena, sin tocar el grafo CEO |
| [0006](adr-0006-pipeline-human-controls.md) | Revisión humana post-hoc + kill switch pre-hoc sobre el pipeline, sin pausas intermedias |

## 9. Índice de milestones

| Milestone | Qué construyó |
|---|---|
| [1](../milestones/milestone-1-demo.md) | `CEOOrchestrator` + 4 agentes "validar-uno" + decisión determinista + permisos/presupuesto + aprobación humana + auditoría |
| [2](../milestones/milestone-2-demo.md) | Supabase real, memoria compartida, protocolo de mensajería, grafo de tareas persistido, auth/roles opcionales, monitorización, primer agente Fase 3 (Research) |
| [3](../milestones/milestone-3-demo.md) | Fase 3 Agente 2 — Sourcing (descubrir-muchos) |
| [4](../milestones/milestone-4-demo.md) | Fase 3 Agente 3 — Economic Analysis |
| [5](../milestones/milestone-5-demo.md) | Fase 3 Agente 4 — Legal Compliance |
| [6](../milestones/milestone-6-demo.md) | Fase 3 Agente 5 — Ecommerce Storefront |
| [7](../milestones/milestone-7-demo.md) | Fase 3 Agente 6 — Marketplace Listing |
| [8](../milestones/milestone-8-demo.md) | Fase 3 Agente 7 — Marketing Campaign |
| [9](../milestones/milestone-9-demo.md) | Fase 3 Agente 8 — Operations (cierra los 8 agentes operativos); valoración de qué queda (Orquestador y CEO no necesitan cambios, CFO es el hueco real) |
| [10](../milestones/milestone-10-demo.md) | Agente CFO — informe de salud financiera catálogo-completo |
| [11](../milestones/milestone-11-demo.md) | `BudgetLedgerService` — persiste reservas/compromisos reales, cierra el gap que dejaba al CFO siempre en cero |
| [12](../milestones/milestone-12-demo.md) | `PipelineOrchestrator` — encadena los 9 pasos de Fase 3 automáticamente (Fase 4.1/4.2) |
| [13](../milestones/milestone-13-demo.md) | Validación combinatoria real + 3 fixes (colisión de `store_slug`, índices, `CFOService` sin full table scan) (Fase 4.3/4.4) |
| [14](../milestones/milestone-14-demo.md) | Revisión humana post-hoc + kill switch pre-hoc sobre el pipeline (Fase 4.5) |
| [15](../milestones/milestone-15-demo.md) | Este documento — cierre de Fase 4 |

## 10. Cómo verlo funcionar

```bash
cd backend && alembic upgrade head && uvicorn app.main:app --reload
cd apps/control-center && npm run dev   # http://localhost:3000
```

- **Un producto de principio a fin:** Control Center → **Pipeline** → un
  formulario, un clic → los 9 pasos con su estado.
- **Un objetivo de Milestone 1:** Control Center → **CEO** → crear
  objetivo → ejecutar → si llega a `HUMAN_APPROVAL`, resolverlo en
  **Approvals**.
- **Trazabilidad de cualquier ejecución:** cada paso (Milestone 1 o
  Fase 3/Pipeline) tiene su propio `correlation_id` — reconstruible vía
  `GET /api/audit?correlation_id=` o la página **Audit**.
