# ADR 0018: Dinero con moneda, conversión con procedencia, y lo que no se puede evaluar

- **Estado:** Aceptada
- **Fecha:** 2026-09-29
- **Depende de:** [ADR 0008](adr-0008-demo-production-isolation.md), [ADR 0011](adr-0011-action-gate.md), [ADR 0016](adr-0016-signal-channel.md), [ADR 0017](adr-0017-supplier-facts-and-risk.md)
- **Enmienda a:** [ADR 0017](adr-0017-supplier-facts-and-risk.md) (§4 «no se convierte entre monedas» y el enum de procedencias)
- **Milestone:** 40

## Contexto

El Milestone 39 dejó una cotización con moneda y una regla: **no se convierte entre
monedas**. Tenía razón con lo que había —convertir exige un tipo de cambio, y un
tipo inventado mete un error del 5 % en el margen sin que nadie lo vea— pero dejó
el sistema en una posición insostenible: el directorio de fixture cotiza en
dólares, el sistema razona márgenes en euros, y **el margen se seguía calculando
restando lo uno de lo otro**, con un aviso en la lista de riesgos y el número mal.
Un aviso no es una salvaguarda.

Y al mirar de cerca aparecieron tres problemas más, ninguno buscado:

1. **`EconomicAnalysis` no tenía canal.** `compute_channel_net_margin` existía desde
   el Milestone 22 y solo lo usaba el agente de listings. Economía calculaba un
   margen sin saber dónde se vende, cuando en una web propia no hay comisión y sí
   pasarela, y en un marketplace es al revés.
2. **Unidad y pedido eran la misma cifra con dos nombres.** El backend la llamaba
   `monthly_unit_sales` y el frontend `monthlyOrders`, multiplicándola por el precio
   de **una** unidad para sacar los ingresos. El techo de CAC que la pantalla
   enseñaba salía de esa confusión, sobre datos de demostración.
3. **Un coste ausente y un coste que no aplica eran el mismo `None`.** El arancel de
   una cotización DDP ya está dentro del precio; la comisión de marketplace en una
   web propia no existe; la pasarela en una web propia nadie la ha dicho y cambia el
   resultado. Tres cosas distintas que sumaban cero euros.

## Decisión

### 1. Un importe no existe sin su moneda, y `Decimal`

`Money` lleva importe y moneda, y **sumar o restar dos monedas distintas falla al
construir el resultado**. La regla del Milestone 39 deja de vivir en prosa y pasa a
vivir en el tipo.

El importe es `Decimal`. `0.1 + 0.2` vale `0.30000000000000004` en coma flotante, y
un céntimo por unidad son cuarenta euros en un pedido de cuatro mil. Cuatro
decimales por dentro —un coste logístico unitario de 0,0042 € es real y a dos
decimales sería cero— y dos al presentar, con `ROUND_HALF_UP`, que es lo que hace
una factura. **Se redondea al final**, nunca entre dos sumas.

**El resto del repositorio no se migra.** Lo que hay es una frontera con una puerta
por sentido, escrita en `app/money/serialization.py`:

| Sentido | Regla |
|---|---|
| Columna `Float` legada → dominio | `Money.from_legacy_float`, que convierte por la representación decimal (`Decimal(str(x))`) y no por la binaria |
| Dominio → columna `JSON` | **Cadena**, nunca `float`: `json.dumps` no sabe serializar un `Decimal`, y convertirlo para que pase tiraría lo ganado |
| Dominio → navegador | **Cadena** más moneda: en JavaScript un número es un `float64` |

`Money.of` **no acepta un `float`**. Quien venga de una columna legada usa
`from_legacy_float`, que lo dice en su nombre.

### 2. Una conversión es un hecho con procedencia

No se levanta la prohibición de la ADR 0017: se completa. Lo prohibido sigue siendo
convertir **sin fuente**. Lo que se añade es una fuente y un registro con diez
campos: moneda y importe origen, moneda e importe destino, tasa, **par sin
ambigüedad**, dirección, fecha efectiva, fuente y procedencia.

El par y la dirección no son adorno: «1,08» puede ser dólares por euro o euros por
dólar, y entre las dos lecturas hay un 16 %. Una tasa usada al revés se registra
como `inverted`, porque los diferenciales de compra y venta no son simétricos.

