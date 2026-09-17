# Milestone 22 Demo

**Origen:** cierre de "resto de paneles" — los componentes con nombre
propio del catálogo compartido (parte2.md §13.2) que Milestone 21 dejó
pendientes de confirmar: `AgentCard`, `ProjectHealth`,
`CorrelationTrace`, `ServiceMap`. **Sin ADR nueva.**

## Qué se entrega

### `AgentCard` (`components/agent-card.tsx`) — `/agents`

Sustituye el markup inline de `agents/page.tsx`. Además de nombre/rol/
capacidades/`StatusChip` (que ya existían), añade **éxito, latencia
media y última actividad calculados en el cliente a partir de
`AgentExecutionLog` real** (`api.listAgentExecutions()`, agrupado por
`agent_id`) — dato que ningún panel mostraba hasta ahora agregado por
agente. `reliability_score` se marca con `DataProvenanceBadge
status="estimated"` (es un valor nominal del descriptor del agente, no
una medición). **No se muestran** coste, versión ni evaluación
(parte2.md §6.5 los pide): `/api/agents` no expone versión (hay un
modelo `Agent` en BD con ese campo, pero el endpoint real usa un
registro en memoria distinto que no lo serializa), y no existe ningún
sistema de coste-por-ejecución ni evaluation suite en el backend —
inventar cualquiera de los tres habría sido fabricar datos.

### `ProjectHealth` (`components/project-health.tsx`) + `lib/decision-health.ts` — `/projects`, `/projects/[id]`

Score multidimensional explicable (parte2.md §5.6): 4 dimensiones reales
— Mercado, Proveedor, Economía, Legal — derivadas del campo
`recommendation` real de cada `DecisionEvidence` (confirmado en
`backend/app/ceo/orchestrator.py`: cada evidencia lleva `{...output.data,
recommendation: output.recommendation, risks: ...}`), con un riesgo
agregado (`bajo`/`medio`/`alto`, "la peor dimensión gana"). **Canal,
marketing y operaciones se omiten deliberadamente** — no están
vinculados a un `Project`/`Decision` en el modelo de datos actual sin
fan-out adicional, y mostrarlos como comodín sería ruido, no señal.
`/projects` (lista) gana un chip de riesgo compacto por fila (requiere
una consulta extra de `listDecisionsForProject` por proyecto, igual
patrón N+1 ya usado en `/approvals`); `/projects/[id]` muestra el
desglose completo por dimensión.

### `CorrelationTrace` (`components/correlation-trace.tsx`) — `/audit`

Cuando `/audit?correlation_id=X` filtra, además de la tabla ya existente
se muestra la cadena de eventos como línea de tiempo conectada
(parte2.md §8.7). **No hardcodea** la secuencia "Solicitud → Economía →
Legal → CFO → Aprobación → Ejecución" del documento — usa los eventos
reales que `GET /api/audit` devuelve, ya ordenados ascendente por
`created_at`, sea cual sea la cadena real (la del `CEOOrchestrator` y la
del `PipelineOrchestrator` difieren).

### `ServiceMap` (`components/service-map.tsx`) — `/status`

Topología de 8 nodos (Usuarios → Frontend → API → Postgres → Auth/
Storage → Queue → Workers → Integraciones), coloreada solo donde hay
señal real: Frontend siempre activo (evidencia trivial: si se está
viendo, está corriendo), API activo/error según si `fetchHealth()`
logró contactar al backend (nueva distinción — antes se colapsaba con
el estado de la base de datos), Postgres y Auth/Storage según
`DetailedHealth` ya existente. Usuarios/Queue/Workers/Integraciones
quedan atenuados con una nota explícita ("sin monitorización todavía")
en vez de inventarse un estado. **Verificado en vivo contra el estado
real de backend caído** (no se levantó el backend real, igual que en
milestones anteriores): el mapa coloreó correctamente Frontend en verde
y API/Postgres en rojo — confirmado por screenshot.

## Decisión de alcance

`IncidentCard`, `QueueStatus`, `VersionCard` (catálogo de parte2.md
§13.2) no se construyeron: no existe ninguna tabla de incidentes, ningún
endpoint de métricas de cola, ni ningún registro de versión/deploy en
este backend. Construirlos habría significado o bien fabricar datos, o
bien un shell vacío sin ningún dato real que mostrar nunca — ninguna de
las dos cosas es "aplicar el sistema de diseño visual".

## Verificación

```bash
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

No se tocó `backend/`. Verificado en el navegador embebido: `/status`
(capturado por screenshot, colores correctos con el backend real caído),
`/agents`, `/audit`, `/projects` renderizan sin errores de consola
propios de la aplicación.
