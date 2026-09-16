# AMAZONA Milestone 2 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1.

**Objetivo:** evolucionar el monolito modular de Milestone 1 (CEO
Orchestrator + 4 agentes especialistas simulados) hacia el núcleo del
sistema descrito en la Fase 2 del roadmap — base de datos real en
Supabase/PostgreSQL, memoria/contexto compartido entre agentes, un
protocolo de mensajería formal entre agentes, evolución de la orquestación
de tareas, autenticación/roles reales, y monitorización — y arrancar la
Fase 3 con el primer agente operativo: **Agente 1, Investigación de
Productos**.

**Depende de:** Milestone 1 completo (tag `milestone-1`) y
[ADR 0001](../../architecture/adr-0001-orchestrator-vs-ceo.md), que fija
que Orquestador (Agente 9) y CEO son dos capas del mismo proceso, no dos
agentes independientes — el protocolo de mensajería de este milestone es
para CEO ↔ agentes especialistas, no para Orquestador ↔ CEO.

**Bloqueo conocido:** las tareas marcadas 🔒 necesitan credenciales reales
de un proyecto Supabase en región UE (`SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`) en `backend/.env` — que no
existe en el repo ni se genera automáticamente (ver
`backend/.env.example`). Sin esas credenciales esas tareas se implementan
y se prueban con un esqueleto que se salta (`pytest.mark.skipif`) en vez
de fallar, y quedan pendientes de verificación manual contra el proyecto
real.

## Restricciones globales (heredadas de Milestone 1 + nuevas)

- Sin dinero real, pedidos, proveedores ni impuestos reales — igual que
  Milestone 1.
- El Agente 1 (Investigación de Productos) usa **fuentes simuladas/mock**
  únicamente; nada de llamadas a APIs externas reales en este milestone.
- PostgreSQL (vía Supabase) pasa a ser la fuente de verdad real para
  desarrollo local y demos; SQLite se mantiene solo como fallback rápido
  para tests unitarios que no dependen de features específicas de
  Postgres.
- Toda acción relevante sigue auditada (tabla `audit_log` + `AuditService`).
- Cualquier acción simulada de alto impacto (gasto, publicación,
  cambio de política) sigue requiriendo aprobación humana explícita —
  igual que Milestone 1, sin excepciones nuevas.
- El núcleo de decisión determinista (Milestone 1: `decision_engine.py`,
  `permissions/engine.py`, `budgets/engine.py`) no se toca en su lógica de
  veto; solo se le añade una fuente de identidad/rol real (2.5).
- Tests antes que implementación para todo comportamiento determinista
  nuevo. Commit por tarea completada.
- Las tareas 🔒 deben quedar verdes en CI sin credenciales reales
  (usando skip o Postgres efímero del propio CI), y documentarse como
  pendientes de verificación manual contra Supabase hasta que existan
  credenciales.

---

## Estructura de archivos (adiciones sobre Milestone 1)

```text
backend/
├── app/
│   ├── memory/
│   │   ├── schemas.py
│   │   └── service.py
│   ├── messaging/
│   │   └── schemas.py          # AgentMessage, contratos versionados
│   ├── auth/
│   │   ├── models.py           # (vía db/models/user.py, role.py)
│   │   ├── service.py          # verificación JWT Supabase, RoleService
│   │   └── dependencies.py     # FastAPI Depends(current_user)
│   ├── research/
│   │   └── service.py          # ResearchService (persiste hallazgos)
│   ├── agents/
│   │   └── product_research.py # Agente 1
│   ├── ai/
│   │   └── mock_trends_provider.py
│   └── db/models/
│       ├── product.py
│       ├── supplier.py
│       ├── product_analysis.py
│       ├── memory_record.py
│       ├── user.py
│       ├── role.py
│       └── agent_execution_log.py
├── alembic/versions/            # nuevas migraciones incrementales
└── tests/
    ├── unit/…
    ├── integration/…
    └── e2e/test_product_research_flow.py

apps/control-center/
├── app/
│   ├── research/page.tsx        # Fase 3: candidatos priorizados
│   ├── login/page.tsx           # 2.5
│   └── status/page.tsx          # 2.6
└── lib/
    ├── auth.ts
    └── research.ts

docs/
├── architecture/
│   ├── adr-0001-orchestrator-vs-ceo.md   # ya existe
│   └── adr-0002-agent-messaging-protocol.md
└── milestones/
    └── milestone-2-demo.md
```

