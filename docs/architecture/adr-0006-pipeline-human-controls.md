# ADR 0006: Controles humanos críticos sobre el Pipeline Orchestrator

- **Estado:** Aceptada
- **Fecha:** 2026-09-17
- **Depende de:** [ADR 0001](adr-0001-orchestrator-vs-ceo.md), [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0005](adr-0005-fase-3-pipeline-orchestrator.md)

## Contexto

Milestone 12 (ADR 0005) construyó `PipelineOrchestrator`: encadena los 9
pasos de Fase 3 automáticamente, y **deliberadamente nunca detiene la
cadena** ante un `NO_GO`/`BLOCKED` intermedio — cada paso se registra en
`steps` y la ejecución sigue hasta el final. Milestone 13 validó ese
comportamiento con tests de regresión explícitos. La consecuencia
señalada en el cierre de ambos milestones: **nada impide hoy que un
resultado agregado de riesgo (varios `NO_GO`, un `CFOReport` en
`CRITICAL`, una ejecución `PARTIAL`) pase desapercibido si nadie revisa
`steps` manualmente**, y **nada permite a un operador desactivar la
ejecución automática del pipeline** si algo empieza a comportarse mal —
ninguna de las dos cosas existe en el sistema hoy.

Investigación previa (sin escribir código) confirmó:
- `Policy` (`backend/app/db/models/policy.py`) es un scaffold de
  Milestone 1 sin ningún camino de lectura/escritura — no se reutiliza
  aquí para no resucitar código muerto.
- `PermissionEngine`/`ActionType`/`PermissionResult` es un gate de
  "¿puede este actor hacer X?", en memoria, sin conocimiento de
  `PipelineRun` — resuelve un eje distinto (permiso por acción), no
  "¿debe esta ejecución del pipeline detenerse o esperar revisión?".
- `Approval` (`backend/app/db/models/approval.py`) tiene `decision_id`
  como FK **no nula** a `decisions.id` — no es reutilizable para
  `PipelineRun` sin forzar una `Decision` falsa o debilitar esa FK para
  todos los llamadores existentes.
- No existe ningún kill-switch/circuit-breaker/feature-flag en todo el
  backend. `ProjectStatus.PAUSED` existe como valor de enum pero ningún
  código lo asigna nunca — es inerte.
- ADR 0001 no fija ningún principio general de "cuándo el sistema exige
  aprobación humana" — cada milestone lo ha decidido caso por caso
  (`decision_engine.py` para el grafo de Milestone 1). Esta ADR es la
  primera en fijar ese principio para el pipeline.

## Decisión

### 1. El pipeline sigue sin detenerse a mitad de ejecución

Se **mantiene** el comportamiento de ADR 0005: ningún paso pausa
`run_pipeline()`. Razonamiento: los 9 pasos son generación/análisis de
datos simulados (ningún paso ejecuta una acción externa real, cobra
dinero, ni publica nada — cada agente ya documenta esto como
`assumption`), así que no hay nada "irreversible" que un humano deba
autorizar *durante* la ejecución. Introducir pausas intermedias
reabriría ADR 0005, invalidaría los tests de regresión de Milestone 13
que verifican explícitamente la no-detención, y complicaría el modelo de
transacción (`run_pipeline` hoy es una secuencia de llamadas a servicios
que ya comprometen su propia transacción cada uno — pausar a mitad
requeriría persistir un estado "en pausa" a mitad de una cadena de
efectos secundarios ya aplicados, un cambio de mucho mayor alcance).

### 2. Control humano post-hoc: revisión obligatoria de ejecuciones de riesgo

Al terminar `run_pipeline()`, una función pura y determinista
(`backend/app/pipeline/review.py::assess_pipeline_run`) decide si la
ejecución **necesita revisión humana**, evaluando `status` y cada
entrada de `steps` con las mismas señales que cada paso ya expone —
sin inventar un umbral nuevo:

- `status == "PARTIAL"` (no llegó a completarse).
- `economics.recommendation == "NO_GO"` o `legal.recommendation == "NO_GO"`.
- `ecommerce"`/`marketplace`/`marketing`/`operations` con `status == "BLOCKED"`.
- `cfo.status` en `{"AT_RISK", "CRITICAL"}`.

Si alguna se cumple, se persiste una fila `PipelineReview` (`PENDING`,
FK a `pipeline_runs.id` — **no** se reutiliza `Approval`, se crea un
modelo nuevo con la misma forma por la incompatibilidad de FK ya
razonada arriba) y `PipelineRun.needs_review = true`. Un humano
resuelve vía `POST /api/pipeline/reviews/{id}/approve` o `/reject`
—mismo patrón de aprobar/rechazar/expirar-por-tiempo que
`api/approvals.py`, mismo estándar de auditoría
(`AuditLog(actor, action="pipeline_review.approve", resource=f"pipeline_review:{id}", ...)`).
Aprobar/rechazar es una anotación de gobernanza (queda registrado quién
decidió qué sobre esa ejecución) — no revierte ni reintenta el pipeline,
que ya es un hecho consumado; es exactamente el mismo espíritu que
`Approval` en el flujo de Milestone 1 (autorizar una acción externa ya
decidida, no deshacer el cómputo que la generó).

