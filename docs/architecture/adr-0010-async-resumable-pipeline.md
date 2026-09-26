# ADR 0010: Pipeline asíncrono y reanudable

- **Estado:** Aceptada
- **Fecha:** 2026-09-26
- **Depende de:** [ADR 0005](adr-0005-fase-3-pipeline-orchestrator.md), [ADR 0006](adr-0006-pipeline-human-controls.md), [ADR 0009](adr-0009-async-job-runtime.md)
- **Milestone:** 32

## Contexto

El `PipelineOrchestrator` de la ADR 0005 encadena los nueve pasos de Fase 3
**dentro de la petición HTTP**. Eso tiene tres consecuencias que el plan maestro
(§6 y §21) pide cerrar:

1. **Un fallo a mitad no deja nada reanudable.** Cada servicio compromete su
   propia transacción, así que un `RuntimeError` en el paso 5 deja cuatro pasos
   de trabajo real en la base de datos y ninguna fila que diga que existen: el
   `steps` de `pipeline_runs` se escribía **al final**, y si no hay final no hay
   `steps`. Lo que queda es huérfano y nadie lo encuentra.
2. **No hay forma de parar ni de continuar.** Ni cancelar una ejecución en
   marcha, ni reintentar el paso que falló, ni seguir por donde iba.
3. **El navegador espera.** Y cuando un paso sea una llamada externa lenta —que
   es adónde va esto— esperar dejará de ser una molestia para ser imposible.

El Milestone 31 (ADR 0009) construyó el runtime que faltaba: trabajos en
PostgreSQL, reintentos con espera, arriendos, cancelación y una bitácora. Falta
usarlo.

## Decisión

### 1. Un trabajo por ejecución, no uno por paso

Una ejecución del pipeline es **un** trabajo `pipeline.run`. Su manejador recorre
los nueve pasos, **salta los que ya están COMPLETED** y late entre paso y paso.

La alternativa —un trabajo por paso, encadenados— se descarta por dos motivos.
El primero es una ventana nueva: entre comprometer el paso N y encolar el N+1
hay un instante en el que un corte deja la ejecución parada sin que nada lo diga,
y taparlo pide un vigilante que hoy no existe. El segundo es más simple: nueve
filas por ejecución en la cola convierten el panel en ruido y reparten la
historia de una misma ejecución entre nueve bitácoras.

Con un solo trabajo, **reanudar es reencolar ese mismo trabajo**
(`JobQueue.requeue`), así que sus intentos y su bitácora son la historia
completa, en un sitio.

### 2. Los pasos son filas, y son la única verdad

`pipeline_runs.steps` (JSON) **desaparece**. Cada paso es una fila de
`pipeline_steps` que se escribe cuando el paso empieza y cuando termina, y cada
pasada por un paso es una fila de `pipeline_step_attempts` —el `PipelineAttempt`
del plan maestro §21— con el trabajo que lo intentó y su error.

Mantener el JSON *y* las filas sería tener la misma verdad en dos sitios, que es
exactamente lo que la ADR 0009 §1 rechaza para la cola. La API **sigue
devolviendo** el mismo `steps` de siempre: se reconstruye desde las filas.

Una aclaración que importa: en ese JSON, `status` significa el estado de
**negocio** del paso (el listing quedó `BLOCKED`, el CFO `CRITICAL`) y es lo que
`assess_pipeline_run` lee para decidir si hace falta revisión humana (ADR 0006
§2). El estado de **ejecución** del paso es una pregunta distinta y viaja aparte,
en `step_status`. Mezclarlos habría roto la evaluación de riesgo en silencio.

La migración convierte el JSON existente en filas antes de borrar la columna, y
el `downgrade` lo reconstruye. Ninguna ejecución ya registrada pierde
información en ninguno de los dos sentidos; lo que sí se pierde es lo que nunca
se guardó: las ejecuciones anteriores no anotaron sus parámetros de negocio
(precio de venta, región de destino), así que **no se pueden reanudar**, y la
aplicación lo dice en vez de inventar un precio.

### 3. `PARTIAL` y `FAILED` dejan de ser lo mismo

Hasta ahora, «research no encontró candidatos» y «economics reventó» acababan
igual. Son cosas distintas y ahora se distinguen:

- **`PARTIAL`** es un resultado de negocio: un paso no pudo entregar nada al
  siguiente. No se reintenta solo —volver a preguntar lo mismo daría lo mismo—,
  los pasos restantes quedan `SKIPPED`, y sigue disparando revisión humana como
  en la ADR 0006.
- **`FAILED`** es un fallo técnico: el paso lanzó. El runtime lo reintenta con
  espera exponencial y, al reintentar, la ejecución continúa por el paso que
  falló en vez de empezar de cero.

Consecuencia práctica: una ejecución en `FAILED` cuyo trabajo está en `RETRYING`
se va a arreglar sola; una en `FAILED` cuyo trabajo está en `FAILED` necesita a
alguien. El panel Estado dice cuál es cuál.

### 4. Reanudar y reintentar un paso son la misma operación

