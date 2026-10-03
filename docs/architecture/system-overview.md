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
proveedores, ni impuestos reales** — todo dato de negocio es simulado y
está documentado como tal en el propio código de cada agente. Desde el
Milestone 44 existe además un núcleo de **pedidos, cobros, reembolsos y
fulfillment, completamente simulado** (sin pasarela, proveedor ni
transportista reales; §25).

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
- **Pedidos, cobros y fulfillment (Milestone 44):** `orders`, `order_items`,
  `payments`, `payment_events`, `refunds`, `fulfillments`,
  `fulfillment_items` (§25). Las migraciones de M44 no están aplicadas en
  Supabase.
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
| [0007](adr-0007-production-security.md) | El entorno decide si hace falta identidad; cada ruta mutadora declara su acción y cada rol su conjunto, deny by default |
| [0008](adr-0008-demo-production-isolation.md) | Un `Protocol` por dominio externo y el proveedor activo como configuración; la pantalla dice siempre cuál responde |
| [0009](adr-0009-async-job-runtime.md) | PostgreSQL es la cola y la fuente de verdad; sin Redis, sin Celery, sin tabla de workers |
| [0010](adr-0010-async-resumable-pipeline.md) | El pipeline se ejecuta en un trabajo por ejecución, con los pasos como filas y reanudación por el paso que falló |
| [0011](adr-0011-action-gate.md) | El `ActionGate` separa analizar de actuar: los vetos ganan, ninguna firma los levanta, y esperar a una persona es un estado del trabajo |
| [0012](adr-0012-product-intelligence-adapters.md) | El contrato son señales con procedencia; primer adaptador real (proxy declarado), y ante un fallo ausencia en vez de cero |
| [0013](adr-0013-signal-evidence-and-comparison.md) | La evidencia de cada señal se persiste en filas; comparar es contrastar qué sabe cada proveedor, no restar cifras que no hablan de lo mismo |
| [0014](adr-0014-entity-resolution.md) | Dos nombres son el mismo producto por normalización determinista o por alias declarado, nunca por parecido; y cada fusión guarda su motivo |
| [0015](adr-0015-multiple-real-sources-cost-and-usage-rights.md) | `real` con varias fuentes es un compuesto entre reales; medido ≠ estimado ≠ simulado; cada llamada externa se cuenta y lo que la licencia no autoriza no se usa |
| [0016](adr-0016-signal-channel.md) | Una señal dice en qué canal se midió; sin canal es agnóstica y nunca «válida para todos»; la equivalencia entre idiomas la declara la fuente |
| [0017](adr-0017-supplier-facts-and-risk.md) | Quién sostiene un hecho sobre un proveedor (`declared`, `supplier_claim`, `third_party_verified`…); `unknown` no se guarda; riesgo por dimensiones, nunca un score opaco |
| [0018](adr-0018-money-conversion-and-not-evaluable.md) | El dinero lleva moneda y es `Decimal`; una conversión es un hecho con procedencia; sin tasa no hay 1:1, hay `NOT_EVALUABLE`, que nunca es un veto |
| [0019](adr-0019-legal-requirements-and-source-anchoring.md) | Aplicabilidad, vigencia y evidencia de cumplimiento son tres cuestiones separadas; `PASS` nunca es «producto legal»; `UNKNOWN` nunca asciende a `PASS` |
| [0020](adr-0020-ecb-reference-exchange-rates.md) | Referencias de tipos de cambio del BCE: observaciones con fecha efectiva propia y ventana propia, republicación conservada, precedencia manual > BCE > mock entre fuentes aceptables, y cero red dentro del análisis |
| [0021](adr-0021-national-transposition-boe.md) | Transposición nacional declarada por una persona y anclada en el BOE: evidencia en capas, texto consolidado informativo con su aviso y atribución, y `PASS` que exige norma verificada, corroborada (`426`) y evidencia de cumplimiento |
| [0022](adr-0022-idempotent-pipeline-run-creation.md) | `Idempotency-Key` en `POST /api/pipeline/runs`: misma clave y misma petición devuelven la ejecución original, otra petición con la misma clave es 409, la garantía es la clave única del trabajo (no una consulta previa) y la clave es obligatoria si algún proveedor puede salir del sistema |
| [0023](adr-0023-single-budget-source-and-absence-is-not-permission.md) | Una sola verdad presupuestaria: el libro de la base de datos es la fuente del CEO, del ActionGate y del pipeline; el presupuesto lo autoriza el propietario y no se crea solo; sin presupuesto, sin importe o sin identidad un gasto real se deniega (la ausencia de información no es un permiso); reservar comprueba el límite en la misma sentencia que escribe |
| [0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md) | Ciclo de vida de una acción externa (`PENDING`/`CALLING`/`SUCCEEDED`/`FAILED_CONFIRMED`/`UNKNOWN_OUTCOME`): una sola frontera de durabilidad antes de llamar, clave de idempotencia estable por operación (no por intento) con capacidad declarada por el adaptador, un timeout nunca es un fallo, un resultado desconocido no libera la reserva ni se reintenta a ciegas y veta el siguiente efecto, y solo una consulta, la misma clave o una persona lo resuelven |
| [0025](adr-0025-generic-idempotency-for-synchronous-routes.md) | Idempotencia genérica de las rutas síncronas con efecto: una fila por `(operación, quien pide, clave)` con índice único, misma clave y contenido devuelven la respuesta original, otro contenido o una petición sin terminar es 409, una negativa del dominio libera la clave y un fallo sin veredicto la bloquea, sin caducidad, obligatoria cuando algo puede salir del sistema; con la clasificación de todas las rutas `POST` |
| [0026](adr-0026-database-identity-guards.md) | La identidad de lo que es único la garantiza la base de datos: un presupuesto por nombre, un saldo por presupuesto, un interruptor por nombre, una reserva y una liquidación por referencia, una pregunta pendiente por paso; una referencia se reserva una sola vez; el techo es finito, en céntimos y acotado; la migración nunca borra ni fusiona filas y se niega si ya hay duplicados |
| [0027](adr-0027-approval-boundary-and-budget-authorisation.md) | `Approval` (decisión del CEO, con su dinero reservado y caducidad) y `PipelineReview` (permiso de un efecto de un paso, de un solo uso, o revisión a posteriori) son dos conceptos distintos con una frontera que hacen cumplir las pruebas, no una convención; y la autorización del presupuesto sigue siendo un comando de consola con auditoría de importe, moneda y ámbito, porque un endpoint que fije el techo de gasto es un endpoint que puede subirlo |
| [0028](adr-0028-orders-payments-fulfilment-core.md) | Núcleo de pedido, pago y fulfillment: el pago solo lo confirma un evento verificado por una única puerta (simulado o real), un pedido tiene varios intentos de cobro, la evidencia financiera nunca se descarta (`DUPLICATE_CAPTURE`) y una unidad comprada no vuelve al pool; enmendada al cierre del milestone (bloqueo `FOR NO KEY UPDATE`, perder una carrera es un 409, el evento de reembolso que coincide con un cierre es evidencia, intenciones del frontend sin caducidad, `code` de idempotencia y la deuda de los tres paneles) y enmienda a las ADR 0011, 0024, 0025 y 0027 |

Las frases que tienen que seguir siendo ciertas tras el hardening pre-M44 y la prueba que fija cada una (doce invariantes y veinte escenarios de caos) están en [`pre-m44-invariants-and-chaos-tests.md`](pre-m44-invariants-and-chaos-tests.md).

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
| … | Milestones 16-28: rediseño del Control Center, Neural Nexus y Decision Engine (ver `docs/milestones/`) |
| [29](../milestones/milestone-29-demo.md) | Seguridad de producción: identidad obligatoria y RBAC por acción (§11) |
| [29.1](../milestones/milestone-29-1-read-authorization.md) | La lectura también exige identidad y rol |
| [30](../milestones/milestone-30-demo.md) | Aislamiento demo/real: un contrato por dominio y el proveedor como configuración (§12) |
| [31](../milestones/milestone-31-demo.md) | Runtime de trabajos asíncronos sobre PostgreSQL (§13) |
| [32](../milestones/milestone-32-demo.md) | El pipeline se ejecuta en ese runtime, con los pasos persistidos y reanudables (§14) |
| [33](../milestones/milestone-33-demo.md) | `ActionGate`: publicar, anunciar y gastar dejan de ocurrir solos (§15) |
| [34](../milestones/milestone-34-demo.md) | Señales con procedencia y el primer adaptador real de Product Intelligence (§16) |
| [35](../milestones/milestone-35-demo.md) | La evidencia mensual detrás de cada señal y el informe de contraste contra el mock (§16.5) |
| [36](../milestones/milestone-36-demo.md) | Cuándo dos nombres son el mismo producto: identidad determinista o declarada, y sin duplicar filas por ejecución (§16.6) |
| [37](../milestones/milestone-37-demo.md) | Varias fuentes reales, el libro de coste del §25, y qué permite la licencia de cada proveedor (§16.7, §17) |
| [38](../milestones/milestone-38-demo.md) | El canal en el contrato de señales y el mismo producto medido en varios idiomas (§16.8) |
| [39](../milestones/milestone-39-demo.md) | Quién sostiene un hecho sobre un proveedor y riesgo explicable (§17) |
| [40](../milestones/milestone-40-demo.md) | Dinero con moneda, economía por canal y techo de CAC (§18) |
| [41](../milestones/milestone-41-demo.md) | Legal con requisitos declarados y anclados en EUR-Lex (§22) |
| [42](../milestones/milestone-42-demo.md) | Tipos de cambio de referencia del BCE: refresco explícito, fecha efectiva intacta y ventana propia (§23) |
| [43](../milestones/milestone-43-demo.md) | Transposición nacional de directivas anclada en el BOE: declarada por una persona, verificada, corroborada de forma determinista y siempre marcada como informativa (§24) |
| [44](../milestones/milestone-44-demo.md) | Pedidos, cobros, reembolsos y fulfillment, simulados y desde el backend: el dinero lo confirma un evento verificado, la evidencia financiera nunca se descarta, una unidad comprada no vuelve al pool y Operaciones lee pedidos reales (§25) |

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
- **Un pedido simulado de principio a fin (Milestone 44):** crear un
  pedido con `python -m app.cli create-test-order`, abrir el cobro, simular
  su captura, comprar, enviar, entregar y reembolsar; verlo en Control
  Center → **Operaciones**. Paso a paso, en
  [`milestone-44-demo.md`](../milestones/milestone-44-demo.md).