---

## Sección A — 2.1 Base de datos central real

### Tarea 1: Tablas de dominio — productos, proveedores, análisis

**Files:**
- Create: `backend/app/db/models/product.py`
- Create: `backend/app/db/models/supplier.py`
- Create: `backend/app/db/models/product_analysis.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration
- Create: `backend/tests/integration/test_product_domain_models.py`

**Produces:** persistencia de primera clase para candidatos de producto,
proveedores y snapshots de análisis — hasta ahora esta info vivía solo
como JSON efímero en `tasks.input`/`tasks.output` por ejecución.

**Esquema:**
- `products`: id, name, category, status (`CANDIDATE|VALIDATING|REJECTED|APPROVED`),
  created_by, source (`research|manual`), created_at
- `suppliers`: id, name, verified (bool), region, contact_info (JSON),
  reliability_score, created_at
- `product_analyses`: id, product_id (FK), objective_id (FK nullable),
  analysis_type (`research|validation`), opportunity_score, confidence,
  data (JSON — igual forma que `AgentResult.data`), created_at

- [ ] Test: crear un `Product`, verificar persistencia y campos.
- [ ] Test: `ProductAnalysis` requiere `product_id` válido (FK).
- [ ] Ejecutar y verificar fallo.
- [ ] Implementar modelos + migración.
- [ ] Ejecutar y verificar éxito.
- [ ] Commit: `feat: add product/supplier/analysis domain tables`

**Acceptance:** `alembic upgrade head` desde limpio crea las tablas sin
pasos manuales; funciona igual en SQLite (dev rápido) y Postgres (CI/Supabase).

---

### Tarea 2 🔒: Conectividad real a Supabase/PostgreSQL

**Files:**
- Modify: `backend/app/db/session.py` (pooling seguro para el pooler de Supabase)
- Create: `backend/tests/integration/test_supabase_connectivity.py`
- Modify: `README.md` / `docs/milestones/milestone-2-demo.md`

**Produces:** verificación de que `DATABASE_URL` apuntando a Supabase
funciona con SQLAlchemy + Alembic (pooler en modo transacción de Supabase
requiere `NullPool` o `pool_pre_ping` sin `PREPARE`, y `sslmode=require`).

- [ ] Test (marcado `skipif` cuando `DATABASE_URL` no es un Postgres real,
      vía `os.environ`) que abre una conexión, hace `SELECT 1`, y cierra.
- [ ] Confirmar que corre en CI (usa el Postgres efímero del workflow) y
      que se salta limpiamente en local sin credenciales.
- [ ] Documentar en `docs/milestones/milestone-2-demo.md` cómo apuntar
      `backend/.env` a un proyecto Supabase real y verificar con
      `alembic upgrade head`.
- [ ] **Verificación manual pendiente:** una vez el usuario aporte
      credenciales reales en `backend/.env`, ejecutar `alembic upgrade
      head` contra el proyecto Supabase real y confirmar en el dashboard
      de Supabase que las tablas existen.
- [ ] Commit: `feat: verify supabase postgres connectivity`

**Acceptance:** el mismo código de conexión funciona contra el Postgres
efímero de CI, un Postgres local de `docker-compose`, y un proyecto
Supabase real, sin ramas de código distintas.

---

## Sección B — 2.2 Sistema de memoria y contexto compartido

### Tarea 3: `MemoryService` — memoria estructurada por entidad

**Files:**
- Create: `backend/app/db/models/memory_record.py`
- Create: `backend/app/memory/schemas.py`
- Create: `backend/app/memory/service.py`
- Create: `backend/tests/unit/test_memory_service.py`
- Create: Alembic migration

**Produces:** los agentes (y el CEO) pueden guardar y recuperar hechos
estructurados ligados a una entidad (`product_id`, `objective_id`) para
que ejecuciones futuras no partan de cero — p. ej. "este proveedor ya fue
verificado el mes pasado".

**Interfaz:**
```python
memory.remember(scope="product", scope_id=product_id, key="supplier_check",
                 value={...}, correlation_id=...)
