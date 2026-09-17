# Milestone 14 Demo

**Ticket:** IVA-33 (Fase 4.5) — Linear, proyecto "Fase 4 — Integración y
pruebas".

Arquitectura: [ADR 0006](../architecture/adr-0006-pipeline-human-controls.md)
(controles humanos críticos sobre el `PipelineOrchestrator`). Plan
completo: [`docs/superpowers/plans/2026-09-17-amazona-milestone-14.md`](../superpowers/plans/2026-09-17-amazona-milestone-14.md).

## Investigación previa (resumen)

Antes de implementar se investigó todo mecanismo de control humano/
gobernanza existente, para reutilizar patrones en vez de inventar
paralelos:

- `Policy` (Milestone 1) es un scaffold sin ningún camino de lectura/
  escritura — no se reutiliza.
- `PermissionEngine`/`ActionType`/`PermissionResult` resuelve "¿puede
  este actor hacer X?", en memoria, sin conocimiento del pipeline — eje
  distinto al que este milestone necesita.
- `Approval` tiene `decision_id` como FK **no nula** a `decisions.id` —
  no reutilizable para `PipelineRun` sin forzar una `Decision` falsa o
  debilitar esa FK para los llamadores existentes.
- No existe ningún kill-switch/circuit-breaker en todo el sistema.
  `ProjectStatus.PAUSED` existe como valor de enum pero nunca se asigna
  — es inerte.
- ADR 0001 no fija ningún principio general de "cuándo el sistema exige
  aprobación humana" — cada milestone lo decide caso por caso.

## Decisión (ver ADR 0006 para el razonamiento completo)

- El pipeline **sigue sin pausar a mitad de ejecución** (ADR 0005 no se
  reabre) — los controles son post-hoc y pre-hoc, no pausas intermedias.
- **Control post-hoc:** `assess_pipeline_run()` (función pura,
  `backend/app/pipeline/review.py`) decide si una ejecución necesita
  revisión humana: `status="PARTIAL"`, `economics`/`legal` en `NO_GO`,
  cualquiera de `ecommerce`/`marketplace`/`marketing`/`operations` en
  `BLOCKED`, o `cfo` en `AT_RISK`/`CRITICAL`. Si aplica, se crea una
  `PipelineReview` (`PENDING`) — modelo nuevo, no se reutiliza `Approval`.
- **Control pre-hoc:** `PipelineKillSwitch` (primera vez que este
  concepto existe en el sistema) — una fila canónica get-or-create
  (mismo patrón que `BudgetLedgerService`, Milestone 11).
  `PipelineOrchestrator.run_pipeline()` la consulta antes de tocar
  cualquier servicio; si está deshabilitado, lanza `PipelineDisabledError`
  (HTTP 423) sin ningún efecto secundario.

## Hallazgo incidental: bug de empate en `CFOService` (Milestone 13)

Al escribir el test de flujo de revisión se detectó que la consulta SQL
"última fila por clave" introducida en Milestone 13
(`MAX(created_at)` + join) puede devolver **más de una fila** por
producto cuando dos filas comparten el mismo `created_at` exacto — a
suficiente volumen de inserciones esto sobre-contaba
`total_products_analyzed`. Corregido reemplazando el `MAX+join` por
`ROW_NUMBER() OVER (PARTITION BY ...)`, que garantiza exactamente una
fila por clave incluso ante empates (cuál de las filas empatadas gana
sigue siendo no determinista — misma ambigüedad que ya existía en todo
el código con `.order_by(created_at.desc()).first()` — pero ya no hay
sobre-conteo). Test de regresión reforzado con timestamps explícitos
para no depender de la resolución del reloj.

## Flujo completo

```bash
# Ejecución de riesgo (precio muy bajo -> economics NO_GO -> cascada BLOCKED)
curl -s -X POST http://localhost:8000/api/pipeline/runs \
  -H "Content-Type: application/json" \
  -d '{"category": "home", "sale_price": 0.5, "destination_region": "mexico"}'
# -> {"needs_review": true, "steps": {"economics": {"recommendation": "NO_GO"}, ...}}

curl -s http://localhost:8000/api/pipeline/reviews
# -> [{"id": "...", "status": "PENDING", "reasons": ["economics recommendation is NO_GO", ...]}]

curl -s -X POST http://localhost:8000/api/pipeline/reviews/<id>/approve \
  -H "Content-Type: application/json" -d '{"actor": "owner@amazona.local"}'

# Kill switch
curl -s -X POST http://localhost:8000/api/pipeline/kill-switch \
  -H "Content-Type: application/json" -d '{"enabled": false, "reason": "incident", "actor": "ops@amazona.local"}'
curl -s -X POST http://localhost:8000/api/pipeline/runs -d '{...}'   # -> 423 Locked
curl -s -X POST http://localhost:8000/api/pipeline/kill-switch -d '{"enabled": true, "actor": "ops@amazona.local"}'
```

O desde el Control Center: página **Pipeline** — un interruptor de kill
switch visible arriba, y el resultado de una ejecución muestra "NEEDS
HUMAN REVIEW" cuando aplica.

**Verificado manualmente en el navegador**: con `sale_price=0.5`, la
ejecución quedó `COMPLETED` con badge **NEEDS HUMAN REVIEW** — economics
`NO_GO` propagó `BLOCKED` en cascada a ecommerce/marketplace/marketing/
operations y CFO quedó `CRITICAL`, exactamente las 6 razones reportadas
por `GET /api/pipeline/reviews`. El interruptor de kill switch se probó
en vivo: deshabilitar → `DISABLED` con el motivo visible → rehabilitar →
`ENABLED`, ambos reflejados en la UI. Verificado también a 375px de
ancho (mobile).

## Base de datos

`pipeline_reviews` (FK a `pipeline_runs.id`) y `pipeline_kill_switch`
(fila única), ambas con RLS activado desde su propia migración;
`pipeline_runs` gana la columna `needs_review` (indexada).

**Verificado contra Supabase real.** La migración se aplicó contra el
proyecto `amazona` (`075bc06fedad → ebc8b88725e2`), y
`SELECT relname, relrowsecurity FROM pg_class WHERE relname IN
('pipeline_reviews', 'pipeline_kill_switch')` confirma `true` en ambas.
`get_advisors` reporta **0 hallazgos** tras la migración.

## Verificar todo en local

```bash
cd backend && ruff check . && mypy app && pytest       # 488 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

## Qué queda para el resto de Fase 4

- **IVA-34 (Milestone 15):** documentación completa del sistema, cierre
  de Fase 4.
