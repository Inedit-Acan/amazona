# Milestone 42 — Tipos de cambio de referencia del BCE

**Fecha:** 30-09-2026 · **ADR:** [0020](../architecture/adr-0020-ecb-reference-exchange-rates.md)
· **Depende de:** [0008](../architecture/adr-0008-demo-production-isolation.md)
· [0009](../architecture/adr-0009-async-job-runtime.md)
· [0015](../architecture/adr-0015-multiple-real-sources-cost-and-usage-rights.md)
· [0017](../architecture/adr-0017-supplier-facts-and-risk.md)
· [0018](../architecture/adr-0018-money-conversion-and-not-evaluable.md)

**Presupuesto: 0 €. Ninguna cuenta, credencial ni servicio de pago.** Las únicas llamadas
externas reales son descargas anónimas y gratuitas de los ficheros XML públicos del BCE (ver
«Llamadas externas»).

## Lo que se encontró al revisar (29-09-2026)

- **El BCE dice que estas tasas no son para transacciones**: son «informativas» y su uso
  transaccional está «fuertemente desaconsejado». Aquí se usan para estimar un margen, y la
  advertencia viaja a la pantalla. No incluyen el diferencial de un banco.
- **Solo pares contra el euro y 29 divisas.** No hay `USD/GBP` ni `VND`. Nuestro catálogo
  admite 6 de las 29 (USD, GBP, CNY, HKD, MXN, PLN).
- **Publicación**: sobre las 16:00 CET los días TARGET. En 90 días (64 publicaciones) no falta
  ningún día laborable; el hueco máximo fue de 3 días (fin de semana).
- **Licencia**: uso libre citando al BCE y diciendo si se modifica el dato. Sin alta. No dice
  nada de retención, scoring ni ingestión por IA.
- **El fichero diario usa comillas simples y el de 90 días comillas dobles.** Se lee con un
  parser XML, no con expresiones regulares.
- **Un fallo latente del M40**: `CompositeExchangeRateProvider` devolvía la primera respuesta
  aunque estuviera caducada, así que una tasa manual de hace seis semanas tapaba una referencia
  de ayer y el análisis quedaba no evaluable con una tasa buena detrás.

## Qué cambia

| | |
|---|---|
| **Escritura** | `ExchangeRateFeed` (puerto), `EcbReferenceRateFeed` (`app/integrations/fx/ecb.py`), `FxRefreshService` (`app/money/fx_refresh.py`) |
| **Lectura** | `EcbExchangeRateProvider` (`app/money/ecb.py`): solo la base de datos |
| **API** | `POST /api/exchange-rates/refresh` y `/backfill` (`EXCHANGE_RATE_WRITE`: OWNER y ADMIN); el listado añade `ingested_at`, `attribution` y `notice` |
| **Trabajo** | `fx.refresh` (solo el fichero diario; se bloquea si no hay fuente real o presupuesto; reintenta si falla la red) |
| **Derechos y coste** | `ecb-reference-rates` en `usage_rights.py` y `costs/policy.py`, escritos antes de la primera llamada |
| **Interfaz** | «referencia BCE», fecha de ingestión, atribución y advertencia en las conversiones; el resumen de referencias BCE separado de las tasas declaradas |
| **Configuración** | `EXCHANGE_RATE_PROVIDER` (`mock` por defecto) y `ECB_RATE_MAX_AGE_DAYS` (7) |

### Las decisiones (ADR 0020)

- **El análisis no hace red.** Lee lo que el refresco guardó. Sin refresco no hay tasas nuevas.
- **La fecha efectiva no se toca.** La tasa del viernes usada el lunes es del viernes y tiene 3
  días. Fecha efectiva, fecha de ingestión, antigüedad y aceptabilidad son cuatro cosas.
- **Ventana por tasa**: 30 días para lo declarado a mano (M40 intacto), **7 días** para el BCE.
- **Precedencia manual > BCE > mock, solo entre fuentes aceptables.** El compuesto salta las
  caducadas y las del futuro; si ninguna vale devuelve la primera caducada para que se rechace
  con su motivo.
