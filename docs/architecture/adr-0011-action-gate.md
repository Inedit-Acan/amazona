# ADR 0011: ActionGate — la raya entre analizar y actuar

- **Estado:** Aceptada
- **Fecha:** 2026-09-26
- **Depende de:** [ADR 0005](adr-0005-fase-3-pipeline-orchestrator.md), [ADR 0006](adr-0006-pipeline-human-controls.md), [ADR 0007](adr-0007-production-security.md), [ADR 0009](adr-0009-async-job-runtime.md), [ADR 0010](adr-0010-async-resumable-pipeline.md)
- **Milestone:** 33
- **Reabre:** ADR 0005 §Decisión y ADR 0006 §1 (la cadena no se detiene), exactamente en el caso que ambas dejaron previsto

## Contexto

La ADR 0005 decidió que el pipeline **nunca se detiene** ante un `NO_GO` o un
`BLOCKED` intermedio, y la ADR 0006 lo mantuvo con un argumento explícito: los
nueve pasos generan datos simulados, ninguno ejecuta una acción externa real, así
que no hay nada irreversible que un humano deba autorizar *durante* la ejecución.
Las dos anotaron la condición que lo cambiaría: **que un paso empiece a ejecutar
una acción externa real**.

El plan maestro §7 pide adelantarse a ese día. Separa **acciones de análisis**
—investigar, cotizar, calcular márgenes, comprobar requisitos, prever, simular,
comparar—, que pueden seguir aunque el resultado sea malo porque no le hacen nada
a nadie, de **acciones con efecto** —publicar, anunciar, gastar, comprar, pagar,
enviar, reembolsar, cambiar un precio, mandar una comunicación contractual—, que
no. Y pide un `ActionGate` que, dadas la decisión económica, la legal, el estado
de riesgo, el presupuesto, la aprobación humana, los permisos y el entorno,
responda `ALLOW`, `DENY` o `REQUIRE_APPROVAL`.

Investigación previa sobre el repositorio, para no duplicar lo que ya existe:

- **`PermissionEngine`** responde «¿puede este actor hacer X?». Es un eje
  distinto —quién— del que hace falta aquí —en qué estado está esto—, así que se
  **consulta** como una entrada más, no se sustituye ni se extiende.
- **`BudgetEngine`** ya sabe la matemática del presupuesto disponible. El gate
  recibe su veredicto; no reimplementa el cálculo.
- **`evaluate_decision`** (grafo CEO, Milestone 1) decide GO/NO_GO sobre un
  `Objective`. No conoce `PipelineRun` ni acciones externas: otro dominio.
- **`PipelineKillSwitch`** ya para ejecuciones nuevas (ADR 0006 §3) y, desde el
  Milestone 32, también las que le llegan a un worker.
- **`JobStatus.WAITING_APPROVAL`** existe desde el Milestone 31 y **nadie lo
  ponía**: se reservó precisamente para esto.

## Decisión

### 1. La cadena sigue sin detenerse para analizar, y se detiene para actuar

Se matiza la ADR 0005: los pasos de análisis siguen corriendo pase lo que pase
—un `NO_GO` económico no impide comprobar la legalidad ni agregar finanzas—, y
los tres pasos que hoy ejecutan una acción con efecto (`ecommerce` y
`marketplace` publican, `marketing` activa publicidad y gasta) pasan por el gate
antes de ejecutarse.

Se hace **ahora**, con los proveedores todavía simulados, y no cuando lleguen los
adaptadores reales. Un gate que nunca ha parado nada es un gate que nadie sabe si
para: el día que se conecte el primer servicio de gasto sería la primera vez que
se ejerce, y esa es exactamente la primera vez que no puede fallar.

Que el proveedor sea simulado **no rebaja ningún veto**. La simulación es una
propiedad del despliegue de hoy, no una autorización.

### 2. La regla es una función pura, y los vetos ganan

`evaluate_action` (`app/gates/action_gate.py`) no toca la base de datos: recibe
las siete entradas del §7 y devuelve la decisión con sus motivos. Quien las
recoge es `ActionGateService`. Es la misma separación que ya existe entre
`decision_engine.py` y el orquestador (ADR 0001) y entre `review.py` y el
pipeline (ADR 0006), y es lo que permite que las seis situaciones que el plan
exige probar sean una tabla de casos.

El orden de la regla es la decisión de fondo:

1. **Vetos**: kill switch apagado, `NO_GO` legal, `NO_GO` económico sobre una
   acción que gasta, presupuesto que no llega, permiso denegado y rechazo humano
   explícito.
2. **La autorización humana**, que solo actúa si no ha tropezado con un veto.
3. **Dudas**: `REVIEW` legal o económico, un `NO_GO` económico sobre algo que no
   gasta, un rol que requiere aprobación, y cualquier gasto en `staging` o
   `production` (plan maestro §33: todavía no hay autonomía económica).
4. Si no queda nada que objetar, `ALLOW`.

**Ninguna firma levanta un veto.** Si algún día alguien necesita saltarse uno,
que cambie el veto y quede escrito, en vez de que exista una puerta trasera que
se usa «solo esta vez».

### 3. Esperar a una persona es un estado del trabajo, no el final de la ejecución

