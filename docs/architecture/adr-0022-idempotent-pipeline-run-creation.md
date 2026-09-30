# ADR 0022: `Idempotency-Key` en `POST /api/pipeline/runs` — repetir una petición no crea otra ejecución

- **Estado:** Aceptada (fase 1)
- **Fecha:** 2026-10-01
- **Depende de:** [ADR 0009](adr-0009-async-job-runtime.md), [ADR 0010](adr-0010-async-resumable-pipeline.md), [ADR 0011](adr-0011-action-gate.md)
- **Milestone:** hardening pre-M44 (D11)

## Contexto

Repetir `POST /api/pipeline/runs` tras un timeout, un doble clic o un reintento de red
creaba otra ejecución completa: **dos peticiones idénticas, con la misma cabecera
`Idempotency-Key`, dejaban dos ejecuciones y dos trabajos** (medido; con el código anterior,
tres peticiones con la misma clave y un cuerpo distinto en la tercera dejaban tres).

La infraestructura existía: `Job.idempotency_key` es única, y `JobQueue.enqueue` ya devuelve
el trabajo existente ante una clave repetida y resuelve la carrera. Pero la puerta HTTP no la
usaba: ni leía la cabecera, ni la clave del trabajo se podía repetir, porque se derivaba del
id de la ejecución **recién creada** (`pipeline-run:{run.id}`). Esa clave protege la relación
ejecución↔trabajo, no la petición.

Hoy los proveedores son simulados y un duplicado no le hace nada a nadie. Con un proveedor real
—gasto, una llamada con efecto— una petición repetida por timeout sería una acción repetida.

## Decisión

### 1. La clave del cliente es la clave del trabajo, con un espacio de nombres

`Idempotency-Key: <valor>` (1–128 caracteres de `A-Za-z0-9._:-`). La clave con la que se guarda es
`pipeline-run:<huella de quien pide>:<valor>`. El espacio de nombres hace que la misma clave de dos
personas no sea la misma clave, y que una clave de esta operación no choque con la de otro tipo de
trabajo ni con las derivadas del id de una ejecución (`pipeline-run:<uuid>`, que sin clave del cliente
siguen siendo la clave del trabajo).

### 2. La petición se identifica por una huella canónica

`PipelineRequest.payload_hash()` es el SHA-256 del JSON canónico de la petición **lógica** (campos
ordenados, valores por defecto ya aplicados): enviar el cuerpo con los campos en otro orden, o con
explícito un valor que valía lo de siempre, es la misma petición. La huella se guarda en el
`payload` del trabajo (`request_hash`); no hay columna nueva.

| Situación | Resultado |
|---|---|
| misma clave, misma petición | la ejecución original, `202`, cabecera `Idempotency-Replayed: true`; no se crea ni se ejecuta nada |
| misma clave, otra petición | `409` («esta clave ya se usó con otra petición»); no se filtra la ejecución ajena |
| clave distinta | petición distinta |
| reintento de algo ya aceptado con el kill switch apagado | la ejecución original (el kill switch solo bloquea peticiones **nuevas**: `423`) |

### 3. La garantía es de la base de datos

No es «consultar antes de insertar». El trabajo, con su clave única, es **lo primero que se
escribe** en la transacción de la petición; la ejecución, sus pasos y la auditoría se crean después y
se confirman juntos. De dos peticiones simultáneas con la misma clave, el `INSERT` del trabajo solo
triunfa una vez: la otra espera a que la primera confirme, falla por la restricción única, y se queda
con la ejecución ganadora.

`JobQueue.enqueue` ganó `commit=False` (el trabajo se crea dentro de la transacción de quien llama) y,
en PostgreSQL, hace ese `INSERT` dentro de un `SAVEPOINT` que se abre **antes** de añadir el trabajo
(`begin_nested()` vuelca lo pendiente). Antes, perder la carrera hacía `rollback()` de **toda** la
transacción, y habría arrastrado la ejecución que quien llama acababa de añadir. Con SQLite (los tests)
no se usan savepoints: su driver no los maneja bien y allí no hay carreras entre procesos.

### 4. Cuándo la clave es obligatoria (y por qué no es «estamos en producción»)

Es obligatoria (`428 Precondition Required`) si la operación puede tener un efecto fuera del sistema:

- **siempre en `staging` y `production`**, donde no se admite suponer que todo es simulado;
- **en cualquier entorno si algún proveedor efectivo no es `MOCK`** (`SANDBOX`, `REAL` o `COMPOSITE`:
  producto, proveedores, regulatorio, publicidad, marketplaces, tipos de cambio y derecho nacional).

Solo `development`, `test` y `demo` con **todos** los proveedores `MOCK` pueden omitirla, y entonces cada
petición es una ejecución nueva: crear un duplicado simulado no le hace nada a nadie. Es
`Settings.idempotency_key_required`; el entorno no es la regla, es uno de sus dos motivos.

## Consecuencias

**A favor**

- Un reintento, un doble clic o un timeout dejan de poder ejecutar el pipeline dos veces.
- Sin migración: la unicidad ya existía en `jobs.idempotency_key` y la huella vive en su `payload`.
- El arreglo del `SAVEPOINT` beneficia a cualquier otro que encole con clave desde una transacción
  que ya lleve trabajo pendiente.

**En contra**

- Un cliente que no envíe la clave seguirá creando duplicados **mientras todo sea simulado**. Es
  deliberado y está dicho en la documentación del endpoint, pero es un duplicado permitido.
- La huella vive en el `payload` (JSON) del trabajo y no en una columna: no se puede indexar ni
  consultar por ella. No hace falta hoy (se busca por clave, que es única).
- Una clave ya usada no caduca.

## Pendiente

- **Fase 2, con migración (aprobación aparte):** una tabla `idempotency_keys` genérica (clave, ámbito,
  huella, referencia al recurso) para las rutas **síncronas** que ejecutan adaptadores
  (`/api/research/runs`, `/api/sourcing/runs`, `…`): sin trabajo no hay dónde guardar la clave.
  Hasta entonces, repetir esas peticiones sigue creando ejecuciones nuevas.
- **Antes del primer adaptador que ejecute acciones reales:** una clave idempotente **hacia el
  proveedor**, estable entre reintentos (por ejemplo derivada de la ejecución y el paso), para que una
  acción remota no se duplique aunque se autorice dos veces ([ADR 0011](adr-0011-action-gate.md),
  enmienda).