- **Identidad de una observación: `(par, fecha efectiva, fuente, tasa)`**, comparada con la más
  reciente. Misma observación → no se escribe. Otra tasa para el mismo par y fecha →
  republicación: fila nueva al lado, la más reciente gana, auditada. Sin restricción única
  sobre la tasa (impediría volver al valor A tras A → B). **No hay migración.**
- **Todo o nada.** Red, HTTP ≠ 200, cuerpo > 1 MB, no UTF-8, XML mal formado o con DTD, sin días,
  tasa ilegible o no positiva, moneda repetida, fecha futura, base ≠ EUR o ninguna moneda
  admitida → no se guarda nada ni se borra nada ni se dice «sin cambios».
- **El histórico de 90 días es recuperación explícita**: solo `backfill`, nunca respaldo
  automático del diario, ni desde el trabajo.
- **Solo divisas del catálogo**; las 23 restantes se listan en `omitted_currencies`. Sin ampliar
  el catálogo. **Sin cruces** (invariantes de `CROSS_VIA_EUR` escritos en la ADR §7).
- **`third_party_verified` ≠ cotizable**: un emisor con nombre sostiene la cifra.

## Qué es real y qué es demo

- **Real**: las referencias del BCE (fuente `ecb:eurofxref`, `third_party_verified`, emisor
  «European Central Bank»), su fecha, su ingestión y su auditoría.
- **Demo, sin cambios**: el fixture de tasas (`simulated`), que sigue detrás y solo donde la ADR
  0008 admite datos simulados. Con `EXCHANGE_RATE_PROVIDER=mock` las cifras son las de antes.

## Verificación

- **Backend**: `ruff` limpio; `mypy` limpio (219 ficheros); **2033 pruebas pasan** con `pytest`
  a secas (lo que corre CI) y con `python -m pytest`. **0 fallos** (tras la corrección de test anterior descrita abajo).
- **Frontend**: `tsc` y `eslint` limpios; **401 pruebas pasan, 0 fallan** (393 + 8 nuevas).
- **Build**: `next build --webpack` correcto, en copia sobre la misma unidad; la copia y su
  junction se retiraron y se comprobó que `node_modules` (513 entradas) y `.next` del propietario
  siguen ahí.
- **Pruebas nuevas** (unitarias y de integración): parseo de los dos XML reales (comillas simples
  y dobles, con el fin de semana), `Decimal`, XML malformado/vacío/DTD/duplicados/no positivos,
  cliente HTTP falso (User-Agent, medidor antes de la red, denegación sin red, 404/429/500/503,
  timeout, cuerpo enorme), derechos y coste, ventana por tasa, fin de semana con fecha original,
  compuesto que salta caducadas, idempotencia, republicación (A → B → A), auditoría, todo o nada
  (fallo de red, base, futuro, base ≠ EUR), histórico solo explícito, precedencia, mock idéntico,
  endpoints (200/409/429/502), trabajo (bloqueo, reintento, sin backfill), reserva del prefijo
  `ecb:` y el análisis económico de extremo a extremo (sin HTTP, referencia caducada → no
  evaluable, nunca `NO_GO`).
- **Inventarios**: `test_api_authorization.py` actualizado con las dos rutas nuevas
  (concretas y de plantilla). `test_api_read_authorization.py` y `test_permission_matrix.py` no
  cambian (no hay lecturas nuevas ni acciones nuevas). `lib/demo-boundary.test.ts` y
  `server-api-boundary.test.ts` pasan sin tocarse.
- **Migración**: **no hay.** No cambia ningún modelo ni ninguna columna; `alembic heads` sigue
  siendo `e5f8a2c1b7d4`. Por eso no hay «migración arriba y abajo».
- **Prueba de humo real** (esquema `create_all` en SQLite en memoria; nunca contra
  `backend/.env`): refresco diario → 6 guardadas, 23 omitidas, fecha efectiva 2026-09-29; segundo
  refresco → 0 guardadas, 6 sin cambios; histórico → 64 días, 378 nuevas y 6 sin cambios; 384
  filas; `100 USD → 88,0669 EUR` con par `EUR/USD` invertido; `USD/GBP` y `VND` sin tasa; 3
  llamadas en el libro de coste.
