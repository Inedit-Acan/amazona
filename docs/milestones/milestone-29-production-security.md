# Milestone 29 — Production Security Foundation (PLAN)

**Estado:** IMPLEMENTADO el 25-09-2026. Este documento se conserva como el plan
que se aprobó; lo que se construyó y cómo probarlo está en
[milestone-29-demo.md](milestone-29-demo.md) y en
[ADR 0007](../architecture/adr-0007-production-security.md).

**Decisión del propietario sobre el §5:** opción A — solo rutas mutadoras. Los
`GET` quedan para el Milestone 29.1.

**Origen:** `AMAZONA_KOVA_plan_maestro_continuación_Claude_Code.md`, §4 (Fase P0)
y §32 (Milestone 29). Este documento cumple el §36.5: plan técnico, archivos a
modificar, migraciones, tests, riesgos y criterios de aceptación antes de
implementar.

---

## 0. Verificación previa del estado real del repositorio (§36.2)

Lo que dice el plan maestro, contrastado con el código a fecha de hoy
(`4714284`). Lo que NO coincide está en la sección 1.

| Afirmación del plan maestro | Real | Detalle |
|---|---|---|
| `require_auth: bool = False` en `backend/app/core/config.py` | ✅ | Línea 37 |
| Auth parcial en `backend/app/auth/` | ✅ | `service.py` (JWT vía JWKS) + `dependencies.py` |
| `verify_aud = False` | ✅ | `auth/service.py`, en `jwt.decode(...)` |
| Endpoints mutadores sin identidad | ✅ | 19 rutas mutadoras; solo 2 ficheros usan `get_current_actor` |
| `actor` viene del body | ✅ | `pipeline.py`, `incidents.py`, y como *fallback* en `approvals.py` y `objectives.py` |
| Mocks en `backend/app/ai/mock_*.py` | ✅ | Los 3 citados, más `mock_ad_performance_directory` y `mock_marketplace_directory` |
| README documenta hasta Milestone 15 | ✅ | `README.md:93` «Fase 4 completa (Milestones 1-15)» |
| Backend con rangos `>=`, sin lock | ✅ | `pyproject.toml`, sin `uv.lock` ni `requirements.txt` |
| Redis provisionado | ✅ | `redis_url` en settings; sin workers |

### Inventario de las 19 rutas mutadoras

```text
POST /api/objectives                            POST /api/marketing/runs
POST /api/objectives/{id}/run                   POST /api/marketplace/runs
POST /api/approvals/{id}/approve                POST /api/operations/runs
POST /api/approvals/{id}/reject                 POST /api/cfo/runs
POST /api/research/runs                         POST /api/pipeline/runs
POST /api/sourcing/runs                         POST /api/pipeline/reviews/{id}/approve
POST /api/economics/runs                        POST /api/pipeline/reviews/{id}/reject
POST /api/legal/runs                            POST /api/pipeline/kill-switch
POST /api/ecommerce/runs                        POST /api/incidents
                                                POST /api/incidents/{id}/resolve
```

El plan maestro cita 10 «a modo de ejemplo»; son 19.

---

## 1. Contradicciones y hallazgos que el plan maestro no recoge (§36.3)

Ninguno invalida el Milestone 29, pero todos cambian cómo hay que hacerlo.

### 1.1 Ya existe media capa de RBAC, y está muerta

El plan maestro propone «implementar roles» desde cero. En realidad ya hay:

- `app/permissions/policies.py`: `ActionType`, `PermissionResult`
  (`ALLOWED` / `HUMAN_APPROVAL_REQUIRED` / `DENIED`), `OWNER_ONLY_ACTIONS`.
- `app/permissions/engine.py`: `PermissionEngine.check()`, denegación por defecto
  cuando el rol es `None`.
- `app/permissions/roles.py`: `RoleService.role_for(user_id)`.
- Tablas `users` y `roles` con su migración (`473eb2bee176`).

**Pero:**

- `RoleService` **no se usa en ningún sitio**. Es código muerto.
- `PermissionEngine` solo se usa en `app/ceo/orchestrator.py:264`, y con el rol
  **escrito a mano**: `self._permissions.check(actor_role="ceo_agent", ...)`.
- `roles` no se siembra en ninguna migración. `users` no lo escribe nadie.

**Impacto.** El Milestone 29 no crea RBAC: **conecta** el que ya existe a la
identidad HTTP y lo amplía. Los `ActionType` actuales (5, pensados para el grafo
CEO) no cubren las acciones de API (`pipeline.run`, `kill_switch.write`,
`review.resolve`…), así que hay que ampliarlos sin romper el uso del CEO.

### 1.2 `settings.environment` existe y no lo lee nadie

