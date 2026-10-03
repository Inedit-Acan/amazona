# ADR 0023: Una sola verdad presupuestaria — y la ausencia de información nunca es un permiso

- **Estado:** Aceptada
- **Fecha:** 2026-10-01
- **Depende de:** [ADR 0011](adr-0011-action-gate.md), [ADR 0015](adr-0015-multiple-real-sources-cost-and-usage-rights.md), [ADR 0022](adr-0022-idempotent-pipeline-run-creation.md)
- **Enmienda a:** [ADR 0011](adr-0011-action-gate.md) (el gate «recibe el veredicto del `BudgetEngine`»: desde ahora lo recibe del libro, con estados) y a lo que el Milestone 11 dejó escrito sobre el `BudgetState` en memoria
- **Milestone:** hardening pre-M44 (D12 y D14)

## Contexto

Había **dos presupuestos** y ninguno era del propietario.

- El orquestador del CEO decidía con un `BudgetState` **en memoria**, nuevo en cada petición y con
  un techo de 100 000 escrito en el código (`DEFAULT_BUDGET_HARD_LIMIT`). Cada solicitud se aprobaba
  contra el techo entero, porque el saldo en memoria nunca recordaba lo anterior.
- El `ActionGate` leía el libro de la base de datos (`budgets`, `budget_allocations`).

Medido sobre PostgreSQL, con un techo de 100 000: **tres solicitudes de 60 000 fueron aprobadas por
el CEO**, el libro acabó con 180 000 reservados y el gate vio −80 000 disponibles y denegó todo gasto.
El CEO decía sí y el gate decía no.

Y la ausencia de información aprobaba: sin fila de presupuesto, `BudgetSignal()` valía
`approved=True` («no hay límite que oponer»); con el importe ausente, también; y sin rol de quien
pide, el gate se saltaba la consulta de permisos aunque el `PermissionEngine` responda `DENIED` a un
rol ausente. La ADR 0015 ya había descartado esa lectura para los costes de las APIs: *el presupuesto
no se hereda de ninguna parte*.

## Decisión

### 1. Una sola fuente: el libro de la base de datos

`BudgetLedgerService` (`budgets`, `budget_allocations`, `financial_events`) es la fuente de verdad
del saldo y del techo. El CEO, el `ActionGate`, el paso de marketing del pipeline y la aprobación
consultan y mueven ese libro; ninguno mantiene su propio saldo en memoria. `BudgetEngine` sigue siendo
la matemática pura (`assess_spend` la usa sobre una foto del libro), y `PermissionEngine` y el gate
siguen siendo componentes distintos: lo que se unifica es **el estado presupuestario**.

### 2. El presupuesto lo autoriza el propietario, y queda auditado

El sistema **no crea un presupuesto por su cuenta**. Solo `authorise_budget` crea o cambia el techo:

    AMAZONA_BOOTSTRAP=1 python -m app.cli authorise-budget --hard-limit 500 [--soft-limit 400]
    python -m app.cli show-budget

Es el mismo patrón que `grant-role` (ADR 0007): dinero y poder del propietario no se conceden por un
endpoint HTTP. Cada autorización deja `budget.authorise` en la auditoría con el antes y el después.
`DEFAULT_BUDGET_HARD_LIMIT` desaparece: nadie puede gastar contra un límite que nadie autorizó.
La configuración (`Settings`) define políticas de funcionamiento, **no** el techo ni el saldo.

### 3. Qué dice el presupuesto de un gasto

`assess_spend` (función pura, como `evaluate_action` y `evaluate_api_call`) devuelve un estado:

| Estado | Cuándo | ¿Aprueba? |
|---|---|---|
| `NOT_APPLICABLE` | la acción no gasta | sí |
| `ZERO_COST` | coste conocido y cero (aunque el presupuesto esté agotado) | sí |
| `AVAILABLE` | hay presupuesto autorizado y el importe cabe | sí |
| `EXHAUSTED` | hay presupuesto autorizado y no cabe | **no** |
| `NO_BUDGET_RECORD` | es un gasto y no hay presupuesto autorizado | **no** |
| `UNKNOWN_COST` | es un gasto y no se sabe lo que cuesta (o es negativo) | **no** |
| `SIMULATED_NO_BUDGET` | no hay presupuesto autorizado pero todo el despliegue es simulado | sí, declarado |
| `NOT_EVALUATED` | nadie lo evaluó (valor por defecto de la señal del gate) | **no** |

No existe `NO_LIMIT_CONFIGURED`: `budgets.hard_limit` es obligatorio y el modelo no admite un
presupuesto sin techo. Si algún día se admitiera, sería un estado propio y no equivaldría a `ALLOW`.
Que exista un presupuesto autorizado manda **también en simulación**: la simulación relaja la
*ausencia* de presupuesto, nunca un techo que sí existe.

### 4. «Simulación» es una sola cosa

