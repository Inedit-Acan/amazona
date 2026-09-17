# AMAZONA Milestone 14 Implementation Plan

> **Para agentes que ejecuten este plan:** implementar tarea por tarea con
> TDD, commits pequeños, y revisión después de cada tarea — igual que
> Milestone 1-13.

**Ticket:** IVA-33 (Fase 4.5, "Implementar controles humanos críticos") —
Linear, proyecto "Fase 4 — Integración y pruebas".

**Objetivo:** cerrar el gap que Milestone 12/13 dejaron señalado
explícitamente — nada impide hoy que un resultado de riesgo del pipeline
pase desapercibido, y nada permite a un operador desactivarlo. Dos
controles, uno post-hoc (revisión humana obligatoria de ejecuciones de
riesgo) y uno pre-hoc (kill switch operativo).

**Depende de:** Milestone 12/13, y la nueva
[ADR 0006](../../architecture/adr-0006-pipeline-human-controls.md)
(decisión de diseño de este milestone).

## Decisión de alcance (ver ADR 0006 para el razonamiento completo)

- El pipeline **sigue sin pausar a mitad de ejecución** — ningún paso
  espera aprobación antes de que el siguiente corra. Los controles son
  post-hoc (revisión obligatoria del resultado) y pre-hoc (kill switch
  antes de arrancar), no pausas intermedias.
- `PipelineReview` es un modelo nuevo (no se reutiliza `Approval`, cuyo
  `decision_id` es una FK no nula a `decisions`).
- El kill switch es una tabla nueva de una sola fila canónica, mismo
  patrón *get-or-create* que `BudgetLedgerService` (Milestone 11) — no
  se reutiliza el modelo `Policy` (scaffold muerto de Milestone 1).
- Criterio de "necesita revisión" (función pura, sin estado): `status ==
  "PARTIAL"`, `economics`/`legal` en `NO_GO`, cualquiera de
  `ecommerce`/`marketplace`/`marketing`/`operations` en `BLOCKED`, o
  `cfo` en `AT_RISK`/`CRITICAL`.

## Restricciones globales (heredadas)

- Toda tabla nueva nace con RLS activado en su propia migración (ADR 0003).
- Tests antes que implementación. Commit por tarea completada.
- Ningún test de Milestone 1-13 cambia de resultado.

---

## Estructura de archivos

```text
backend/
├── app/
│   ├── pipeline/
│   │   ├── review.py            # assess_pipeline_run (función pura)
│   │   ├── kill_switch.py       # PipelineKillSwitchService
│   │   └── service.py           # modificado: chequea kill switch, crea PipelineReview
│   ├── api/
│   │   └── pipeline.py          # modificado: endpoints de revisión + kill switch
│   ├── core/errors.py           # + PipelineDisabledError, PipelineReviewNotPendingError
│   └── db/models/
│       ├── pipeline_run.py      # + needs_review
│       ├── pipeline_review.py   # nuevo
│       └── pipeline_kill_switch.py  # nuevo
├── alembic/versions/              # nueva migración
└── tests/
    ├── unit/
    │   └── test_pipeline_review_assessment.py
    ├── integration/
    │   ├── test_pipeline_kill_switch_service.py
    │   ├── test_pipeline_review_flow.py
    │   └── test_pipeline_api_governance.py
    └── e2e/
        └── test_pipeline_human_controls_flow.py

apps/control-center/
├── app/
│   └── pipeline/page.tsx        # modificado: badge "needs review" + kill switch toggle
├── lib/api.ts                   # + tipos y métodos de revisión/kill switch
```

---

## Sección A — Kill switch

### Tarea 1: `PipelineKillSwitch` (tabla + servicio)

