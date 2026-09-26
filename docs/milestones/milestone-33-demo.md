# Milestone 33 — Action Gate

**Fecha:** 26-09-2026 · **ADR:** [0011](../architecture/adr-0011-action-gate.md)
· **Anterior:** [Milestone 32](milestone-32-demo.md)

Tercera fase P1 del plan maestro (§7 y §32). El sistema deja de poder publicar,
anunciar o gastar sobre un `NO_GO`. Hasta hoy sí podía: lo único que lo impedía
era que los proveedores fueran simulados.

---

## Qué cambia

### La raya entre analizar y actuar

El plan maestro §7 separa las acciones que **no le hacen nada a nadie**
—investigar, cotizar, calcular márgenes, comprobar requisitos legales, agregar
finanzas— de las **nueve que sí**: publicar producto, activar publicidad, gastar,
comprar a un proveedor, pagar, enviar, reembolsar, cambiar un precio real y
enviar una comunicación contractual.

De los nueve pasos del pipeline, tres ejecutan una de esas nueve: `ecommerce` y
`marketplace` publican, y `marketing` activa publicidad **y** gasta el
presupuesto diario. Esos tres pasan por el gate. Los otros seis no, y siguen
corriendo pase lo que pase — la cadena **no se detiene para analizar**.

`operations` calcula hoy un plan de fulfillment y no envía nada, así que es
análisis. El día que envíe de verdad, entra en el mapa con `ship_order` y esa es
la única línea que hay que tocar.

### La regla

`app/gates/action_gate.py` es una función pura con las siete entradas del §7
—decisión económica, decisión legal, riesgo, presupuesto, aprobación humana,
permisos y entorno— y tres salidas. El orden es la decisión de fondo:

| | Situación | Resultado |
|---|---|---|
| **Vetos** | kill switch apagado · legal `NO_GO` · economía `NO_GO` si la acción gasta · presupuesto que no llega · permiso denegado · rechazo humano | `DENY` |
| **Firma** | una persona lo autorizó y no hay ningún veto | `ALLOW` |
| **Dudas** | legal o economía en `REVIEW` · economía `NO_GO` sobre algo que no gasta · rol que requiere aprobación · **cualquier gasto** en `staging` o `production` | `REQUIRE_APPROVAL` |
| | nada que objetar | `ALLOW` |

**Ninguna firma levanta un veto.** Está probado explícitamente, caso por caso: si
algún día alguien necesita saltarse uno, que cambie el veto en vez de firmarlo.

Las entradas las recoge `ActionGateService` de donde ya viven: el kill switch de
su tabla, el presupuesto con la matemática de `BudgetEngine`, el permiso de
`PermissionEngine`, el entorno de `Settings` y las recomendaciones de los pasos
de análisis de la propia ejecución. El gate decide; no calcula por su cuenta.

### Esperar a una persona

`REQUIRE_APPROVAL` deja el paso en `WAITING_APPROVAL` y **para el trabajo** en el
estado del mismo nombre, que el Milestone 31 reservó para esto y que nadie ponía
todavía. No gasta intentos: lo que falta no es tiempo. Resolver la petición
reencola el trabajo y la ejecución continúa por ese mismo paso, sin repetir nada
de lo anterior.

`BLOCKED` y `WAITING_APPROVAL` no son lo mismo y por eso son dos estados: uno
espera a que se arregle una condición, el otro a que alguien decida.

### Una sola bandeja

`pipeline_reviews` gana `kind` (`POST_HOC` | `ACTION_GATE`), `step` y `action`.
Las puertas del gate entran en la misma bandeja de `/approvals` que las
revisiones del Milestone 14, que ya sabía aprobar y rechazar.

Lo que cambia es el impacto, y la interfaz lo dice: aprobar una revisión post-hoc
no cambia nada de lo hecho, y aprobar una puerta **hace que la acción ocurra**.
Una autorización vale para el paso que la pidió: el siguiente paso con efecto
vuelve a preguntar.

### Denegar no es fallar

Un paso denegado queda en `DENIED` con sus motivos y no se reintenta — no hay
nada que el tiempo arregle. La ejecución llega al final con el análisis completo,
y la evaluación de riesgo de la ADR 0006 la manda a la bandeja post-hoc: que el
sistema haya impedido algo es justo lo que alguien tiene que mirar.

Cada evaluación queda auditada como `action_gate.allow`, `.deny` o
`.require_approval`, con sus motivos y el `correlation_id` de la ejecución.

### El panel Estado

La tarjeta Pipeline gana el contador «Esperando», el estado «Esperando
autorización» y una marca roja con las acciones que el gate no dejó ejecutar
(«2 denegadas», y al pasar el ratón, cuáles). El veredicto de una línea pone lo
que espera a una persona por delante de todo lo demás: nadie más lo va a mover.

## Lo que esto cambia en el día a día

**Muchas ejecuciones se paran ahora.** Con datos de demostración un `REVIEW`
legal o económico es frecuente, así que lo normal pasa a ser que una ejecución
espere autorización a mitad de camino. No es un efecto secundario: es lo que
pedía el §7. Pero cambia la sensación de usar el sistema y conviene saberlo antes
de abrir el panel y encontrarse la cola llena.

## Las desviaciones respecto al plan maestro

