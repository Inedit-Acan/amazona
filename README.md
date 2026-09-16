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

Detalle completo del plan de implementación en [`docs/superpowers/plans/2026-09-15-amazona-milestone-1.md`](docs/superpowers/plans/2026-09-15-amazona-milestone-1.md).

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

Guía completa de demo (los tres escenarios de Milestone 1) en
[`docs/milestones/milestone-1-demo.md`](docs/milestones/milestone-1-demo.md).

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

Milestone 1 completo: objetivo simulado -> planificación -> agentes especialistas ->
decisión determinista -> permisos/presupuesto -> aprobación humana -> auditoría,
expuesto vía API REST y el Control Center.

## Notas

- Amazon SP-API: prohibido usar sus datos para entrenar modelos.
- No hay dinero real, pedidos, proveedores ni impuestos reales en Milestone 1.
- Toda acción relevante debe quedar auditada; el CEO nunca puede saltarse permisos, límites de presupuesto ni aprobaciones humanas requeridas.