`Settings.operating_in_simulation`: todos los proveedores efectivos son `MOCK` (producto, proveedores,
regulatorio, publicidad, marketplaces, tipos de cambio y derecho nacional) **y** el entorno no es
`staging` ni `production`. De ahí dependen tres reglas, y no hay otra definición:

| Regla | En simulación | Fuera de ella |
|---|---|---|
| Gasto sin presupuesto autorizado | pasa, como `SIMULATED_NO_BUDGET` | `NO_BUDGET_RECORD`: deniega |
| Solicitante sin rol | no hay permisos que consultar, como siempre | `DENIED`: no saber quién pide no es un permiso |
| `Idempotency-Key` de [ADR 0022](adr-0022-idempotent-pipeline-run-creation.md) | opcional | obligatoria |

Un gasto de coste desconocido se deniega siempre, también en simulación.

### 5. Reservar es comprobar y escribir en una sola sentencia

    UPDATE budget_allocations SET reserved = reserved + :a
     WHERE id = :id AND hard_limit - reserved - committed >= :a

Evaluar primero y reservar después dejaba que dos peticiones a la vez vieran el mismo saldo libre.
Ahora, de N solicitudes que no caben juntas, solo las que caben tocan una fila. El CEO reserva al
pedir la aprobación (con el id de la aprobación generado antes, para no dejar una aprobación sin
reserva); el pipeline reserva **en la misma transacción que consume la autorización y arranca el
paso**, completa con `COMMIT` y, si el paso no llega a ejecutar nada, libera. Un reintento no duplica
la reserva (`idempotent=True`, una reserva viva por paso) y no se compara contra la suya propia.

### 6. Lo que no cambia

El Decision Engine, `opportunity_score`, la matemática de `BudgetEngine`, el `PermissionEngine` y el
orden de la regla del gate. Sin migración: las tablas son las mismas.

## Consecuencias

**A favor**

- No existe un universo donde el CEO diga sí y el gate diga no: miden el mismo libro. Con un techo de
  100 000, dos solicitudes de 60 000 no caben juntas venga la segunda por el CEO o por el pipeline, y
  tampoco si llegan a la vez (probado sobre PostgreSQL).
- Un gasto real sin presupuesto autorizado, sin importe o sin saber quién lo pide, se deniega.

**En contra**

- **Sin presupuesto autorizado no hay libro que mover**: en simulación el CEO y el pipeline siguen
  funcionando, pero sin reservas ni gastos registrados, y el panel de finanzas muestra ceros hasta que
  el propietario autorice uno. Es honesto, pero cambia lo que se ve.
- **No hay pantalla ni endpoint para autorizar el presupuesto**: es un comando en la máquina que tiene
  la base de datos. Es deliberado (ver 2) y queda pendiente decidir una interfaz.
- **Un paso que falla tras reservar deja su reserva viva** (un fallo no se convierte en un cero): hace
  falta una forma humana de liberarla. *Resuelto en la [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md)*:
  una reserva se libera sola solo si se sabe que la petición no salió o que el proveedor confirmó que no hubo efecto, y
  si no se sabe la cierra una persona con `resolve-action`.
- `budgets.name` no tenía restricción única en la base. *Resuelto en la [ADR 0026](adr-0026-database-identity-guards.md)*:
  hay restricciones únicas para el presupuesto, su saldo, el interruptor del pipeline, los movimientos del libro y las
  preguntas pendientes; y el techo debe ser un número finito, en céntimos y no superior a 10 000 000.

## Antes del primer proveedor de pago real

Un presupuesto autorizado en cada entorno real; el medio para liberar reservas huérfanas y una clave
idempotente hacia el proveedor, estable entre reintentos ([ADR 0011](adr-0011-action-gate.md),
enmienda) —ambos ya resueltos en la [ADR 0024](adr-0024-external-actions-lifecycle-and-unknown-outcome.md)—; y que los adaptadores que ejecuten acciones declaren su coste (`0` con procedencia, o un
importe) en lugar de dejarlo en `None`.

## Enmienda (Milestone 45): el ingreso tiene su propio registro; el margen es una lectura

El libro de presupuesto (`budgets`, `financial_events`) **sigue siendo la única fuente del gasto** y no se amplía con ingresos: sus
importes son `Numeric(12,2)` sin moneda y su unicidad es «una reserva y una liquidación por referencia», incompatible con la identidad
de un ingreso (un `PaymentEvent`) y con la regla de no convertir divisas. Los ingresos verificados viven en el registro de la
[ADR 0030](adr-0030-verified-revenue-ledger.md). El **margen** de un pedido será una proyección de lectura que combine ambas fuentes y
solo se calcule con pedido, cobro verificado y gasto confirmado y conocido, todos en EUR; si no, «Sin datos». Un gasto desconocido
no es 0, y como el libro de presupuesto no guarda moneda, ningún margen se afirma fuera de EUR. *(Decidido en la ADR 0030; no cambia
ninguna regla de este ADR.)*