- **Trazabilidad de cualquier ejecución:** cada paso (Milestone 1 o
  Fase 3/Pipeline) tiene su propio `correlation_id` — reconstruible vía
  `GET /api/audit?correlation_id=` o la página **Audit**.

---

## 11. Identidad, roles y entornos (Milestone 29)

Añadido después del cierre de Fase 4. Detalle completo en
[ADR 0007](adr-0007-production-security.md).

### 11.1 El entorno manda

`Settings.environment` (`backend/app/core/config.py`) toma uno de cinco valores
y de él salen tres propiedades que el resto del backend consulta:

| Propiedad | development · test · demo | staging · production |
|---|---|---|
| `enforces_auth` | solo con `REQUIRE_AUTH=true` | siempre |
| `enforces_rbac` | no | sí |
| `allows_declared_actor` | sí | no |

`validate_for_startup()` corre al importar `app.main` y aborta el arranque de un
entorno exigente mal configurado (sin Supabase, o con CORS apuntando a
localhost en producción).

### 11.2 De token a rol

```text
Authorization: Bearer …
        ↓  AuthService.verify()   firma + exp + iss + aud
      sub, email
        ↓  RoleService.role_for_subject()
   users.subject → users.role_id → roles.name
        ↓
      Actor(subject, email, role, source)
```

`users.subject` guarda el `sub` de Supabase. El propietario da de alta a alguien
por email con `python -m app.cli grant-role`; el primer inicio de sesión
verificado reclama la fila.

### 11.3 Qué puede cada rol

`ApiAction` en `backend/app/permissions/policies.py`; deny-by-default.

| Acción | OWNER | ADMIN | OPERATOR | ANALYST | REVIEWER | VIEWER | SYSTEM |
|---|---|---|---|---|---|---|---|
| `objective.write` | ✅ | ✅ | ✅ | — | — | — | ✅ |
| `agent.run` | ✅ | ✅ | ✅ | ✅ | — | — | ✅ |
| `pipeline.run` | ✅ | ✅ | ✅ | — | — | — | ✅ |
| `approval.resolve` | ✅ | ✅ | — | — | ✅ | — | — |
| `review.resolve` | ✅ | ✅ | — | — | ✅ | — | — |
| `incident.write` | ✅ | ✅ | ✅ | — | — | — | ✅ |
| `kill_switch.write` | ✅ | ✅ | — | — | — | — | — |
| `business.read` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `diagnostics.read` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `audit.read` | ✅ | ✅ | — | — | ✅ | — | — |
| `order.write` (M44) | ✅ | ✅ | ✅ | — | — | — | — |
| `payment.write` (M44) | ✅ | ✅ | ✅ | — | — | — | — |
| `fulfilment.write` (M44) | ✅ | ✅ | ✅ | — | — | — | — |
| `refund.write` (M44) | ✅ | ✅ | — | — | — | — | — |

Convive con el `PermissionEngine`/`ActionType` de Milestone 1, que resuelve otro
eje: qué puede hacer un **agente** mientras se ejecuta, y cuya respuesta puede
ser «pregunta a un humano» (ADR 0007 §4).

### 11.4 Auditoría

`audit_log` gana `actor_role` y `actor_source` (`token` / `declared` / `cli` /
`system`), así que una fila histórica dice si el nombre que aparece en `actor`
estaba verificado o solo afirmado por quien llamó.

### 11.5 Lectura (Milestone 29.1)

Las 33 rutas de lectura se reparten en cuatro categorías, aplicadas **por
router** y no por ruta, para que un `GET` añadido más tarde nazca protegido:

| Categoría | Nº | Acción | Público |
|---|---|---|---|
| Sondas (`/health`, `/health/ready`) | 2 | — | **sí** |
| Negocio | 32 | `business.read` | no |
| Diagnóstico (`/health/detailed`) | 1 | `diagnostics.read` | no |
| Auditoría (`/api/audit`) | 1 | `audit.read` | no |

`/health` responde liveness y `/health/ready` readiness (comprueba la base de
datos, 503 si no responde). Ninguno revela versión de esquema, entorno ni
proveedores: un balanceador no puede llevar un token, así que lo que ven las
sondas lo ve cualquiera.

### 11.6 La sesión en el Control Center

Vive en **cookies** (`@supabase/ssr`), no en `localStorage`, porque el
renderizado en servidor de Next no puede leer `localStorage` y son 14 páginas
las que cargan sus datos ahí.

```text
lib/auth.ts         navegador      createBrowserClient
lib/auth-server.ts  servidor       createServerClient + cookies(), en cache() de React
middleware.ts       navegación     refresca el token (lo único que puede escribir cookies)
lib/api-server.ts   servidor       sustituye el resolutor de token de lib/api.ts
```

Una página de servidor **debe** importar `api` desde `@/lib/api-server`: desde
`@/lib/api` sus peticiones saldrían sin cabecera `Authorization`, lo que en
desarrollo no se nota y en producción es un 401.
`lib/server-api-boundary.test.ts` lo comprueba.

Ambas lecturas de sesión tienen un techo de 4 s: sin él, con Supabase
inalcanzable, una página tardaba 51 s en responder.

### 11.7 Lo que sigue abierto

Rate limiting, enumeración de identificadores y que el backend siga expuesto sin
gateway. La multi-tenencia no aplica: hay una sola organización.

---

## 12. Proveedores externos: demo vs real (Milestone 30)

Detalle en [ADR 0008](adr-0008-demo-production-isolation.md).

### 12.1 El contrato

`app/integrations/ports.py` declara un `Protocol` por dominio externo y los
agentes dependen de él, no de una clase concreta:

```text
Agent → Port (Protocol) → Adapter → External API
```

| Dominio | Puerto | Agente |
|---|---|---|
| `product_intelligence` | `ProductSignalProvider` | `ProductResearchAgent` |
| `suppliers` | `SupplierDirectory` | `SupplierSourcingAgent` |
| `regulatory` | `RegulatoryDirectory` | `LegalComplianceAgent` |
| `ads` | `AdPerformanceDirectory` | `MarketingCampaignAgent` |
| `marketplaces` | `MarketplaceDirectory` | `MarketplaceListingAgent` |
| `payments` (Milestone 44) | `PaymentProvider` | `PaymentService` / `RefundService` |
| `fulfilment` (Milestone 44) | `FulfilmentProvider` | `FulfilmentService` |

### 12.2 Quién está activo

`ProviderRegistry` lo resuelve desde Settings (`<DOMINIO>_PROVIDER` =
`mock` | `sandbox` | `real`). Dos reglas, comprobadas al arrancar y reportadas
por separado:

- **`staging`/`production` no arrancan** si algún dominio sigue en `mock`.
- **Pedir un adaptador que no existe falla** en cualquier entorno, en vez de
  caer al mock en silencio.

`GET /health/detailed` devuelve el entorno y el binding de cada dominio con su
`simulated: true|false`.

### 12.3 En el frontend

`lib/demo/` sigue alimentando los paneles, marcado con `DataProvenanceBadge`.
`lib/demo-boundary.test.ts` congela la superficie: los 41 módulos que hoy
dependen de datos de demostración están listados, la lista solo puede encoger, y
el núcleo (`api.ts`, `auth.ts`, `format.ts`, `dates.ts`, `utils.ts`) no puede
tocarlos nunca. Retirarlos panel a panel es el Milestone 30.1.

---

## 13. Runtime de trabajos (Milestone 31)

Detalle en [ADR 0009](adr-0009-async-job-runtime.md).

### 13.1 Qué es un Job, y qué no

```text
Objective → Task     grafo del CEO (Milestone 1).  Unidad de NEGOCIO.
Job                  runtime (Milestone 31).       Unidad de EJECUCIÓN.
```

Son cosas distintas y las dos conservan su nombre. Un día una `Task` se
ejecutará mediante uno o varios `Job`; hoy no se tocan.

### 13.2 El ciclo

```text
enqueue → QUEUED ──claim──→ RUNNING ──complete──→ COMPLETED
             ↑                  │
             │              fail│
             │                  ▼
             └──espera── RETRYING          (agotados los intentos → FAILED)
                                            FAILED ──requeue──→ QUEUED

WAITING_APPROVAL · BLOCKED    el runtime NO los reclama (Milestone 33)
CANCELLED                     terminal; el resultado que llegue tarde se descarta
```

Reclamar es `SELECT … FOR UPDATE SKIP LOCKED` sobre `jobs`: PostgreSQL es la
cola **y** la fuente de verdad. Redis no interviene.

### 13.3 Arriendos en lugar de una tabla de workers

Un trabajo reclamado lleva `lease_worker` y `lease_expires_at`. `heartbeat()` lo
extiende; un arriendo vencido es un worker muerto y el segador lo reencola. Por
eso **no hay tabla `Worker`**: la única pregunta que importa —¿sigue vivo quien
tiene esto?— ya la responde el arriendo.

`complete()` y `fail()` comprueban que el trabajo sigue siendo del worker que
llama, así que un worker zombi no puede pisar a su sustituto.