1. **Se reabren la ADR 0005 y la ADR 0006** en el punto que ambas dejaron
   previsto. Los tests que afirmaban que la cadena nunca se detiene ahora
   afirman que no se detiene **para analizar** y sí **para actuar**.
2. **«retry step» del §21 y las puertas del gate comparten ruta**: resolver una
   petición reanuda la ejecución por el paso que la pidió; no hay una segunda
   forma de continuar.
3. **Sin tabla de decisiones del gate.** El §27 (versionado de decisiones) pedirá
   algo así algún día; hoy la auditoría ya guarda actor, acción, recurso, motivos
   y correlación, y una tabla paralela sería el mismo registro dos veces.

## Probarlo

```bash
cd backend && alembic upgrade head
python -m app.jobs.worker   # en otra terminal

# Legal NO_GO de verdad (categoría restringida en la UE sin certificación):
# las tres acciones con efecto quedan DENIED y el análisis termina.
curl -X POST localhost:8000/api/pipeline/runs -H 'Content-Type: application/json' \
  -d '{"category":"accessories","sale_price":50.0,"destination_region":"mexico","market":"eu"}'

# Economía NO_GO: la ejecución se para y pide autorización.
curl -X POST localhost:8000/api/pipeline/runs -H 'Content-Type: application/json' \
  -d '{"category":"home","sale_price":0.5,"destination_region":"mexico"}'
curl -s localhost:8000/api/pipeline/reviews | python -m json.tool   # kind: ACTION_GATE
curl -X POST localhost:8000/api/pipeline/reviews/<id>/approve \
  -H 'Content-Type: application/json' -d '{"actor":"owner@amazona.local"}'

# Qué ha impedido el sistema, y por qué:
curl -s "localhost:8000/api/audit?correlation_id=<cid>" | python -m json.tool
```

## Verificación

- Backend: `ruff` y `mypy` limpios · **1069 tests** (991 antes, +78), de los
  cuales 40 son la tabla de la regla —`ALLOW`, `DENY`, `REQUIRE_APPROVAL` por
  cada una de las nueve acciones, y que ninguna firma levante un veto— y 17 el
  recorrido completo dentro del pipeline.
- Frontend: `tsc` y `eslint` limpios · **272 tests** (262 antes, +10).
- `next build --webpack` en una copia del proyecto, sin tocar el `.next` de
  desarrollo. Las 20 rutas compilan.
- **Humo de extremo a extremo con el backend y el worker de verdad** (uvicorn +
  `python -m app.jobs.worker --once` como proceso aparte, base SQLite temporal),
  con las 27 comprobaciones en verde:
  - ejecución limpia → `COMPLETED` con tres `action_gate.allow` auditados;
  - legal `NO_GO` → tienda, marketplace y publicidad `DENIED`, análisis y CFO
    `COMPLETED`, tres `action_gate.deny` auditados y la ejecución en la bandeja
    post-hoc;
  - economía `NO_GO` → ejecución y trabajo en `WAITING_APPROVAL`, **sin gastar
    intentos**, con `awaiting_approval` en la bitácora, y el runtime no la vuelve
    a reclamar;
  - aprobar por HTTP → la ejecución vuelve a la cola sola, el paso se ejecuta y
    **el análisis no se repite** (mismos ids);
  - el siguiente paso con efecto **vuelve a preguntar**; rechazarlo lo deja
    `DENIED` y la cadena llega al final;
  - kill switch apagado → 423 al encolar.
- La migración se ejecuta de verdad en los tests, arriba y abajo: las revisiones
  que ya existían quedan marcadas `POST_HOC` —no como puertas sin resolver, que
  las metería en la bandeja pidiendo algo que nadie espera—.
- El panel se comprobó en el navegador con un backend falso: el contador
  «Esperando», el estado «Esperando autorización» y la marca «2 denegadas» con su
  explicación al pasar el ratón. Sin errores de consola.

## No verificado

- Lo de siempre y por lo de siempre (ver
  [system-overview §15](../architecture/system-overview.md#15-pendientes-de-integración)):
  PostgreSQL real, la conversión del JSON histórico sobre datos reales, la
  concurrencia de `SKIP LOCKED` y el login real. Ninguno bloquea este milestone.
- El gate **no se ha ejercido contra un servicio externo real**, porque todavía
  no hay ninguno conectado. Eso es exactamente el orden que pide el plan: la
  puerta antes que la conexión.

## Lo que queda abierto

1. **Una petición del gate no caduca.** Si nadie decide, la ejecución espera
   indefinidamente. Es deuda operativa reconocida y queda para un milestone
   posterior; no se resolvió aquí para no ampliar el alcance.
2. **Milestone 34**: arquitectura de adaptadores de Product Intelligence — el
   primer sitio donde el gate protegerá una llamada real.
3. **`operations` sigue siendo análisis.** Cuando envíe pedidos de verdad, entra
   en `STEP_SIDE_EFFECTS` con `ship_order`.
4. **El rol de quien pide** (`pipeline_runs.requested_by_role`) solo se rellena
   cuando la petición llega autenticada; en desarrollo suele ir vacío, y el gate
   lo trata como «no hay rol que consultar», que no es lo mismo que un rol sin
   permiso.
5. **Sin tabla de decisiones del gate** (§27 del plan): hoy vive en la auditoría.
