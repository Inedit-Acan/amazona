# Milestone 29 — Production Security Foundation

**Fecha:** 25-09-2026 · **ADR:** [0007](../architecture/adr-0007-production-security.md)
· **Plan:** [milestone-29-production-security.md](milestone-29-production-security.md)

Primera fase del plan maestro de continuación (§4, P0). Objetivo: que en un
entorno real ninguna acción mutadora se ejecute sin identidad verificada, que el
rol decida qué puede cada quien, y que la auditoría no se pueda falsear — sin
cambiar nada del entorno de desarrollo.

---

## Qué cambia

1. **Cinco entornos de verdad.** `ENVIRONMENT` pasa a ser un enum
   (`development`, `test`, `demo`, `staging`, `production`) del que salen
   `enforces_auth`, `enforces_rbac` y `allows_declared_actor`. Antes el campo
   existía en `config.py` y **no lo leía nadie**.
2. **Las 19 rutas mutadoras piden identidad y rol.** Antes solo dos consultaban
   el token, y aun así aceptaban como alternativa un `actor` del cuerpo.
3. **Un token incompleto ya no vale.** Se exigen firma asimétrica, `exp`, `sub`,
   `iss` y `aud`, con emisor y audiencia comprobados. Antes se verificaba la
   firma y se ignoraba el resto (`verify_aud: False`).
4. **RBAC conectado a identidad real.** `ApiAction` + matriz por rol +
   `role_can()`, deny-by-default. El kill switch solo lo accionan OWNER y ADMIN;
   VIEWER no muta nada; ANALYST ejecuta agentes de análisis pero no el kill
   switch; REVIEWER resuelve decisiones pero no lanza trabajo.
5. **El `actor` del cuerpo se ignora en entornos reales.** Lo que se persiste y
   se audita es la identidad del token.
6. **`users.subject`** vincula la cuenta de Supabase con el usuario local, y
   `audit_log` gana `actor_role` y `actor_source`.
7. **`python -m app.cli grant-role`** crea el primer OWNER desde la máquina. No
   hay endpoint que conceda roles, a propósito.
8. **Producción mal configurada no arranca**: sin Supabase, o con CORS
   apuntando a localhost, el proceso falla al importar `app.main`.

## Lo que ya existía y estaba muerto

Merece decirse porque cambia la lectura del plan maestro, que proponía
«implementar roles» desde cero:

- `PermissionEngine`, `ActionType`, `PermissionResult`, `RoleService` y las
  tablas `users`/`roles` estaban en el repositorio desde Milestone 1.
- `RoleService` **no se usaba en ningún sitio**.
- `PermissionEngine` solo se invocaba desde `CEOOrchestrator`, con el rol
  escrito a mano (`actor_role="ceo_agent"`).
- Ninguna migración sembraba roles; ningún código creaba usuarios.

Así que este milestone no crea RBAC: lo conecta, lo amplía y lo siembra.

## Probarlo

### En desarrollo, nada cambia

```bash
cd backend && alembic upgrade head && uvicorn app.main:app --reload
```

Sin `ENVIRONMENT`, el entorno es `development`: el Control Center sigue
funcionando sin sesión y los `POST` siguen saliendo.

### Simular producción

```bash
cd backend
export ENVIRONMENT=production
export SUPABASE_URL=https://tu-proyecto.supabase.co
export SUPABASE_ANON_KEY=…
export CORS_ORIGINS='["https://tu-dominio"]'

alembic upgrade head
AMAZONA_BOOTSTRAP=1 python -m app.cli grant-role --email tu@correo.com --role OWNER
python -m app.cli list-users
uvicorn app.main:app
```

Comprobaciones rápidas:

```bash
# 401: sin identidad no se muta
curl -i -X POST localhost:8000/api/pipeline/kill-switch -d '{"enabled":false,"actor":"quien-sea"}'

# el arranque falla si falta configuración
ENVIRONMENT=production SUPABASE_URL= uvicorn app.main:app   # RuntimeError
```

### Ver que el `actor` del cuerpo ya no cuela

Con un token de ADMIN, accionar el kill switch mandando
`"actor": "impersonated@attacker.example"`: la fila de `audit_log` guarda el
email del token, `actor_role=ADMIN` y `actor_source=token`. Es exactamente lo que
comprueba `test_the_audited_actor_is_the_token_not_the_body`.

## Criterios de aceptación del plan maestro

| Criterio | Test |
|---|---|
| Una petición no autenticada no puede ejecutar ningún mutador | `test_no_mutating_route_runs_without_a_token` (19 rutas) |
| VIEWER no puede mutar | `test_viewer_cannot_mutate_anything` (19 rutas) |
| ANALYST no puede usar el kill switch | `test_analyst_cannot_use_the_kill_switch` |
| REVIEWER puede resolver approvals autorizadas | matriz + `test_operator_cannot_resolve_approvals` |
| ADMIN/OWNER pueden manejar el kill switch | `test_owner_and_admin_hold_the_kill_switch` |
| El actor de auditoría procede de identidad autenticada | `test_the_audited_actor_is_the_token_not_the_body` |

## Verificación

- `ruff check .` limpio · `mypy app` limpio (148 ficheros) · `pytest` **652
  pasando** (498 antes: +154, de los cuales ~90 son de seguridad).
- La migración se ejecuta de verdad en los tests, arriba y abajo
  (`test_migration_production_security.py`). Eso destapó un fallo real antes de
  llegar a CI: `sa.func.now()` en `bulk_insert` se manda como valor, no como
  SQL.
- **No verificado aquí:** `alembic upgrade head` contra PostgreSQL. No hay
  Postgres ni Docker en esta máquina; lo cubre el job de CI, que aplica toda la
  cadena sobre una base limpia.
- **No verificado aquí:** un token real de Supabase. `aud="authenticated"` es lo
  que emite Supabase por defecto y es configurable (`JWT_AUDIENCE`), pero
  conviene confirmarlo contra un token real del propietario antes de desplegar.
- Frontend sin cambios: el alcance acordado es solo backend.

## Lo que queda abierto

1. **Los `GET` siguen abiertos** (Milestone 29.1). Hay un test que lo dice por
   escrito para que no se olvide.
2. **Los roles viven en la base de datos de AMAZONA**, no en Supabase.
3. **Sin rate limiting** ni gateway delante del backend.
4. **Milestone 30** (aislamiento demo/producción) es el siguiente del plan
   maestro y no se ha empezado.