### 13.4 Tablas

| Tabla | Para qué |
|---|---|
| `jobs` | la cola y el estado |
| `job_attempts` | cada pasada por un worker, con su error |
| `job_events` | bitácora de solo añadir |

### 13.5 Lo que falta

`WAITING_APPROVAL` existe pero nadie lo pone todavía: eso es el Milestone 33.
`BLOCKED` sí se usa desde el 32 (§14).

## 14. El pipeline en el runtime (Milestone 32)

`POST /api/pipeline/runs` **encola** y responde 202: crea la ejecución en
`QUEUED`, sus nueve pasos en `PENDING` y un trabajo `pipeline.run`. Un worker lo
reclama y recorre los pasos, escribiendo cada uno al empezar y al terminar; los
que ya están `COMPLETED` no se repiten, y eso es lo que hace que reanudar
conserve el trabajo válido.

### 14.1 Los pasos son filas

`pipeline_runs.steps` (JSON) desaparece. La verdad son `pipeline_steps` (un paso
por fila) y `pipeline_step_attempts` (cada pasada por un paso, con el trabajo que
la intentó y su error). La API sigue devolviendo el mismo `steps` de siempre,
reconstruido desde las filas: `status` sigue siendo el estado de **negocio** del
paso —lo que lee la evaluación de riesgo de la ADR 0006— y el de ejecución viaja
aparte, en `step_status`.

`pipeline_runs` gana `job_id` y `request`: sin los parámetros de negocio no se
puede continuar lo que alguien empezó.

### 14.2 Cuatro maneras de pararse

| Estado | Qué pasó | Quién lo mueve |
|---|---|---|
| `PARTIAL` | un paso no pudo entregar nada al siguiente | nadie: es negocio, y va a revisión |
| `FAILED` | un paso reventó | el runtime lo reintenta; si agota intentos, una persona |
| `BLOCKED` | el kill switch estaba apagado cuando le tocó | una persona: reactivar y reanudar |
| `CANCELLED` | alguien la paró | una persona: reanudar |

### 14.3 Los controles

- `POST /api/pipeline/runs/{correlation_id}/resume` continúa por el primer paso
  que no esté `COMPLETED`; con `from_step` rehace ese paso y los siguientes.
  Reencola **el mismo trabajo**, así que la historia queda en un sitio.
- `POST /api/pipeline/runs/{correlation_id}/cancel` para la ejecución; una en
  marcha se entera en su siguiente latido, entre dos pasos.

Ambas usan la acción `pipeline.run` ya existente: no hay rol nuevo.

### 14.4 Tablas

| Tabla | Para qué |
|---|---|
| `pipeline_steps` | un paso de una ejecución, con su estado y lo que produjo |
| `pipeline_step_attempts` | cada pasada por un paso, con su trabajo y su error |

El razonamiento completo está en la [ADR 0010](adr-0010-async-resumable-pipeline.md).

## 15. El ActionGate (Milestone 33)

La raya entre **analizar** —que no le hace nada a nadie y sigue pase lo que
pase— y **actuar** —las nueve acciones con efecto del plan maestro §7—. De los
nueve pasos del pipeline, tres actúan: `ecommerce` y `marketplace` publican, y
`marketing` activa publicidad y gasta.

### 15.1 La regla

`app/gates/action_gate.py` es una función pura con las siete entradas del §7 y
tres salidas. El orden es la decisión:

1. **Vetos** (`DENY`): kill switch apagado, legal `NO_GO`, economía `NO_GO` si la
   acción gasta, presupuesto insuficiente, permiso denegado, rechazo humano.
2. **Firma** (`ALLOW`): una persona lo autorizó y no hay ningún veto.
3. **Dudas** (`REQUIRE_APPROVAL`): `REVIEW` legal o económico, economía `NO_GO`
   sobre algo que no gasta, rol que requiere aprobación, y cualquier gasto en
   `staging` o `production`.
4. Nada que objetar: `ALLOW`.

**Ninguna firma levanta un veto.** Las entradas las recoge `ActionGateService`
de donde ya viven —kill switch, `BudgetEngine`, `PermissionEngine`, `Settings` y
los pasos de análisis de la ejecución—: el gate decide, no calcula.

### 15.2 Qué le pasa a la ejecución

| Salida | El paso | La ejecución | El trabajo |
|---|---|---|---|
| `ALLOW` | se ejecuta | sigue | sigue |
| `DENY` | `DENIED`, con motivos | **sigue**: lo que solo analiza no se detiene | termina normal |
| `REQUIRE_APPROVAL` | `WAITING_APPROVAL` | `WAITING_APPROVAL` | `WAITING_APPROVAL`, sin gastar intentos |

Denegar no es fallar: no se reintenta, y la ejecución entra en la bandeja
post-hoc porque que el sistema haya impedido algo es lo que alguien tiene que
mirar.

### 15.3 Dónde se decide

`pipeline_reviews` tiene dos clases: `POST_HOC` (mirar lo que ya pasó, Milestone
14) y `ACTION_GATE` (autorizar lo que no ha pasado). Misma tabla y misma bandeja
en `/approvals`; la diferencia es que resolver una puerta **mueve la ejecución**
—aprobar la continúa por ese paso, rechazar lo deja denegado y la cadena sigue—.
Una autorización vale para el paso que la pidió: el siguiente vuelve a preguntar.

Cada evaluación se audita como `action_gate.allow`, `.deny` o
`.require_approval`, con sus motivos.

El razonamiento completo está en la [ADR 0011](adr-0011-action-gate.md).

## 16. Product Intelligence: señales con procedencia (Milestone 34)

El primer dominio con un adaptador real. Lo que cambia no es solo que se mida
algo de verdad: es que un número medido y uno inventado dejan de ser la misma
fila.

### 16.1 El contrato

`ProductSignalProvider.discover()` devuelve candidatos hechos de `Signal`, y cada
señal lleva los nueve campos del plan maestro §8 —`provider`, `source`, `query`,
`market`, `observed_at`, `value`, `confidence`, `raw_reference`, `method`— más
`kind` y `simulated`. `supports()` declara qué sabe medir cada proveedor, que es
lo que permite componer sin adivinar.

`method` dice qué es y qué no es el número. No es documentación: es el campo que
viaja con el dato cuando el dato se aleja de donde se produjo.

### 16.2 Los tres modos

| `PRODUCT_INTELLIGENCE_PROVIDER` | Qué hace | Dónde vale |
|---|---|---|
| `mock` | fixtures con procedencia, marcados como simulados | desarrollo, demo, test |
| `real` | solo lo medido; lo que no se sabe, ausente | cualquier entorno |
| `composite` | lo real primero, fixtures para los huecos | **no** en staging ni producción |

`composite` cuenta como simulado precisamente porque puede servir fixtures: un
panel que dijera «real» mentiría en la parte que importa.

### 16.3 El adaptador real

Wikimedia Pageviews: interés mensual por término y proyecto lingüístico. **Proxy
de interés, nunca demanda de compra ni ventas.** Ventana de doce meses completos,
normalización logarítmica contra un techo declarado, confianza acotada a 0,75, y
una señal de trayectoria cuando hay al menos seis meses.

Ante cualquier fallo —404, 429, 500, cuerpo raro, timeout— **no hay señal, nunca
un cero**. Hay tope de peticiones por ejecución, porque la investigación corre
dentro de un trabajo con arriendo de 60 s (ADR 0009).

### 16.4 Lo que esto todavía no es

Los candidatos salen de un catálogo de términos versionado
(`product_intelligence/terms.py`): la pregunta, no la respuesta. **No es
descubrimiento** — solo mide lo que alguien ya pensó— y debe complementarse con
fuentes y mecanismos reales más adelante.

Y un candidato real hoy **no tiene score**: sin señal de competencia no hay
fórmula, y la fórmula no se toca en este milestone (§9 del plan). Lo que falta es
una segunda fuente real, no rellenar mejor.

Cuatro límites conocidos, escritos para que no se descubran por sorpresa:

| Límite | Qué significa | Qué hace falta |
|---|---|---|
| **Wikimedia es un proxy de interés** | mide consultas a una enciclopedia; **no** demanda de compra, ventas ni intención de gasto | contrastarlo (M35) y, cuando haya decisión de gasto, una fuente comercial |
| **No hay segunda fuente real** | competencia y demanda comercial siguen sin medirse; un candidato real se queda sin score | un adaptador real de marketplace o de búsqueda comercial |
| **No hay descubrimiento real** | los candidatos salen de un catálogo escrito a mano: solo se mide lo que alguien ya pensó | marketplaces, minería de reseñas, señales sociales, distribución de precios |
| **La resolución de entidades no cruza idiomas** | resuelta la parte ortográfica y la declarada en el Milestone 36 (§16.6): «Air fryer» y «Airfryer» son uno. «Freidora de aire» **sigue siendo otro candidato**, porque unirlos exige un nombre por mercado y no un nombre canónico único | un nombre por mercado en el catálogo, o los *langlinks* de Wikimedia, que dan la equivalencia entre idiomas desde una fuente |

Ninguno se tapa con datos inventados: una señal que falta se queda ausente, y el
`opportunity_score` no se toca fuera del milestone que le corresponda (§9).

### 16.5 La evidencia y el contraste (Milestone 35)

Cada señal guarda **las medidas que la componen** (`product_signal_observations`):
doce meses de visitas detrás de un 0,7483, con el valor crudo de la fuente. En
filas porque es consultable; la normalización vive en la señal.

`POST /api/research/comparisons` contrasta los dos proveedores para la misma
pregunta y guarda el informe (`research_comparisons`). **No se puede ejecutar
donde los datos simulados están prohibidos**: comparar exige correr el mock.

Lo que el informe dice hoy, medido y no supuesto:

