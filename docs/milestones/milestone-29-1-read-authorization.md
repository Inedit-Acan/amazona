# Milestone 29.1 — Autorización de lectura (PLAN)

**Estado:** IMPLEMENTADO el 25-09-2026. Lo que sigue es el plan tal como se
aprobó; al final, la sección «Resultado» dice qué se construyó y qué cambió
respecto a lo planeado.

**Decisiones del propietario:**

1. **Auditoría (§3.5):** OWNER, ADMIN y REVIEWER. `VIEWER`, `OPERATOR` y
   `ANALYST` no leen `/api/audit`.
2. **Conflicto (§5):** el propietario commitea sus cambios de
   `app/login/page.tsx`, `components/session-badge.tsx` y `top-header.tsx`, y
   la implementación se hace encima de esa base.

**Origen:** criterio que quedó abierto en el
[Milestone 29](milestone-29-demo.md) y §33 del plan maestro («no dar acceso
público al backend»). El Milestone 29 cerró las 19 rutas mutadoras; este cierra
las de lectura.

---

## 1. El problema, medido

Hoy **35 endpoints de lectura** responden a cualquiera que alcance el backend
por red: 33 `GET` en los routers más `/health` y `/health/detailed`. En
`production` eso significa que sin autenticarse se puede leer el catálogo de
productos, los proveedores y sus precios, los análisis económicos, las
decisiones del CEO, las aprobaciones, las incidencias, el estado del kill switch
y **el registro de auditoría completo con el email de quién hizo cada cosa**.

## 2. El obstáculo real: el renderizado en servidor

No es el backend. Son estas **15 páginas**, que cargan datos en el servidor de
Next y hoy **no llevan token**:

```text
agents · approvals · audit · cfo · dashboard · ecommerce · economics
legal · marketing · operations · projects · research · sourcing · status
```

(`/ceo` y `/login` son las dos únicas que renderizan en cliente.)

La causa está en `lib/auth.ts`: el cliente de Supabase se crea con
`createClient` de `@supabase/supabase-js`, que guarda la sesión en
**`localStorage`**. El servidor no puede verla. Por eso `authHeader()` en
`lib/api.ts` dice literalmente *«Only relevant in the browser»* y devuelve `{}`
en servidor.

**Conclusión:** exigir identidad en los `GET` sin tocar antes la sesión rompe
las 15 páginas con un 401. El trabajo de este milestone es, sobre todo, de
frontend.

---

## 3. Política propuesta

Cuatro categorías. Como en el Milestone 29, **solo se aplica en `staging` y
`production`**: `development`, `test` y `demo` siguen exactamente igual.

### 3.1 Categorías

| Categoría | Nº | Autenticación | Roles |
|---|---|---|---|
| **Liveness** | 1 | pública | — |
| **Readiness** | 1 (nuevo) | pública | — |
| **Diagnóstico** | 1 | requerida | los 7 |
| **Negocio** | 32 | requerida | los 7 |
| **Auditoría** | 1 | requerida | OWNER · ADMIN · REVIEWER |

### 3.2 Público: `/health` y el nuevo `/health/ready`

Un balanceador o un orquestador de contenedores **no puede llevar un JWT**. Si
la sonda de salud exige identidad, el despliegue se declara caído y nadie
enruta tráfico. Por eso hay dos, y ninguno dice nada que no haga falta:

```text
GET /health         →  {"status": "ok", "service": "amazona-backend"}
                       Liveness. No toca la base de datos. Sin cambios.

GET /health/ready   →  200 {"status": "ok"}  |  503 {"status": "degraded"}
                       Readiness. Comprueba la base de datos y NADA MÁS:
                       ni versión, ni entorno, ni proveedores.
```

`/health/ready` es nuevo. Existe para que `/health/detailed` pueda dejar de ser
público sin dejar a la infraestructura sin sonda.

### 3.3 El análisis de `/health/detailed`

Hoy devuelve esto, **sin pedir identidad**:

| Campo | Qué revela a un anónimo | Veredicto |
|---|---|---|
| `database: ok\|error` | si estás degradado ahora mismo | lo necesita la infra → va a `/health/ready` |
| `migration` | el hash exacto de tu esquema Alembic | **fingerprinting** → autenticado |
| `supabase_configured` | qué proveedor de identidad usas | autenticado |
| `environment` | si esto es `production` | autenticado |
| `providers[]` | los nombres de clase (`MockTrendsProvider`…) y **qué dominios van con datos simulados** | **lo más sensible** → autenticado |

