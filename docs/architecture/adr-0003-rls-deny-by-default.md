# ADR 0003: Row Level Security — deny-by-default en las 24 tablas públicas

- **Estado:** Aceptada
- **Fecha:** 2026-09-16

## Contexto

El linter de seguridad de Supabase marcaba **"RLS Disabled in Public"**
(nivel `critical`) en las 24 tablas del esquema `public` del proyecto
`amazona` — ver
[milestone-2-demo.md](../milestones/milestone-2-demo.md#seguridad-row-level-security).
El backend conecta a Postgres directamente vía `DATABASE_URL` con el rol
`postgres` (dueño de todas las tablas), que **bypasea RLS
independientemente de si está activado** — por eso este hallazgo no era
explotable a través de la app actual. Pero si en algún momento algo usa
la `anon key` directamente contra la API REST de Supabase (PostgREST) —
por ejemplo, si un futuro milestone añade llamadas cliente-servidor
directas a Supabase desde el Control Center — cualquiera con esa clave
podría leer o escribir todas las filas de todas las tablas.

## Decisión

RLS está **activado en las 24 tablas**, con una única política explícita
**deny-all** por tabla dirigida a los roles `anon` y `authenticated`
(los que usa PostgREST):

```sql
ALTER TABLE public.<tabla> ENABLE ROW LEVEL SECURITY;

CREATE POLICY deny_all_anon_authenticated ON public.<tabla>
  AS PERMISSIVE FOR ALL TO anon, authenticated
  USING (false) WITH CHECK (false);
```

**No se ha definido ningún modelo de acceso real** (qué fila puede ver
o modificar qué usuario) — eso queda fuera de alcance de este fix. El
efecto de esta migración es puramente cerrar el acceso público por
completo, no abrir un acceso selectivo nuevo.

**Por qué el backend no se ve afectado:** las 24 tablas son propiedad
del rol `postgres`, y los dueños de tabla bypasean RLS automáticamente
salvo que se aplique `FORCE ROW LEVEL SECURITY` (que deliberadamente
**no** se ha aplicado). Verificado en vivo contra el proyecto real:
`postgres` sigue leyendo/escribiendo con normalidad; `anon` y
`authenticated` ven 0 filas de una fila insertada expresamente para la
prueba, en la misma transacción.

**Por qué la migración comprueba la existencia de los roles antes de
crear la política:** `anon`/`authenticated` son roles que aprovisiona
la plataforma Supabase, no existen en un Postgres vanilla — como el
contenedor efímero que usa el job de CI para `alembic upgrade head`. La
migración activa RLS en cualquier caso (lo cual ya deniega el acceso a
cualquier rol no-dueño, exista o no `anon`), y solo crea la política
explícita cuando esos roles están presentes.

## Razonamiento

1. **Deny-by-default es más seguro que no decidir nada.** Activar RLS
   sin ninguna política ya deniega el acceso a cualquier rol no-dueño
   — la política explícita añadida aquí es redundante en términos de
   efecto, pero autodocumenta la intención en el propio esquema
   (`pg_policies` deja de estar vacío, lo que evita que alguien asuma
   erróneamente "sin políticas = sin RLS todavía configurado").
2. **No se añaden políticas permisivas todavía** porque no existe un
   modelo de acceso por usuario definido — el Control Center no llama
   hoy a la API REST de Supabase con la `anon key`, así que no hay
   ningún caso de uso real que una política permisiva deba servir. Añadir
   una política de acceso sin un modelo claro (¿qué fila pertenece a qué
   usuario?) sería inventar reglas de negocio a ciegas.
3. **El backend no cambia.** Sigue usando `DATABASE_URL` con el rol
   `postgres`, que bypasea RLS por ser el dueño de las tablas — cero
   cambios de comportamiento, verificado con la suite completa (180
   tests de backend) y el build de frontend en verde.

## Consecuencias

- **Prerrequisito explícito antes de Milestone 3 o cualquier trabajo
  futuro:** si algún cliente (Control Center u otro) necesita usar la
  `anon key` o JWT de usuario directamente contra la API REST de
  Supabase, hace falta **definir primero un modelo de acceso real**
  (qué fila pertenece a qué usuario/rol) y añadir políticas permisivas
  específicas — nunca relajar el deny-all a ciegas.
- El backend (rol `postgres`, vía `DATABASE_URL`) sigue siendo el único
  camino de acceso a los datos. Esto es consistente con la arquitectura
  ya establecida en Milestone 1/2 (el backend nunca ha usado PostgREST).
- Migración: `backend/alembic/versions/10de07bea94d_enable_rls_deny_by_default.py`.
  Aplicada en vivo al proyecto Supabase real (`alembic_version` en
  `10de07bea94d`); el linter de seguridad de Supabase ya no reporta
  ningún hallazgo.