memory.recall(scope="product", scope_id=product_id, key="supplier_check") -> MemoryRecord | None
memory.recall_all(scope="product", scope_id=product_id) -> list[MemoryRecord]
```

- [ ] Test: `remember` seguido de `recall` devuelve el mismo valor.
- [ ] Test: `remember` con la misma `(scope, scope_id, key)` actualiza
      (no duplica) el registro — última escritura gana, pero cada
      escritura se audita.
- [ ] Test: `recall` de una clave inexistente devuelve `None`, no excepción.
- [ ] Implementar (tabla `memory_records` + servicio).
- [ ] Cablear: el Orchestrator llama a `memory.remember(...)` después de
      cada resultado de agente especialista (además de persistir en
      `tasks`/`decision_evidence` — la memoria es la vista "qué sabemos
      de este producto", no el log de ejecución).
- [ ] Commit: `feat: add shared memory service for agent context`

**Acceptance:** dos ejecuciones distintas para el mismo `product_id`
pueden leer lo que la primera aprendió, sin acoplarse a la tabla `tasks`.

---

### Tarea 4 🔒 (stretch, condicionada): memoria semántica con pgvector

**Files:**
- Modify: `backend/app/memory/service.py`
- Create: Alembic migration (columna `embedding vector(...)`, extensión `pgvector`)
- Create: `backend/tests/integration/test_semantic_memory.py`

**Produces:** búsqueda de "productos similares ya investigados" por
similitud semántica — solo si Supabase tiene `pgvector` habilitado
(viene preinstalado en Supabase, pero requiere `create extension vector`).

- [ ] Test `skipif` si `pgvector` no está disponible (detectar vía
      `SELECT 1 FROM pg_extension WHERE extname='vector'`).
- [ ] Implementar columna de embedding + búsqueda por distancia coseno.
      **No se generan embeddings reales con un modelo externo en este
      milestone** — se usa un vector determinista derivado del texto
      (p. ej. hash-based) como placeholder, documentado como tal, hasta
      que exista un proveedor de embeddings real.
- [ ] Commit: `feat: add optional pgvector-backed semantic memory recall`

**Acceptance:** si `pgvector` no está disponible, el resto del sistema
sigue funcionando igual (memoria estructurada de la Tarea 3 no depende de
esto). Esta tarea puede diferirse a Milestone 3 si el tiempo aprieta —
está marcada *stretch* a propósito.

---

## Sección C — 2.3 Protocolo de comunicación entre agentes

### Tarea 5: Esquema formal `AgentMessage` + ADR del protocolo

**Files:**
- Create: `backend/app/messaging/schemas.py`
- Create: `docs/architecture/adr-0002-agent-messaging-protocol.md`
- Create: `backend/tests/unit/test_agent_message_schema.py`

**Produces:** contrato versionado para *toda* comunicación CEO ↔ agente
especialista, reemplazando el `dict` suelto que se pasaba como
`task_input`/`AgentResult` en Milestone 1.

```python
class AgentMessage(BaseModel):
    schema_version: str = "1.0"
    message_id: str
    correlation_id: str
    sender: str          # "ceo" | agent_id
    recipient: str        # agent_id | "ceo"
    capability: str
    payload: dict
    sent_at: datetime