| | Fixtures | Wikimedia |
|---|---|---|
| Candidatos | 3 | 4 |
| Con competencia | 3 | **0** |
| Puntuables | 3 | **0** |
| Confianza media | 0,30 | **0,71** |

Lo medido es más fiable y no alcanza para puntuar. Y **no hay ningún candidato
en común**: los nombres del mock no existen fuera de la demo, así que restar sus
cifras no significaría nada — lo comparable es qué sabe medir cada uno.

Esas cifras son **las del día en que se midieron**. La conclusión se repite —cero
candidatos en común, y lo real sin nada que puntuar—, pero los recuentos exactos se
mueven porque la fuente está viva: el 27-09-2026, al cerrar el Milestone 36, la
misma comparación con los mismos términos dio 5 candidatos y confianza 0,7063
porque la API contestó a los cinco. El informe es una foto, no una serie.

El razonamiento completo está en la
[ADR 0012](adr-0012-product-intelligence-adapters.md) y en la
[ADR 0013](adr-0013-signal-evidence-and-comparison.md); las fuentes candidatas
para cerrar el hueco, con sus costes, en
[fuentes comerciales](../design/fuentes-comerciales-product-intelligence.md).

### 16.6 Quién es un candidato (Milestone 36)

Dos nombres son el mismo producto por **normalización determinista** —sin
diacríticos, en minúsculas, sin puntuación, sin el paréntesis de desambiguación de
Wikipedia— o por **alias escrito a mano** en un catálogo versionado. Por nada más:
no hay umbral de similitud, y no es una simplificación temporal. Un 0,85 de
parecido uniría «Air fryer» con «Air dryer» algún día y nadie sabría qué día
empezó.

Hacía falta antes de la segunda fuente, y resultó hacer falta ya con una sola.
Medido: `terms_for("home", ["air fryer"])` preguntaba por `air fryer` **y** por
`Air fryer`, que en Wikimedia son dos artículos distintos —30.897 visitas contra
5—, así que un solo producto se persistía dos veces, uno con 0,7483 de demanda y
un gemelo con 0,1297.

La misma clave se usa en los cuatro sitios donde se comparan nombres: el catálogo
de términos (para no preguntar dos veces), la composición de proveedores (para
componer en vez de duplicar), el informe de comparación y `ResearchService`, que
**busca el producto antes de crearlo** por identidad y categoría. Las señales y
observaciones se acumulan sobre el producto que ya estaba; cada ejecución sigue
dejando su propio análisis.

Cada fusión guarda su motivo en filas (`product_identity_aliases`): con qué nombre
llegó, a qué identidad, por qué vía (`normalised` o `alias:<versión>`) y en qué
ejecución — incluida la palabra que escribió quien pidió la investigación, que la
canonicalización haría desaparecer. `/api/products` lo publica y la pantalla de
Investigación lo dice: una fusión que no se ve es indistinguible de un error.

Lo que **no** resuelve: las traducciones. Medido, aliasar «Freidora de aire» a
«Air fryer» cambiaría 12.099 visitas reales de `es.wikipedia` por un 404, porque
resolver idiomas necesita un nombre **por mercado**. El razonamiento está en la
[ADR 0014](adr-0014-entity-resolution.md).

Tres consecuencias más que conviene tener presentes, con su detalle en el
[Milestone 36](../milestones/milestone-36-demo.md):

- **Los datos anteriores al milestone conservan su clave.** El relleno de la
  migración aplica solo la normalización, no el catálogo de alias —congelar una
  lista que cambia daría la ilusión de estar al día—, así que una fila antigua
  llamada `airfryer` mantiene su propia clave y su duplicado preexistente **no se
  resuelve solo**.
- **`identity_key` es nulable y no es única.** Nula significa «no resuelta», no
  «sin identidad». Y no es única porque en `products` también hay productos dados de
  alta a mano: decidir que dos nombres son el mismo producto es del catálogo de
  alias, no de un índice.
- **Las ejecuciones convergen.** Dos investigaciones —o dos ejecuciones del
  pipeline— sobre la misma categoría aterrizan en el mismo producto: acumula varios
  análisis, comparte `store_slug` (el slug sigue al producto, como
  `generate_store_slug` promete desde siempre) y sus tiendas, listados y campañas se
  acumulan sobre esa fila. El mismo término bajo dos categorías sigue siendo dos
  productos, porque la categoría viene de la petición y no de la fuente.

### 16.7 Varias fuentes reales, y qué permite cada licencia (Milestone 37)

**Medido, estimado y simulado son tres cosas.** Hasta aquí una señal era «simulada o
no», y eso juntaba un número que una fuente **observó** con uno que una fuente
**modeló**. Los dos vienen del mundo y no valen lo mismo. `SignalBasis` los separa,
con techo de confianza por base —1,0 medido, 0,6 estimado, 0,4 fixture— que **falla
al construir la señal** si se excede en vez de recortarse en silencio, y con orden de
preferencia: lo medido gana a lo estimado, y lo estimado a lo inventado.

**`real` con varias fuentes es un compuesto entre reales.** Una lista ordenada de
nombres de adaptador: el primero que da una señal manda, los siguientes rellenan lo
que falte, y como no hay fixtures de por medio el resultado **no es simulado** y
sirve donde los datos simulados están prohibidos. `composite` sigue significando lo
que significaba. Una fuente configurada que no existe, o una lista vacía, abortan el
arranque.

**Tener el dato no es tener permiso.** Una matriz por proveedor declara ocho usos
—almacenamiento, retención, transformación, métricas derivadas, scoring, IA/LLM,
redistribución, uso comercial— más la atribución, con su fuente y su fecha. **Lo que
no se sabe no se permite**: `UNKNOWN` pesa igual que `DENIED` para actuar, y se
distingue solo para saber qué queda por leer. Se aplica donde importa: una señal cuya
licencia no permite puntuar **no entra en el score** y se dice quién la retuvo; una
cuya licencia no permite almacenar **no se persiste** y la auditoría lo cuenta.

**eBay Browse entra como adaptador de referencia y sus datos no se usan.** Es la
primera señal de competencia **medida** del sistema —el hueco que impedía puntuar—,
es gratis, tiene sandbox y cubre varios mercados. Pero su contrato define «Restricted
APIs» por lo que la API aporta, y no se ha podido determinar si Browse entra ahí, así
que casi toda su fila está sin resolver y sus señales se leen sin guardarse ni
puntuar. El razonamiento completo, en la
[ADR 0015](adr-0015-multiple-real-sources-cost-and-usage-rights.md).

Y `ProviderKind.SANDBOX`, que desde la ADR 0008 era una casilla del enum sin nada
detrás, resuelve ahora a los mismos adaptadores contra su host de pruebas.

### 16.8 Dónde se mide una señal (Milestone 38)

`market` dice en qué **geografía**; `channel` dice en qué **canal**. Hasta el
Milestone 38 solo existía la primera, y eso hacía que «cuánta competencia hay»
significara cosas incompatibles sin que nada en el dato lo avisara: dentro de un
marketplace es cuántos vendedores compiten; para una web propia es dificultad
orgánica y coste del clic.

**Cuatro tipos cerrados y plataformas abiertas.** `own_web`, `marketplace`, `search`
y `social` son conceptos y no crecen con cada proveedor; Amazon, eBay, Etsy, Mercado
Libre o TikTok Shop son **valores**, y añadir uno es una línea de catálogo y
**ninguna migración**. La señal guarda una clave autodescriptiva
(`marketplace:amazon`) y el **tipo lo da el catálogo**, no un `split(':')`. Una clave
no declarada falla al construir la señal. Y TikTok no es TikTok Shop: uno descubre y
el otro cobra.

**Sin canal significa agnóstica, nunca «válida para todos».** Competencia y las dos
demandas no significan nada sin decir dónde se midieron; el interés, la trayectoria,
el riesgo y la escalabilidad son propiedades del producto. Así que una señal ligada a
canal sirve **solo** para su canal, y sin canal declarado solo para una decisión
igualmente sin canal — si valiera para todos, el relleno de un fixture decidiría sobre
Amazon. El score dice para qué canal se calculó y, cuando no puede, si lo impidió una
licencia o un canal equivocado.

**El mismo producto en varios idiomas.** Los *langlinks* de Wikimedia declaran la
equivalencia que el Milestone 36 había dejado pendiente: «Air fryer» es «Freidora de
aire» en `es.wikipedia`, y el mercado español pasa de un 404 medido a **0,6805 de
demanda**. El candidato conserva su nombre canónico —si no, medir cuatro mercados
daría cuatro productos— y la equivalencia se guarda con su motivo
(`langlinks:es.wikipedia`). Sin equivalencia declarada, ese término **no se mide**: no
se traduce ni se aproxima.

`SEARCH_DEMAND` y `MARKETPLACE_DEMAND` se separan de `DEMAND` como pedía el plan §8, y
**nadie las emite todavía**: no hay fuente de volumen de búsqueda comercial. Wikimedia
sigue en `DEMAND` y sigue significando **interés**. El razonamiento completo, en la
[ADR 0016](adr-0016-signal-channel.md).

## 17. Quién sostiene un hecho sobre un proveedor (Milestone 39)

El plan maestro §10 pide cuatro niveles de procedencia y dice, con esas palabras: «No
marcar un proveedor como "verified" sin explicar qué significa». Lo que había era un
`bool` en `Supplier` y otro en `SupplierQuote`, y un `reliability_score` con
`default=0.0` que hacía indistinguible «no sabemos si es fiable» de «no es nada
fiable».

**`SupplierFactProvenance`**: `third_party_verified`, `supplier_claim`,
`amazona_estimate`, `simulated` y `unknown`. `unknown` **no se guarda** —una fila que
dice «no se sabe» afirma lo mismo que no tener fila— y `third_party_verified` **falla
al construirse** sin emisor, en el dominio y no en la pantalla.