`environment: str = "development"` está declarado en `config.py` y **cero**
referencias en `app/`. La separación de ambientes del §P0.1 es enteramente nueva;
no hay nada que refactorizar, pero tampoco nada en lo que apoyarse.

### 1.3 `users.id` no es el `sub` de Supabase

`IdMixin` genera el id con `new_id()` local. `RoleService.role_for()` hace
`db.get(User, user_id)`, es decir espera el **id local**. Pero
`get_current_actor()` devuelve el **`sub` de Supabase**. Hoy no se nota porque
nadie los cruza; en cuanto se conecten, no casan.

**Impacto.** Hace falta una migración para mapear identidad externa → usuario
local. Es la única migración del milestone.

### 1.4 Nadie puede crear el primer usuario

No hay endpoint, ni seed, ni CLI que escriba en `users` o `roles`. Si se activa
`REQUIRE_AUTH=true` con RBAC y denegación por defecto, **el sistema queda cerrado
para todo el mundo, incluido el propietario**. Hace falta un camino de arranque
explícito, y es la parte más delicada del milestone.

### 1.5 El frontend ya manda el token, pero solo desde el navegador

`lib/api.ts` añade `Authorization: Bearer` en cada petición vía
`lib/auth.ts:getAccessToken()`. Es una buena noticia: los mutadores ya viajan
autenticados **si hay sesión**.

Pero el comentario de `authHeader()` lo dice: *«Only relevant in the browser —
server components only ever issue GETs»*. Los ~14 `page.tsx` que cargan datos en
servidor **no llevan token**. Es lo que obliga a decidir el alcance (sección 3).

### 1.6 La auditoría no guarda el rol ni la fuente

`AuditLog` tiene `actor`, `action`, `resource`, `before`, `after`,
`correlation_id`, `created_at`. El §P0.5 pide además `role` y `source`. Faltan
dos columnas: segunda parte de la migración.

### 1.7 Cobertura de tests de seguridad: 4 casos

`tests/integration/test_api_auth.py` cubre solo `/api/objectives` (falta token,
token inválido, token válido) y que los GET no piden auth. De 100 ficheros de
test, **uno** toca autenticación. No hay ni un test de autorización.

---

## 2. Objetivo

Que en `production` ninguna petición sin identidad autenticada pueda ejecutar una
acción mutadora, que el rol decida qué puede hacer cada identidad, y que la
auditoría registre quién hizo qué con identidad verificada — sin cambiar el
comportamiento del entorno de desarrollo del propietario.

## 3. Alcance

1. **Ambientes** (`P0.1`): `Environment` como enum
   (`development`/`test`/`demo`/`staging`/`production`), validado al arrancar.
2. **Auth global** (`P0.2`): dependencia `require_actor` aplicada a las 19 rutas
   mutadoras. JWT endurecido: issuer, audience, expiración y proyecto esperado.
3. **RBAC** (`P0.3`): los 7 roles del plan sobre el `PermissionEngine` existente,
   alimentado por `RoleService` con identidad real.
4. **Operaciones reforzadas** (`P0.4`): kill switch, approvals y pipeline reviews
   exigen rol autorizado además de identidad.
5. **Identidad no declarativa**: en `production` se ignora cualquier `actor` del
   body; se usa el del token.
6. **Auditoría** (`P0.5`): `role` y `source` en `audit_log`.
7. **Arranque del primer OWNER**: camino explícito, documentado y auditado.
8. **Tests** de autenticación y autorización para las 19 rutas.
9. **ADR-0007** y actualización del README.

## 4. Fuera de alcance

- Milestone 30 (aislamiento demo/producción) y posteriores.
- Proteger los `GET` (ver sección 5: decisión pendiente).
- Row Level Security más allá de lo que ya hace ADR-0003.
- Rotación de claves, refresh tokens, MFA, rate limiting.
- Lock de dependencias Python (§29 del plan maestro; propongo milestone aparte).
- Tocar `lib/demo` del frontend (es Milestone 30).

## 5. Decisión pendiente: ¿los `GET` también?

El plan maestro dice «ningún endpoint **mutador**» (§P0.2), pero también «no dar
acceso público al backend» (§33). Son dos alcances distintos:

- **A — solo mutadores.** 19 rutas. El frontend ya manda el token desde el
  navegador, así que no hay trabajo en Next.js. Riesgo residual: en producción,
  cualquiera con acceso de red al backend puede **leer** proyectos, proveedores,
  economía, decisiones y auditoría.
- **B — mutadores + lectura.** Cierra el riesgo, pero obliga a propagar la sesión
  de Supabase al servidor de Next (cookies + cliente SSR) y a tocar los ~14
  `page.tsx` que cargan datos en servidor. Es aproximadamente el doble de trabajo
  y toca ficheros que el propietario tiene modificados sin commitear.

