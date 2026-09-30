# ADR 0020: Referencias de tipos de cambio del BCE — observaciones con fecha propia, ventana propia y cero red en el análisis

- **Estado:** Aceptada
- **Fecha:** 2026-09-30
- **Depende de:** [ADR 0008](adr-0008-demo-production-isolation.md), [ADR 0009](adr-0009-async-job-runtime.md), [ADR 0015](adr-0015-multiple-real-sources-cost-and-usage-rights.md), [ADR 0017](adr-0017-supplier-facts-and-risk.md), [ADR 0018](adr-0018-money-conversion-and-not-evaluable.md)
- **Enmienda a:** [ADR 0018](adr-0018-money-conversion-and-not-evaluable.md) (§2 «no hay red»: aparece la primera fuente de red de tipos de cambio, solo en el refresco) y su regla de una única ventana de 30 días (ahora es por tasa)
- **Milestone:** 42

## Contexto

El Milestone 40 dejó una conversión trazable y una única fuente: una persona escribiendo el
cambio que le aplicó el banco. La ADR 0018 lo dijo así: *«una fuente oficial —el BCE publica
referencias diarias gratis— se estudia aparte y no es dependencia de nada»*. Hoy es el hueco
que más pesa: toda cotización que no está en euros deja el margen `NOT_EVALUABLE` salvo que
alguien teclee la tasa.

Al leer la fuente antes de escribir código (29-09-2026) aparecieron cuatro hechos que
condicionan el diseño:

1. **El BCE dice que no son para transacciones.** La página de las tasas y su documento de
   marco: son referencias «for information purposes only» y su uso «para transacciones» está
   «fuertemente desaconsejado». Aquí sirven para **estimar un margen**, no para cobrar.
2. **Solo publica pares contra el euro** (`1 EUR = X divisa`), 29 divisas, en días TARGET,
   sobre las 16:00 CET. No hay `USD/GBP`, ni `VND`. Nuestro catálogo (`CURRENCIES`) admite 6
   de esas 29 (USD, GBP, CNY, HKD, MXN, PLN) más el EUR.
3. **La licencia es uso libre con condiciones**: citar al BCE, decir si se modifica el dato,
   avisar a quien compre un documento que lo incorpore de que es gratuito, no enmarcar la
   web. No exige alta. **No dice nada** de scoring, retención ni ingestión por IA por
   separado.
4. **El BCE puede republicar** una tasa hasta el siguiente día TARGET (documento de marco), y
   documentó dos horas distintas para la fijación (14:10 y 14:15). Solo nos quedamos con la
   fecha.

Y una tensión con el M40: el proveedor manual elegía por fecha efectiva y después por rango de
procedencia; con una fuente diaria en la misma tabla, una tasa del BCE de hoy le ganaría a una
declarada de ayer, contra «lo declarado gana». Y `CompositeExchangeRateProvider` devolvía la
primera respuesta **aunque estuviera caducada**: una tasa manual de hace seis semanas tapaba
una referencia de ayer y el análisis quedaba no evaluable con una tasa buena detrás. Era un
fallo latente del M40 que el BCE dejaría de esconder.

## Decisión

### 1. Lectura y escritura son dos lados, y el análisis solo lee

- **Escritura**: un puerto `ExchangeRateFeed` y un adaptador (`app/integrations/fx/ecb.py`)
  descargan el fichero XML público y lo devuelven como observaciones con fecha; un servicio
  (`app/money/fx_refresh.py`) las valida y las guarda en `exchange_rates`.
- **Lectura**: `EcbExchangeRateProvider` **lee solo la base de datos**. El análisis económico
  no hace una petición HTTP jamás; sin nada guardado, el margen es `NOT_EVALUABLE`.

Se reutiliza el contrato FX del M40 (`ExchangeRate`, `convert`, `Conversion`): el adaptador
devuelve tasas `EUR/divisa`; `USD→EUR` es la misma fila **invertida**, y la conversión ya
registra `direction = inverted`.

### 2. Qué es una observación, y por qué no hay una restricción única

**Identidad de una observación: `(base, quote, effective_date, source, rate)`.** Se reutiliza
la tabla `exchange_rates`; no se crea una tabla del BCE. Toda tasa ingerida lleva
`source = "ecb:eurofxref"` (el prefijo `ecb:` está **reservado** al refresco y el alta manual
lo rechaza), venga del fichero diario o del histórico.

Al ingerir una observación se compara con la **más reciente** ya guardada para ese par, fecha
y fuente:

| Caso | Qué pasa |
|---|---|
| No había ninguna | Se inserta |
| La más reciente trae **la misma tasa** | No se escribe (idempotencia) |
| La más reciente trae **otra tasa** | Se inserta una **fila nueva**, la anterior **se conserva**, la más reciente gana al leer, y se audita con los dos valores (`exchange_rate.ecb_republished`) |