Son **tres hechos distintos**, y por eso tres columnas: quién sostiene que la empresa
es quien dice ser (`suppliers.verification`), quién sostiene **esa tarifa**
(`supplier_quotes.provenance`) y quién sostiene el coste logístico
(`logistics_provenance`, casi siempre nuestro estimador). Que una empresa esté
auditada no audita su tarifa.

**Una cotización lleva ya sus condiciones comerciales**: moneda, unidad y cantidad
cotizadas, MOQ, Incoterm (los once de 2020, conjunto cerrado), condiciones de pago,
preparación separada de transporte, modo de transporte, coste logístico, mercado de
destino y vigencia. Todo nulable: un Incoterm por defecto sería una condición pactada
que nadie pactó, y cinco columnas dejaron de ser `NOT NULL` para que un número que
nadie ha dicho pueda faltar.

**No se convierte entre monedas.** Un precio sin moneda se rechaza; dos precios en
monedas distintas no se comparan y se dice que no se pueden comparar. Inventar un tipo
de cambio metería un error del 5 % en el margen sin que nadie lo viera.

**Las ocho capacidades del §16 son declaraciones**, no booleanos: `supplier_capabilities`
guarda qué, si la soporta, quién lo dice, desde cuándo y una nota, por proveedor o por
producto. Sin fila la respuesta es `unknown`, **nunca** `false`.

**La identidad de proveedor es la regla del Milestone 36 aplicada a empresas**: nombre
normalizado más dónde está, determinista o declarada, nunca por parecido. `fold` vive
desde aquí en `app/core/text.py` para no tener dos copias que divergen.

**El riesgo del §11 son ocho respuestas, no un número.** `SupplierRiskProfile` no tiene
puntuación total y hay un test que lo comprueba; cada dimensión trae nivel, motivo y
los hechos que miró, y existe un cuarto nivel —`unknown`— porque un riesgo que nadie
ha evaluado no es un riesgo bajo. Se deriva al leer y no se guarda: una evaluación
guardada envejece sin avisar.

**La entrada manual es permanente**, con acción propia `SUPPLIER_WRITE` —distinta de
`AGENT_RUN`, porque correr el agente es pedir datos y esto es afirmar un hecho sobre
una empresa real— y sin `SYSTEM`: ningún proceso automático afirma hechos sobre una
empresa. El razonamiento completo, en la [ADR 0017](adr-0017-supplier-facts-and-risk.md).

## 18. Dinero, conversión y lo que no se puede evaluar (Milestone 40)

El Milestone 39 dejó una cotización con moneda y la regla de no convertir entre
ellas. Lo que no dejó fue nada que lo impidiera: el margen se seguía calculando
restando un coste en dólares de un precio en euros, con un aviso en la lista de
riesgos y el número mal. Un aviso no es una salvaguarda.

**`Money` lleva importe y moneda, y restar dos monedas distintas falla al construir
el resultado.** El importe es `Decimal`: `0,1 + 0,2` vale `0,30000000000000004` en
coma flotante, y un céntimo por unidad son cuarenta euros en un pedido de cuatro
mil. Cuatro decimales por dentro, dos al presentar, y **se redondea al final**. El
resto del repositorio sigue en `float` y la frontera tiene una puerta por sentido
en `app/money/serialization.py`.

**Una conversión es un hecho con procedencia**: diez campos, con el par y la
dirección sin ambigüedad —«1,08» puede ser dólares por euro o al revés, y entre las
dos lecturas hay un 16 %— y **se guardan todas**, porque el precio y la logística se
convierten por separado. Sin tasa aplicable no hay conversión: hay `NOT_EVALUABLE`,
y **nunca 1:1**. Una tasa de más de treinta días deja de valer; una del futuro se
rechaza. La fuente es una persona escribiendo el cambio que le aplicó el banco, bajo
una acción propia que ni `SYSTEM` tiene.

**`NOT_EVALUABLE` no es un resultado negativo.** Un margen negativo se sabe y es
malo; esto es que no se sabe. Sale como `REVIEW` y **nunca** como `NO_GO`, porque el
ActionGate veta los `NO_GO` que gastan (ADR 0011). Y hay tres evaluabilidades: el
margen por unidad puede ser firme mientras el margen por pedido y el techo de CAC no
lo son.

**Cada coste está en una de cinco situaciones**, y las cuatro que suman cero euros
significan cuatro cosas distintas: está dentro de otro (y dice cuál), no aplica (con
motivo), nadie lo ha dicho y hace falta, o nadie lo ha dicho y no cambia nada. Los
invariantes fallan si un contenedor no existe o no se conoce, y así las tres
instancias de doble contabilización del Milestone 39 —DDP, estimador logístico,
comisión de marketplace— dejan de ser parches por caso.

**Cada componente lleva su procedencia**, y el margen declara la **más floja**: un
suelo, no una nota. Si un solo sumando viene de un fixture, el margen es simulado.

**Unidad, pedido y adquisición dejan de ser lo mismo.** Hasta aquí el backend
llamaba `monthly_unit_sales` a la cifra que el frontend llamaba `monthlyOrders`, y
el techo de CAC salía de esa confusión. Ahora son cinco cifras nombradas, y
`unidades_por_pedido` es un dato **declarado**: un 1 que nadie declaró deja el CAC
sin evaluar. Una adquisición es un pedido, escrito para que no sea una suposición.

El CAC máximo dice **cuánto podríamos permitirnos pagar**, no cuánto costará.
`target_cac` no se calcula. El razonamiento completo, en la
[ADR 0018](adr-0018-money-conversion-and-not-evaluable.md).

## 19. El coste de las llamadas externas (Milestone 37)

El plan maestro §25 lo pide **antes** de introducir LLM o APIs comerciales, y la
secuencia del §32 no lo programó en ningún milestone: `provider, operation, units,
estimated_cost, actual_cost, currency, correlation_id` con límites por proveedor,
ejecución y día.

`external_api_costs` guarda esos siete campos más `unit` —qué se cuenta: «8 unidades»
sin decir de qué no es un dato—, `outcome` y `denied_reason`. **Una denegación deja
fila igual que un permiso**: es lo que explica por qué una investigación volvió sin
señales, y sin ella el sistema parecería averiado en vez de prudente. `actual_cost` es
nulable y **nulo no es cero**: es que el proveedor todavía no ha dicho lo que cobró.

Tres reglas gobiernan si una llamada se hace:

- **Un proveedor de pago sin límite de gasto autorizado no se llama.** El presupuesto
  no se hereda de ninguna parte, y un proveedor sin política de coste escrita se trata
  como de pago.
- **Gratis no es lo mismo que sin límite.** eBay publica 5.000 llamadas al día,
  Wikimedia pide no pasar de 200 por segundo, y esas cuotas se respetan aunque el
  precio sea cero.
- **Cuando no cabe, no hay señal.** Nunca un cero (ADR 0012 §4).

La decisión es una función pura, al estilo de `evaluate_action`; el contador que la
consulta y apunta el resultado **se inyecta** desde quien tiene sesión y
`correlation_id`, porque un gasto sin ejecución a la que atribuirlo no se puede
auditar. `GET /api/costs/api-usage` lo publica —consumido, cuota, estimado, cobrado,
autorizado y denegaciones— y el panel Estado lo enseña sin rellenar con demostración
cuando la petición falla.

Está **separado del ActionGate** a propósito: aquél gobierna publicar, anunciar y
gastar dinero del negocio; esto es infraestructura con sus propias ventanas. Los dos
los leerá el CFO más adelante.

## 20. Pendientes de integración

Cuatro comprobaciones que **no se pueden cerrar en esta máquina** y que no
pertenecen a ningún milestone concreto: son deuda de verificación, no de código.
Se listan aquí —y no solo en el milestone donde aparecieron— para que no se
pierdan entre milestones, y **ninguna bloquea el siguiente**. Lo que sí hacen es
bloquear producción: las cuatro deben estar cerradas antes de que AMAZONA
opere sobre datos reales.

| Pendiente | De dónde viene | Qué lo cierra |
|---|---|---|
| **Migraciones sobre PostgreSQL/Supabase real.** La cadena completa (`alembic upgrade head`) no se puede aplicar sobre SQLite: la migración de RLS del Milestone 3 emite `DO $$` de PostgreSQL sin guardia de dialecto. Cada migración nueva sí se ejecuta aislada y con datos en `tests/unit/test_migration_*.py`. | Milestones 29, 31, 32 | CI la aplica sobre PostgreSQL limpio en cada push; falta ejecutarla una vez contra la base real antes de desplegar. **Las tres migraciones del Milestone 44 (`f6a1c8d3e925`, `a9d2e7b4c136`, `b3c8f1a5d742`) no están aplicadas en Supabase** y solo se han ejercido sobre PostgreSQL local y el de CI |
| **Conversión del JSON histórico (`pipeline_runs.steps` → `pipeline_steps`) sobre datos reales.** Probada ida y vuelta sobre SQLite con ejecuciones completas y `PARTIAL`; nunca ejecutada sobre las filas que haya en Supabase. | Milestone 32 ([ADR 0010](adr-0010-async-resumable-pipeline.md) §2) | Aplicar la migración sobre una copia de la base real y comparar el `steps` reconstruido con el original antes de tocar producción |
| **Concurrencia real de `SELECT … FOR UPDATE SKIP LOCKED`.** SQLite lo ignora sin error, así que el reclamo único está probado por construcción y por los tests, pero no contra PostgreSQL con varios workers a la vez. | Milestone 31 ([ADR 0009](adr-0009-async-job-runtime.md) §1) | Dos o más `python -m app.jobs.worker` contra la misma base PostgreSQL, comprobando que ningún trabajo se ejecuta dos veces |
| **Login, refresco y cierre de sesión reales.** El flujo de sesión del Control Center está construido y probado con tokens fabricados; falta ejercerlo contra Supabase con credenciales de prueba. | Milestone 29.1 ([ADR 0007](adr-0007-production-security.md)) | Un usuario de prueba en Supabase: entrar, dejar caducar el token para ver el refresco del middleware, y salir |

