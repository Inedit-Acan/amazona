# Milestone 2 Demo

> Se completa progresivamente a medida que se implementan las tareas del
> plan ([`docs/superpowers/plans/2026-09-16-amazona-milestone-2.md`](../superpowers/plans/2026-09-16-amazona-milestone-2.md)).

## Conectar el backend a un proyecto Supabase real

1. En el dashboard de Supabase del proyecto (región UE):
   - **Project Settings → Database → Connection string** (o "Reset
     database password" si no la tienes) para obtener la contraseña de
     Postgres.
   - **Project Settings → API → service_role key**.
2. Copia `backend/.env.example` a `backend/.env` si aún no existe.
3. Rellena:
   ```bash
   DATABASE_URL=postgresql+psycopg://postgres:<DB-PASSWORD>@db.<project-ref>.supabase.co:5432/postgres?sslmode=require
   SUPABASE_URL=https://<project-ref>.supabase.co
   SUPABASE_ANON_KEY=<anon-key>
   SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
   ```
4. Verifica:
   ```bash
   cd backend
   .venv/Scripts/python -m pytest tests/integration/test_supabase_connectivity.py -v
   ```
   Estos tests se saltan (no fallan) si `DATABASE_URL` no es alcanzable —
   deberían pasar una vez rellenado `backend/.env` correctamente.
5. Aplica cualquier migración pendiente:
   ```bash
   alembic upgrade head
   ```

**Nota:** el esquema de Milestone 1 y las tablas de dominio de Milestone 2
(`products`, `suppliers`, `product_analyses`) ya están aplicadas en el
proyecto Supabase real usado para este milestone
(`alembic_version` debe coincidir con la última revisión en
`backend/alembic/versions/`).

## Seguridad: Row Level Security

El proyecto Supabase tiene **RLS deshabilitado** en todas las tablas —
pendiente de decisión y política (ver sección 2.5 del plan). El backend no
usa la API REST de Supabase (PostgREST) para acceder a datos — conecta
directo a Postgres vía `DATABASE_URL` — por lo que esto no es explotable a
través de la app actual, pero **si en algún momento se usa la `anon key`
directamente contra la API REST de Supabase, cualquiera podría leer o
escribir todas las filas.** No se ha aplicado ninguna política todavía.
