# Milestone 45 — Reconciliación programada, registro de ingresos verificados y pantallas sin dinero inventado

**Fecha:** 02-10-2026 → 04-10-2026 · **ADR:** [0029](../architecture/adr-0029-scheduled-reconciliation-and-unknown-outcome-authority.md)
· [0030](../architecture/adr-0030-verified-revenue-ledger.md) · **Enmienda a:**
[0009](../architecture/adr-0009-async-job-runtime.md)
· [0023](../architecture/adr-0023-single-budget-source-and-absence-is-not-permission.md)
· [0024](../architecture/adr-0024-external-actions-lifecycle-and-unknown-outcome.md)
· [0028](../architecture/adr-0028-orders-payments-fulfilment-core.md) · **Depende de:**
[0003](../architecture/adr-0003-rls-deny-by-default.md)
· [0011](../architecture/adr-0011-action-gate.md)
· [0025](../architecture/adr-0025-generic-idempotency-for-synchronous-routes.md)
· [0026](../architecture/adr-0026-database-identity-guards.md)

**Presupuesto: 0 €. Ninguna cuenta, credencial, pasarela, proveedor ni transportista reales.** Ninguna prueba sale de la máquina
(una guarda de `tests/conftest.py` lo hace cumplir). **Supabase no se ha modificado:** las migraciones de M44 y de este milestone
no están aplicadas en ella (§«Estado de Supabase»).

## La regla

**Una cifra de dinero sale de un hecho que el backend registró, o dice que no hay dato. Nunca de un generador, nunca de una
constante, y un error de lectura no es un dato.** M44 dejó el dinero bien guardado pero mal contado: cuatro pantallas
enseñaban pedidos y beneficios inventados. M45 hace tres cosas, en este orden: **(1)** programa lo que mira los estados que
pueden bloquear dinero cuando nadie está mirando, sin que ningún tick cierre jamás un resultado desconocido a ciegas;
**(2)** construye una proyección inmutable de los hechos de pago verificados, el *registro de ingresos verificados*;
**(3)** hace que Panel, Finanzas y Proyectos lean eso, o digan «Sin datos» y por qué.

Y una cuarta regla, de vocabulario, que atraviesa todo: **«Registro verificado» no es «real».** Un hecho de pago verificado no
es una transacción comercial real; puede pertenecer a un pedido simulado. Hasta que exista una procedencia estructurada, ninguna
pantalla afirma que el dinero sea real.

## Qué se construyó

14 commits sobre `c60b0e4` (el cierre de M44; 12 de código o ADR y 2 arreglos documentales), cada uno publicado con su CI revisado
job por job y **todos en `success`**. **137 ficheros, +19 141 / −4 142
líneas**: sólo **35 ficheros / 2 824 líneas son de `backend/app`** (el código del producto); **42 ficheros / 8 559 líneas son
pruebas del backend**. M45 es, sobre todo, la prueba de que lo que ya existía se comporta como dice.

| # | Commit | Qué |
|---|---|---|
| 1 | `d78e8f6` | fix (P2-1): perder una carrera sobre una acción externa en cobros y reembolsos es un 409 de dominio, nunca un 500 |
| 2 | `354b80f` | fix (P3-12): la consola informa de un evento de proveedor rechazado con un error limpio, no con un *traceback* |
| 3 | `2d59204` | fix (P2-2): Operaciones pagina los pedidos por cursor y **dice cuándo trunca** |
| 4 | `584f60f` | **ADR 0029**: reconciliación programada y quién puede cerrar qué |
| 5 | `acfaf25` | reconciliación programada **dentro del worker**, con tope de intentos y sin cerrar jamás un desconocido a ciegas (el propietario fusionó los commits 5, 6 y 7 *del plan original*: servicios, disparador y pruebas) |
| 6 | `b094277` | **ADR 0030**: el registro de ingresos verificados |
| 7 | `b2200de` | el **registro de ingresos verificados**: una proyección inmutable de los hechos de pago verificados |
| 8 | `46e2922` | agregados de **solo lectura** del registro (`/api/revenue/summary`, `/series`, `/entries`) |
| 9 | `d109342` | **Panel**: lee el registro y tiene un estado vacío honesto |
| 10 | `0db0dd4` | **Finanzas**: hecho registrado, coste declarado y proyección, en tres zonas sin aritmética entre ellas |
| 11 | `38fdacd` | **Proyectos**: sólo proyectos reales del backend, sin pedidos inventados |
| 12 | `815b094` | invariantes de punta a punta, caos y mutaciones; y los errores de lectura que encontraron |
| — | `be81776`, `b4b2890` | dos arreglos de `system-overview.md` (los reconciliadores ya están programados) |
| 13 | este | `docs: milestone 45` (sólo documentación) |