Se compara contra la más reciente y no contra «alguna anterior» a propósito: si el BCE publica
A, luego B y luego A, la tercera es una republicación legítima y debe ganar. **Ninguna
restricción única sobre `rate` sirve**: una que incluyera la tasa rechazaría el regreso al
valor A; una que la excluyera impediría la republicación. La identidad se aplica en el
servicio, dentro de la transacción del refresco. Dos refrescos concurrentes podrían escribir
dos veces la misma observación; es inofensivo (misma tasa, misma fecha) y el trabajo usa
arriendo (ADR 0009). **No hay migración**: el índice `(base, quote, effective_date)` de M40
sirve.

Las filas son inmutables. Nada se borra ni se actualiza: el margen de marzo se calculó con la
tasa de marzo.

### 3. Cuatro fechas distintas

| Concepto | Origen | Se altera |
|---|---|---|
| **Fecha efectiva** | atributo `time` del BCE | **Nunca**. La tasa del viernes usada el lunes sigue siendo del viernes y tiene 3 días |
| **Fecha de ingestión** | `created_at` de la fila | Es cuándo entró en nuestra base; viaja en la conversión (`ingested_at`) |
| **Antigüedad** | fecha del análisis − fecha efectiva | Se calcula y se guarda con la conversión |
| **Aceptabilidad** | política nuestra, por tasa | `ExchangeRate.max_age_days`; una tasa aceptable no es futura ni excede su ventana |

**Ventana por tasa.** Una tasa manual conserva los **30 días** del M40 (la ventana de una
negociación). Una referencia del BCE trae la suya, por defecto **7 días** (`ECB_RATE_MAX_AGE_DAYS`,
entre 1 y 30): cubre el hueco de fin de semana (3 días observados; algo más con un festivo
TARGET) y unos días de margen si el refresco falla. En 90 días de datos no falta ningún día
laborable. «Última tasa disponible» no significa «válida»: pasada su ventana, la tasa se
rechaza con `StaleRateError` y el margen queda no evaluable, nunca `NO_GO`.

### 4. Precedencia: manual > BCE > mock, solo entre fuentes aceptables

`CompositeExchangeRateProvider` devuelve **la primera fuente que dé una tasa aceptable** por
antigüedad. Si una fuente prioritaria está caducada o es del futuro, salta a la siguiente. Si
ninguna es aceptable devuelve la primera que contestó, para que quien convierta la rechace con
su motivo (`StaleRateError`) y no confunda «hay tasa y es vieja» con «no hay tasa». Los
derechos de uso se comprueban en la lectura: sin `STORAGE`, `TRANSFORMATION` y
`DERIVED_METRICS` permitidos, el proveedor no lee nada.

- `ManualExchangeRateProvider` ya no lee filas `ecb:*`; `EcbExchangeRateProvider` solo esas.
- **Precedencia, no frescura**: una tasa manual de 20 días sigue ganando a una del BCE de
  ayer, porque una persona la declaró deliberadamente y su fecha se muestra. Deja de ganar
  cuando caduca.
- `EXCHANGE_RATE_PROVIDER=mock` (por defecto) es exactamente el sistema anterior: las filas
  del BCE se ignoran y las cifras son las mismas. Con `real` se añade el BCE ya guardado; el
  fixture solo detrás y solo donde la ADR 0008 admite datos simulados.

### 5. Solo pares EUR/divisa y solo divisas del catálogo

M42 guarda las monedas que `CURRENCIES` ya admite (hoy 6 de 29) y **lista** las omitidas en el
resultado de cada refresco (`omitted_currencies`). No amplía el catálogo: admitir una moneda
comercial es una decisión aparte (implica que un proveedor puede cotizar en ella). `VND`, que
el mock usa, no la publica el BCE: sigue necesitando tasa declarada. **No hay cruces**.

### 6. Todo o nada; el histórico es recuperación explícita

La fuente se lee entera y se valida entera **antes** de escribir nada. Falla la red, HTTP
distinto de 200, cuerpo mayor de 1 MB, no UTF-8, XML mal formado o con DTD/entidades, sin
días, día sin monedas, fecha o tasa ilegible, tasa no positiva o no finita, moneda repetida,
fecha futura, base distinta de EUR, o ninguna moneda admitida ⇒ **no se guarda nada, no se
borra nada y no se declara «sin cambios»**. Lo ya guardado sigue valiendo dentro de su
ventana.

- El **fichero diario** es el camino normal.
- El **histórico de 90 días** solo lo llama `backfill_history`, que solo se alcanza por
  `POST /api/exchange-rates/backfill`. **Nunca** es el respaldo automático de un fallo del
  diario: un fallo se reintenta con espera por el runtime.