**Files:**
- Create: `backend/app/db/models/pipeline_kill_switch.py`
- Create: `backend/app/pipeline/kill_switch.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: Alembic migration
- Create: `backend/tests/integration/test_pipeline_kill_switch_service.py`

- [ ] Test: por defecto (sin fila previa) el kill switch está habilitado
      (`is_enabled() -> True`).
- [ ] Test: `disable(reason=..., actor=...)` persiste `enabled=False` +
      audita; `is_enabled()` refleja el cambio.
- [ ] Test: `enable(actor=...)` revierte y audita.
- [ ] Implementar `PipelineKillSwitchService` (mismo patrón
      get-or-create de `BudgetLedgerService`). Aplicar migración a
      Supabase real, confirmar RLS + `get_advisors` en 0.
- [ ] Commit: `feat: add pipeline kill switch`

### Tarea 2: `PipelineOrchestrator` respeta el kill switch

**Files:**
- Modify: `backend/app/pipeline/service.py`
- Modify: `backend/app/core/errors.py` (+ `PipelineDisabledError`)
- Modify: `backend/app/api/pipeline.py` (handler 423)
- Modify: `backend/app/main.py` (registrar el exception handler)

- [ ] Test: con el kill switch deshabilitado, `run_pipeline()` lanza
      `PipelineDisabledError` sin crear ningún `Product`/fila.
- [ ] Test: `POST /api/pipeline/runs` devuelve 423 con el switch
      deshabilitado.
- [ ] Implementar.
- [ ] Commit: `feat: make pipeline orchestrator respect the kill switch`

---

## Sección B — Revisión humana obligatoria

### Tarea 3: `assess_pipeline_run` (función pura)

**Files:**
- Create: `backend/app/pipeline/review.py`
- Create: `backend/tests/unit/test_pipeline_review_assessment.py`

- [ ] Test: `status="PARTIAL"` ⇒ necesita revisión, motivo incluido.
- [ ] Test: `economics`/`legal` en `NO_GO` ⇒ necesita revisión.
- [ ] Test: cualquiera de ecommerce/marketplace/marketing/operations en
      `BLOCKED` ⇒ necesita revisión.
- [ ] Test: `cfo` en `AT_RISK`/`CRITICAL` ⇒ necesita revisión.
- [ ] Test: una ejecución completamente sana (`COMPLETED`, todo
      `GO`/`READY`/`HEALTHY`) ⇒ no necesita revisión.
- [ ] Implementar `assess_pipeline_run(status, steps) -> PipelineAssessment`
      (`needs_review: bool`, `reasons: list[str]`).
- [ ] Commit: `feat: add pure pipeline risk assessment`

### Tarea 4: `PipelineReview` (tabla) + integración en `run_pipeline`

**Files:**
- Create: `backend/app/db/models/pipeline_review.py`
- Modify: `backend/app/db/models/pipeline_run.py` (+ `needs_review`)
- Modify: `backend/app/db/models/__init__.py`
- Modify: `backend/app/pipeline/service.py`
- Create: Alembic migration (misma migración de la Tarea 1, o una
  adicional)
- Create: `backend/tests/integration/test_pipeline_review_flow.py`

- [ ] Test: una ejecución de riesgo crea una `PipelineReview` `PENDING`
      y `PipelineRun.needs_review=True`.
- [ ] Test: una ejecución sana no crea ninguna `PipelineReview` y
      `needs_review=False`.
- [ ] Implementar; aplicar migración a Supabase real, confirmar RLS +
      `get_advisors` en 0.
- [ ] Commit: `feat: persist a pipeline review when a run needs human attention`

### Tarea 5: API de revisión (approve/reject)

**Files:**
- Modify: `backend/app/api/pipeline.py`
- Modify: `backend/app/core/errors.py` (+ `PipelineReviewNotPendingError`)
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_pipeline_api_governance.py`

**Produces:**
- `GET /api/pipeline/reviews` → pendientes, más reciente primero.
- `POST /api/pipeline/reviews/{id}/approve` → `{actor}`.
- `POST /api/pipeline/reviews/{id}/reject` → `{actor}`.
- `GET /api/pipeline/kill-switch` → estado actual.
- `POST /api/pipeline/kill-switch` → `{enabled, reason, actor}`.

- [ ] Test: aprobar/rechazar resuelve la revisión, audita
      (`pipeline_review.approve`/`.reject`), 409 si ya resuelta.
- [ ] Test: `GET /api/pipeline/kill-switch` refleja el estado tras un
      `POST`.
- [ ] Commit: `feat: add pipeline review and kill switch api`

---

## Sección C — Control Center

### Tarea 6: Página "Pipeline" — badge de revisión + interruptor

**Files:**
- Modify: `apps/control-center/app/pipeline/page.tsx`
- Modify: `apps/control-center/lib/api.ts`

**Produces:** el resultado de una ejecución muestra "Needs human
review" con los motivos cuando aplica; un interruptor visible activa/
desactiva el kill switch, con confirmación.

- [ ] Verificar en navegador (desktop + mobile) con datos reales.
- [ ] Commit: `feat: surface pipeline review and kill switch in the control center`

---

## Sección D — Verificación end-to-end

### Tarea 7: E2E + doc de cierre

**Files:**
- Create: `backend/tests/e2e/test_pipeline_human_controls_flow.py`
- Create: `docs/milestones/milestone-14-demo.md`

**Escenario:** una categoría/precio que produce `NO_GO` en economics →
la ejecución del pipeline queda con `needs_review=True` y una
`PipelineReview` `PENDING` → un humano la aprueba → queda auditada.
Además: deshabilitar el kill switch → un intento de `POST
/api/pipeline/runs` es rechazado con 423 → reactivarlo → vuelve a
funcionar.

- [ ] Escribir el test, correr, verificar que pasa.
- [ ] Documentar en `docs/milestones/milestone-14-demo.md`.
- [ ] Commit: `test: verify pipeline human controls end to end`

---

## Definition of Done — Milestone 14

1. `PipelineKillSwitch` y `PipelineReview` son tablas reales, con RLS
   activado desde su propia migración, verificadas contra Supabase real.
2. `PipelineOrchestrator.run_pipeline()` respeta el kill switch (lanza
   `PipelineDisabledError` sin efectos secundarios cuando está
   deshabilitado) y crea una `PipelineReview` `PENDING` cuando el
   resultado es de riesgo, sin pausar la ejecución en sí (ADR 0006).
3. API de revisión y kill switch, auditada con el mismo estándar
   `AuditLog` del resto del sistema.
4. El Control Center refleja ambos controles.
5. El flujo E2E demuestra el ciclo completo: ejecución de riesgo →
   revisión pendiente → resolución humana, y kill switch on/off.
6. `docs/milestones/milestone-14-demo.md` documenta el milestone.
7. Ningún test de Milestone 1-13 cambia de resultado.
