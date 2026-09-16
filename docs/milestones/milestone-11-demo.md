# Milestone 11 Demo

**Ticket:** IVA-59 (Linear).

Conecta el `BudgetEngine`/`BudgetState` del orquestador (Milestone 1, ADR
0001) con persistencia real en `budget_allocations`/`financial_events`
(`backend/app/db/models/budget.py`). Este gap salió a la luz al construir
el Agente CFO (Milestone 10, IVA-58): su informe agregado siempre
reportaba presupuesto reservado/comprometido/gastado en cero, porque
nada escribía nunca en esas tablas — el orquestador gestiona presupuesto
enteramente en memoria.

## Investigación previa (resumen)

Antes de tocar código se investigó cómo funciona hoy el presupuesto:

- `BudgetEngine`/`BudgetState` (`backend/app/budgets/engine.py`) es un
  objeto pydantic puro, en memoria, una instancia por `CEOOrchestrator`,
  con `hard_limit=100_000.0` hardcodeado. Solo `authorize()` y
  `reserve()` se llamaban en producción — `commit()`/`release()` nunca se
  invocaban fuera de `test_budget_engine.py`.
- La reserva **nunca se resolvía**: `orchestrator.py::_maybe_create_approval`
  reserva presupuesto en memoria y crea una fila `Approval` (DB), pero la
  acción real de aprobar/rechazar ocurre en un endpoint completamente
  distinto (`backend/app/api/approvals.py::_resolve`), que no tenía
  ninguna referencia a `BudgetEngine`/`BudgetState`. Es decir: ni
  siquiera en memoria se llegaba a comprometer o liberar una reserva tras
  la decisión humana.
- Ninguna fila `Budget`/`BudgetAllocation`/`FinancialEvent` se escribía
  nunca en producción (confirmado por grep; el único lugar que las
  construye era un fixture de test del Agente CFO).

**Conclusión de alcance:** conectar esto correctamente requiere escribir
en dos sitios — el paso de reserva del orquestador *y* el paso de
resolución de la API de aprobaciones — o `committed`/`spent` se quedarían
siempre en cero. Se propuso el plan al usuario antes de implementar (por
el alcance mayor al literal del ticket) y se aprobó seguir adelante con
ambos puntos.

## Diseño

- **`BudgetEngine`/`BudgetState` no se tocan.** Su lógica de autorización
  en memoria y su test de seguridad ante condiciones de carrera (20
  `reserve()` concurrentes contra un límite de 1000 aprueban exactamente
  10) siguen intactos y sin riesgo.
- **`backend/app/budgets/service.py::BudgetLedgerService`** (nuevo): un
  registro duradero en paralelo. Obtiene-o-crea una única fila `Budget`
  canónica (`name="orchestrator-default"`, `hard_limit=100_000.0` —
  mismo valor que antes, ahora centralizado en una constante compartida
  `DEFAULT_BUDGET_HARD_LIMIT`) y su `BudgetAllocation`, y expone
  `record_reserve`/`record_commit`/`record_release`, cada una
  actualizando la asignación y añadiendo una fila `FinancialEvent`
  (`type` RESERVE/COMMIT/RELEASE, `reference=f"approval:{approval_id}"`
  para trazabilidad — no hizo falta tocar el esquema).
- **Orquestador** (`_maybe_create_approval`): tras el `reserve()` en
  memoria existente, llama a `record_reserve(...)` con `add()`+`flush()`
  únicamente — viaja dentro de la misma transacción única de
  `run_objective()` (que sigue comprometiéndose una sola vez al final).
- **API de aprobaciones** (`_resolve`): al `APPROVED` llama a
  `record_commit`; al `REJECTED` o a la expiración diferida (`EXPIRED`)
  llama a `record_release`. Mismo `db.commit()` que ya existía.
- **Limitación conocida y documentada (no introducida por este trabajo,
  preexistente):** una aprobación que expira sin que nadie llame al
  endpoint después de esa fecha nunca libera su reserva — no existe hoy
  ningún barrido en segundo plano. Fuera de alcance de IVA-59.

## Verificación

```bash
# Objetivo con presupuesto asignado, hasta HUMAN_APPROVAL
curl -s -X POST http://localhost:8000/api/objectives -d '{...}' # spend_amount: 150.0
curl -s -X POST http://localhost:8000/api/objectives/<id>/run
curl -s -X POST http://localhost:8000/api/cfo/runs
# -> reserved=150.0, committed=0.0, budget_utilization=0.0015 (150/100000)

curl -s -X POST http://localhost:8000/api/approvals/<approval_id>/approve -d '{"actor": "..."}'
curl -s -X POST http://localhost:8000/api/cfo/runs
# -> reserved=0.0, committed=150.0, spent=150.0, budget_utilization=0.003 ((150+150)/100000)
```

**Verificado manualmente en el navegador**: se ejecutó el flujo completo
(crear objetivo con `spend_amount=150.0` → correr → aprobar) contra el
backend real con una base SQLite de desarrollo, y la página **CFO**
mostró "budget utilization ... reserved $0.00, committed $150.00, spent
$150.00" tras la aprobación — el mismo informe que en Milestone 10
mostraba siempre cero.

**Cobertura de tests:**
- `backend/tests/integration/test_budget_ledger_service.py` — unit-level
  del nuevo `BudgetLedgerService` (reserve/commit/release,
  get-or-create idempotente, release nunca deja `reserved` negativo).
- `backend/tests/integration/test_ceo_orchestrator.py` — tras
  `run_objective()` con presupuesto asignado, `budget_allocations`
  refleja la reserva real y `financial_events` tiene el evento `RESERVE`.
- `backend/tests/integration/test_budget_ledger_via_approvals_api.py` —
  el escenario completo end-to-end vía HTTP: reservar (al correr),
  comprometer (al aprobar), liberar (al rechazar), y **una prueba
  específica de que el Agente CFO reporta `budget_utilization` real y
  distinto de cero tras la aprobación** — el consumidor directo de este
  gap, verificado explícitamente como pidió el ticket.

```bash
cd backend && ruff check . && mypy app && pytest       # 427 tests
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```