**Recomendación:** hacer **A** en el Milestone 29 y **B** como Milestone 29.1
inmediatamente después, para no mezclar el endurecimiento del backend con un
cambio de arquitectura de sesión en el frontend.

---

## 6. Diseño técnico

### 6.1 Ambientes

```python
class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    DEMO = "demo"
    STAGING = "staging"
    PRODUCTION = "production"
```

`Settings.environment` pasa de `str` a `Environment`, con propiedades derivadas:

```python
@property
def enforces_auth(self) -> bool:      # staging y production
@property
def allows_declared_actor(self) -> bool:  # todo menos staging/production
```

Validación al arrancar (`app/main.py`, en el lifespan):

- `production` sin `supabase_url` → `RuntimeError`.
- `production` con `require_auth=False` → `RuntimeError`.
- `production` con `cors_origins` conteniendo `localhost` → `RuntimeError`.

`require_auth` se mantiene como override explícito para desarrollo, pero deja de
ser la única puerta: en `staging`/`production` la auth se exige aunque
`REQUIRE_AUTH` no esté puesto.

### 6.2 Identidad

`AuthService.verify()` endurecido:

- `verify_aud=True` con `audience="authenticated"` (el `aud` que emite Supabase).
- `issuer=f"{supabase_url}/auth/v1"`.
- `options={"require": ["exp", "sub", "iss", "aud"]}`.
- Mantener `RS256`/`ES256`; nunca aceptar `none` ni HS256 con la anon key.

Nueva dependencia en `app/auth/dependencies.py`:

```python
async def require_actor(...) -> Actor        # 401 si no hay identidad válida
async def require_role(*allowed: RoleName)   # 403 si el rol no basta
```

`Actor` es un dataclass `{subject, email, role, source}` — lo que consume la
auditoría.

En entornos que no exigen auth, `require_actor` devuelve un `Actor` de
desarrollo (`source="declared"`) para no romper el flujo local del propietario.

### 6.3 Mapeo identidad → usuario → rol

Migración: columna `users.subject` (`String(255)`, único, nullable) con el `sub`
de Supabase, e índice. `RoleService` gana:

```python
def actor_for(self, subject: str, email: str | None) -> Actor | None
```

Resolución: por `subject`; si no existe pero el email del token coincide con un
usuario sin `subject`, se vincula (primer login) y se audita. Si no hay usuario,
el rol es `None` → denegado por defecto.

### 6.4 Roles y política

`roles` se siembra en la migración con los 7 nombres del plan maestro
(`OWNER`, `ADMIN`, `OPERATOR`, `ANALYST`, `REVIEWER`, `VIEWER`, `SYSTEM`).

`ActionType` se amplía sin tocar los 5 existentes:

```text
PIPELINE_RUN · AGENT_RUN · REVIEW_RESOLVE · APPROVAL_RESOLVE
KILL_SWITCH_WRITE · INCIDENT_WRITE · OBJECTIVE_WRITE
```

Matriz (denegado salvo lo indicado):

| Acción | OWNER | ADMIN | OPERATOR | ANALYST | REVIEWER | VIEWER | SYSTEM |
|---|---|---|---|---|---|---|---|
| `OBJECTIVE_WRITE` | ✅ | ✅ | ✅ | — | — | — | ✅ |
| `AGENT_RUN` | ✅ | ✅ | ✅ | ✅ | — | — | ✅ |
| `PIPELINE_RUN` | ✅ | ✅ | ✅ | — | — | — | ✅ |
| `APPROVAL_RESOLVE` | ✅ | ✅ | — | — | ✅ | — | — |
| `REVIEW_RESOLVE` | ✅ | ✅ | — | — | ✅ | — | — |
| `INCIDENT_WRITE` | ✅ | ✅ | ✅ | — | — | — | ✅ |
| `KILL_SWITCH_WRITE` | ✅ | ✅ | — | — | — | — | — |

`ANALYST` puede lanzar agentes porque research/sourcing/economics/legal son
análisis sin efectos externos (§7 del plan maestro). `OPERATOR` no toca el kill
switch, como pide el criterio de aceptación.

### 6.5 Arranque del primer OWNER

Comando de gestión `python -m app.cli grant-role --email … --role OWNER`, que:

- exige `AMAZONA_BOOTSTRAP=1` en el entorno del proceso;
- crea el usuario si no existe;
- escribe una entrada de auditoría con `source="cli"`;
- se niega a ejecutarse si ya existe un OWNER, salvo `--force`.

Documentado en el README como paso obligatorio antes de desplegar.

### 6.6 Auditoría

