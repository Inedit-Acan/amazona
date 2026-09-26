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
| [0007](adr-0007-production-security.md) | El entorno decide si hace falta identidad; cada ruta mutadora declara su acción y cada rol su conjunto, deny by default |
| [0008](adr-0008-demo-production-isolation.md) | Un `Protocol` por dominio externo y el proveedor activo como configuración; la pantalla dice siempre cuál responde |
| [0009](adr-0009-async-job-runtime.md) | PostgreSQL es la cola y la fuente de verdad; sin Redis, sin Celery, sin tabla de workers |
| [0010](adr-0010-async-resumable-pipeline.md) | El pipeline se ejecuta en un trabajo por ejecución, con los pasos como filas y reanudación por el paso que falló |

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

## 15. Pendientes de integración

Cuatro comprobaciones que **no se pueden cerrar en esta máquina** y que no
pertenecen a ningún milestone concreto: son deuda de verificación, no de código.
Se listan aquí —y no solo en el milestone donde aparecieron— para que no se
pierdan entre milestones, y **ninguna bloquea el siguiente**. Lo que sí hacen es
bloquear producción: las cuatro deben estar cerradas antes de que AMAZONA
opere sobre datos reales.

| Pendiente | De dónde viene | Qué lo cierra |
|---|---|---|
| **Migraciones sobre PostgreSQL/Supabase real.** La cadena completa (`alembic upgrade head`) no se puede aplicar sobre SQLite: la migración de RLS del Milestone 3 emite `DO $$` de PostgreSQL sin guardia de dialecto. Cada migración nueva sí se ejecuta aislada y con datos en `tests/unit/test_migration_*.py`. | Milestones 29, 31, 32 | CI la aplica sobre PostgreSQL limpio en cada push; falta ejecutarla una vez contra la base real antes de desplegar |
| **Conversión del JSON histórico (`pipeline_runs.steps` → `pipeline_steps`) sobre datos reales.** Probada ida y vuelta sobre SQLite con ejecuciones completas y `PARTIAL`; nunca ejecutada sobre las filas que haya en Supabase. | Milestone 32 ([ADR 0010](adr-0010-async-resumable-pipeline.md) §2) | Aplicar la migración sobre una copia de la base real y comparar el `steps` reconstruido con el original antes de tocar producción |
| **Concurrencia real de `SELECT … FOR UPDATE SKIP LOCKED`.** SQLite lo ignora sin error, así que el reclamo único está probado por construcción y por los tests, pero no contra PostgreSQL con varios workers a la vez. | Milestone 31 ([ADR 0009](adr-0009-async-job-runtime.md) §1) | Dos o más `python -m app.jobs.worker` contra la misma base PostgreSQL, comprobando que ningún trabajo se ejecuta dos veces |
| **Login, refresco y cierre de sesión reales.** El flujo de sesión del Control Center está construido y probado con tokens fabricados; falta ejercerlo contra Supabase con credenciales de prueba. | Milestone 29.1 ([ADR 0007](adr-0007-production-security.md)) | Un usuario de prueba en Supabase: entrar, dejar caducar el token para ver el refresco del middleware, y salir |