Numeración: el plan de la fase 0 eran 16 commits; tras fusionar los tres de la reconciliación quedan los 13 de arriba (más los dos
arreglos documentales). Los dos commits de `docs: ADR` (4 y 6) van **antes** del código que deciden, como en M44.

### Lo nuevo, de un vistazo

- **3 migraciones** (cadena: `… → b3c8f1a5d742` [M44] → `d7e2a9c4f1b8` → `c4e8b1d9a273` → `e5a1d7c93b04`): campos de proceso de
  `payment_events` para la reconciliación; la tabla `revenue_ledger_entries` (con trigger *append-only* y restricciones
  compuestas); y el índice de las lecturas de agregados.
- **4 rutas de lectura** (`business.read`): `GET /api/revenue/summary`, `/series`, `/entries` y `GET /api/reconciliation/status`.
- **3 tipos de trabajo recurrente** en el worker: `reconcile.actions` (cada 5 min, umbral de 15), `reconcile.payment_events`
  (cada 2 min, umbral de 5, **tope de 5 intentos automáticos por evento**) y `reconcile.report` (solo lectura). Se apagan con
  `reconciliation_enabled`.
- **2 módulos**: `app/reconciliation/` y `app/revenue/`; y `app/jobs/recurring.py`.
- **1 comando de consola nuevo**: `retry-payment-event`.
- **Frontend**: Panel, Finanzas y Proyectos reescritos sobre datos verificados; Operaciones pagina. Se **borran** `lib/cfo-view.ts`,
  `lib/demo/cfo.ts`, `lib/demo/projects.ts`, `lib/finance.ts` y sus pruebas: 0 pantallas dependen ya de pedidos generados.

## Qué es real, qué es simulado y qué sigue pendiente

| | Hoy |
|---|---|
| **Real** | El dominio de M44; la reconciliación programada; el registro de ingresos (inmutable, idempotente, atómico con el evento que lo causa); los agregados; la reconciliación en solo lectura (`check_ledger`); las tres pantallas leyendo el backend; todo probado sobre PostgreSQL |
| **Simulado** | La pasarela (`simulated-payments`), el proveedor y el envío (`simulated-fulfilment`). Un evento simulado se firma con una clave **efímera por proceso** y entra por la misma puerta que un webhook real: por eso **un humano no puede firmar uno desde fuera**, y por eso la prueba manual usa la consola (`simulate-payment`, que corre dentro del proceso) |
| **Declarado** | El coste de una línea de pedido (una cotización o una persona lo declaran; nadie ha comprobado el pago). Nunca se llama beneficio |
| **PLAN** | Lo que el modelo económico y el especialista de finanzas del Director ejecutivo *esperan*. No ha ocurrido. Sin símbolo de moneda en Proyectos, porque la evidencia no declara moneda |
| **Todavía demo** | Parte del Panel (agentes en curso, decisiones y oportunidades de ejemplo, **etiquetadas «Demo»**): 33 módulos del frontend siguen en el trinquete `demo-boundary` |
| **No existe** | Pasarela, proveedor y transportista reales; checkout, clientes, RGPD; IVA/OSS, facturas, contabilidad; beneficio neto, EBITDA, caja; conversión de divisas; seguimiento de envíos; devoluciones físicas |

## Decisiones arquitectónicas de M45

Cada una con su origen (ADR o decisión del propietario) y su consecuencia comprobable.

