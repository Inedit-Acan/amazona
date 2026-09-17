# Milestone 23 Demo

**Origen:** `docs/design/AMAZONA_handoff_backend_paneles_pendientes.md`
§1 — primera de las 4 piezas aprobadas para resolver lo que Milestones
19/21/22 dejaron fuera por falta de datos reales. **Sin ADR nueva** —
arreglo trivial, sin decisión de arquitectura.

## Qué se entrega

`db/models/agent.py::Agent` y el registro en memoria
(`agents/registry.py::build_default_agent_manager`) ya tenían
`version`/`cost_profile` para los 13 agentes (`version="1.0.0"`,
`cost_profile={"simulated_cost_per_task": 0.0}`) — el único problema era
que `api/agents.py::AgentOut` los descartaba al serializar.

- **Backend:** `AgentOut` gana `version: str` y `cost_profile: dict`;
  `list_agents()` los pasa tal cual desde el `AgentDescriptor`. Sin
  migración, sin tabla nueva — exactamente como preveía la nota.
- **Frontend:** `Agent` (`lib/api.ts`) gana los dos campos.
  `VersionCard` (nuevo, `components/version-card.tsx`) muestra la
  versión con `DataProvenanceBadge status="verified"` (es el valor
  literal que asigna el registro, no una estimación) y `cost_profile`
  con `status="estimated"` (es un coste nominal declarado, no medido
  por ejecución — distinción explícita de la nota). Se monta dentro de
  `AgentCard` (`/agents`), bajo las métricas reales de ejecución que ya
  añadió Milestone 22.

## Verificación

```bash
cd backend && ruff check . && mypy app && pytest       # 488 tests, sin regresiones
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

`tests/integration/test_api.py` no asume la forma exacta de `AgentOut`
(solo cuenta agentes y compara `role`), así que el campo añadido no
rompe nada. Verificado en el navegador embebido: `/agents` renderiza sin
errores de consola propios de la aplicación (el backend real no se
levantó — apunta a Supabase de producción, fuera de alcance sin
permiso).

## Qué sigue

Milestone 24 — "Actividad económica — últimos 30 días" en el Panel
general (endpoint nuevo de solo lectura, sin tocar agentes).
