# ADR 0026: La identidad de lo que es único, garantizada por la base de datos

- **Estado:** Aceptada
- **Fecha:** 2026-10-01
- **Depende de:** [ADR 0003](adr-0003-rls-deny-by-default.md) (RLS), [ADR 0022](adr-0022-idempotent-pipeline-run-creation.md), [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md), [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md)
- **Enmienda a:** [ADR 0023](adr-0023-single-budget-source-and-absence-is-not-permission.md) (`budgets.name` sin restricción única)
- **Milestone:** hardening pre-M44, fase 2 (defensas en la base de datos)

## Contexto

El código daba por único un presupuesto, su saldo, el interruptor del pipeline, un movimiento del libro y una pregunta
pendiente, y lo protegía con locks (`pg_advisory_xact_lock`) y con consultas previas («¿ya existe?»). Un lock cubre los
caminos que lo toman; una consulta previa no cubre dos peticiones a la vez. Cuando falla, el daño no es un error: son
**dos filas donde el código supone una**, y cada lector elige la suya.

Medido sobre PostgreSQL, con la base como estaba:

- **`budget_allocations`** (el saldo): con 30 primeras reservas simultáneas y un presupuesto sin fila de saldo, **3 de 12
  pruebas dejaron entre 2 y 4 filas**. La aritmética `UPDATE … WHERE hard_limit - reserved - committed >= :a` comprueba el
  límite **en la fila que actualiza**, así que con varias filas el techo se parte: cada una admite hasta el techo entero.
  (Con 12 hilos no se reprodujo en 6 pruebas: la ventana es estrecha, no inexistente.)
- **`budgets.name`, `pipeline_kill_switch.name`**: únicos por convención; dos filas harían que dos lectores respondieran
  cosas distintas (el código desempataba por antigüedad, un parche que admite el duplicado).
- **`financial_events`**: nada impedía liquidar dos veces la misma reserva. Dos `COMMIT` de la misma `reference` cuentan el
  dinero dos veces.
- **`pipeline_reviews`**: dos preguntas `PENDING` para el mismo paso permiten contestar una y dejar la otra viva.

## Decisión

### 1. Restricciones

| Qué | Restricción |
|---|---|
| un presupuesto por nombre | `UNIQUE (budgets.name)` — `uq_budgets_name` |
| un saldo por presupuesto | `UNIQUE (budget_allocations.budget_id)` — `uq_budget_allocations_budget_id` |
| un interruptor por nombre | `UNIQUE (pipeline_kill_switch.name)` — `uq_pipeline_kill_switch_name` |
| una referencia se **reserva** una vez | índice único parcial sobre `financial_events(reference)` `WHERE type = 'RESERVE'` |
| una referencia se **liquida** una vez (comprometida **o** liberada) | índice único parcial sobre `financial_events(reference)` `WHERE type IN ('COMMIT','RELEASE')` |
| una pregunta pendiente por paso | índice único parcial sobre `pipeline_reviews(pipeline_run_id, step)` `WHERE kind = 'ACTION_GATE' AND status = 'PENDING'` |
| una revisión a posteriori pendiente por ejecución | índice único parcial sobre `pipeline_reviews(pipeline_run_id)` `WHERE kind = 'POST_HOC' AND status = 'PENDING'` |

Los eventos sin `reference` (`NULL`) no tienen identidad que repetir. Una pregunta resuelta (`CONSUMED`, `REJECTED`,
`APPROVED`) no impide abrir otra pendiente: lo único único es lo **abierto**.

### 2. Una referencia se reserva una sola vez

Es el cambio de semántica de esta ADR. Antes, tras liquidar una reserva se podía volver a reservar con la misma
`reference`; ahora **un gasto nuevo es otro gasto y necesita otra referencia** (`action:{id}` para el pipeline,
`approval:{id}` para el CEO: ya eran únicas por construcción). `BudgetLedgerService.reserve` lo comprueba **antes** de
tocar el saldo y lo dice con un `ValidationError`; la restricción de la base es el respaldo, no el mensaje:

