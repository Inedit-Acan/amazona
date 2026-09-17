# Milestone 17 Demo

**Origen:** `docs/design/AMAZONA_handoff_fusion_marketplace_y_pipeline.md`,
Tarea 2 — segunda y última fusión de contenido antes de la fase de
sistema de diseño visual. **Sin ADR nueva** — la decisión de arquitectura
ya estaba aprobada en ADR-0006; este milestone solo cierra la decisión
de ubicación de UI que esa ADR había dejado explícitamente abierta, vía
una adenda a la misma ADR.

## Decisión confirmada con Ivan

El handoff dejaba dos opciones razonables para el kill switch del
pipeline (Aprobaciones o Estado) y pedía no decidirlo unilateralmente.
Confirmado: **Aprobaciones** — opción (a) del handoff, coherente con el
mapeo "Decisión humana → Aprobaciones" y con que ambas piezas
(`PipelineReview` + `PipelineKillSwitch`) se introdujeron juntas en
ADR-0006 como "control humano sobre el pipeline". Documentado como
adenda en [`docs/architecture/adr-0006-pipeline-human-controls.md`](../architecture/adr-0006-pipeline-human-controls.md#adenda--ubicación-de-ui-milestone-17).

## Qué se entrega

Los endpoints de `api/pipeline.py` **no cambian** (handoff, explícito) —
este milestone es enteramente frontend + documentación.

- **`components/pipeline-review-card.tsx`** (nuevo): mismo lenguaje
  visual que `ApprovalCard` (Card, `StatusBadge`, botones Approve/Reject)
  para `PipelineReview`, que no comparte forma suficiente con `Approval`
  para una sola card (`PipelineReview` no tiene `decision_id`/`action`/
  `amount`; `Approval` no tiene `reasons`/`pipeline_run_id`).
- **`components/kill-switch-control.tsx`** (nuevo, movido de
  `app/pipeline/page.tsx`): mismo componente `KillSwitchControl` de
  Milestone 14, ahora reutilizable.
- **`app/approvals/page.tsx`**: llama `api.listApprovals()` y
  `api.listPipelineReviews()` en paralelo (ambas funciones de cliente ya
  existían en `lib/api.ts` desde Milestone 14 — no hizo falta tocar la
  capa de API), fusiona ambos arrays en un tipo discriminado
  `InboxItem`, ordena pendientes primero en la misma bandeja (un solo
  grid, cada tipo con su card), y monta `KillSwitchControl` fijo en la
  cabecera, antes de la bandeja.
- **`app/pipeline/page.tsx`** eliminado.

## Verificación

```bash
cd backend && ruff check . && mypy app && pytest       # 488 tests, sin cambios (api/pipeline.py intacto)
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

Verificado en el navegador embebido contra el dev server real
(`preview_start`): `/approvals` renderiza el título/descripción nuevos y
el estado de error manejado correctamente sin backend disponible (no se
levantó el backend real porque apunta a la base Supabase de producción
del proyecto — fuera de alcance sin permiso explícito); sin errores de
consola propios de la aplicación. `grep` confirma que no queda ningún
`href="/pipeline"` ni referencia colgante en `apps/control-center`.

## Cierre de la Fase 1 (fusión de contenido)

Con Milestone 16 y 17, `nav-items.ts` refleja exactamente las 15
entradas aprobadas sin rutas huérfanas fuera del menú. Empieza la Fase 2:
sistema de diseño visual (`docs/design/AMAZONA_sistema_de_diseno_
visual.md`), Milestone 18 en adelante.
