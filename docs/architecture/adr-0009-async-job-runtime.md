# ADR 0009: Runtime de trabajos asíncronos sobre PostgreSQL

- **Estado:** Aceptada
- **Fecha:** 2026-09-26
- **Depende de:** [ADR 0005](adr-0005-fase-3-pipeline-orchestrator.md), [ADR 0007](adr-0007-production-security.md)
- **Milestone:** 31

## Contexto

Hoy un pipeline entero se ejecuta **dentro de la petición HTTP**: el navegador
espera a que nueve agentes terminen, un fallo a mitad devuelve un 500 sin dejar
nada reanudable, y no hay forma de que el sistema trabaje cuando nadie mira. El
plan maestro lo pone como fase P1 y pide `Job`, `JobAttempt`, `Worker`, `Queue`
y `JobEvent`, con reintentos, idempotencia, timeout, cola de mensajes muertos,
cancelación, reanudación, latido y detección de worker muerto.

Investigación previa sobre el repositorio:

- **Redis está provisionado y no lo usa nadie.** Solo aparece como `redis_url`
  en `Settings` y una nota en `app/events/bus.py` sobre un adaptador futuro.
- **`app/tasks/` ya existe y es otra cosa.** Una `Task` es una unidad de trabajo
  del grafo del CEO (Milestone 1), con su propio `TaskStatus`. No es la unidad
  de ejecución que pide este milestone.
- El plan pide estados que **ninguna librería de colas modela**:
  `WAITING_APPROVAL` y `BLOCKED`, que son del dominio (una puerta humana, un
  veto legal) y no de la infraestructura.

## Decisión

### 1. PostgreSQL es la cola **y** la fuente de verdad

El estado de un trabajo tiene que ser durable, consultable y auditable de todos
modos: el panel Estado lo enseña, la auditoría lo referencia y `WAITING_APPROVAL`
y `BLOCKED` son decisiones de negocio que sobreviven a cualquier reinicio. Si ese
estado ya vive en PostgreSQL, **poner además la cola en Redis significa tener la
misma verdad en dos sitios** — y la forma más segura de que se desincronicen es
justamente esa.

Reclamar un trabajo es:

```sql
SELECT ... FROM jobs
WHERE status = 'QUEUED' AND available_at <= now()
ORDER BY available_at
LIMIT 1
FOR UPDATE SKIP LOCKED
```

`SKIP LOCKED` es el patrón estándar para esto desde PostgreSQL 9.5: dos workers
nunca se llevan la misma fila, y el que llega tarde se salta la bloqueada en vez
de esperarla. Reclamar el trabajo y escribir su intento ocurren en la **misma
transacción**, así que no existe el estado intermedio en el que un trabajo está
reclamado pero nadie ha registrado quién.

### 2. Redis no se usa en este milestone

Es una desviación explícita del objetivo 3 del plan maestro («Redis worker»), y
la razón es la de arriba: con PostgreSQL como fuente de verdad, Redis solo
aportaría **menos latencia de arranque** —evitar el sondeo— a cambio de una
pieza más que puede caerse, desincronizarse o quedarse con mensajes que la base
de datos no tiene.

El sondeo cuesta una consulta indexada cada dos segundos por worker. Cuando esa
latencia sea el problema, Redis entra como **señal de despertar** —un `PUBLISH`
al encolar que ahorra la espera— sin dejar de ser PostgreSQL quien manda. Eso no
invalida nada de lo construido aquí; por eso se puede posponer.

### 3. Sin Celery, RQ, arq ni Dramatiq

Todas ellas traen su propio modelo de trabajo, su propio estado y su propio
almacén. Como el nuestro tiene que existir igualmente, usarlas significaría
mantener dos máquinas de estados y sincronizarlas. El runtime propio son ~250
líneas con reintentos, arriendos, idempotencia y cancelación, todas las cuales
necesitábamos escribir de todos modos para casar con `WAITING_APPROVAL`,
`BLOCKED`, `correlation_id` y la auditoría.

### 4. El arriendo es el timeout y la detección de worker muerto

Un trabajo reclamado lleva `lease_worker` y `lease_expires_at`. Un manejador
largo llama a `heartbeat()` para extenderlo. Un arriendo vencido es un worker
muerto, y el segador lo devuelve a la cola.

Con eso **no hace falta una tabla `Worker`** ni que los workers se registren o se
vigilen entre ellos: basta con que un arriendo vencido sea recuperable. Es una
pieza menos que puede mentir.

El mismo mecanismo protege contra el worker zombi: `complete()` y `fail()`
comprueban que el trabajo sigue siendo suyo, así que un worker que resucita tarde
no puede pisar lo que hizo su sustituto.

### 5. La cola de mensajes muertos es un estado, no otra cola

Un trabajo que agota sus intentos queda en `FAILED`, con todas sus filas de
`JobAttempt` y su último error. Consultarla es `status=FAILED` y vaciarla es
`POST /api/jobs/{id}/requeue`. Una cola aparte solo añadiría otro sitio donde
mirar y otro del que las cosas se pueden perder.

### 6. Un tipo desconocido falla en el acto

No se reintenta tres veces: que nadie haya registrado ese manejador es un error
de despliegue, y esperar no lo arregla. La API además lo rechaza al encolar, para
que quien llama se entere en el momento en vez de que el trabajo muera en la
cola.

## Consecuencias

**A favor**

- Una sola fuente de verdad. El estado que ves en el panel es el estado real.
- Reclamo transaccional: no hay ventana entre reclamar y registrar.
- Cero infraestructura nueva. El worker es `python -m app.jobs.worker`.
- El mantenimiento va dentro del bucle del worker —liberar reintentos, segar
  arriendos—, así que no hay un proceso aparte que alguien pueda olvidar
  arrancar.

**En contra**

- **Sondeo**: hasta 2 segundos de latencia entre encolar y empezar. Aceptable
  para trabajos que duran segundos o minutos; si algún día importa, §2.
- **Carga en la base de datos**: una consulta indexada por worker cada 2 s. Con
  decenas de workers habría que revisarlo; con unos pocos es ruido.
- **Sin prioridades ni particiones**. Un solo carril FIFO por
  `available_at`. Añadir una columna de prioridad al índice de reclamo es
  barato cuando haga falta.
- El latido **no es automático**: un manejador largo tiene que llamarlo. Si no,
  el segador lo dará por muerto y lo reencolará. Está documentado en
  `JobContext`, y el arriendo por defecto (60 s) da margen.

## Alternativas descartadas

- **Redis como cola, PostgreSQL como historia.** §1: dos verdades.
- **Celery/RQ/arq.** §3: máquina de estados duplicada.
- **Tabla `Worker` con registro y latido propio.** §4: el arriendo ya responde
  la única pregunta que importa —¿sigue vivo quien tiene esto?— sin una tabla
  que mantener al día.
- **Ejecutar en `BackgroundTasks` de FastAPI.** Muere con el proceso, no es
  reanudable y no se puede observar: es exactamente el problema que hay hoy.