- **Inspección visual** (DOM, no captura; copia de compilación contra una SQLite desechable
  sembrada con el fichero diario real): la conversión dice «referencia BCE · ingerida el
  2026-09-29», y debajo la advertencia y la atribución; el panel de tasas separa lo declarado de
  «Referencia BCE · 6 tasas guardadas»; sin errores de consola.

## Llamadas externas y coste

Todas gratuitas y anónimas, contra `www.ecb.europa.eu` y `data-api.ecb.europa.eu`:

- **Investigación previa al código**: unas **8 descargas** de los ficheros y de una observación
  SDMX (algunas repetidas por errores de mi propio script de análisis) y **4 lecturas de páginas
  de documentación** del BCE (tasas, aviso legal, documento de marco y ayuda de la API).
- **Fixtures**: 1 descarga del fichero diario para guardarlo en `tests/fixtures/ecb/`.
- **Prueba de humo**: **3** peticiones (diario, diario otra vez, histórico), registradas por el
  `CostMeter`.

Las pruebas automáticas no tocan la red; la inspección visual usó el fichero diario ya guardado.
No llevé la cuenta exacta de las de investigación: **≈ 16 peticiones en total, 0 €.** Ninguna
cuenta, credencial ni servicio contratado.

## Corrección de un test anterior, descubierta durante M42

`tests/integration/test_economics_api.py` declaraba las tasas con `datetime.date.today()`, el
día **local** de la máquina, mientras la API rechaza fechas posteriores al día **UTC**. Entre las
22:00 y las 24:00 UTC en una zona adelantada (CEST) la suite fallaba en local (también sobre el
`HEAD` limpio, anterior a M42); CI corre en UTC y no lo veía. Se corrigió **solo el test**: una
función `_utc_today()` construye el día UTC (`datetime.datetime.now(datetime.UTC).date()`), que
es la regla real de la aplicación, en los tres usos del fichero. La regla de producción y la
validación de tasas futuras no cambian, y no se introdujo ningún reloj simulado. Al corregirlo
ya había pasado la medianoche UTC, así que el fallo no era reproducible en ese momento: la
garantía es por construcción (el test y la API calculan el día con la misma regla).

## Lo que NO se verificó

- **CI de GitHub Actions**: no se ha hecho `push`.
- **Migraciones contra PostgreSQL/Supabase real**: no hay PostgreSQL, y este milestone no añade
  ninguna.
- **El rol real** (403 con un token de REVIEWER/SYSTEM) lo cubren los inventarios contra tokens
  fabricados, no contra Supabase.
- **Ninguna captura de pantalla** (el panel se congela oculto); se comprobó por DOM.
- Que el BCE mantenga el acceso anónimo, el formato ni su disponibilidad: no hay SLA ni cuota
  publicada.
- **Concurrencia**: dos refrescos simultáneos podrían escribir dos veces la misma observación
  (inofensivo: misma tasa y fecha); no se probó con dos procesos reales.

## Limitaciones y deuda

- **Sin planificador**: nadie dispara el refresco solo. Si nadie lo pide, las referencias
  caducan a los 7 días y el margen vuelve a ser no evaluable.
- **Cobertura parcial**: 6 monedas; 23 del BCE fuera del catálogo; `VND` no la publica el BCE.
- **Sin cruces** y **sin diferencial bancario**: el margen con una referencia del BCE es algo
  optimista.
- La API muestra la tasa con ocho decimales (`1.13550000`) por la columna `Numeric(18, 8)`; la
  auditoría de republicaciones sí la normaliza.
- Los permisos de uso de las tasas (almacenamiento, retención, scoring…) se leen del uso libre
  general del BCE, no de una cláusula expresa de cada uno.
- La API SDMX del Data Portal no se usa: sus términos propios no se verificaron.
- El índice de ADRs y de milestones de `system-overview.md` estaba desactualizado desde el M39;
  se ha completado.
