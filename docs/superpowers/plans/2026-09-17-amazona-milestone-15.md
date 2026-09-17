# AMAZONA Milestone 15 Implementation Plan

**Ticket:** IVA-34 (Fase 4.6, "Documentar el sistema") — Linear, proyecto
"Fase 4 — Integración y pruebas". Último milestone de Fase 4.

**Objetivo:** ningún código nuevo. Producir la documentación que le falta
al proyecto: un punto de entrada único que explique el sistema completo
tal como quedó tras 14 milestones, sin exigir leer los 14
`milestone-N-demo.md` uno a uno. El `README.md` actual quedó congelado en
el estado de Milestone 2 (secciones "Estado"/"Arquitectura" desactualizadas
desde entonces) — parte de este milestone es corregir eso, no solo añadir
un documento nuevo aparte.

**Sin ADR** — no hay ninguna decisión de arquitectura que tomar; es
documentación de lo ya construido y decidido en ADR 0001-0006.

## Alcance

1. **`docs/architecture/system-overview.md`** (nuevo, el documento
   principal): arquitectura de las dos capas de orquestación paralelas
   (`CEOOrchestrator` vs `PipelineOrchestrator`), catálogo completo de los
   13 agentes con su capability/tabla/API, modelo de datos por dominio,
   los dos mecanismos de control humano (aprobación de gasto de
   Milestone 1 + revisión/kill-switch de Milestone 14), seguridad (RLS),
   e índices de ADRs y milestones con un resumen de una línea cada uno.
2. **`README.md`** actualizado: arquitectura real (no la aspiracional de
   11 agentes del README original), estado real (Fase 1-4 completas),
   enlace a `system-overview.md` como punto de entrada.
3. **`docs/milestones/milestone-15-demo.md`** (cierre de Fase 4 completa).

## Verificación

- Todo enlace interno de los tres documentos resuelve a un archivo real
  del repo (verificado a mano, no hay tooling de link-checking en este
  proyecto).
- `cd backend && pytest` y `cd apps/control-center && npm run build`
  siguen en verde (no se tocó código, verificación de que nada se rompió
  por accidente al editar `README.md`, que sí tiene bloques `bash`
  copiables).