El último campo lo añadí yo en el Milestone 30 y es justo el que más importa:
dice qué partes del negocio funcionan con datos inventados, es decir **dónde el
sistema es más débil**. Combinado con `migration` y `environment`, un anónimo
obtiene un retrato bastante completo del despliegue.

**Propuesta:** `/health/detailed` pasa a requerir identidad (cualquier rol) y
mantiene el cuerpo completo. La infraestructura usa `/health` y `/health/ready`.

### 3.4 Negocio: los 32 restantes, rol VIEWER en adelante

`VIEWER` es «solo lectura» en el plan maestro, así que los siete roles pueden
leer datos de negocio. La restricción por rol seguirá estando donde importa: en
quién puede **cambiar** algo.

<details>
<summary>Las 32 rutas</summary>

```text
/api/agents                                   /api/pipeline/runs
/api/approvals                                /api/pipeline/runs/{correlation_id}
/api/agent-executions                         /api/pipeline/reviews
/api/products                                 /api/pipeline/kill-switch
/api/projects                                 /api/tasks
/api/projects/{project_id}                    /api/incidents
/api/decisions                                /api/cfo/runs
/api/decisions/{decision_id}                  /api/cfo/runs/{correlation_id}
/api/research/runs/{correlation_id}           /api/economics/analyses/timeseries
/api/sourcing/runs/{correlation_id}           /api/economics/runs/{correlation_id}
/api/legal/runs/{correlation_id}              /api/ecommerce/runs/{correlation_id}
/api/marketing/runs/{correlation_id}          /api/marketplace/runs/{correlation_id}
/api/operations/runs/{correlation_id}         /api/products/{id}/suppliers
/api/products/{id}/economics                  /api/products/{id}/legal
/api/products/{id}/campaigns                  /api/products/{id}/storefronts
/api/products/{id}/marketplace-listings       /api/products/{id}/operations
```

</details>

### 3.5 Auditoría: más estrecho — **decisión que necesita tu visto bueno**

`GET /api/audit` devuelve quién hizo qué, con el email de cada actor y el
`before`/`after` de cada cambio. Es una categoría de sensibilidad distinta al
resto: no es información del negocio, es información **sobre las personas que lo
operan**.

**Decidido:** OWNER, ADMIN y REVIEWER. REVIEWER entra porque necesita el
historial para juzgar lo que aprueba. `VIEWER`, `OPERATOR` y `ANALYST` no.

---

## 4. Diseño técnico

### 4.1 Backend

Tres acciones nuevas en `ApiAction` (`app/permissions/policies.py`):

```python
BUSINESS_READ    = "business.read"      # los 7 roles
AUDIT_READ       = "audit.read"         # OWNER, ADMIN, REVIEWER
DIAGNOSTICS_READ = "diagnostics.read"   # los 7 roles
```

`BUSINESS_READ` y `DIAGNOSTICS_READ` tienen hoy la misma matriz. Se mantienen
separadas porque son clases de sensibilidad distintas —negocio frente a
infraestructura— y separarlas ahora cuesta un miembro de enum; fundirlas y
volver a separarlas después costaría tocar 32 rutas.

Las rutas usan el mismo `authorize(...)` del Milestone 29, así que el mecanismo
ya existe y está probado. Para no repetir la dependencia 32 veces se aplica **a
nivel de router** con `dependencies=[Depends(authorize(ApiAction.BUSINESS_READ))]`
en `include_router`, y solo `audit` y `health/detailed` la declaran a mano.

### 4.2 Frontend: sesión en cookies

Es el cambio de fondo. Hoy la sesión vive en `localStorage`; tiene que vivir en
**cookies** para que el servidor de Next la vea.

```text
@supabase/ssr
   ├── lib/auth.ts          cliente de navegador con almacenamiento en cookie
   ├── lib/auth-server.ts    (nuevo) cliente de servidor, lee cookies()
   ├── middleware.ts         (nuevo) refresca el token en cada navegación
   └── lib/api.ts            authHeader() deja de devolver {} en servidor
```

**Lo elegante:** si `authHeader()` sabe leer la cookie en servidor, **las 15
páginas no se tocan**. Siguen llamando a `api.listProducts()` y el token viaja
solo.

### 4.3 Orden de ejecución — importa

Hacerlo al revés deja un intervalo con la aplicación rota:

1. **Primero 29.1-a (frontend):** sesión en cookies y token en SSR. Es
   inofensivo mientras los `GET` siguen abiertos — simplemente empiezan a
   llegar con `Authorization`.
2. **Después 29.1-b (backend):** exigir identidad y rol en la lectura.

Así no existe nunca un estado en el que el backend rechace lo que el frontend
todavía no manda.

---

## 5. Conflicto con tu trabajo sin commitear — **hay que resolverlo antes**

El cambio de sesión toca exactamente dos ficheros que tienes modificados y sin
commitear:

```text
apps/control-center/app/login/page.tsx      (inicio de sesión)
apps/control-center/components/session-badge.tsx  (sesión en la cabecera)
```

Y `components/top-header.tsx`, que no está en git, depende de ellos.

**Decidido (a):** el propietario commitea esos cambios y la implementación se
hace encima. Hasta que estén en git, el Milestone 29.1 no empieza: 29.1-a es
precisamente el paso que los toca.

## 6. Alcance

**Dentro:** las 4 categorías, las 3 acciones nuevas, el nuevo `/health/ready`,
la sesión en cookies, el token en SSR, y tests de autorización de lectura.

**Fuera, y por qué:**

- **Granularidad fina por dominio** (p. ej. que ANALYST no vea `/api/cfo/*`).
  Se puede añadir después sin volver a tocar las 32 rutas; empezar por ahí sería
  inventar una política antes de saber quién usa qué.
- **Rate limiting y enumeración de ids.** No es RBAC; necesita un gateway.
- **Multi-tenencia.** Hoy hay una sola organización; `{product_id}` no tiene
  dueño contra el que comparar.
- **Milestone 30.1.** Sigue congelado por el trinquete, como acordamos.

## 7. Archivos afectados

```text
Backend (modificados)
  app/permissions/policies.py    3 ApiAction + matriz
  app/main.py                    dependencias por router, /health/ready,
                                 /health/detailed autenticado
  app/api/audit.py               AUDIT_READ explícito

Backend (nuevos)
  tests/integration/test_api_read_authorization.py

Frontend (modificados)
  lib/auth.ts                    cookies en vez de localStorage
  lib/api.ts                     authHeader() consciente del servidor
  app/login/page.tsx             ⚠ lo tienes modificado
  components/session-badge.tsx   ⚠ lo tienes modificado
  package.json                   + @supabase/ssr

Frontend (nuevos)
  lib/auth-server.ts
  middleware.ts

Docs
  docs/architecture/adr-0007-production-security.md   §«Alcance deliberado» deja de ser cierto
  README.md · system-overview.md · milestone-29-1-demo.md
```

**Migraciones: ninguna.** Los roles ya están sembrados y las acciones nuevas son
solo código.

## 8. Tests

```text
integration/test_api_read_authorization.py
  · las 35 rutas de lectura, inventariadas como en el Milestone 29
  · /health y /health/ready responden 200 sin token
  · /health/ready devuelve 503 y cuerpo mínimo con la base de datos caída
  · /health/detailed devuelve 401 sin token y el cuerpo completo con él
  · las 32 de negocio devuelven 401 sin token
  · VIEWER lee las 32 de negocio
  · VIEWER, OPERATOR y ANALYST reciben 403 en /api/audit
  · OWNER, ADMIN y REVIEWER leen /api/audit
  · en development las 35 siguen abiertas (no regresión)
  · el inventario cubre todos los GET (falla si alguien añade uno sin categoría)

unit/test_permission_matrix.py
  · ampliado a 7 roles × 10 acciones = 70 casos
```

## 9. Impacto en seguridad

**Cierra:** lectura anónima de datos de negocio y del registro de auditoría, y
el fingerprinting del despliegue vía `/health/detailed`.

**No cierra:** rate limiting, enumeración de identificadores, y que el backend
siga expuesto sin gateway. La sesión en cookies además exige `Secure`,
`HttpOnly` y `SameSite=Lax` bien puestos — es parte del trabajo, y es el riesgo
nuevo que introduce el cambio.

## 10. Rollback

Como en el Milestone 29, la exigencia depende del entorno y no del código:
`ENVIRONMENT=development` lo desactiva entero. Sin migraciones que revertir. El
cambio de sesión a cookies sí es un cambio real de frontend: su rollback es
revertir el commit.

## 11. Criterios de aceptación