| Decisión | Dónde | Consecuencia |
|---|---|---|
| **Un `UNKNOWN_OUTCOME` solo lo cierra información**: una consulta autoritativa, una respuesta tardía o una persona. Ningún tick | ADR 0029 §7 | El barrido marca `CALLING → UNKNOWN_OUTCOME` y **conserva la reserva**; nunca libera lo que pudo salir. Probado con 1, 3 y 10 pasadas y edades de 1 s y de un año |
| **La reconciliación vive dentro del worker**, no en un proceso aparte | ADR 0029 §2 | «No hay un proceso que alguien pueda olvidar arrancar». `reconciliation_enabled=false` devuelve el comportamiento de M44 |
| **Tope de 5 intentos por evento y sin estados nuevos**: un evento que llega al tope sigue `RECEIVED` y queda visible para una persona | ADR 0029 §6 | Un evento venenoso no bloquea el lote ni se «cierra» a la fuerza |
| **El `lookup` de los simuladores no es autoritativo** (es memoria de proceso) y no cierra nada | ADR 0029 §7 | Un worker es otro proceso que la API: su `lookup` leería «no existe» y liberaría la reserva |
| **Sin valor por defecto para el techo de una llamada externa** con proveedores reales; un valor *provisional y no contractual* solo con proveedores simulados | ADR 0029 §3 | Con un proveedor de escritura real, el arranque falla hasta que alguien lo declare |
| **El registro de ingresos es una proyección, no una segunda fuente de verdad**: cada entrada nombra el `PaymentEvent` que la causó | ADR 0030 §2 | Una entrada por evento (`UNIQUE`), una `CAPTURE` por cobro y un `REFUND` por reembolso, en **la misma transacción** que el cambio de estado |
| **Es inmutable** (trigger *append-only*: `UPDATE`, `DELETE` y `TRUNCATE` se rechazan) | ADR 0030 §8 | `LedgerWatch` lo comprueba además *a lo largo del tiempo* |
| **No es el libro contable ni fiscal de KOVA** | ADR 0030 §1 y §17 | No hay margen, beneficio, coste, impuestos, IVA/OSS, caja ni comisiones en ninguna respuesta; cada una dice que no es contabilidad |
| **`CONFLICT` y `UNMATCHED` con dinero no generan entrada**, y se enseñan aparte como *evidencia pendiente* | ADR 0030 D1 | No se oculta el movimiento ni se cuenta como ingreso |
| **Un reembolso hereda la clasificación de la captura que revierte** (restricción compuesta en la base) | ADR 0030 D2 | Devolver un duplicado reduce el dinero en revisión, nunca el ingreso |
| **Multimoneda exacta por moneda; solo EUR se consolida**; las demás se declaran «no agregables» | ADR 0030 D3 | Una moneda nunca se suma ni se convierte en otra |
| **Un agregado se calcula en lectura, sobre texto exacto (`Decimal`), nunca `float`** | ADR 0030, enmienda del Commit 10 | Sumas exactas verificadas sobre 990 000 entradas (resumen de 30 días 126 → 12 ms) |
| **La etiqueta «REAL» se retira: pasa a «Registro verificado»** | propietario, 03-10 | Un hecho verificado no es una transacción real; pendiente de una procedencia estructurada |
| **`check_ledger` es una auditoría completa y lineal («A pura»)**, sin caché | propietario, 03-10 | Criterio de reevaluación: una caché limitada al `GET` si pasa de ~1 s de forma sostenida con datos reales |
| **Finanzas en tres zonas sin aritmética entre ellas** (registro verificado · declarado · PLAN) | propietario, 04-10 | La procedencia es un **tipo** (`Verified`/`Declared`/`Planned`): sumar un hecho con una proyección no compila |
| **Margen de contribución declarado: solo con cobertura de coste del 100 %** y en EUR | propietario, 04-10 | Una línea sin coste no vale cero: deja el pedido sin margen, y el agregado en «Sin datos» con su motivo |
| **11 tarjetas DEMO adicionales del CFO retiradas** (caja, runway, impuestos, tesorería, cuentas…) | propietario, 04-10 | «Prefiero un CFO más reducido pero basado en información defendible» |
| **Producto ≠ Proyecto; «Beneficio real» por proyecto retirado; sin tope de 12 productos** | propietario, 04-10 | Un pedido puede llevar varios productos y no hay regla aprobada de reparto: repartir el ingreso sería inventarlo |
| **La proyección PLAN va sin símbolo de moneda y sin total** mientras `finance_validation` no declare moneda; **el id real del proyecto es su identificador visible** | propietario, 04-10 | Nada se suma con nada; no hay códigos derivados de la posición en una lista |
| **Un error de lectura no es un dato**: «No se pudo leer» (`UNREAD`) es distinto de «Sin datos» | Commit 12 | Un proyecto cuya decisión no se pudo leer ya no dice «sin decisión»; un análisis sin leer bloquea el total del PLAN |
| **Una arquitectura de pruebas con oráculo independiente** | Commit 12 | El oráculo del registro no importa el código que prueba; cada frase del encargo apunta a su prueba y falla si desaparece |