`POST /api/pipeline/runs/{correlation_id}/resume` continúa por el primer paso que
no esté `COMPLETED` —que es justamente el que falló—. Con `from_step` se fuerza
el punto de partida: ese paso y los siguientes se rehacen aunque ya hubieran
terminado, porque su resultado depende del que se va a rehacer. Eso cubre el
«retry step» del plan maestro §21 sin una segunda ruta que hiciera casi lo mismo.

Lo único que nunca se puede es pisar una ejecución que un worker tiene entre
manos: eso es un 409.

Cancelar (`/cancel`) marca la ejecución y cancela su trabajo. Una ejecución en
marcha se entera en su siguiente latido —entre dos pasos—, deja el paso en curso
en `CANCELLED` y **no toca los que no habían empezado**: siguen en `PENDING`, que
es lo que permite reanudarla después sin repetir nada.

### 5. El kill switch apagado deja el trabajo en `BLOCKED`, no en `FAILED`

La ADR 0006 §3 consulta el switch antes de tocar cualquier servicio. Con el
pipeline asíncrono eso son dos momentos: al encolar (423 en el acto, como
siempre) y al ejecutar, porque entre uno y otro puede pasar tiempo.

Si está apagado cuando le toca el turno, el trabajo queda en `BLOCKED`: el
runtime no lo reclama, **no gasta intentos**, y vuelve cuando un operador
reactiva el switch y alguien lo reencola. La `JobStatus.BLOCKED` de la ADR 0009
ya nombraba el kill switch como su motivo; esto es su primer uso real, adelantado
respecto al Milestone 33, que la usará para sus propias condiciones (veto legal,
presupuesto agotado).

El mecanismo es un `JobBlockedError` que el manejador lanza y el worker traduce
a `JobQueue.block()`. Se pone en el worker y no en el manejador porque es el
worker quien sabe su propio nombre, que es lo que hace que la transición
compruebe que el trabajo sigue siendo suyo —igual que `complete()` y `fail()`—.

Las dos alternativas se descartan por lo mismo: **agotar los intentos de golpe**
(quedaría en `FAILED`, etiquetando de fallo técnico la decisión deliberada de un
operador) y **reintentar con espera** (haría ruido en la bitácora por algo que
solo arregla una persona).

## Consecuencias

**A favor**

- Un fallo a mitad deja cuatro pasos hechos y visibles, y continuar no los
  repite. Es la diferencia entre perder el trabajo y no perderlo.
- El navegador no espera: `POST /api/pipeline/runs` responde 202 en
  milisegundos.
- La historia de una ejecución está en un sitio: sus pasos, sus intentos por
  paso, y los intentos y la bitácora del trabajo que la ejecutó.
- Cada paso conserva su `correlation_id` propio (ADR 0005) y la auditoría de
  negocio se cruza con la del runtime por el `correlation_id` de la ejecución,
  que es el del trabajo.

**En contra**

- **Cambio de contrato**: `POST /api/pipeline/runs` ya no devuelve la ejecución
  terminada, sino una en `QUEUED`. Quien la llamaba esperando resultados tiene
  que consultar después. En el repositorio no había ningún consumidor —el
  Control Center nunca llamó a esa ruta—, pero es una rotura y hay que decirlo.
- **El latido solo ocurre entre pasos.** Un paso que tarde más que el arriendo
  (60 s por defecto) se dará por muerto y otro worker lo repetirá. Hoy los nueve
  son simulados y tardan milisegundos; cuando uno sea una llamada externa lenta
  hará falta un arriendo por tipo de trabajo, que el runtime todavía no tiene.
- **Un trabajo por ejecución** significa que los nueve pasos corren en el mismo
  worker, uno detrás de otro. No hay paralelismo dentro de una ejecución (no lo
  habría igualmente: cada paso necesita el id del anterior), pero tampoco puede
  repartirse una ejecución entre varios workers.
- **Una ejecución que agota sus intentos no genera revisión.** La evaluación de
  riesgo de la ADR 0006 corre al cerrar en `COMPLETED` o `PARTIAL`; un fallo
  técnico definitivo se ve como trabajo agotado en el panel y se reanuda, no se
  revisa. Si algún día debe entrar en la bandeja, es un cambio consciente.

## Alternativas descartadas

- **Un trabajo por paso, encadenados.** §1: una ventana nueva y nueve bitácoras
  por ejecución.
- **Conservar `pipeline_runs.steps` junto a las filas.** Dos verdades que se
  desincronizan; además obligaría a escribir el JSON en cada paso para que no
  mintiera, que es hacer el trabajo dos veces.
- **Mantener además un modo síncrono opcional** para no romper el contrato.
  Rechazada: dos caminos de ejecución con semánticas distintas de fallo y
  reanudación es exactamente la clase de duplicado que luego nadie mantiene, y
  el plan maestro §6 es explícito en que los pipelines largos no deben correr
  dentro del request.
- **Reutilizar `Job.payload` como estado del pipeline** en vez de tablas nuevas.
  Rechazada: el payload es la entrada del trabajo, no su progreso, y consultarlo
  («¿qué ejecuciones se quedaron en legal?») sería leer JSON de una tabla de
  infraestructura.