## 21. Deuda funcional registrada

Lo del §18 es deuda de **verificación**: cosas ciertas que solo un entorno real
confirma. Esto es otra cosa — deuda de **función**: cosas que el sistema todavía no
sabe hacer y que alguna decisión ya necesita. Se registran aquí para que no vivan solo
en el milestone donde se descubrieron.

| Deuda | Por qué importa | Dónde debería ir |
|---|---|---|
| **CAC real medido** | El Milestone 40 calcula **cuánto podríamos permitirnos pagar** por una adquisición, y sigue sin saber cuánto costará. Un techo de 12,50 € no dice nada sobre si el clic cuesta 0,40 € o 4 € | Exige plataformas de anuncios con gasto real. Es §17 del plan maestro, y no antes de que haya una web propia con tráfico |
| **Rentabilidad objetivo (`target_cac`)** | El Milestone 40 calcula el techo de **equilibrio**: el CAC con el que el beneficio es cero. Operar en el equilibrio no es un negocio | Fijar un beneficio o margen mínimo por pedido. El contrato ya tiene el hueco (`target_margin_per_order`) y está vacío a propósito |
| **~~Fuente automática de tipos de cambio~~** *(cerrada en el Milestone 42 para las 6 monedas que el catálogo admite y el BCE publica; queda lo de abajo)* | Hoy la tasa la escribe una persona. Funciona para una negociación al mes y no para un catálogo | Un adaptador con fecha y fuente, bajo el libro de coste del §25. El BCE publica referencias diarias gratis y sin alta: pendiente de pasar por la matriz de derechos del Milestone 37 |
| **`Decimal` en el resto del repositorio** | El dominio monetario del Milestone 40 es exacto; `budgets` (que ya almacenaba `Numeric` y razonaba en `float`), `external_api_cost` y las columnas heredadas de `economic_analyses` no | Un milestone propio de migración, o irlo pagando cada vez que un dominio toque dinero |
| **~~Fuente de tipos de cambio~~** *(cerrada en el Milestone 42 para USD, GBP, CNY, HKD, MXN y PLN)* | Desde el Milestone 39 una cotización lleva su moneda, y **no hay con qué convertirla**. Dos cotizaciones en monedas distintas no se comparan, el coste de aterrizaje del mock (en dólares) no se puede sumar a costes en euros, y el margen que Economics calcula sobre un coste en otra moneda lleva un aviso en vez de una conversión. Inventar un tipo de cambio metería un error del 5 % que nadie vería | Un adaptador de tipos de cambio con fecha y fuente, bajo el libro de coste del §25. Es requisito previo para que el margen del M40 sea real sobre cualquier proveedor que no cotice en euros |
| **Catálogo de qué países forman cada mercado** | Sin él, un proveedor con país declarado (`ES`) y un destino expresado como mercado (`eu`) dan riesgo geopolítico **desconocido**: el sistema se niega a decir que cruza una frontera porque `es` no es la misma cadena que `eu`. Afecta a una de las ocho dimensiones del §11 | Una línea de catálogo por mercado, como los canales del Milestone 38. Ninguna migración |
| **Certificaciones de proveedor** | El plan §10 las pide («certifications») y el Milestone 39 no las modela: siguen siendo dato de demostración en la pantalla. Una certificación necesita emisor, alcance y caducidad, que es una tabla propia. **El Milestone 41 modela la evidencia de cumplimiento de un *producto* frente a un requisito, no las certificaciones de un *proveedor*: esta sigue abierta** | Un milestone propio; puede reutilizar `compliance_evidence` y su regla de emisor obligatorio |
| **Derecho nacional y otras fuentes de normativa** *(parcialmente cerrada en el Milestone 43: una transposición nacional declarada ya se verifica y se ancla en el BOE; queda lo demás)* | El Milestone 41 solo ancla Derecho de la UE (EUR-Lex). Una directiva no puede dar `PASS` sin una transposición nacional **declarada**, y esa declaración no la verifica nadie. Safety Gate, BOE, ECHA y Access2Markets quedan fuera | Safety Gate como milestone complementario (señal de riesgo por producto); BOE para verificar transposiciones. Cada uno pasa antes por derechos y coste (ADR 0015) |
| **Cruces de tipos de cambio** | El BCE solo publica pares contra el euro. `USD→GBP` no está publicado y calcularlo es otra cosa que leerlo: una tasa derivada por AMAZONA, que la licencia obliga a rotular como modificada. Hoy todo se convierte a EUR y no hace falta | Un milestone que implemente `CROSS_VIA_EUR` con los invariantes de la [ADR 0020](adr-0020-ecb-reference-exchange-rates.md) §7: dos patas de la misma fecha, un solo salto, sin mezclar fuentes |
| **Diferencial bancario en el margen** | Una referencia del BCE es la tasa intermedia; un banco o un procesador aplica un diferencial. El margen calculado con ella es algo optimista. Modelar un diferencial sería inventarlo | Un coste declarable de conversión de divisa, con su procedencia, no un número por defecto |
| **Planificador del refresco de tasas** | El refresco existe (endpoint y trabajo `fx.refresh`) pero nadie lo dispara solo: si nadie lo pide, las referencias caducan a los 7 días y el margen vuelve a ser no evaluable | Una capa de ejecución que encole el trabajo (§23 bis del plan maestro: aplazada). Hasta entonces, una persona |
| **Monedas del BCE fuera del catálogo y monedas que el BCE no publica** | 23 de las 29 divisas del BCE no se guardan porque el catálogo no las admite; `VND` (que usa el mock) no la publica el BCE | Ampliar el catálogo cuando un proveedor real cotice en una de ellas (decisión aparte); `VND` sigue pidiendo tasa declarada |
| **Derecho nacional genérico** | El Milestone 43 solo ancla la transposición de una directiva ya declarada. Una norma española que se aplica a un producto **sin** directiva detrás (jurisdicción `es`, sin CELEX) sigue sin poder declararse ni verificarse | Un milestone propio: modelo de requisito sin CELEX, con la misma regla (una persona declara, el BOE verifica). Sin búsqueda ni inferencia |
| **Cobertura de la legislación consolidada** | La AEBOE consolida principalmente normas con rango de ley: un real decreto u orden no consolidado da `404` y el requisito queda en revisión. Verificar su publicación por el sumario exigiría pedir a una persona la fecha de publicación | Decidir con las normas reales que se declaren; el sumario ya está integrado como comprobación auxiliar |
| **Derogaciones parciales de una norma nacional** | Las banderas del BOE son de la norma entera. Una derogación parcial solo aparece como relación posterior, y el sistema solo eleva a revisión las de anulación o suspensión (`220`, `221`, `230`, `231`) sin interpretar su efecto | Que una persona las lea; el sistema no decide su efecto jurídico |
| **Ancla nacional para otros países y fuentes** | El BOE es el único adaptador de Derecho nacional. Otros países, Safety Gate y ECHA quedan fuera | Un adaptador por fuente tras `NationalNormSource`, cada uno con sus derechos y coste (ADR 0015) |
| **~~Coste de adquisición (CAC) en Economics~~** *(cerrada en el Milestone 40)* | `EconomicAnalysis` tiene precio de venta, costes fijos y margen, y **no tiene CAC**. Un producto con 40 % de margen y un coste de adquisición del 60 % del precio pierde dinero, y hoy el sistema no puede verlo. **La evaluación económica de venta directa no puede considerarse completa sin esto**, y la venta directa es el canal prioritario | El plan maestro lo roza en §17 (límites de `max CPC` y `max CAC` para campañas) y en §18 (el embudo devolviendo datos a Economics), y **no le da ubicación inequívoca**. Se propone un milestone propio del dominio Economics: *«el coste de adquisición entra en la decisión»*, antes del `opportunity_score` v2 del §9, que lo necesita para su factor de margen |
| **Reconciliadores programados (M44)** | `reconcile-actions`, `reconcile-payment-events` y `resolve-action` solo existen como comandos manuales. Sin ellos se quedan atascados: acciones `PENDING` (reserva retenida), cobros `OPENING` o `UNKNOWN_OUTCOME` (bloquean cobros nuevos), eventos `RECEIVED`, reembolsos y fulfillments en `UNKNOWN_OUTCOME` | Trabajos del runtime asíncrono (§13), antes de conectar ningún proveedor real. Propuesto para el Milestone 45 |
| **Dashboard, CFO y Proyectos con pedidos reales (M44)** | Siguen mostrando pedidos inventados (`buildOrders`), etiquetados como demostración; Operaciones ya no coincide con ellos | Convertirlos a `GET /api/orders` y al libro económico de ingresos. Decidido por el propietario para el Milestone 45 |
| **Libro económico de ingresos** | El dinero cobrado y reembolsado vive en `payments`, pero ninguna cifra económica (CFO, márgenes) lo usa: el presupuesto tiene una sola fuente de verdad y los ingresos todavía no | Un libro alimentado por capturas y reembolsos verificados. Propuesto para el Milestone 45 |
| **Cierre de un cobro `OPEN` sin evento del proveedor** | No existe `payment.cancel` ni caducidad: un intento abierto que el proveedor nunca cierra bloquea nuevos intentos de ese pedido | Antes de una pasarela real |
| **Corregir P2-1 y P2-2 (M44)** | `ExternalActionStateError` no tiene tratamiento HTTP en cobros y reembolsos; Operaciones lee como máximo 500 pedidos sin avisar de que trunca | Decidido por el propietario: Milestone 45, con `fix:` propios |