### 3. Control humano pre-hoc: kill switch operativo

Se introduce `PipelineKillSwitch` (primera vez que este concepto existe
en el sistema): una única fila canónica (mismo patrón *get-or-create*
que `BudgetLedgerService`, Milestone 11) con `enabled: bool` (default
`true`), `reason: str | None`, `updated_by`, `updated_at`.
`PipelineOrchestrator.run_pipeline()` la consulta **antes** de tocar
cualquier servicio de Fase 3; si `enabled=false`, lanza
`PipelineDisabledError` (404→409-style, mapeado a HTTP 423 Locked) sin
crear ningún `Product`/fila nueva. Un operador la desactiva/reactiva vía
`POST /api/pipeline/kill-switch` (`{enabled, reason, actor}`), auditado
igual que cualquier otra transición de estado del sistema.

## Alternativas consideradas

1. **Pausar la cadena a mitad de ejecución en el paso que produce
   `NO_GO`/`BLOCKED`, esperando aprobación antes de continuar.**
   Rechazada — ver punto 1 de la Decisión: no hay ninguna acción externa
   real que proteger a mitad del pipeline, y reabriría ADR 0005.
2. **Reutilizar `Approval` para las revisiones del pipeline**, aflojando
   `decision_id` a nullable o añadiendo un `resource_type`/`resource_id`
   polimórfico. Rechazada: cambiaría el contrato de una tabla que ya
   usan `CEOOrchestrator`/`BudgetLedgerService`/`api/approvals.py`,
   arriesgando esos tres puntos por una necesidad que un modelo nuevo
   cubre sin tocar nada existente.
3. **Resucitar el modelo `Policy`** como backing store del kill switch.
   Rechazada: es un scaffold sin ningún camino de lectura/escritura hoy;
   forzar su primer uso real en esta ADR mezclaría dos decisiones
   (reactivar `Policy` en general vs. el kill switch específico) sin
   necesidad — un modelo dedicado y pequeño es más simple y más fácil de
   auditar por separado.
4. **No revisar automáticamente — dejar que un humano navegue
   `GET /api/pipeline/runs` y detecte el riesgo por sí mismo.** Rechazada:
   es exactamente el estado actual que este milestone existe para
   cerrar — nada garantiza que alguien lo revise.

## Consecuencias

- `PipelineRun` gana una columna `needs_review` (booleana, indexada) —
  aditivo, no rompe ningún consumidor existente de la API.
- Dos tablas nuevas (`pipeline_reviews`, `pipeline_kill_switch`), ambas
  con RLS activado desde su propia migración (ADR 0003).
- El Control Center gana una vista de revisiones pendientes y un
  interruptor de kill switch — ambos solo relevantes para un operador
  humano, no para el flujo normal de generar productos.
- Si en el futuro se decide que ciertos pasos SÍ deben pausar a mitad de
  ejecución (p. ej. porque un paso empieza a ejecutar una acción externa
  real), eso reabre esta ADR y ADR 0005 explícitamente — no se asume
  aquí.

## Adenda — ubicación de UI (Milestone 17)

Esta ADR dejó sin resolver dónde vive la UI de ambos controles en el
Control Center. `docs/design/AMAZONA_handoff_fusion_marketplace_y_
pipeline.md` (Tarea 2) documentó dos opciones razonables — Aprobaciones
o Estado — y la dejó como decisión de producto explícita, no técnica.

**Decisión confirmada con Ivan: Aprobaciones.** `PipelineReview` entra en
la misma bandeja que `Approval` en `/approvals` (misma página, cards
distintas por la diferencia de forma entre ambos modelos — ver
`components/pipeline-review-card.tsx` vs `components/approval-card.tsx`),
y `PipelineKillSwitch` es un control fijo en la cabecera de esa misma
página (`components/kill-switch-control.tsx`), no en `/status`.

Razonamiento: coherente con "Decisión humana → Aprobaciones" (mapeo de
propiedad funcional en `AMAZONA_especificacion_paneles_aprobados_
parte2.md` §10) y con el espíritu original de esta ADR — ambas piezas se
introdujeron juntas en Milestone 14 como "control humano sobre el
pipeline", así que viven juntas en la superficie de Decisión humana en
vez de separarse entre Aprobaciones y Estado. `/pipeline` como ruta de
menú independiente se retira (Milestone 17); los endpoints de
`api/pipeline.py` no cambian.