## Verlo funcionar

La **primera prueba integral local** recorre, a mano y paso a paso, toda la cadena —arranque → investigación y decisión → pedido →
cobro simulado y verificado → registro de ingresos → fulfillment → reconciliación → Panel → Finanzas → Proyectos— con lo que debe
observarse en cada pantalla y qué resultado es PASS o FAIL:

**[`milestone-45-integral-test.md`](milestone-45-integral-test.md)**

Se ensayó entera el 04-10-2026 contra una base PostgreSQL local desechable (borrada al terminar), con las salidas y las cifras
que el guion fija. **Nunca la apuntes a Supabase.** La misma cadena está además automatizada en
`backend/tests/integration/test_m45_end_to_end.py`.

## Verificación

- **CI del último commit de código (`815b094`, run `37216329429`)**: Backend **4229 pasadas, 7 omitidas, 1 warning** (566 s) y
  Control Center **642/642** con build de 20 páginas. Ningún paso de ningún job fuera de `success`. (Cierre de M44: 3 517 pruebas.)
- **Las 7 omitidas** son la variante `[sqlite]` de pruebas que solo tienen sentido en PostgreSQL (carreras entre reconciliadores,
  `TRUNCATE`, suma exacta de importes enormes…); su variante `[postgres]` **se ejecuta y pasa** en el CI.
- **Migraciones sobre PostgreSQL limpio**: 43 revisiones hasta `e5a1d7c93b04`, en el CI y en el ensayo manual.
- **Mutaciones**: **22/22** de backend y **14/14** de frontend detectadas. Dos sobrevivieron a la primera pasada y eran huecos
  reales de la batería (una caída tras la frontera de durabilidad con el barrido programado; y el tope del reembolso, que tiene
  tres capas y una la absorbe otra); cerrados con prueba.
- **Una caminata aleatoria con el oráculo del registro tras cada paso** (40 semillas en SQLite y 10 en PostgreSQL), una tormenta
  de 5 hilos concurrentes, y los eventos en los seis órdenes posibles.
- Las pruebas que fijan cada frase están en `backend/tests/integration/test_m45_coverage_map.py` y en
  [`pre-m44-invariants-and-chaos-tests.md`](../architecture/pre-m44-invariants-and-chaos-tests.md).

## Llamadas externas y coste

**0 €.** Ninguna llamada de red a un tercero: los adaptadores de pago y fulfillment son simulados y la guarda de `conftest.py`
rechaza (y hace fallar al test) cualquier conexión que no sea a `127.0.0.0/8`, `::1` o un socket de Unix. El **gasto acumulado del
proyecto sigue en 0 €**: ninguna cuenta, ninguna credencial, ningún proveedor de pago, abastecimiento o transporte contratado.

## Estado de Supabase

**Intacto: 12 migraciones, la última `20260917114106`.** Su base sigue en la revisión `ebc8b88725e2` (M14) y el repositorio tiene
**43 revisiones** hasta `e5a1d7c93b04`: **le faltan 24**, de las cuales **3 son de M45** y el resto de M29–M44 (incluida la de
RLS `9f2b6c0a1d47`). Es decir, **todo el núcleo de pedidos, cobros, reembolsos, fulfillment, reconciliación y registro de ingresos
no existe en la base real.** El procedimiento (la «Fase B») está escrito y se ensayó en local con éxito en documentos locales del propietario que **no están
versionados**; **no se ha ejecutado y requiere autorización expresa** porque escribe en la base real. M45 no lo abre.

## Lo que NO se verificó

- **Nada contra un proveedor real, ni contra Supabase, ni con autenticación real** (en `development` los `GET` están abiertos; las
  rutas de dinero requieren `business.read`).