- Solo se usan estos ficheros de `www.ecb.europa.eu`. La API SDMX del Data Portal no se usa
  porque sus términos propios no se verificaron.

### 7. Cruces: no se implementan; su diseño y sus invariantes (para un milestone futuro)

`USD→GBP` **no está publicado**: se **calcularía** por EUR, y una tasa calculada es otra cosa
que una tasa publicada. Cuando haga falta (hoy todo se convierte a `ACCOUNTING_CURRENCY`, EUR),
una dirección `CROSS_VIA_EUR` debe cumplir:

1. **Dos patas de la misma fecha efectiva.** Nunca se mezclan fechas ni fuentes: una pata del
   BCE y otra manual no se combinan.
2. Solo un salto por EUR. No hay cadenas.
3. Si falta cualquiera de las dos patas, o alguna no es aceptable, **no hay tasa** (no
   evaluable), no una tasa a medias.
4. La conversión registra **las dos patas** (par, tasa, fecha, fuente, ingestión), la fecha
   efectiva compartida y la antigüedad, y se rotula «calculada por AMAZONA a partir de tasas
   del BCE» (condición 3 de la licencia: el dato modificado se dice).
5. La procedencia es el techo de la pata más débil; la ingestión, la más reciente.
6. Se calcula con `Decimal` y se redondea solo al final.

### 8. Semántica de la fuente, hasta la pantalla

Toda tasa del BCE conserva y puede exponer: fuente (`ecb:eurofxref`), fecha efectiva, fecha de
ingestión, procedencia `third_party_verified` con `declared_by = European Central Bank`,
**atribución requerida** y **la advertencia de que es una referencia informativa, no la tasa
transaccional que aplica un banco o un procesador de pagos**. `third_party_verified` significa
que un emisor con nombre sostiene la cifra, no que sea cotizable. La API de tasas devuelve
`ingested_at`, `attribution` y `notice`; la tarjeta de economía unitaria rotula «referencia
BCE», la fecha de ingestión, y la atribución y la advertencia cuando un cálculo usa esa fuente.
No se incluye el diferencial bancario: el margen calculado con una referencia del BCE es algo
optimista, y modelar el spread sería inventar un dato.

### 9. Derechos y coste, antes de la primera llamada

`ecb-reference-rates`, leído el 29-09-2026: `STORAGE`, `RETENTION`, `TRANSFORMATION`,
`DERIVED_METRICS`, `SCORING`, `REDISTRIBUTION` y `COMMERCIAL_USE` permitidos **a partir del
uso libre general** —la licencia no los enumera y las notas lo dicen—, atribución requerida.
**`AI_INGESTION` sigue `UNKNOWN`, es decir denegado.** Coste gratuito, sin cuota publicada
(`quota_units_per_day = None` significa «no sé»), tope propio de 2 peticiones por ejecución;
cada petición pasa por el `CostMeter`. Una petición por refresco.

### 10. Cómo se ejecuta

`POST /api/exchange-rates/refresh` y `/backfill`, con `EXCHANGE_RATE_WRITE` (solo OWNER y
ADMIN), y un trabajo `fx.refresh` (solo el fichero diario) para que un planificador o una capa
de ejecución futura lo dispare. **No hay planificador** en este milestone y **no hay refresco
perezoso dentro del análisis**. Sin fuente real configurada, o con el presupuesto denegado, el
trabajo se bloquea en vez de gastar intentos; un fallo de red o de formato se reintenta. Cada
refresco y cada republicación quedan en la auditoría.

## Consecuencias

- Una cotización en USD, GBP, CNY, HKD, MXN o PLN es evaluable sin que nadie teclee una tasa,
  mientras el refresco esté al día; con la referencia caducada, el margen vuelve a ser no
  evaluable.
- **Cobertura parcial**: 23 monedas del BCE no se guardan y `VND` no existe en la fuente.
- Sin refresco no hay tasas nuevas: el sistema depende de que alguien (o un trabajo futuro)
  lo pida. Es deliberado: el análisis no hace red.
- El BCE puede cambiar el formato, dejar de ser anónimo o republicar: el adaptador falla en
  voz alta, y no se sustituye por otra vía con alta.
- Se corrige un fallo latente del M40 (una tasa manual caducada tapando una válida).

## Lo que esta ADR no decide

Cruces (solo su diseño), diferencial bancario, ampliación del catálogo de monedas, series
históricas más allá de los 90 días, otras fuentes de tipos de cambio, un planificador, y el
uso de estas tasas para precios que se cobren al cliente de KOVA (el BCE lo desaconseja).