**Y se guardan todas.** El precio y el coste logístico se convierten por separado;
guardar solo la última dejaría la otra sin rastro, que es lo contrario de lo que
esta columna existe para hacer.

- **Sin tasa aplicable no hay conversión**: hay `NOT_EVALUABLE`. **Nunca 1:1.**
- **Una tasa pasada de los 30 días deja de valer.** Una de hace seis meses es peor
  que no tener ninguna, porque tiene aspecto de dato.
- **Una tasa del futuro se rechaza.** Convertir hoy con el cambio de mañana es leer
  la respuesta antes del examen.

La única fuente de este milestone es `ManualExchangeRateProvider`: una persona
escribe el cambio que le aplicó el banco. Es el mismo argumento que sostuvo la
entrada manual de proveedores del Milestone 39 — la fuente real más barata que
existe somos nosotros. Sin red, sin altas, sin credenciales. Acción de permiso
propia, `EXCHANGE_RATE_WRITE`, que **ni siquiera `SYSTEM` tiene**: ningún proceso
automático declara el número por el que se multiplica todo lo demás.

En un entorno que admite datos simulados (ADR 0008) hay además una tasa de fixture,
marcada `simulated`, para que la cadena de demostración pueda llegar al final. En
staging y producción no se monta: allí, sin tasa declarada, el análisis es no
evaluable. Que es lo correcto.

### 3. `NOT_EVALUABLE` no es un resultado negativo

Un margen negativo se sabe y es malo. `NOT_EVALUABLE` es que **no se sabe**.
Confundirlos descartaría productos buenos por falta de un dato administrativo.

Consecuencia concreta sobre la ADR 0011: un análisis no evaluable sale como
`REVIEW` —una duda— y **nunca** como `NO_GO`. El ActionGate veta los `NO_GO` que
gastan; «no se puede saber» no puede parar el sistema como si fuera «va mal».

Y hay **tres evaluabilidades, no una**: se puede tener un margen por unidad firme,
un margen por pedido no evaluable (nadie declaró las unidades por pedido) y un
techo de CAC no evaluable por lo mismo.

**Economics no decide.** Emite un resultado económico; vender o no vender pertenece
a la capa posterior.

### 4. Cinco situaciones para un coste, y ninguna es «cero»

| Estado | Significa | ¿Suma? | ¿Bloquea? |
|---|---|---|---|
| `KNOWN` | Hay importe y quién lo sostiene | Sí | No |
| `INCLUDED_IN_ANOTHER` | Ya está dentro de otro, **y dice cuál** | No | No |
| `NOT_APPLICABLE` | No existe aquí, con motivo escrito | No | No |
| `UNKNOWN_REQUIRED` | Nadie lo ha dicho y cambia la respuesta | No | **Sí** |
| `UNKNOWN_OPTIONAL` | Nadie lo ha dicho y no cambia nada material | No | No |

Los cuatro últimos suman cero euros y significan cuatro cosas distintas. **Un coste
incluido en otro no es 0 € y uno que no aplica no es un coste desconocido.**

La protección contra contar dos veces deja de ser un parche por caso y pasa a ser un
mecanismo con invariantes: cada concepto aparece exactamente una vez, lo que dice
estar dentro de otro **nombra un contenedor que existe y se conoce**, y la suma
recorre solo lo conocido. No hace falta una regla contra los ciclos: un ciclo exige
que todos sus miembros estén dentro de otro, y entonces ninguno es conocido.

Los tres casos del Milestone 39 pasan a ser instancias del mismo mecanismo: Incoterm
DDP (arancel dentro del precio), estimador logístico (arancel dentro del transporte,
porque aplica un factor de aduana) y marketplace (pasarela dentro de la comisión).

### 5. Procedencia por componente, no solo en el resultado

Cada coste lleva **su** procedencia, y el resultado expone la composición completa.
El margen declara además su **procedencia más floja**: un margen no vale más que el
más flojo de sus sumandos, así que si uno solo viene de un fixture el margen es un
margen simulado y lo dice. Es la misma regla que hace simulado a un proveedor
compuesto en la ADR 0008 — un suelo, no una puntuación.

