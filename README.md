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

## Estado

Fase 1 — Fundación (semanas 1–3).

## Notas

- Amazon SP-API: prohibido usar sus datos para entrenar modelos.
- No hay dinero real, pedidos, proveedores ni impuestos reales en Milestone 1.
- Toda acción relevante debe quedar auditada; el CEO nunca puede saltarse permisos, límites de presupuesto ni aprobaciones humanas requeridas.