`audit_log` gana `role` (`String(50)`, nullable) y `source`
(`String(20)`, nullable: `token` / `declared` / `cli` / `system`). Nullable para
no reescribir las filas históricas, que son append-only.

---

## 7. Archivos afectados

**Backend — modificados**

```text
app/core/config.py            Environment, validaciones, propiedades derivadas
app/auth/service.py           aud/iss/exp obligatorios
app/auth/dependencies.py      require_actor, require_role, Actor
app/permissions/policies.py   nuevos ActionType + matriz por rol
app/permissions/engine.py     check() por rol real
app/permissions/roles.py      actor_for(), vinculación por email
app/db/models/user.py         columna subject
app/db/models/audit.py        columnas role, source
app/main.py                   validación de arranque
app/api/*.py (13 ficheros)    dependencia en las 19 rutas mutadoras
app/pipeline/kill_switch.py   actor verificado
```

**Backend — nuevos**

```text
app/auth/actor.py                         dataclass Actor
app/cli.py                                grant-role
alembic/versions/xxxx_production_security.py
tests/integration/test_api_authorization.py
tests/unit/test_permission_matrix.py
tests/unit/test_environment_guards.py
```

**Docs**

```text
docs/architecture/adr-0007-production-security.md   nuevo
README.md                                            estado real + seguridad
docs/architecture/system-overview.md                 sección de seguridad
docs/milestones/milestone-29-demo.md                 guía de demo
```

**Frontend:** ninguno en la opción A.

## 8. Migración

Una sola, reversible:

```text
1. users.subject          String(255) nullable + índice único
2. audit_log.role         String(50)  nullable
3. audit_log.source       String(20)  nullable
4. seed de roles          los 7 nombres, idempotente
```

`downgrade()` elimina columnas y los roles sembrados. Sin pérdida de datos:
todo es aditivo y nullable.

## 9. Tests

```text
unit/test_permission_matrix.py      7 roles × 7 acciones = 49 casos explícitos
unit/test_environment_guards.py     production sin supabase → RuntimeError, etc.
integration/test_api_authorization.py
  · las 19 rutas devuelven 401 sin token cuando el entorno exige auth
  · VIEWER recibe 403 en las 19
  · ANALYST recibe 403 en kill switch y 200 en research
  · REVIEWER resuelve approvals y reviews; OPERATOR no
  · ADMIN y OWNER manejan el kill switch
  · el actor auditado es el sub del token, no el del body
  · en development se mantiene el comportamiento actual (sin regresión)
```

Objetivo: de 4 casos de seguridad a ~80.

## 10. Impacto en seguridad

**Cierra:** ejecución anónima de mutadores, suplantación vía `actor` del body,
kill switch sin identidad, aceptación de tokens sin `aud`/`iss`/`exp`.

**No cierra:** lectura anónima (opción A, sección 5), RLS más allá de ADR-0003,
rate limiting, y que el backend siga expuesto sin gateway.

## 11. Riesgos

| Riesgo | Mitigación |
|---|---|
| Quedarse fuera del sistema al activar auth | `grant-role` documentado y probado ANTES de activar; `development` sin cambios |
| Romper el entorno local del propietario | `development` mantiene el comportamiento actual; test de no regresión |
| Tocar los 13 ficheros de API y romper algo | Dependencia a nivel de ruta, sin cambiar firmas ni respuestas |
| Conflicto con los archivos sin commitear del propietario | El milestone no toca el frontend |
| `aud="authenticated"` no coincide con la config real de Supabase | Verificar contra un token real del propietario antes de cerrar |

## 12. Rollback

`alembic downgrade -1` y `ENVIRONMENT=development`. Como la exigencia de auth
depende del entorno y no del código, revertir es una variable de entorno; la
migración es aditiva y no borra nada.

## 13. Criterios de aceptación (§32)

```text
una petición no autenticada no puede ejecutar ningún mutador en production
VIEWER no puede mutar
ANALYST no puede usar kill switch
REVIEWER puede resolver approvals autorizadas
ADMIN/OWNER pueden manejar kill switch
actor de auditoría procede de identidad autenticada
```

Más los propios de este repositorio: `ruff` y `mypy` limpios, `pytest` verde,
`alembic upgrade head` sobre base limpia, y `next build` sin cambios.

## 14. Verificación

1. `ruff check .` · `mypy app` · `pytest -v` en `backend/`.
2. `alembic upgrade head` y `alembic downgrade -1` sobre PostgreSQL limpio.
3. Arranque en los 5 ambientes, comprobando que `production` mal configurado
   falla al arrancar.
4. Control Center contra el backend en `development`: sin regresión.
5. `npx tsc --noEmit`, `npm test` y `next build` en copia temporal.