`REQUIRE_APPROVAL` deja el paso en `WAITING_APPROVAL`, pide la autorización y
para el trabajo en `JobStatus.WAITING_APPROVAL` mediante `JobQueue.hold_for_approval()`
—hermano de `block()` (Milestone 32) y con el mismo principio: **no gasta
intentos**, porque lo que falta no es tiempo—. Resolver la petición reencola el
trabajo y la ejecución continúa por ese mismo paso, con todo lo anterior intacto.

Distinguir `BLOCKED` de `WAITING_APPROVAL` no es cosmético: uno espera a que se
arregle una condición y el otro a que alguien decida, y solo el segundo aparece
cuando se pregunta «¿qué está esperando a que yo diga algo?».

### 4. Una sola bandeja: `PipelineReview` gana una clase

En vez de una tabla nueva, `pipeline_reviews` gana `kind` (`POST_HOC` |
`ACTION_GATE`), `step` y `action`. Las revisiones del Milestone 14 siguen siendo
lo que eran; las puertas del gate entran en la **misma** bandeja de
`/approvals`, que ya existe, ya sabe aprobar y rechazar y ya está auditada.

La diferencia que sí importa está en lo que hace resolverlas: una revisión
post-hoc es una anotación sobre algo ya ocurrido, y una puerta **mueve la
ejecución** —aprobar la continúa, rechazar deja ese paso denegado y la cadena
sigue—. La interfaz lo dice con todas las letras en el impacto de cada botón.

Una autorización vale para el paso que la pidió y para nada más: el siguiente
paso con efecto vuelve a preguntar. Es lo mismo que ya hacía `Approval` en el
grafo del CEO —autorizar una acción concreta, no conceder un permiso general—.

### 5. Denegar no es fallar

Un paso denegado queda en `DENIED`, con sus motivos, y **no se reintenta**: no
hay nada que el tiempo arregle. La ejecución llega hasta el final con sus pasos
de análisis completos, y la evaluación de riesgo de la ADR 0006 la manda a la
bandeja post-hoc: que el sistema haya impedido algo es justo lo que alguien tiene
que mirar.

Cada evaluación con nombre y apellidos queda en la auditoría
(`action_gate.allow` / `.deny` / `.require_approval`, con los motivos y el
`correlation_id`). Un `DENY` sin rastro sería indistinguible de un fallo.

## Consecuencias

**A favor**

- El sistema ya no puede publicar ni gastar sobre un `NO_GO`. Antes podía, y solo
  lo impedía que los proveedores fueran simulados.
- La puerta existe **antes** que la conexión real: el Milestone 34 y siguientes
  añaden adaptadores contra un gate que ya está probado en uso.
- `WAITING_APPROVAL` deja de ser un estado decorativo del runtime.
- Las siete entradas del plan están todas, y cada una viene de la pieza que ya
  la sabía: kill switch, `BudgetEngine`, `PermissionEngine`, `Settings`, los
  pasos de análisis de la propia ejecución y la bandeja de aprobaciones.

**En contra**

- **Muchas ejecuciones se paran ahora.** Con datos de demostración, un `REVIEW`
  legal o económico es frecuente, así que lo normal pasa a ser que una ejecución
  espere autorización a mitad. Es lo que pedía el §7, pero cambia la sensación de
  usar el sistema y hay que decirlo.
- **Una ejecución puede esperar indefinidamente.** No hay caducidad de las
  peticiones del gate: si nadie decide, ahí se queda. Es deuda operativa
  reconocida y queda para un milestone posterior.
- **Dos clases en una tabla.** `pipeline_reviews` ya no es homogénea, y quien
  consulte la tabla tiene que mirar `kind`. Es el precio de tener una sola
  bandeja, y se pagó a sabiendas.
- **Reabre dos ADR.** Los tests de regresión que afirmaban que la cadena nunca se
  detiene se reescribieron para afirmar lo que ahora es verdad. Eso es correcto
  —la conducta cambió a propósito— pero significa que esa garantía ya no está
  vigente tal como se escribió en 2026-09-16.

## Alternativas descartadas

- **Modo sombra: evaluar y registrar sin bloquear** hasta que existan adaptadores
  reales. Rechazada por §1: un gate que nunca ha parado nada no se sabe si para.
- **Gate solo en la frontera de los adaptadores**, sin tocar el pipeline.
  Rechazada: deja el cableado pendiente justo para el momento en que importa, y
  hoy no habría nada que probar.
- **Tabla `action_approvals` propia.** Más limpia sobre el papel —son dos cosas
  distintas— y peor en la práctica: una segunda bandeja que vigilar, una segunda
  pantalla que mantener y dos sitios donde mirar antes de decidir.
- **Extender `PermissionEngine`** para que respondiera también por estado de
  negocio. Rechazada: mezclaría «quién puede» con «en qué estado está esto», que
  son ejes distintos; el gate consulta al motor de permisos, no lo absorbe.
- **Tabla `action_gate_decisions`.** La auditoría ya guarda actor, acción,
  recurso, motivos y `correlation_id`; una tabla paralela sería un segundo
  registro de lo mismo. Si algún día hacen falta preguntas analíticas sobre las
  denegaciones (plan maestro §27), se reabre.