Se añade `DECLARED` al enum de la ADR 0017: el precio de venta, los costes fijos y un
tipo de cambio los **afirma el operador**. No los dice el proveedor ni los calcula un
modelo. Va por delante de `AMAZONA_ESTIMATE`: quien escribe el cambio que le aplicó
el banco lo sabe; un estimador solo lo modela.

### 6. Unidad, pedido y adquisición

```
margen_por_unidad   = precio_venta − Σ costes variables conocidos
margen_por_pedido   = margen_por_unidad × unidades_por_pedido
techo_antes_fijos   = margen_por_pedido
coste_fijo_pedido   = costes_fijos_mensuales / pedidos_mensuales_esperados
CAC_máximo          = margen_por_pedido − coste_fijo_pedido
```

`unidades_por_pedido` es un dato **declarado**. Un `1` que nadie ha declarado no
vale: deja el margen por pedido y todo el CAC en `NOT_EVALUABLE`, con
`units_per_order` en la lista de lo que falta. Los fixtures pueden usar 1 y quedan
marcados `simulated`.

**Una adquisición es un pedido, y es una decisión declarada** (`ORDERS_PER_ACQUISITION`).
La compra repetida es LTV y queda fuera; está escrito para que no sea una suposición
silenciosa.

El CAC máximo dice **cuánto podríamos permitirnos pagar**, no cuánto costará. Un
techo negativo se conserva negativo: significa que el producto pierde dinero antes
de gastar un euro en adquisición.

**`target_cac` no se calcula.** El hueco (`target_margin_per_order`) queda preparado
y vacío hasta que alguien fije un beneficio mínimo.

### 7. El canal viene del catálogo del Milestone 38

No hay una segunda taxonomía. Un canal no declarado falla, y un canal **no
transaccional** —una superficie de búsqueda, una red social— se rechaza: ahí se
descubre, no se cobra, y un margen de venta donde no se vende no significa nada.

### 8. El navegador calcula, pero no decide

El backend es la implementación canónica: lo que se guarda y lo que se enseña como
resultado oficial sale de él. `lib/economics-mirror.ts` existe para el simulador
—mover un control y ver el efecto sin una llamada por píxel— y es un **espejo
declarado**, con tests de paridad contra fixtures capturados del backend que fallan
el día que se separen.

## Alternativas descartadas

**Migrar todo el repositorio a `Decimal` ahora.** Treinta revisiones de columnas
`Float` y seis dominios. Es un milestone propio; lo que no se podía dejar sin hacer
era el dominio nuevo.

**Un tipo de cambio fijo o cacheado «solo para que salgan los números».** Es la
opción que deja el panel bonito y las cuentas mal: el error no se ve, se propaga al
margen, del margen al techo de CAC y de ahí a una decisión de compra.

**Que `NOT_EVALUABLE` fuera un `NO_GO`.** Es lo cómodo y es lo que convierte la falta
de un dato administrativo en un veto.

**Una tabla de obligatoriedad por canal, rígida.** Habría vuelto a aplanar «incluido
en otro» y «no aplica» en la misma casilla, que es de donde salía la doble
contabilización.

**Un `risk`/`score` único para el margen según su procedencia.** Lo mismo que la ADR
0017 rechazó para el riesgo: el suelo es explicable, un número no.

## Consecuencias

- El margen por fin dice de qué está hecho y en qué canal y moneda se calculó.
- **Las cotizaciones del mock en dólares dejan de ser evaluables en producción** sin
  una tasa declarada. Es incómodo y es cierto.
- `margin_percent` pasa a ser nulable, y seis consumidores tuvieron que aprender que
  un margen puede faltar.
- El coste de la pasarela en una web propia es **obligatorio**: sin declararlo, el
  análisis no es evaluable. Un 2,9 % del precio es una séptima parte de un margen
  del 20 %.
- Bajar la migración cuesta información: el esquema anterior no sabe representar «no
  se pudo evaluar», así que lo no evaluado vuelve a parecer margen cero.
- Queda deuda legacy explícita: `budgets` (que ya almacenaba `Numeric` y razonaba en
  `float`), `external_api_cost`, las columnas heredadas de `economic_analyses` y el
  motor del navegador.