```text
sin token, ninguna ruta de negocio ni de auditoría responde en production
/health y /health/ready responden sin token, y no revelan versión,
  entorno ni proveedores
/health/detailed no responde sin token
VIEWER lee negocio y NO lee auditoría
OWNER, ADMIN y REVIEWER leen auditoría
las 15 páginas renderizadas en servidor siguen funcionando autenticadas
development, test y demo se comportan exactamente como hoy
```

---

# Resultado

Se implementó en dos commits, en el orden previsto.

## 29.1-a — La sesión llega al servidor

`@supabase/ssr` sustituye a `@supabase/supabase-js` en el cliente de navegador:
la sesión pasa de `localStorage` a **cookies**. La API pública de `lib/auth.ts`
no cambia, así que `login/page.tsx` y `session-badge.tsx` **no se tocaron**.

- `lib/auth-server.ts` lee la misma sesión desde las cookies de la petición.
- `middleware.ts` refresca el token en cada navegación: es lo único que puede
  escribir cookies.
- `lib/api-server.ts` sustituye el resolutor de token y reexporta `api`. Las 14
  páginas de servidor lo importan de ahí.

**Cambio respecto al plan:** el plan decía que «las 15 páginas no se tocan» si
`authHeader()` sabe leer cookies en servidor. No se pudo: `lib/api.ts` lo
importan también componentes de cliente, y cualquier referencia a `next/headers`
desde ahí —aunque fuera tras un `typeof window`— entra en el bundle del
navegador y rompe el build. La solución fue un resolutor inyectable y un módulo
`api-server.ts` aparte, con 14 cambios de una línea en los imports. Es más
explícito: la frontera servidor/cliente se ve en el código.

Son 14 páginas, no 15: `app/page.tsx` renderiza en servidor pero no llama a la
API.

### Dos cosas medidas, no supuestas

Con un backend falso que hacía eco de las cabeceras y una cookie de sesión
plantada a mano:

1. **El token viaja.** Con sesión, las tres llamadas de una página salen con
   `Authorization`; sin sesión, ninguna.
2. **Supabase caído bloqueaba la aplicación.** Una página tardaba **51 s**: el
   middleware y *cada* llamada a la API esperaban a Supabase sin techo. Con un
   límite de 4 s en ambos y la lectura de sesión memoizada por render
   (`cache()` de React, una vez en lugar de una por llamada), el peor caso
   queda en **8,2 s** y el camino sano en **0,11 s**.

## 29.1-b — La lectura exige identidad

Las tres acciones (`business.read`, `audit.read`, `diagnostics.read`) y la
política de §3, aplicadas **por router** con `include_router(dependencies=…)`.
Un `GET` añadido más tarde nace protegido; olvidar un decorador es justo como
las rutas de lectura acaban abiertas sin que nadie se entere.

`/health/ready` es nuevo y público. `/health/detailed` pasa a exigir identidad.

### Dos defectos que salieron al probar

- **`/health/detailed` se saltaba la inyección de dependencias**: llamaba a
  `get_settings()` dentro del cuerpo, así que no respetaba ningún override y
  reportaba el entorno equivocado. Ahora lo recibe como dependencia.
- **`/api/decisions` y `/api/tasks` exigen `project_id`** y devuelven 422 sin
  él. No es un fallo, pero el inventario de rutas tenía que reflejarlo.

## Verificación

- Backend: `ruff` y `mypy` limpios · **829 tests** (674 antes, +155).
- Frontend: `tsc`, `eslint` y `next build` limpios · **237 tests** (234 antes).
- Humo en desarrollo: las 6 rutas comprobadas siguen devolviendo 200 sin token.
  El entorno del propietario no cambia.
- `test_the_inventory_covers_every_read_route` fija las 36 rutas de lectura: un
  `GET` nuevo obliga a decidir su categoría.

## No verificado

- **Login, refresh y logout reales.** Necesitan la clave anónima de Supabase del
  propietario en `apps/control-center/.env.local` **y** una cuenta creada con
  `python -m app.cli grant-role`. Lo que sí está probado es el mecanismo: que
  una sesión en cookie llega al servidor y se convierte en cabecera
  `Authorization`, y que sin ella no se manda nada.
- `alembic upgrade head` contra PostgreSQL: este milestone no añade migraciones.

## Lo que queda abierto

Rate limiting, enumeración de identificadores y el backend sin gateway delante.
El Milestone 30.1 (retirar `lib/demo` de los 41 módulos) sigue congelado por su
trinquete, por decisión del propietario.
