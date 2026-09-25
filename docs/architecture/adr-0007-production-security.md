# ADR 0007: Base de seguridad para producción

- **Estado:** Aceptada
- **Fecha:** 2026-09-25
- **Depende de:** [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0006](adr-0006-pipeline-human-controls.md)
- **Milestone:** 29

## Contexto

Hasta hoy el backend acepta cualquier mutación sin identidad. `require_auth`
vale `False` por defecto en `app/core/config.py`, y de las 19 rutas mutadoras
solo dos consultaban la identidad del token —y aun así aceptaban como
alternativa un `actor` enviado en el cuerpo de la petición—. El kill switch del
pipeline, que es el control de emergencia que ADR 0006 introdujo, se podía
accionar con un `POST` anónimo firmando con el nombre que uno quisiera.

Esto es razonable mientras el sistema es una simulación en una máquina local, y
deja de serlo en cuanto haya dinero, proveedores o publicidad reales detrás. El
plan maestro lo fija como la fase P0: nada de integraciones reales antes de
esto.

Investigación previa sobre el código actual:

- **Ya existía media capa de RBAC, y estaba muerta.** `PermissionEngine`,
  `ActionType`, `PermissionResult`, `RoleService` y las tablas `users`/`roles`
  (migración `473eb2bee176`) llevaban desde Milestone 1 en el repositorio.
  `RoleService` no se usaba en ningún sitio y `PermissionEngine` solo se
  invocaba desde `CEOOrchestrator` con el rol **escrito a mano**
  (`actor_role="ceo_agent"`). Ninguna migración sembraba roles y ningún código
  creaba usuarios.
- **`settings.environment` existía y no lo leía nadie.** Cero referencias en
  `app/`.
- **`users.id` no es el `sub` de Supabase.** `IdMixin` genera un id local, así
  que la identidad del token y el usuario de la base de datos no se cruzaban.
- **El frontend ya manda el token** en cada petición desde el navegador
  (`lib/api.ts`), pero no desde los componentes de servidor, que solo hacen
  `GET`.

## Decisión

### 1. El entorno decide, no una bandera suelta

`Settings.environment` pasa a ser un enum de cinco valores y de él derivan tres
propiedades: `enforces_auth`, `enforces_rbac` y `allows_declared_actor`. En
`staging` y `production` la identidad se exige siempre, el rol decide y un
`actor` del cuerpo nunca se cree. `require_auth` se mantiene como opt-in local.

`Settings.validate_for_startup()` se ejecuta al importar `app.main`: un proceso
de producción sin `SUPABASE_URL`, sin anon key o con un origen CORS local **no
arranca**. Un despliegue que acepta mutaciones anónimas en silencio es peor que
uno que no levanta.

### 2. Un token incompleto no es un token válido

`AuthService.verify()` exige firma asimétrica (`RS256`/`ES256`), `exp`, `sub`,
`iss` y `aud`, y comprueba emisor y audiencia contra la configuración. Antes se
verificaba la firma y se ignoraba todo lo demás (`verify_aud: False`).

### 3. `Actor` como unidad de identidad

Cada ruta mutadora recibe un `Actor` (`subject`, `email`, `role`, `source`) en
vez de una cadena. `source` distingue `token` de `declared`, y es lo que permite
que la auditoría diga si el nombre registrado estaba verificado o solo
afirmado.

### 4. RBAC de HTTP separado del de agentes

`ApiAction` + `API_ROLE_ACTIONS` + `role_can()` conviven con el
`ActionType`/`PermissionEngine` anterior en vez de sustituirlo.

Son dos ejes distintos: el de agentes responde «¿puede este agente gastar?» y su
respuesta puede ser «pregunta a un humano»; el de HTTP responde «¿puede esta
persona pedir esto?» y su respuesta es sí o no. Fundirlos habría obligado a que
`PermissionEngine.check()` entendiera roles reales y devolviera
`HUMAN_APPROVAL_REQUIRED` para acciones de API donde no significa nada, y habría
roto la llamada existente del `CEOOrchestrator`. La matriz es deny-by-default:
un rol desconocido, o ninguno, no puede nada.

### 5. El primer OWNER se crea desde la máquina, no por HTTP

`python -m app.cli grant-role` con `AMAZONA_BOOTSTRAP=1`. No hay endpoint para
conceder roles: un endpoint capaz de crear el primer OWNER sería un endpoint
capaz de escalar a cualquiera. El comando audita cada concesión y se niega a
crear un segundo OWNER sin `--force`.

### 6. La identidad externa se vincula una sola vez

`users.subject` guarda el `sub`. El propietario da de alta a una persona por
email antes de que esa persona haya entrado nunca; el primer login verificado
reclama la fila y a partir de ahí la búsqueda es solo por `subject`. Seguir
emparejando por email permitiría que una cuenta recreada heredara el rol de
otra.

## Alcance deliberado: solo mutadores

Los `GET` siguen abiertos. El plan maestro pide literalmente que «ningún
endpoint **mutador**» se ejecute sin identidad (§P0.2), y cerrar además la
lectura obliga a propagar la sesión de Supabase al servidor de Next.js y a tocar
los ~14 `page.tsx` que cargan datos en servidor — un cambio de arquitectura de
sesión en el frontend que no debe mezclarse con el endurecimiento del backend.

**Riesgo residual explícito:** en producción, cualquiera con acceso de red al
backend puede leer proyectos, proveedores, economía, decisiones y auditoría.
Queda como Milestone 29.1, y hay un test que lo deja por escrito
(`test_read_endpoints_stay_open_in_this_milestone`).

## Consecuencias

**A favor**

- Ninguna de las 19 rutas mutadoras se ejecuta sin identidad verificada donde
  importa, y el rol decide qué puede cada uno.
- El kill switch solo lo tocan OWNER y ADMIN.
- La auditoría registra rol y procedencia de la identidad.
- El entorno de desarrollo del propietario no cambia: sin `ENVIRONMENT`, sigue
  siendo `development` y todo funciona como antes.

**En contra**

- Un despliegue real necesita ahora un paso manual (`grant-role`) antes de
  servir tráfico. Es intencionado, y está documentado en el README.
- Los roles viven en la base de datos de AMAZONA, no en Supabase. Si algún día
  se quieren gestionar desde allí (custom claims), habrá que migrarlos.
- La matriz es estática, en código. Roles por proyecto o permisos a medida
  necesitarían otra ADR.

## Alternativas descartadas

- **Middleware global que exija auth en todo.** Habría cerrado también los `GET`
  y roto el renderizado en servidor del Control Center sin avisar.
- **Fundir el RBAC de HTTP en `PermissionEngine`.** §4.
- **Roles en los claims del JWT.** Cambiar el rol de alguien exigiría que
  cerrara sesión y volviera a entrar, y dejaría la autorización fuera del
  alcance de la auditoría de AMAZONA.
- **Un endpoint de bootstrap protegido por una clave de despliegue.** Una clave
  más que rotar y filtrar, para algo que se hace una vez.