```

- [ ] Test: mensaje válido se construye y serializa.
- [ ] Test: `schema_version` no soportada es rechazada explícitamente
      (no falla en silencio con datos corruptos).
- [ ] Documentar en el ADR *por qué* esto es CEO↔especialistas y no
      Orquestador↔CEO (referencia directa a ADR 0001).
- [ ] Commit: `feat: add versioned agent messaging schema`

**Acceptance:** cualquier payload que cruce la frontera CEO↔agente pasa
por `AgentMessage`, no por un `dict` sin tipar.

---

### Tarea 6: `AgentManager` valida contra el esquema registrado por capability

**Files:**
- Modify: `backend/app/agents/manager.py`
- Modify: `backend/app/agents/base.py` (cada `Agent` declara su
  `input_schema`/`output_schema` opcional)
- Create: `backend/tests/unit/test_agent_manager_schema_validation.py`

**Produces:** si un agente devuelve algo que no cumple el contrato
declarado, el error se detecta en el momento (con mensaje claro), no
como un `KeyError` silencioso tres pasos después en el CEO.

- [ ] Test: agente que declara `input_schema` rechaza un `task_input`
      que no lo cumple, con un error claro.
- [ ] Test: agentes sin `input_schema` declarado (compatibilidad con los
      4 agentes de Milestone 1) siguen funcionando sin cambios.
- [ ] Implementar.
- [ ] Commit: `feat: validate agent io against declared schemas`

**Acceptance:** los 4 agentes de Milestone 1 (Product/Supplier/Finance/
Legal) siguen pasando sus tests sin modificarse — este cambio es
aditivo, no rompe compatibilidad.

---

## Sección D — 2.4 Gestión de tareas y orquestación (evolución)

### Tarea 7: Persistir `task_dependencies` y exponerlas

**Files:**
- Modify: `backend/app/ceo/orchestrator.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/tests/integration/test_ceo_orchestrator.py`
- Modify: `backend/tests/integration/test_api.py`

**Produces:** Milestone 1 dejó la tabla `task_dependencies` sin usar (el
grafo vivía solo en memoria en `TaskService`). Ahora se persiste, y
`GET /api/tasks?project_id=` devuelve `depends_on: [task_id, ...]` por
tarea.

- [ ] Test: tras `run_objective`, existen filas en `task_dependencies`
      que reconstruyen el grafo del plan.
- [ ] Test API: la respuesta de `/api/tasks` incluye `depends_on`.
- [ ] Implementar.
- [ ] Commit: `feat: persist and expose task dependency graph`

**Acceptance:** el grafo de tareas de un proyecto es reconstruible
100% desde la base de datos, sin depender del `TaskService` en memoria
de esa ejecución (que muere con el proceso).

---

### Tarea 8: Ejecuciones concurrentes de objetivos son seguras

**Files:**
- Create: `backend/tests/integration/test_concurrent_orchestration.py`
- Modify: `backend/app/ceo/orchestrator.py` (si el test revela un bug)

**Produces:** prueba explícita (no solo argumento de diseño) de que dos
`run_objective` concurrentes sobre objetivos distintos no interfieren
entre sí (cada uno crea su propio `TaskService` en memoria — Milestone 1
ya lo hacía así, esta tarea lo verifica y lo deja documentado).

- [ ] Test: lanzar dos `run_objective` en threads separados sobre dos
      objetivos distintos con la misma sesión de fábrica; verificar que
      ambos proyectos terminan con sus 5 tareas completas y sin mezclar
      datos entre sí.
- [ ] Si aparece una condición de carrera real, corregirla (probablemente
      en el manejo de sesión de SQLAlchemy por hilo).
- [ ] Commit: `test: verify concurrent objective runs do not interfere`

**Acceptance:** el resultado se documenta en un comentario corto en el
test explicando qué garantiza (aislamiento por instancia de
`TaskService` + sesión de DB propia), para que futuras tareas no
reintroduzcan estado compartido mutable accidentalmente.

---

### Tarea 9: Política de reintentos acotados para tareas fallidas

**Files:**
- Modify: `backend/app/tasks/service.py`
- Modify: `backend/app/ceo/orchestrator.py`
- Modify: `backend/tests/unit/test_task_service.py`

**Produces:** si un agente falla (excepción, no un `AgentResult` de
negocio negativo), la tarea se reintenta hasta un límite determinista
(p. ej. 2 reintentos) antes de marcarse `FAILED` definitivamente — sigue
sin haber red real de por medio, así que esto cubre fallos simulados
inyectables en tests, preparando el terreno para Milestone 3 cuando haya
llamadas reales.

- [ ] Test: un agente que falla las primeras N-1 veces y luego tiene
      éxito termina `COMPLETED`, con el conteo de reintentos auditado.
- [ ] Test: un agente que siempre falla termina `FAILED` tras el límite,
      no en bucle infinito.
- [ ] Implementar `max_retries` configurable con default conservador.
- [ ] Commit: `feat: add bounded retry policy for failed tasks`

**Acceptance:** el límite de reintentos es explícito y testeado; no hay
reintentos infinitos posibles.

---

## Sección E — 2.5 Autenticación, permisos y roles

### Tarea 10: Tablas `users`/`roles` + `PermissionEngine` dirigido por rol

**Files:**
- Create: `backend/app/db/models/user.py`
- Create: `backend/app/db/models/role.py`
- Modify: `backend/app/permissions/engine.py`
- Modify: `backend/app/permissions/policies.py`
- Modify: `backend/tests/unit/test_permission_engine.py`

**Produces:** reemplaza el `actor_role: str` suelto de Milestone 1 por
identidad real respaldada por DB, preservando **todas** las reglas
obligatorias de Milestone 1 (self-escalation prohibida siempre, edición
de política solo `owner`, gasto externo siempre requiere aprobación
humana).

- [ ] Test: los 8 tests de `test_permission_engine.py` de Milestone 1
      siguen pasando sin cambios de comportamiento (solo cambia de dónde
      viene `actor_role`).
- [ ] Test nuevo: un rol inexistente en DB es tratado como sin permisos
      (denegado por defecto, nunca "permitido por defecto").
- [ ] Implementar tablas + `RoleService.role_for(user_id) -> str`.
- [ ] Commit: `feat: back permission checks with real user/role records`

**Acceptance:** ningún test de Milestone 1 relacionado con permisos
cambia de resultado — este cambio es de *dónde viene la identidad*, no
de *qué está permitido*.

---

### Tarea 11 🔒: Verificación de JWT de Supabase Auth en la API

**Files:**
- Create: `backend/app/auth/service.py`
- Create: `backend/app/auth/dependencies.py`
- Modify: endpoints mutadores en `backend/app/api/*.py`
  (`POST /api/objectives`, `POST /api/objectives/{id}/run`,
  `POST /api/approvals/{id}/approve|reject`, futura edición de política)
- Create: `backend/tests/unit/test_auth_service.py`

**Produces:** los endpoints que mutan estado exigen un JWT válido de
Supabase Auth cuando `settings.is_supabase_configured` es `True`; en
modo sin Supabase configurado (dev/CI sin credenciales) se mantiene el
comportamiento abierto de Milestone 1 para no romper nada, con un aviso
claro en logs de que la auth está desactivada.

- [ ] Test: `is_supabase_configured=False` → los endpoints funcionan
      igual que Milestone 1 (sin romper ningún test existente).
- [ ] Test: token inválido/ausente con Supabase configurado → 401,
      usando un JWT firmado con una clave de prueba (no credenciales
      reales) para simular el caso "configurado".
- [ ] Test: token válido (firmado con la misma clave de prueba) → pasa,
      y el `actor` de la auditoría es el `sub` del JWT, no un string libre.
- [ ] Implementar verificación JWT contra el JWKS de Supabase
      (`supabase_url + /auth/v1/.well-known/jwks.json`), con caché del
      JWKS.
- [ ] **Verificación manual pendiente:** con credenciales reales, crear
      un usuario de prueba en Supabase Auth, obtener un JWT real, y
      confirmar que `POST /api/objectives` lo acepta.
- [ ] Commit: `feat: verify supabase auth jwts on mutating endpoints`

**Acceptance:** sin credenciales, todo sigue verde (modo abierto
explícito, no un fallo silencioso). Con credenciales, un JWT inválido es
rechazado y uno válido es aceptado y trazable por `sub`.

---

### Tarea 12 🔒: Login en el Control Center

**Files:**
- Create: `apps/control-center/lib/auth.ts`
- Create: `apps/control-center/app/login/page.tsx`
- Modify: `apps/control-center/lib/api.ts` (adjuntar `Authorization: Bearer <jwt>`)
- Modify: `apps/control-center/components/shell.tsx` (estado de sesión)

**Produces:** pantalla de login (email/password contra Supabase Auth)
que guarda el JWT y lo adjunta a cada llamada a la API. Si
`NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` no están
configuradas, el Control Center sigue funcionando sin login (modo
abierto, igual que el backend).

- [ ] Implementar con el SDK `@supabase/supabase-js` (cliente, solo la
      clave `anon`, nunca la `service_role`).
- [ ] Verificar en navegador: sin credenciales configuradas, el flujo
      Milestone 1 sigue intacto.
- [ ] **Verificación manual pendiente:** con credenciales reales, login
      real y llamada autenticada a `POST /api/objectives`.
- [ ] Commit: `feat: add control center login against supabase auth`

**Acceptance:** el Control Center de Milestone 1 no se rompe para nadie
que no configure Supabase; quien lo configure obtiene auth real.

---

## Sección F — 2.6 Monitorización y logs

### Tarea 13: `AgentExecutionLog` — latencia y coste medidos de verdad

**Files:**
- Create: `backend/app/db/models/agent_execution_log.py`
- Modify: `backend/app/agents/manager.py` (`execute()` mide tiempo)
- Create: `backend/tests/unit/test_agent_manager.py` (extensión)

**Produces:** `AgentDescriptor.latency_profile`/`cost_profile`
(Milestone 1) pasan de ser campos declarativos a alimentarse con
mediciones reales de cada ejecución, persistidas para poder alimentar
`reliability_score` en el futuro.

- [ ] Test: `execute()` registra una fila con `duration_ms` y `agent_id`.
- [ ] Implementar.
- [ ] Commit: `feat: record agent execution latency`

**Acceptance:** después de correr el flujo E2E, `agent_execution_log`
tiene 4 filas (una por especialista) con duración > 0.

---

### Tarea 14: `GET /api/health/detailed`

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_health.py` (extensión)

**Produces:** endpoint operativo que reporta conectividad a DB, versión
de migración aplicada (`alembic_version`), y si Supabase/auth están
configurados — sin filtrar credenciales.

- [ ] Test: responde 200 con `{"database": "ok", "migration": "<rev>",
      "supabase_configured": bool}`.
- [ ] Test: si la DB no responde, devuelve 503 (no 500 ni cuelgue).
- [ ] Implementar.
- [ ] Commit: `feat: add detailed health endpoint`

**Acceptance:** se puede diagnosticar "¿está viva la DB? ¿qué migración
corre? ¿hay Supabase configurado?" con una sola llamada, sin secretos en
la respuesta.

---

### Tarea 15: Página "System status" en el Control Center

**Files:**
- Create: `apps/control-center/app/status/page.tsx`
- Modify: `apps/control-center/components/nav-items.ts`

**Produces:** vista simple que pinta `GET /api/health/detailed` +
últimas entradas de `agent_execution_log` (vía un endpoint de listado
nuevo o reutilizando el patrón de `/api/audit`).

- [ ] Verificar en navegador (desktop + mobile), como en Milestone 1.
- [ ] Commit: `feat: add system status page`

**Acceptance:** el owner puede ver de un vistazo si el sistema está sano
sin abrir una terminal.

---

## Sección G — Fase 3 (inicio): Agente 1 — Investigación de Productos

### Tarea 16: Proveedor mock de tendencias/nichos

**Files:**
- Create: `backend/app/ai/mock_trends_provider.py`
- Create: `backend/tests/unit/test_mock_trends_provider.py`

**Produces:** fuente de datos determinista y fixture-driven (sin red)
que simula señales de tendencia/demanda por categoría/keyword, en el
mismo espíritu que `MockProvider` de la AI Gateway de Milestone 1.

- [ ] Test: misma consulta → mismo resultado (determinista).
- [ ] Test: categorías/keywords distintas producen señales distintas
      (no todo es una constante disfrazada).
- [ ] Implementar con un dataset fixture embebido (JSON o dict Python),
      no llamada externa.
- [ ] Commit: `feat: add mock trends and niche data provider`

**Acceptance:** cero llamadas de red — verificable inspeccionando el
código, no solo confiando en la documentación.

---

### Tarea 17: `ProductResearchAgent` — capability `product_research`

**Files:**
- Create: `backend/app/agents/product_research.py`
- Create: `backend/tests/unit/test_product_research_agent.py`
- Modify: `backend/app/agents/registry.py` (`build_default_agent_manager`)

**Produces:** dado un input de investigación (categoría, keywords,
`max_results`), devuelve una lista rankeada de candidatos con
opportunity score — no valida UN producto dado (eso ya lo hace
`ProductAgent`), sino que **descubre y prioriza varios**.

```python
class RankedProductCandidate(BaseModel):
    name: str
    category: str
    opportunity_score: float
    demand_signal: float
    competition_level: str
    niche_rationale: str

class ProductResearchResult(AgentResult):
    # data["candidates"]: list[RankedProductCandidate] (serializado)
```

- [ ] Test: input con categoría conocida devuelve `max_results`
      candidatos ordenados por `opportunity_score` descendente.
- [ ] Test: candidatos con datos insuficientes se excluyen (no se
      inventan scores altos con datos vacíos — mismo principio que
      `ProductAgent` de Milestone 1: dato faltante → confianza baja o
      exclusión, nunca optimismo infundado).
- [ ] Implementar reutilizando la lógica de scoring de `ProductAgent`
      generalizada a N candidatos.
- [ ] Registrar en `build_default_agent_manager()`.
- [ ] Commit: `feat: add product research agent`

**Acceptance:** `AgentResult` válido (mismo contrato de Milestone 1:
evidence/risks/assumptions/data), con `data.candidates` como el
artefacto principal.

---

### Tarea 18: `ResearchService` — persistir hallazgos y exponerlos

**Files:**
- Create: `backend/app/research/service.py`
- Create: `backend/app/api/research.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_research_api.py`

**Produces:**
- `POST /api/research/runs` → dispara una investigación (categoría/
  keywords), ejecuta `ProductResearchAgent`, persiste cada candidato
  como `Product` (`status=CANDIDATE`, `source=research`) +
  `ProductAnalysis` (`analysis_type=research`), audita el run.
- `GET /api/research/runs/{id}` → resultado con los candidatos y sus
  scores.
- `GET /api/products?status=CANDIDATE` → lista para la UI.

- [ ] Test: `POST /api/research/runs` crea N `Product` + N
      `ProductAnalysis`, auditado con `correlation_id`.
- [ ] Test: `GET /api/research/runs/{id}` reconstruye el resultado desde
      DB (no desde estado en memoria).
- [ ] Implementar.
- [ ] Commit: `feat: add product research api`

**Acceptance:** una investigación es 100% reconstruible desde la base de
datos después de reiniciar el proceso — igual estándar que el resto del
sistema desde Milestone 1.

---

### Tarea 19: Página "Research" en el Control Center + puente a validación

**Files:**
- Create: `apps/control-center/app/research/page.tsx`
- Create: `apps/control-center/lib/research.ts` (extiende `lib/api.ts`)
- Modify: `apps/control-center/components/nav-items.ts`
- Modify: `apps/control-center/app/ceo/page.tsx` (aceptar un candidato
  pre-cargado vía query param para saltar a validación)

**Produces:** lista de candidatos priorizados con score, y un botón
"Validar este producto" que lleva a la página CEO con el `context`
pre-rellenado a partir del candidato investigado — cerrando el loop
Investigación → Validación que pide el enunciado ("lista de productos
priorizados con análisis de oportunidad").

- [ ] Verificar en navegador (desktop + mobile) con datos reales del
      backend, como en Milestone 1.
- [ ] Commit: `feat: add research page and validation handoff`

**Acceptance:** desde "Research" se puede disparar una investigación,
ver candidatos rankeados, y pasar uno a validación sin retipear datos.

---

### Tarea 20: E2E — flujo completo Investigación → Validación

**Files:**
- Create: `backend/tests/e2e/test_product_research_flow.py`
- Update: `docs/milestones/milestone-2-demo.md`

**Escenario:**
1. `POST /api/research/runs` con una categoría → candidatos rankeados.
2. Tomar el candidato mejor puntuado, crear un `Objective` cuyo
   `context` deriva de sus datos de investigación.
3. `POST /api/objectives/{id}/run` → decisión determinista, igual que
   Milestone 1.
4. Verificar trazabilidad completa por `correlation_id` a través de
   ambos runs (investigación + validación) vía `/api/audit`.

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar el flujo en `docs/milestones/milestone-2-demo.md`
      (mismo estilo que el doc de Milestone 1).
- [ ] Commit: `test: verify product research to validation flow end to end`

**Acceptance:** el flujo completo Fase 2 + inicio Fase 3 es reproducible
desde un entorno limpio, con o sin Supabase real configurado.

---

## Definition of Done — Milestone 2

1. `products`, `suppliers`, `product_analyses` son tablas reales,
   pobladas por el flujo de investigación y el de validación.
2. El sistema corre contra Postgres real (CI) de forma verificada;
   contra Supabase real en cuanto existan credenciales (🔒 documentado,
   no bloqueante para el resto del milestone).
3. Existe un `MemoryService` que los agentes pueden usar para no repetir
   trabajo entre ejecuciones sobre la misma entidad.
4. Toda comunicación CEO↔agente especialista pasa por `AgentMessage`
   versionado, con validación de esquema en el `AgentManager`.
5. El grafo de dependencias de tareas es 100% reconstruible desde DB.
6. Ejecuciones concurrentes de objetivos distintos están verificadas
   como seguras; las tareas fallidas tienen una política de reintento
   acotada y determinista.
7. Los permisos están respaldados por usuarios/roles reales en DB, sin
   cambiar ninguna regla obligatoria de Milestone 1. Auth JWT de
   Supabase protege los endpoints mutadores cuando está configurada, y
   no rompe nada cuando no lo está.
8. Hay un endpoint de salud detallado y un log de ejecución de agentes
   con latencia medida real, visibles desde el Control Center.
9. El Agente 1 (Investigación de Productos) genera una lista de
   candidatos priorizados con scoring de oportunidad, usando solo
   fuentes simuladas, persistidos y auditados, con un puente funcional
   hacia el flujo de validación de Milestone 1.
10. Ningún test de Milestone 1 cambia de resultado — todo lo nuevo es
    aditivo o mejora la fuente de la verdad sin romper contratos
    existentes.

## Después de Milestone 2

Fase 3 continúa con los agentes 2–8 (proveedores, análisis económico,
legal, e-commerce, marketplaces, marketing, atención al cliente),
siguiendo el mismo patrón que el Agente 1: capability propia, fuentes
simuladas primero, `AgentMessage` para comunicarse con el CEO,
persistencia en las tablas de dominio correspondientes. Las llamadas a
APIs externas reales (búsqueda de tendencias real, proveedores reales)
quedan para cuando el roadmap lo indique explícitamente — no antes.
