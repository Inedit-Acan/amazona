# Milestone 2 Demo

Plan completo:
[`docs/superpowers/plans/2026-09-16-amazona-milestone-2.md`](../superpowers/plans/2026-09-16-amazona-milestone-2.md).
Arquitectura: [ADR 0001](../architecture/adr-0001-orchestrator-vs-ceo.md)
(Orquestador vs. CEO),
[ADR 0002](../architecture/adr-0002-agent-messaging-protocol.md)
(protocolo de mensajería entre agentes), y
[ADR 0003](../architecture/adr-0003-rls-deny-by-default.md)
(RLS deny-by-default).

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

**Resuelto.** Las 24 tablas del esquema `public` tienen RLS activado con
una política explícita deny-all para `anon`/`authenticated` — ver
[ADR 0003](../architecture/adr-0003-rls-deny-by-default.md). El linter
de seguridad de Supabase ya no reporta ningún hallazgo. El backend
(rol `postgres`, vía `DATABASE_URL`) no se ve afectado — sigue siendo
dueño de las tablas y bypasea RLS.

**Sigue pendiente:** definir un modelo de acceso real (qué fila
pertenece a qué usuario) es un prerrequisito antes de que cualquier
cliente use la `anon key`/JWT directamente contra la API REST de
Supabase — no relajar el deny-all sin ese modelo.

## Autenticación (opcional, 🔒)

Por defecto (`REQUIRE_AUTH` sin definir o `false`) todo funciona exactamente
igual que Milestone 1, sin login. Para exigir JWT de Supabase Auth en los
endpoints que mutan estado (`POST /api/objectives`, `POST
/api/objectives/{id}/run`, `POST /api/approvals/{id}/approve|reject`):

```bash
# backend/.env
REQUIRE_AUTH=true
```

Y en el Control Center, para habilitar la pantalla de login:

```bash
# apps/control-center/.env.local
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>
```

**Verificación manual pendiente:** con `REQUIRE_AUTH=true` y credenciales
reales, crear un usuario en Supabase Auth (dashboard → Authentication →
Users), iniciar sesión en `/login`, y confirmar que crear/ejecutar un
objetivo funciona con el JWT real y que el `actor` auditado es el `sub`
del token, no un texto libre.

## Sistema de memoria y monitorización

- `GET /health/detailed` — conectividad de BD, revisión de migración
  aplicada, si Supabase está configurado.
- `GET /api/agent-executions?correlation_id=` — latencia real medida por
  ejecución de agente. Visible en `/status` del Control Center.
- La memoria compartida (`memory_records`) se alimenta automáticamente en
  cada ejecución del CEO — no requiere ninguna llamada manual.

## Flujo completo: Investigación → Validación (Fase 3, Agente 1)

```bash
# 1. Investigar una categoría
curl -s -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" \
  -d '{"category": "electronics", "max_results": 5}'
# -> {"correlation_id": "...", "candidates": [{"product_id": ..., "name": ...,
#     "opportunity_score": ..., "data": {"demand_signal": ..., "competition_level": ...}}]}

# 2. Validar el candidato mejor puntuado (usando sus señales de demanda/competencia)
curl -s -X POST http://localhost:8000/api/objectives \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Validate <candidate> opportunity",
    "created_by": "owner@amazona.local",
    "context": {
      "product_validation": {"estimated_monthly_searches": <demand_signal*15000>, "competition_level": "<competition_level>"},
      "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": true},
      "finance_validation": {"unit_cost": 5.0, "sale_price": 20.0, "monthly_unit_sales": 300, "monthly_fixed_costs": 500.0},
      "legal_validation": {"restricted_category": false}
    }
  }'

curl -s -X POST http://localhost:8000/api/objectives/<objective_id>/run
```

O desde el Control Center: página **Research** → *Run research* → *Validate
this product* en el candidato deseado → salta a **CEO** con el título y
`product_validation` ya rellenados → *Create & run objective*.

Los dos runs (investigación y validación) tienen `correlation_id`
distintos y son ambos 100% reconstruibles vía `GET /api/audit?correlation_id=`
— cubierto por
`backend/tests/e2e/test_product_research_flow.py`.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 180+ tests, ~24s
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```
