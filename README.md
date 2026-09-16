# AMAZONA

Sistema de e-commerce impulsado por IA con agentes especializados.

## Arquitectura de agentes

- **Orquestador (Agente 9):** coordina el flujo entre agentes.
- **Agente CEO:** define objetivos y toma decisiones de alto nivel.
- **Agente CFO:** control económico; se integra con un software de facturación certificado Verifactu (no emite facturas propias).
- **8 agentes operativos:** investigación de productos, proveedores, análisis económico, legal, e-commerce, marketplaces, marketing y atención al cliente.

## Stack técnico (Milestone 1)

- Frontend: Next.js, React, TypeScript, Tailwind CSS, shadcn/ui
- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic
- Datos: PostgreSQL / Supabase (proyecto en región UE), Redis
- Infra: Docker, GitHub Actions

Planes de implementación:
[Milestone 1](docs/superpowers/plans/2026-09-15-amazona-milestone-1.md) ·
[Milestone 2](docs/superpowers/plans/2026-09-16-amazona-milestone-2.md).
Decisiones de arquitectura:
[ADR 0001 — Orquestador vs. CEO](docs/architecture/adr-0001-orchestrator-vs-ceo.md) ·
[ADR 0002 — Protocolo de mensajería entre agentes](docs/architecture/adr-0002-agent-messaging-protocol.md).

## Desarrollo local

```bash
# Infraestructura (PostgreSQL + Redis)
docker compose -f infra/docker-compose.yml up -d

# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate  # Windows; usar `source .venv/bin/activate` en Unix
pip install -e ".[dev]"
alembic upgrade head
pytest
uvicorn app.main:app --reload

# Control Center (otra terminal)
cd apps/control-center
npm install
npm run dev
```

`GET http://localhost:8000/health` debe responder `{"status": "ok", "service": "amazona-backend"}`.
El Control Center queda disponible en http://localhost:3000.

Guías de demo:
[Milestone 1](docs/milestones/milestone-1-demo.md) (los tres escenarios de
validación) ·
[Milestone 2](docs/milestones/milestone-2-demo.md) (Supabase real, auth
opcional, memoria/monitorización, flujo Investigación → Validación).

`backend/.env.example` documenta las variables de Supabase
(`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`DATABASE_URL`) — copia a `backend/.env` (gitignored) y rellena con
credenciales reales para conectar a Postgres real en vez del valor local
por defecto.

## Calidad

CI (`.github/workflows/ci.yml`) ejecuta en cada push/PR:

- Backend: `ruff check`, `mypy`, `alembic upgrade head` contra PostgreSQL limpio, `pytest`.
- Control Center: `eslint`, `tsc --noEmit`, `npm test`, `next build`.

Para ejecutar los mismos checks en local:

```bash
cd backend && ruff check . && mypy app && pytest
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

## Estado

- **Milestone 1** completo: objetivo simulado -> planificación -> agentes
  especialistas -> decisión determinista -> permisos/presupuesto ->
  aprobación humana -> auditoría, expuesto vía API REST y el Control
  Center.
- **Milestone 2** completo: base de datos central real en Supabase
  (región UE), memoria compartida entre agentes, protocolo de mensajería
  versionado, grafo de tareas persistido, reintentos acotados,
  auth/roles opcionales (`REQUIRE_AUTH`), monitorización
  (`/health/detailed`, latencia de agentes), y el primer agente de
  Fase 3 — Investigación de Productos, con el loop
  Investigación → Validación cerrado en el Control Center.
- ⚠️ RLS pendiente de política en el proyecto Supabase (ver
  [milestone-2-demo.md](docs/milestones/milestone-2-demo.md#seguridad-row-level-security)).

## Notas

- Amazon SP-API: prohibido usar sus datos para entrenar modelos.
- No hay dinero real, pedidos, proveedores ni impuestos reales.
- El Agente 1 (Investigación de Productos) usa únicamente fuentes
  simuladas/mock — sin llamadas a APIs externas reales.
- Toda acción relevante debe quedar auditada; el CEO nunca puede saltarse permisos, límites de presupuesto ni aprobaciones humanas requeridas.