- **El orquestador del CEO sobre PostgreSQL** se ejercitó en el recorrido automatizado y en el ensayo manual, pero **no** con el
  worker corriendo durante horas: los trabajos recurrentes se probaron con relojes controlados y con la edad de las filas, no con
  el paso real del tiempo.
- **El volumen**: el rendimiento de los agregados se midió con 990 000 entradas; el CFO agregado, en cambio, **carga como mucho 300
  pedidos y 1 000 entradas** y lo dice (debe sustituirse por agregados de backend si el volumen real lo exige).
- **La carga de la caminata en CI**: ~97 pruebas más en el CI; el tiempo del backend pasó de ~9 a ~9,4 min.

## Desviaciones y decisiones de interpretación

- **Los commits 5, 6 y 7 del plan se fusionaron en uno** (decisión del propietario): servicios, disparador y pruebas de reconciliación.
- **El Commit 12 (pruebas y mutaciones) encontró, y corrigió, defectos de la propia M45** (§siguiente): por eso toca frontend,
  que el plan no preveía para un commit de pruebas.
- **Los scripts de mutaciones no están en el repositorio**: editan `backend/app` y no deben correr en el CI. Se conservan fuera,
  y su reproducción está descrita en el handoff local del Commit 12 (no versionado).
- **Dashboard conserva paneles de demostración** (etiquetados «Demo») que no son dinero; lo que sí es dinero sale del registro.

## Defectos corregidos durante el milestone

| Defecto | Dónde se halló | Corrección |
|---|---|---|
| **P2-1** — `ExternalActionStateError` sin tratamiento HTTP en cobros y reembolsos: una carrera daba un 500 | auditoría de M44 | `d78e8f6`: 409 de dominio |
| **P3-12** — `simulate-payment` con un `--event-id` repetido imprimía un *traceback* | documentación de M44 | `354b80f`: error limpio y código de salida 3 |
| **P2-2** — Operaciones leía como mucho 500 pedidos sin avisar | auditoría de M44 | `2d59204`: cursor y `has_more` |
| **Un error de lectura se convertía en un dato**: `.catch(() => [])` en Proyectos y Finanzas (un proyecto sin decisión *leída* decía «sin decisión»; el CFO decía «ningún producto tiene análisis») | invariantes del Commit 12 | `815b094`: «No se pudo leer», lo ya cargado se conserva, el total PLAN se bloquea |
| **La tarjeta «Cartera» de Proyectos mezclaba hechos y una columna PLAN bajo un solo «Verificado»** | frontera transversal del Commit 12 | `815b094`: lleva las dos etiquetas |
| **`test_m44_architecture.py` llevaba 5 bytes 0x08 desde M44** (sus `\b` eran retrocesos): una guarda de arquitectura que apenas casaba nada, sin ningún error | Commit 12 | `815b094` + una prueba que vigila todo el árbol de fuentes |

Ningún defecto hallado por las invariantes fue un fallo del dinero verificado, de las reconciliaciones ni de los agregados.

## Limitaciones conocidas y deuda

Clasificación al cierre. **No hay ningún P0**: no se conoce ningún defecto que pierda o duplique dinero, permita un efecto externo
repetido, cierre un resultado desconocido a ciegas, o exponga datos personales.

### P1 — bloquean conectar nada real

| ID | Hallazgo |
|---|---|
| P1-1 | **No existe ningún adaptador real de pago ni de fulfillment.** `staging` y `production` no arrancan sin ellos (intencionado) |
| P1-2 | **Falta una procedencia estructurada SIMULATED / REAL** en los hechos financieros. Hoy `Order.is_simulated` existe en el pedido, pero el registro no la guarda, y por eso ninguna pantalla puede decir «real». Antes de conectar una pasarela debe poder distinguirse `VERIFIED_SIMULATED`, `VERIFIED_NON_SIMULATED`, `DECLARED`, `PLAN` y `DEMO` |
| P1-3 | **Las condiciones de la ADR 0029 antes del primer proveedor real**: declarar el techo de una llamada externa y un `lookup` autoritativo en el adaptador. Hoy ninguno lo declara y `ExternalActionService.reconcile()` no lo llama ningún código de producción |
| P1-4 | **Supabase no tiene M44 ni M45** (§«Estado de Supabase»). Hasta aplicar la Fase B, ninguna prueba contra la base real puede recorrer un pedido |