## 22. Requisitos legales declarados y anclados en una fuente (Milestone 41)

El plan maestro §12 pide sustituir el directorio regulatorio simulado por fuentes
verificables. La tentación es preguntarle a una base pública a qué productos se aplica
una norma, y **ninguna lo responde**: EUR-Lex publica el texto, la vigencia y las
fechas, y decidir que una norma se aplica a *este* producto es un juicio jurídico. Un
adaptador que lo respondiera lo estaría infiriendo y lo presentaría como un dato de una
fuente oficial. El razonamiento completo, en la
[ADR 0019](adr-0019-legal-requirements-and-source-anchoring.md).

**Tres cuestiones que no se rellenan una con otra**, cada una con su procedencia
(`SupplierFactProvenance`, ADR 0017) y su tabla:

| Cuestión | La sostiene | Tabla |
|---|---|---|
| Aplicabilidad | Una persona (`declared`); el sistema no puede | `regulatory_requirements` |
| Existencia y vigencia | EUR-Lex vía Cellar (`third_party_verified`) | `regulatory_anchors` |
| Evidencia de cumplimiento | Una persona o el emisor del certificado | `compliance_evidence` |

**Cuatro estados cerrados.** `PASS` significa únicamente *dentro del alcance y de los
requisitos declarados y comprobados, Legal no ha encontrado un bloqueo*: nunca «producto
legal». `UNKNOWN` —nada declarado, o una jurisdicción sin fuente— **jamás asciende a
`PASS`** y sale como `REVIEW`, no como `NO_GO` (ADR 0018). `BLOCKED` exige una restricción
con la norma verificada y en vigor. Hacia el ActionGate: `PASS→GO`, `REVIEW_REQUIRED` y
`UNKNOWN→REVIEW`, `BLOCKED→NO_GO`; presupuesto, permisos y aprobaciones siguen aplicándose.

**Fechas que no se confunden**: `verified_at` (cuándo se preguntó), las fechas de la fuente
(`source_effective_from/to`, **sin interpretar**: puede haber dos fechas de entrada en vigor
y `9999-12-31` no está documentado como «sin fin») y `recheck_after`, una **política operativa
nuestra** (30 días, configurable) cuyo vencimiento pide revisión y **no** dice que la norma
haya dejado de estar en vigor.

**Una directiva no basta**: verifica el acto de la UE, no la ley nacional. **La confianza** es
el techo del eslabón más débil (`third_party_verified` 0,8, `declared` 0,6), reglas internas
**no calibradas**.

**Fuente**: el SPARQL público de Cellar, sin alta (el «webservice» y el volcado de EUR-Lex
exigen cuenta EU Login y **no se usan**). Metadatos CC0; derechos y coste escritos antes de la
primera llamada. Con `REGULATORY_PROVIDER=mock` (por defecto) el análisis es el de siempre,
con las mismas cifras y sin `legal_status`; con `real` evalúa los requisitos declarados. En
la prueba de humo Cellar agotó el tiempo en dos de tres consultas y dio un 504 en la tercera:
el sistema degradó a `REVIEW_REQUIRED` sin guardar nada.

Escribir es `REGULATORY_WRITE` (solo OWNER y ADMIN); leer es `BUSINESS_READ`. La pantalla
Legal enseña los tres bloques por separado y sigue rotulando como demostración el resto de
su matriz. Detalle y límites, en
[`milestone-41-demo.md`](../milestones/milestone-41-demo.md).

## 23. Referencias de tipos de cambio del BCE (Milestone 42)

Hasta el Milestone 41 la única fuente de tipos de cambio era una persona escribiendo el
cambio que le aplicó el banco. El Milestone 42 añade el BCE, que publica gratis y sin alta
cuántas unidades de cada divisa valen un euro. El razonamiento completo, en la
[ADR 0020](adr-0020-ecb-reference-exchange-rates.md).

**Lo que es y lo que no.** Es una **referencia informativa**: el BCE dice que no debe usarse
para transacciones. Sirve para estimar un margen; no es la tasa que aplica un banco o un
procesador de pagos, y no incluye su diferencial. «Procedencia `third_party_verified`» quiere
decir que un emisor con nombre la sostiene, no que sea cotizable.

**Dos lados.** El **refresco** (`POST /api/exchange-rates/refresh`, el trabajo `fx.refresh`,
solo OWNER y ADMIN por la API) descarga el fichero diario y guarda observaciones en
`exchange_rates`. El **análisis económico solo lee la base de datos**: no hace red jamás. Sin
planificador todavía: alguien (o un trabajo futuro) tiene que pedir el refresco.

**Cuatro fechas que no se confunden**: la *fecha efectiva* es la de la fuente y no se toca (la
tasa del viernes usada el lunes sigue siendo del viernes); la *fecha de ingestión* es cuándo
entró en nuestra base; la *antigüedad* se calcula y se guarda con cada conversión; la
*aceptabilidad* es política nuestra y **es por tasa**: 30 días para lo declarado a mano (M40) y
**7 días** para el BCE (`ECB_RATE_MAX_AGE_DAYS`).

**Precedencia**: manual > BCE > mock, pero **solo entre fuentes aceptables**. Una tasa manual
caducada ya no tapa una referencia válida (fallo latente del M40, corregido).

**Observaciones, no valores**: identidad `(par, fecha efectiva, fuente, tasa)`. Repetir la
misma observación no duplica; una tasa distinta para el mismo par y fecha (republicación) se
guarda **al lado** de la anterior, la más reciente gana y se audita. Nada se borra.

**Todo o nada**: cualquier fallo de red, formato o contenido inesperado no guarda nada, no
borra nada y no declara «sin cambios». El histórico de 90 días es **recuperación explícita**
(`POST /api/exchange-rates/backfill`), nunca respaldo automático del diario.

**Cobertura**: solo pares `EUR/divisa`; solo las divisas que el catálogo ya admite (6 de las 29
que publica el BCE: USD, GBP, CNY, HKD, MXN, PLN); el resto se lista como omitido en cada
refresco. **Sin cruces** (`USD/GBP` no está publicado y calcularlo es otro milestone; sus
invariantes están escritos en la ADR). `VND` no la publica el BCE.

`EXCHANGE_RATE_PROVIDER=mock` (por defecto) es exactamente el sistema anterior, con las mismas
cifras. Detalle y límites, en [`milestone-42-demo.md`](../milestones/milestone-42-demo.md).

## 24. Transposición nacional anclada en el BOE (Milestone 43)

La ADR 0019 dejó dicho que una directiva verifica el acto de la UE y no la ley nacional que
lo traspone, y permitía `PASS` con una transposición escrita en texto libre. El Milestone 43
añade el BOE como fuente de Derecho nacional **solo para eso**: verificar y anclar una norma
española que **una persona ha declarado** como transposición de una directiva. El
razonamiento completo, en la [ADR 0021](adr-0021-national-transposition-boe.md).

**La regla que lo gobierna:** el sistema no infiere qué norma española traspone una directiva
ni qué norma se aplica a un producto. No hay búsqueda, no hay propuesta, no hay LLM.

**Seis capas que no se rellenan una con otra:** la norma *declarada* (una persona), la
*publicación oficial* (sumario del diario, comprobación auxiliar), el *texto consolidado,
análisis y metadatos* (AEBOE, **meramente informativos**), la *vigencia y estado* (banderas de
la fuente), la *relación con la norma UE* (relación `426 TRANSPONE` de su análisis) y la
*evidencia de cumplimiento* del producto (M41).

**Corroboración determinista:** año y número de la directiva del texto de la relación se
comparan con el CELEX declarado solo si se leen sin ambigüedad; si no, `not_assessable`. Una
relación `427` (parcial) no basta. Nada de similitud textual.

**`PASS` de una directiva** exige a la vez: norma nacional declarada, verificada (comprobación
vigente), en vigor según las banderas, sin relaciones de anulación o suspensión, corroborada
(`426`) **y** evidencia de cumplimiento. Todo lo demás es `REVIEW_REQUIRED`, nunca `BLOCKED`.
Un `404` no es «no existe»: es «no consolidada o inexistente». Un fallo de red o de lectura
del sumario **no** es una conclusión negativa: solo un sumario leído bien que no lista la
norma lo es. **Se endurece M41:** el texto libre ya no basta (se conserva como declaración
humana). Confianza de lo que descansa en datos informativos del BOE: techo **0,7**, regla
interna no calibrada.

**Lo informativo viaja con el dato:** cada comprobación guarda `informational = true`, el
aviso «Texto consolidado de carácter meramente informativo…» y la atribución «Basado en datos de
la Agencia Estatal Boletín Oficial del Estado»; la API y la pantalla los muestran siempre, con
el enlace oficial y el ELI. Las fechas de la fuente se muestran tal cual y **no se comparan con
hoy**. El texto de las normas no se guarda.

**Todo o nada:** metadatos y análisis o nada; el sumario es auxiliar (`confirmed`,
`absent_from_summary`, `check_failed`, `not_checked`).

**Fuente:** la API de datos abiertos de la AEBOE, sin alta ni credenciales y sin cuota
publicada. `User-Agent` neutro del proyecto, sin ningún dato personal. Derechos y coste
escritos antes de la primera llamada; `AI_INGESTION` denegado. `NATIONAL_LAW_PROVIDER=mock`
(por defecto) no llama a nadie. Escribir es `REGULATORY_WRITE`. Detalle y límites, en
[`milestone-43-demo.md`](../milestones/milestone-43-demo.md).

---

## 25. Pedidos, cobros, reembolsos y fulfillment, simulados (Milestone 44)