- reservar otra vez lo que sigue vivo con `idempotent=True` sigue siendo un no-op (es el reintento tras una caída);
- reservar otra vez lo ya liquidado, o sin `idempotent` lo que sigue vivo, se rechaza.

### 3. El código no depende solo de las restricciones

- `_allocation` serializa la creación del saldo por presupuesto (lock transaccional en PostgreSQL) y vuelve a consultar
  tras tomarlo; la restricción cubre cualquier camino que se salte el lock.
- `PipelineOrchestrator._open_review` abre la pregunta en un SAVEPOINT (abierto **antes** de añadir la fila: añadirla antes
  la volcaría fuera) y, si otro ejecutor abrió la misma un instante antes, devuelve **esa** en vez de fallar. Una
  `IntegrityError` que no sea ese duplicado (una clave ajena rota, por ejemplo) **se relanza**: no se disimula.
- Un techo (`authorise_budget`) tiene que ser un número **finito**, en **céntimos** (más decimales se redondearían a otra
  cosa de lo que se escribió) y **no superior a 10 000 000**. `inf`, `nan`, `1e30` y un cero de más se rechazan antes de
  escribir nada. No es una política de negocio sino una guarda contra un error de tecleo: no existe un presupuesto
  ilimitado.

### 4. La migración no toca datos

`e1b8d4a62f37` **no borra, no fusiona y no arregla filas**. Comprueba primero las siete garantías y, si ya hay duplicados,
**se niega a continuar antes de cambiar nada** (DDL transaccional en PostgreSQL: la versión de Alembic no avanza) y lista
cuáles son. Una persona decide qué fila es la buena. La docstring de la migración trae las siete consultas de solo lectura
para ejecutar **antes** de aplicarla a una base real; las siete deben devolver cero filas.

No crea tablas, así que no hay RLS nueva que activar.

### 5. Lo que se evaluó y no se restringió

| Tabla | Por qué no |
|---|---|
| `exchange_rates` | Una observación se conserva con su republicación (ADR 0020): repetir un par y una fecha es historia, no un duplicado. |
| `regulatory_requirements`, `national_transpositions`, `compliance_evidence` | Qué cuenta como «el mismo requisito» es una decisión de producto (ADR 0014, 0019, 0021), no una columna. |
| `external_api_costs`, `audit_log`, `events` | Son registros de hechos: cada fila es un hecho aunque se parezca a otra. |
| `approvals` | Una por decisión por construcción, y se resuelve con compare-and-set (ADR 0011). |
| `pipeline_steps`, `jobs.idempotency_key`, `users.email/subject`, `roles.name`, `memory_records` | Ya tienen su restricción. |

## Consecuencias

- La clase de error «dos filas donde el código supone una» pasa de «posible bajo carga» a «imposible»; un camino nuevo que
  se salte los guardias recibe un error de la base de datos en lugar de un saldo partido.
- **Estas restricciones son de este repositorio: no se han aplicado a Supabase.** La migración (y las dos anteriores,
  `c4e9a7d21f58` y `d7a3c5e91b24`) se aplicarán después, bajo el procedimiento separado y con aprobación expresa,
  ejecutando antes las siete consultas de solo lectura.
- Un test de la fase anterior asumía que una referencia liquidada podía reservarse otra vez; se reescribió a la semántica
  nueva. Otro asumía que los lectores toleraban filas duplicadas del interruptor; ahora lo que se prueba es que la base no las
  admite.
- Si alguna base real tuviera duplicados, la migración se niega y hay que limpiarlos a mano: es el coste de no tocar datos.

## Alternativas descartadas

- **Solo locks de aplicación**: ya estaban, y no cubren a quien se los salta (ni lo que hoy aún no existe).
- **Desduplicar dentro de la migración** («quedarse con la fila más antigua»): decide por una persona qué dinero cuenta.
- **Una restricción única de `(budget_id, type, reference)` en el libro**: impide la liquidación doble, pero también permite
  `COMMIT` tras `RELEASE`; son dos movimientos que se excluyen, y por eso hay un solo índice para las dos liquidaciones.
- **Reintentar silenciosamente ante la `IntegrityError`**: ocultaría una clave ajena rota como si fuera una carrera.