### P2

| ID | Hallazgo |
|---|---|
| P2-1 | **`finance_validation` no declara moneda.** Por eso la proyección de Proyectos va sin símbolo y sin total; cuando la declare, podrá denominarse y sumarse |
| P2-2 | **El CFO agregado depende del conjunto cargado** (300 pedidos, 1 000 entradas): un pedido antiguo cobrado hoy puede quedar fuera, y entonces su coste es «desconocido» (no cero) y el agregado se bloquea diciendo por qué. Sustituir por agregados de backend si el volumen lo justifica |
| P2-3 | **Ningún dato une un proyecto con un pedido ni con un producto**, ni existe una regla aprobada para repartir el ingreso de un pedido con varias líneas. Sin ello, Proyectos **no puede** mostrar ingresos. Requiere un modelo de relación y, después, esa regla |
| P2-4 | **El gasto no es legible**: `financial_events` no guarda moneda y no tiene ruta de lectura; `ExternalAction.amount` tampoco. Sin él no hay beneficio, EBITDA ni caja posibles |
| P2-5 | **El Panel conserva 9 lecturas silenciosas** (`.catch(() => [])`: agentes, ejecuciones, aprobaciones, revisiones y, por producto, proveedores, economía, legal, tienda y campañas). No son dinero, pero «0 aprobaciones pendientes» cuando la lectura falló es engañoso. Un trinquete fija el número y solo puede bajar |
| P2-6 | Un cobro `OPEN` solo se cierra por evento del proveedor (no hay `payment.cancel` ni caducidad) — heredado de M44 |
| P2-7 | Un reembolso `SENDING` sin confirmar se marca `refund_unconfirmed` tras 1 h, pero nada lo reconcilia — heredado de M44 |
| P2-8 | El webhook no tiene limitación de frecuencia ni lista de IPs — heredado de M44 |
| P2-9 | Sin bandeja de aprobación de pedidos (`REQUIRE_APPROVAL` devuelve 409) y sin formularios de pedido/cobro/fulfillment en el Control Center — heredado de M44 |
| P2-10 | **Un canal desconocido en `POST /api/economics/runs` da un 500**, no un 422 (`UnknownChannelError` sin tratamiento HTTP). Hallado al ensayar el guion; es de M40 |
| P2-11 | `ProjectOut` no expone `created_at`: el inicio de un proyecto solo se conoce por la auditoría (`project.created`) y, sin ella, es «Sin datos» |

### P3

| ID | Hallazgo |
|---|---|
| P3-1 | `GET /api/audit` devuelve como mucho 500 entradas por correlación: una ejecución con más podría dejar fuera un `task.completed` (la fecha saldría «Sin datos», nunca inventada) |
| P3-2 | Proyectos hace tres peticiones por proyecto: con decenas de proyectos habrá que paginar o pedir agregados |
| P3-3 | **Textos que dicen más de lo que saben**: Operaciones llama «Dinero realmente cobrado» a lo cobrado en simulación (y suma duplicados y discrepancias, así que **no coincide con el ingreso verificado del Panel**: es lo esperado, pero conviene renombrarlo); la tarjeta de decisión de Proyectos imprime la puntuación de oportunidad en bruto («1», en escala 0–1) |
| P3-4 | El aviso de backend caído del Control Center está en inglés («Could not reach the AMAZONA backend») |
| P3-5 | `lib/product-channels.ts` conserva tres exportaciones huérfanas (`loadProductOperationsData` y compañía); `projectCodeFor` se sigue llamando «código de proyecto» y habla de productos |
| P3-6 | `check_ledger` recorre todo el registro (3–4 s con 1 M de entradas) cada 5 minutos y en cada `GET /api/reconciliation/status` — decidido («A pura»), con criterio de reevaluación |
| P3-7 | Los scripts de mutaciones viven fuera del repositorio |
| P3-8 | Heredados de M44, sin cambios: P3-1 a P3-11 de [`milestone-44-demo.md`](milestone-44-demo.md) (claves sin índice, índices redundantes, `alembic check` con deriva, `float` en el libro de presupuesto, sin entorno de DOM, intenciones por pestaña…) y 200 ficheros sin `ruff format` |
| P3-9 | Avisos del CI ajenos al código: `StarletteDeprecationWarning` de httpx (`httpx2`), `MODULE_TYPELESS_PACKAGE_JSON` de las pruebas del frontend, Node 20 del runner |

