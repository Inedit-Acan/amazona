# Milestone 31 — Async Job Runtime

**Fecha:** 26-09-2026 · **ADR:** [0009](../architecture/adr-0009-async-job-runtime.md)
· **Anterior:** [Milestone 29.1](milestone-29-1-read-authorization.md)

Primera fase P1 del plan maestro (§6 y §32). Objetivo: que el trabajo largo deje
de vivir dentro de la petición HTTP y pase a un runtime que se puede reintentar,
cancelar, observar y reanudar.

Como pide el §32, **no se migra el pipeline todavía** —eso es el Milestone 32—:
aquí se construye el runtime y se pone a ejecutar una tarea de verdad.

---

## Qué cambia

### El runtime

1. **Tres tablas.** `jobs` (la cola y la fuente de verdad), `job_attempts` (cada
   pasada por un worker, con su error) y `job_events` (bitácora de solo añadir).
2. **PostgreSQL es la cola**, con `SELECT … FOR UPDATE SKIP LOCKED`. Reclamar el
   trabajo y registrar el intento ocurren en la misma transacción.
3. **Los nueve estados** del plan maestro. `WAITING_APPROVAL` y `BLOCKED` ya
   existen y el runtime sabe que **no son suyos**: no los reclama. Los usará el
   Milestone 33.
4. **Reintentos con espera exponencial** (5 s, 10 s, 20 s… con techo de 10 min),
   guardada en `available_at`: no hace falta ningún temporizador aparte.
5. **Idempotencia**: encolar dos veces con la misma clave devuelve el mismo
   trabajo. Es lo que hace seguro reintentar una petición HTTP cuyo resultado no
   se conoce.
6. **Arriendos**: un trabajo reclamado lleva worker y caducidad. El latido lo
   extiende; un arriendo vencido es un worker muerto y el segador lo devuelve a
   la cola. Sin tabla `Worker` y sin que los workers se vigilen entre ellos.
7. **Cancelación** que llega a un trabajo en marcha por su siguiente latido, y
   **el resultado de un worker zombi se descarta** en vez de pisar lo que hizo su
   sustituto.
8. **La cola de mensajes muertos es el estado `FAILED`**, y vaciarla es
   `POST /api/jobs/{id}/requeue`.

### El worker

```bash
python -m app.jobs.worker          # bucle
python -m app.jobs.worker --once   # trata un trabajo y termina
```

Se pueden levantar varios. Cada vuelta libera reintentos vencidos, siega
arriendos muertos y reclama: el mantenimiento va **dentro** del bucle, así que no
hay un proceso aparte que alguien pueda olvidar arrancar.

### Los tipos de trabajo

- **`research.run`** — una investigación de producto de verdad, el mismo trabajo
  que `POST /api/research/runs` hace de forma síncrona. La diferencia es dónde
  ocurre: el navegador no espera y un fallo se reintenta.
- **`diagnostic.echo`** — devuelve su payload; con `{"fail": true}` falla a
  propósito. Sirve para comprobar el runtime de extremo a extremo en un
  despliegue recién levantado sin tocar datos de negocio.

### La API

`GET /api/jobs` · `GET /api/jobs/types` · `GET /api/jobs/{id}` (con sus intentos
y su bitácora) · `POST /api/jobs` · `POST /api/jobs/{id}/cancel` ·
`POST /api/jobs/{id}/requeue`.

Acción nueva `job.write`, que tienen OWNER, ADMIN, OPERATOR y SYSTEM. **Leer la
cola es `business.read`**: ver lo que hace el sistema no es lo mismo que hacerle
trabajar, así que VIEWER, ANALYST y REVIEWER miran pero no encolan.

### El panel Estado

Tarjeta «Runtime de trabajos»: contadores por estado, los últimos trabajos con
su tipo, intentos y error, y un veredicto en una línea. Un trabajo agotado pesa
más que una cola larga —una cola con trabajo es un sistema ocupado; un trabajo
agotado es trabajo que nadie terminará salvo que lo reencolen—.

Es **el único panel de esa pantalla sin datos de demostración**: o el backend
responde la cola o no se enseña nada. Una cola inventada diría que el sistema
está trabajando cuando no lo está.

## La desviación respecto al plan maestro

El objetivo 3 del §32 dice «Redis worker». **Redis no se usa.**

Con PostgreSQL como fuente de verdad —y tiene que serlo: el estado debe ser
durable, consultable y auditable, y `WAITING_APPROVAL`/`BLOCKED` son decisiones
de negocio— poner además la cola en Redis significa tener la misma verdad en dos
sitios, que es la forma más segura de que se desincronicen.

Lo que Redis aportaría es **menos latencia de arranque**: evitar el sondeo de 2
segundos. Cuando eso importe, entra como señal de despertar sin dejar de ser
PostgreSQL quien manda, y nada de lo construido aquí cambia. El razonamiento
completo está en la ADR 0009 §2.

## Probarlo

```bash
cd backend && alembic upgrade head

# En una terminal
python -m app.jobs.worker

# En otra: encolar y mirar
curl -X POST localhost:8000/api/jobs -H 'Content-Type: application/json' \
  -d '{"type":"research.run","payload":{"category":"electronics","max_results":3}}'
curl -s localhost:8000/api/jobs | python -m json.tool

# Comprobar los reintentos
curl -X POST localhost:8000/api/jobs -H 'Content-Type: application/json' \
  -d '{"type":"diagnostic.echo","payload":{"fail":true},"max_attempts":2}'
```

(En `development` no hace falta token; en `staging`/`production`, sí.)

## Verificación

- Backend: `ruff` y `mypy` limpios · **927 tests** (829 antes, +98).
- Frontend: `tsc` y `eslint` limpios · **249 tests** (237 antes, +12).
- **Humo de extremo a extremo con el worker real**: encolado → ejecutado →
  `COMPLETED` con 3 productos creados y el `correlation_id` como referencia;
  fallo → `RETRYING` con espera → `FAILED` al agotar intentos → reencolado a
  `QUEUED`.
- La migración se ejecuta de verdad en los tests, arriba y abajo, y hay un test
  que compara **columna a columna** el modelo contra la migración: es el
  desajuste clásico —añadir una columna al modelo y olvidarla en la migración—
  que en desarrollo no se nota porque los tests crean el esquema desde los
  modelos.
- El panel se comprobó en el navegador con un backend falso: el caso sin
  respuesta y el caso poblado, a 1280 y 1896 px.
- Los tests de inventario del Milestone 29 y 29.1 hicieron su trabajo: las seis
  rutas nuevas fallaron hasta darles su categoría.

## No verificado

- `alembic upgrade head` contra PostgreSQL: no hay Postgres en esta máquina. Lo
  cubre CI. **`SKIP LOCKED` solo actúa ahí**: en SQLite se ignora, así que la
  concurrencia real de dos workers está probada por construcción y por los tests
  de reclamo único, pero no contra PostgreSQL.
- Varios workers a la vez contra la misma base de datos real.

## Lo que queda abierto

1. **Milestone 32**: mover `PipelineOrchestrator` a trabajos, con cada paso
   persistido y reanudable.
2. **Milestone 33**: `ActionGate`, que es quien pondrá trabajos en
   `WAITING_APPROVAL` y `BLOCKED`.
3. **Sondeo**: 2 s de latencia de arranque. Redis como señal de despertar cuando
   haga falta (ADR 0009 §2).
4. **Sin prioridades**: un solo carril FIFO.
5. El latido no es automático; un manejador largo tiene que llamarlo.
