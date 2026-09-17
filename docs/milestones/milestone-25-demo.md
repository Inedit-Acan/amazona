# Milestone 25 Demo

**Origen:** `docs/design/AMAZONA_handoff_backend_paneles_pendientes.md`
§4 — `IncidentCard` v1, manual, sobre el modelo `Incident` ya existente
como scaffold sin API. **Sin ADR nueva** — la nota ya documentó y
descartó la alternativa (resucitar `Incident` para autocreación) con el
mismo razonamiento que ADR-0006 aplicó a `Policy`; no hay decisión de
arquitectura nueva que registrar.

## Qué se entrega

### Backend — `api/incidents.py`

`db/models/incident.py::Incident` ya estaba provisionado en el esquema
inicial con RLS activado (`alembic/versions/10de07bea94d_enable_rls_deny_by_default.py`)
— no hizo falta ninguna migración, solo la capa de API que nunca existió:

- `GET /api/incidents` — lista completa, más recientes primero.
- `POST /api/incidents` — crea un incidente `OPEN` (`title`,
  `description` opcional, `severity` acotada a `LOW`/`MEDIUM`/`HIGH`/
  `CRITICAL`, `actor`).
- `POST /api/incidents/{id}/resolve` — marca `RESOLVED` + `resolved_at`;
  409 si ya no está `OPEN` (`IncidentNotOpenError`, nuevo, mismo patrón
  que `PipelineReviewNotPendingError`).

`Incident` no tiene columna `resolved_by`/`created_by` y no se le añadió
una — el rastro de quién hizo qué se apoya en `AuditLog`
(`incident.create`/`incident.resolve`, `resource=incident:{id}`),
igual que ya hace el resto del sistema para acciones sin campo de actor
dedicado en su propia tabla. 7 tests nuevos en
`tests/integration/test_incidents_api.py` (creación, listado, resolución,
conflicto al resolver dos veces, 404, severidad inválida rechazada por
Pydantic, y el registro de auditoría).

**Explícitamente fuera (handoff §4):** ninguna creación automática de
incidentes a partir de señales del sistema (backend caído según
`ServiceMap`, `PipelineReview` sin resolver, etc.) — es v1 puramente
manual.

### Frontend — sección "Incidentes" en `/status`

- `Incident`/`IncidentSeverity`/`IncidentStatus` + `listIncidents`/
  `createIncident`/`resolveIncident` en `lib/api.ts`.
- **`IncidentCard`** (nuevo): título, severidad (badge de 4 colores,
  propio — no reutiliza `StatusChip`, que es vocabulario de estado de
  ciclo de vida, no de criticidad), `StatusChip` de estado
  (`OPEN`/`RESOLVED`, añadidos al vocabulario compartido), botón
  "Marcar como resuelto" cuando está abierto.
- **`IncidentReportForm`** (nuevo): formulario mínimo (título,
  severidad, descripción opcional) — registro manual, como pide la nota.
- `/status` gana una sección "Incidentes" justo debajo del `ServiceMap`
  (prioridad visual alta cuando hay incidentes abiertos, parte2.md
  §9.18), con incidentes abiertos y resueltos en listas separadas.

## Verificación

```bash
cd backend && ruff check . && mypy app && pytest       # 498 tests (+7 nuevos), sin regresiones
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

Verificado en el navegador embebido: `/status` renderiza la sección
Incidentes completa (formulario + "Sin incidentes abiertos" con el
backend real no disponible, degradando con gracia vía el mismo patrón
`.catch(() => [])` que ya usan `executions`/`health`). El flujo completo
crear→resolver no se verificó contra un backend real (mismo motivo que
milestones anteriores: apunta a Supabase de producción) — se apoya en
los 7 tests de integración contra SQLite más `tsc`/`build` en verde.

## Qué sigue

Milestone 26 — radar de oportunidades de 5 ejes en Investigación (la
pieza que toca el agente, dejada para el final según el orden sugerido
por la nota).