## Decisiones del propietario durante el milestone

1. **02-10:** P2-1 y P2-2 se corrigen en M45, con `fix:` propios; Dashboard, CFO y Proyectos pasan a datos reales con un libro de ingresos.
2. **03-10 (ADR 0029):** los commits 5, 6 y 7 se fusionan; un desconocido solo lo cierra información; `check_ledger` «A pura».
3. **03-10 (ADR 0030):** D1 evidencia pendiente visible sin ser ingreso; D2 el reembolso hereda la clasificación; D3 margen solo en EUR y
   con coste confirmado; D4 módulo `app/revenue/` y nombre «Registro de ingresos verificados» (**no** el libro contable de KOVA).
4. **03-10:** la etiqueta «REAL» se retira; `Order.is_simulated` se registra como hallazgo, **sin** convertir «verificado» en «real».
5. **04-10 (Finanzas):** tres zonas sin aritmética entre ellas; retirar las 11 tarjetas DEMO adicionales; cobertura parcial visible;
   límite de 300 pedidos como deuda explícita.
6. **04-10 (Proyectos):** retirar «Beneficio real»; producto ≠ proyecto; sin tope de 12 productos; proyección PLAN sin moneda ni total;
   id real como identificador visible.
7. **04-10:** pushes autorizados uno a uno y CI revisado job por job antes de seguir.

## Criterios de salida de M45

Los fijados en la fase 0 y su estado:

| Criterio | Estado |
|---|---|
| Ningún estado que pueda bloquear dinero queda sin un reconciliador programado que lo mire o lo haga visible | ✔ — salvo lo declarado a propósito: un cobro `OPEN` y un reembolso `SENDING` sin confirmar (P2-6, P2-7), y la consulta autoritativa (P1-3) |
| Ningún `UNKNOWN_OUTCOME` se cierra sin información | ✔ — probado en el recorrido, en la caminata, en el caos y en las mutaciones |
| Todo ingreso o reembolso del registro tiene un `PaymentEvent` verificado y cuadra con `payments` | ✔ — oráculo independiente tras cada paso de la caminata |
| Ninguna pantalla muestra un pedido inexistente ni un importe inventado | ✔ para el dinero de Panel, Finanzas y Proyectos; **Panel conserva paneles «Demo»** que no son dinero |
| CI verde en cada commit | ✔ — 14 de 14 (verificado con `gh run list`) |
| Supabase intacta · 0 € gastados | ✔ · ✔ |

## Bloqueos antes de conectar algo real

- **Una prueba contra Supabase real:** aplicar la Fase B (24 revisiones), con autorización expresa, copia previa y el procedimiento ya
  ensayado. Hasta entonces no existe en esa base ni un pedido, ni un cobro, ni el registro.
- **Un proveedor o una pasarela reales:** P1-1, P1-2 y P1-3; derechos, coste y política de gasto escritos antes de la primera llamada
  (ADR 0015); consulta autoritativa; `payment.cancel` o caducidad; limitación del webhook; observabilidad de `attention_required`.
- **El primer euro real:** todo lo anterior, un presupuesto autorizado por el propietario (`authorise-budget`), reconciliación probada
  contra el sandbox del proveedor, y la autorización expresa del propietario para ese primer gasto. Hoy no se cumple ninguno.

## Qué queda fuera de M45, expresamente

Web pública KOVA, carrito, checkout y cuentas de cliente; pasarela, proveedor o transportista reales; datos personales (RGPD);
IVA/OSS, facturas y contabilidad; beneficio neto, EBITDA y caja; conversión de divisas; devoluciones físicas y seguimiento de envíos;
la relación producto ↔ proyecto y el reparto del ingreso; la procedencia estructurada SIMULATED/REAL; la Fase B de Supabase; y las
lecturas silenciosas del Panel operativo. Son M46 o posteriores.
