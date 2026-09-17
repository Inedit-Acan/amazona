# Milestone 19 Demo

**Origen:** `docs/design/AMAZONA_sistema_de_diseno_visual.md` §9.2 —
"Panel general (`/dashboard`)", segundo paso del orden recomendado para
la Fase 2. Especificación funcional: `AMAZONA_especificacion_paneles_
aprobados_v0.5.md` §3. **Sin ADR nueva.**

## Qué se entrega

Reescritura de `app/dashboard/page.tsx` sobre la base de Milestone 18
(`KpiCard`, `DataProvenanceBadge`, `StatusChip`, `EmptyState` — estos dos
últimos, nuevos, construidos aquí por primera vez y reutilizables desde
ya en cualquier panel):

- **KPIs superiores** (`KpiCard`, nuevo `components/kpi-card.tsx`):
  Proyectos, Agentes en línea, Aprobaciones pendientes — conteos reales,
  `provenance="verified"` — y Salud financiera, tomada del `CFOReport`
  más reciente (`api.listCFORuns()`, ya existente), `provenance=
  "estimated"` (es un reporte generado por el agente CFO, no un hecho
  verificado) o `"pending"` si el agente CFO aún no se ha ejecutado
  nunca.
- **Actividad empresarial**: las 8 ejecuciones de agente más recientes
  (`api.listAgentExecutions()`, ya existente pero no consumido por
  ningún panel hasta ahora), cruzadas con el nombre del agente,
  mostrando `StatusChip` (COMPLETED/FAILED según `execution.success`).
- **Decisiones necesarias**: la misma lista de aprobaciones pendientes
  que ya existía, reetiquetada según el nombre de sección de la spec.
- **Oportunidades**: `EmptyState` (nuevo, `components/empty-state.tsx`)
  con CTA a Investigación, en vez de una tabla de oportunidades.

## Decisión de alcance (por qué no está todo lo que pide la spec)

- **Sin gráfico "Ventas / margen últimos 30 días" (v0.5 §3.2).** No
  existe en el sistema ningún dato de ventas real ni una serie temporal
  de márgenes — es un sistema simulado, sin tabla de pedidos/ventas con
  histórico (`OperationsRecord` es un registro por ejecución de agente,
  no un ledger de ventas). Inventar cifras para ese gráfico violaría
  directamente el principio central de este mismo sistema de diseño
  (§3: "Nunca presentar una estimación como si fuera un hecho
  confirmado") de una forma mucho más grave — series temporales
  completamente fabricadas, no una estimación etiquetada. Se omite el
  gráfico en vez de fabricarlo.
- **"Oportunidades" es un `EmptyState`, no una tabla.** No existe ningún
  endpoint que liste oportunidades agregadas históricamente — Investigación
  solo devuelve candidatos al lanzar un análisis (`POST /api/research/runs`),
  y el panel general no debe disparar esa acción con efectos secundarios
  solo para poblar una vista de resumen. El `EmptyState` es honesto sobre
  esta limitación real y enlaza a Investigación.
- **KPI "variación" y "mini sparkline" (v0.5 §3.2) no están.** No hay
  ningún endpoint de snapshots históricos de estas métricas (solo el
  valor actual), así que no hay ninguna variación real que mostrar.
  `KpiCard` admite un `caption` textual en vez de inventar una tendencia.
- **Sin buscador global en la cabecera.** `GlobalSearch` (catálogo de
  componentes compartidos, parte2.md §13.2) necesitaría un endpoint de
  búsqueda cruzada que no existe — un campo de búsqueda no funcional
  sería peor que no tenerlo. Se deja para cuando el backend lo soporte.

## Verificación

```bash
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

No se tocó `backend/`. Verificado en el navegador embebido: la página
renderiza el título/descripción nuevos y maneja el estado sin backend
correctamente (mismo motivo que milestones anteriores — no se levantó
el backend real contra Supabase). **No verificado visualmente con datos
reales**: levantar el backend contra una base local habría requerido
tocar el manejo de conexiones SQLite multi-hilo en `db/session.py`
(fuera de alcance de este milestone) para evitar errores de
`check_same_thread`; el camino con datos reales se apoya en que el
código es un mapeo directo sobre arrays tipados, con el mismo patrón ya
probado en `ApprovalCard`/`PipelineReviewCard`, más `tsc`/`build` en
verde.

## Qué sigue

Milestone 20 — Director ejecutivo (`/ceo`) + `AgentGraph3D`, el de mayor
riesgo técnico de la Fase 2.