Hasta el Milestone 43 AMAZONA analizaba y decidía, pero no tenía dónde ocurre una venta. El Milestone 44 construye ese
lugar: **el núcleo de pedido, pago y fulfillment, completamente simulado y pensado desde el backend**. No hay pasarela,
proveedor ni transportista reales, ni cliente final, ni carrito, ni web pública; lo que se construyó es lo que un proveedor
real tendrá que cumplir después. El razonamiento completo y las enmiendas del cierre, en la
[ADR 0028](adr-0028-orders-payments-fulfilment-core.md); la demo, la verificación y los límites, en
[`milestone-44-demo.md`](../milestones/milestone-44-demo.md).

**La regla que lo gobierna:** el dinero lo confirma un evento verificado, y la evidencia financiera nunca se descarta. Ninguna ruta
acepta un campo «pagado»; el navegador no confirma nada; un cobro tardío o duplicado se registra aunque contradiga al pedido.

### 25.1 Qué hay

```text
HTTP (13 rutas) ─► ApiAction (RBAC) ─► run_idempotent (Idempotency-Key obligatoria: 428 si falta)
                                    │
     OrderService · PaymentAttemptService · RefundService · FulfilmentService
                                    │      ActionGateService (permiso, kill switch, coste por operación, veto por desconocido)
                                    ▼
                 ExternalActionService (open · reserve · begin_call · execute · finish · reconcile · resolve · sweep)
                                    │  observadores por prefijo de referencia, dentro de la MISMA transacción
        order_payment:{id} ─► PaymentOpenObserver        order_refund:{id} ─► RefundActionObserver
        order_fulfilment:{id}:{purchase|ship} ─► FulfilmentActionObserver

 hechos entrantes:  POST /api/payments/webhooks/{provider}  y  CLI simulate-payment / simulate-refund
        └► PaymentIngress.receive: 1) verifica (HMAC-SHA256, tiempo constante, ±300 s) · 2) guarda el evento `RECEIVED`
           (hash y lista blanca, jamás el cuerpo) · 3) lo aplica en otra transacción (única vía que cambia un cobro o paga un pedido)
```

**Tablas** (7, migraciones `f6a1c8d3e925`, `a9d2e7b4c136`, `b3c8f1a5d742`, con RLS deny-by-default como el resto):
`orders`, `order_items`, `payments`, `payment_events`, `refunds`, `fulfillments`, `fulfillment_items`. Un pedido tiene N
líneas, N intentos de cobro y N fulfillments; un cobro, N reembolsos; un fulfillment, N líneas. Diez columnas de dinero,
todas `Numeric(18,4)` con su moneda; en la API el dinero viaja como cadena.

**Máquinas de estado.**

| Entidad | Estados |
|---|---|
| `Order` | `AWAITING_PAYMENT → {PAID, CANCELLED}` · `PAID → COMPLETED`. Solo `PaymentService` escribe `PAID` y solo el servicio de fulfillment escribe `COMPLETED` |
| `Payment` (un intento) | `REQUESTED → OPENING → OPEN \| FAILED \| UNKNOWN_OUTCOME`; `OPEN → SUCCEEDED \| FAILED \| EXPIRED` solo por evento verificado; un segundo cobro real es `DUPLICATE_CAPTURE`, uno de otro importe `CAPTURE_MISMATCH` |
| `Refund` | `REQUESTED → SENDING → SUCCEEDED` (solo por `refund.succeeded` verificado) · `UNKNOWN_OUTCOME` conserva la reserva · `FAILED` la libera |
| `Fulfillment` | `READY → PURCHASING → PURCHASED → SHIPPING → SHIPPED → COMPLETED`; `UNKNOWN_OUTCOME` desde comprar o enviar; `CANCELLED` y `FAILED` solo antes de comprar |
| `ExternalAction` | `PENDING → CALLING → {SUCCEEDED, FAILED_CONFIRMED, UNKNOWN_OUTCOME}` (ADR 0024) |

Cada entidad con una operación externa distingue **nada enviado**, **posiblemente enviado** y **resultado desconocido**; el
segundo se escribe en la misma transacción que `begin_call`. Un `UNKNOWN_OUTCOME` no se repite a ciegas, no libera
reservas y solo sale por reconciliación, respuesta tardía o resolución humana.

### 25.2 Las rutas y quién puede

| Ruta | Clave | Permiso |
|---|---|---|
| `POST /api/orders` · `POST /api/orders/{id}/fulfillments` | `Idempotency-Key` | `order.write` · `fulfilment.write` |
| `POST /api/orders/{id}/payments` | `Idempotency-Key` + `ExternalAction` | `payment.write` |
| `POST /api/orders/{id}/refunds` | `Idempotency-Key` + `ExternalAction` | `refund.write` (solo OWNER y ADMIN) |
| `POST /api/fulfillments/{id}/purchase` · `…/ship` | `Idempotency-Key` + `ExternalAction` | `fulfilment.write` |
| `POST /api/orders/{id}/cancel` · `POST /api/fulfillments/{id}/{complete,cancel,fail}` | por estado (repetir es 409) | `order.write` · `fulfilment.write` |
| `POST /api/payments/webhooks/{provider}` | firma del proveedor | sin identidad: se autentica la firma |
| `GET /api/orders` (`status`, `limit` ≤ 200, `cursor`; devuelve una **página** `{items, limit, count, has_more, next_cursor}`) · `GET /api/orders/{id}` | — | `business.read` |

No hay `GET` de un cobro, reembolso o fulfillment suelto: se leen dentro del pedido, con su `attention_required` y sus motivos,
que **se calculan al leer** y nunca se escriben en un `GET`. Un `POST` sin `Idempotency-Key` es un 428 (también en
simulación). Un reembolso solo lo pide una persona con permiso: ningún camino los crea solo.

### 25.3 Lo que sigue siendo cierto en cualquier circunstancia

- **El pago solo lo confirma un evento autenticado.** El simulador usa la misma puerta que un webhook real, con una clave
  efímera por proceso que nunca se guarda.
- **Nunca se pierde dinero cobrado:** un cobro tardío, uno duplicado o uno de otro importe se registra y deja el pedido
  `attention_required`; un pedido cancelado no vuelve a `PAID`.
- **El reembolso lo acota la base de datos**, no el código: `0 ≤ reembolsado ≤ reservado ≤ cobrado`.
- **Una unidad comprada no vuelve al pool** (`release_allocation` es un compare-and-set con la compra sin hacer).
- **El bloqueo del pedido es siempre `FOR NO KEY UPDATE`** y el orden es pedido → cobro o fulfillment (un interbloqueo real lo exigió).
- **Perder una carrera por comprar o enviar es un 409**, nunca un 500.
- **Sin datos personales:** un pedido solo lleva una `customer_ref` opaca (`sim_…` en simulación, sin `@`, con `CHECK`
  en la base de datos); el cuerpo bruto de un webhook no se guarda en ninguna columna.
- **Desconocido no es cero:** una compra cuyo coste no se conoce se deniega (es lo que ocurre si se crea el pedido sin
  `--unit-cost`).

### 25.4 La consola (`python -m app.cli`)

Todos los comandos que cambian algo exigen `AMAZONA_BOOTSTRAP=1`.

| Comando | Qué hace |
|---|---|
| `create-test-order` | crea un pedido de una línea sin datos personales (`--product-id`, `--quantity`, `--unit-price`; `--unit-cost` si se conoce) |
| `simulate-payment` | emite un evento de pago simulado (`succeeded`, `failed`, `expired`, `attempt-failed`) por la misma puerta que un webhook |
| `simulate-refund` | emite el evento con que el proveedor confirma (`succeeded`) o niega (`failed`) un reembolso |
| `reconcile-payment-events` | aplica los eventos `RECEIVED` que no llegaron a aplicarse |
| `reconcile-actions` | libera reservas cuya petición nunca salió y marca las demás como desconocidas |
| `resolve-action` | cierra una acción de resultado desconocido, con su motivo, tras comprobarla a mano |
| `show-actions` | lista las acciones externas y en qué punto está cada una (`--open`: solo las abiertas) |

**Ninguno de estos reconciliadores está programado:** son comandos manuales (P1-1, ver el milestone).

### 25.5 Qué ve el Control Center

**Operaciones lee pedidos reales** (`GET /api/orders`) y deja de inventarlos: pedidos por estado, dinero realmente cobrado y
reembolsado (suma exacta por moneda), el pipeline de fulfillment, los pedidos que requieren atención con los motivos del
backend, el detalle de cada uno, y una tarjeta «Lo que esta pantalla todavía no puede mostrar» (transportistas, devoluciones
físicas, SLA, rendimiento por proveedor, clientes y canal, automatizaciones) con «Sin datos». **Dashboard, CFO y Proyectos
siguen mostrando pedidos inventados**, etiquetados como demostración (P1-2). Todavía **no hay formularios** para crear un
pedido, un cobro o un fulfillment desde la pantalla; las funciones de `api.ts` ya existen y exigen la clave de intención
como parámetro obligatorio.

### 25.6 Qué es real y qué es simulado

| | Hoy |
|---|---|
| Dominio (pedidos, cobros, reembolsos, fulfillment), reglas, base de datos, API, permisos, auditoría, idempotencia | **Real**, probado sobre PostgreSQL |
| Pasarela de pago, proveedor de abastecimiento y transportista | **Simulados** (`simulated-payments`, `simulated-fulfilment`); no existe ningún adaptador real |
| Clientes, carrito, checkout, IVA/OSS, facturas, contabilidad, devoluciones físicas, seguimiento de envíos | **No existen** |
| Migraciones de M44 en Supabase | **No aplicadas** (Supabase tiene 12; requiere autorización y procedimiento aparte) |

`staging` y `production` **no arrancan** hasta que existan adaptadores no simulados de pago y fulfillment (§12.2): es
intencionado.
