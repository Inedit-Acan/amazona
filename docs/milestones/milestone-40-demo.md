# Milestone 40 — Economía por canal, moneda normalizada y techo de CAC

**Fecha:** 29-09-2026 · **ADR:** [0018](../architecture/adr-0018-money-conversion-and-not-evaluable.md)
· **Enmienda a:** [0017](../architecture/adr-0017-supplier-facts-and-risk.md)
· **Depende de:** [0008](../architecture/adr-0008-demo-production-isolation.md)
· [0011](../architecture/adr-0011-action-gate.md)
· [0016](../architecture/adr-0016-signal-channel.md)

**Presupuesto: 0 €. Ninguna cuenta, credencial, servicio externo ni llamada de pago.**

## Lo que se encontró al revisar

- **`EconomicAnalysis` no tenía moneda.** El margen se calculaba restando un coste en
  dólares de un precio en euros, con un aviso en la lista de riesgos y el número mal.
- **Tampoco tenía canal.** `compute_channel_net_margin` existía y solo lo usaba el
  agente de listings: Economía calculaba un margen sin saber dónde se vende.
- **Unidad y pedido eran la misma cifra con dos nombres** (`monthly_unit_sales` en el
  backend, `monthlyOrders` en el frontend), y el techo de CAC que la pantalla
  enseñaba salía de esa confusión sobre datos de demostración.
- **Un coste ausente y uno que no aplica eran el mismo `None`.**

## Qué cambia

### Dinero exacto, con frontera declarada

`Money` (importe + moneda, `Decimal`) se niega a sumar o restar monedas distintas:
la regla del Milestone 39 pasa de la prosa al tipo. Cuatro decimales por dentro, dos
al presentar, `ROUND_HALF_UP`, y **se redondea al final**.

El resto del repositorio **no se migra**. Hay una puerta por sentido en
`app/money/serialization.py`, y `Money.of` no acepta un `float`.

### Conversión explícita, trazable y múltiple

Diez campos por conversión, con el par y la dirección sin ambigüedad. **Se guardan
todas**: el precio y la logística se convierten por separado.

Sin tasa aplicable, `NOT_EVALUABLE`. **Nunca 1:1.** Una tasa de más de 30 días deja
de valer; una del futuro se rechaza.

La fuente es una persona escribiendo el cambio que le aplicó el banco, bajo
`EXCHANGE_RATE_WRITE` — acción propia que **ni `SYSTEM` tiene**.

### `NOT_EVALUABLE` separado de cualquier resultado negativo

Un análisis no evaluable sale `REVIEW`, nunca `NO_GO`, y el ActionGate lo trata como
duda. Hay **tres evaluabilidades**: margen por unidad, margen por pedido y techo de
CAC pueden caer por separado.

### Cinco situaciones para cada coste

`known`, `included_in_another` (que **nombra** su contenedor), `not_applicable` (con
motivo), `unknown_required` (bloquea) y `unknown_optional` (se anota). Invariantes
que fallan si un contenedor no existe o no se conoce.

### Procedencia por componente

Cada coste dice quién lo sostiene, y el margen declara su procedencia **más floja**:
un suelo, no una nota. Nuevo valor `DECLARED` para lo que afirma el operador.

### Unidad → pedido → adquisición

Cinco cifras distintas y nombradas. `unidades_por_pedido` es un dato **declarado**;
un 1 que nadie declaró deja el CAC sin evaluar. Una adquisición es un pedido, y está
escrito. `target_cac` **no se calcula**.

### El canal, del catálogo del M38

Sin segunda taxonomía. Un canal no transaccional se rechaza.

## Informe de las pruebas pedidas

### 1. Backend, frontend, build y migraciones

| Verificación | Resultado |
|---|---|
| `ruff check .` | limpio |
| `mypy app` | sin incidencias en 207 ficheros |
| `pytest` | **1 729 en verde** (eran 1 605) |
| `npx tsc --noEmit` | limpio |
| `npm test` | **375 en verde** (eran 356) |
| `npx eslint .` | sin avisos |
| `next build --webpack` | compilado, 20/20 páginas, en copia aislada con junction |
| Migración `d8b4c1e70a29` | arriba y abajo con datos, sobre el esquema congelado del M39 |

### 2. `Decimal` y redondeo (`tests/unit/test_money.py`)

`0.1 + 0.2 ≠ 0.3` en coma flotante y **sí** es exacto con `Money` · `Money.of(0.1)`
se rechaza y obliga a pasar por la frontera legada · `Decimal(str(0.1))` frente a
`Decimal(0.1)` · precisión interna de cuatro decimales (0,0042 € no es cero) ·
`ROUND_HALF_UP` al presentar · **redondear entre dos sumas da 0,12 y redondear al
final da 0,11**, y el test lo fija · `Money × Money` no compila.

### 3. `unidades_por_pedido > 1`

`test_the_margin_per_order_is_the_margin_per_unit_times_the_units` (3 u. → margen
por pedido ×3) · `test_with_more_units_per_order_the_cac_ceiling_rises` (12,33 €
frente a 37,00 €, **con el mismo margen por unidad**) · el equivalente sobre HTTP y
sobre base de datos. En el humo: 14,17 €/unidad y 42,51 €/pedido con 3 unidades.

### 4. `unidades_por_pedido` desconocido

`test_without_units_per_order_there_is_no_order_margin_and_no_cac`: margen por
unidad **evaluable**, margen por pedido y CAC `NOT_EVALUABLE`, y `units_per_order`
en la lista de lo que falta. Y `test_a_one_that_nobody_declared_cannot_exist`: una
cantidad con valor y procedencia `unknown` **no se puede construir**.

### 5. Los cinco estados de coste (`tests/unit/test_cost_components.py`)

Uno por estado, más `test_the_four_non_known_states_all_add_nothing_and_mean_four_things`,
que comprueba que las cuatro situaciones que suman cero son cuatro cosas distintas.
Y los rechazos: conocido sin importe, conocido sin procedencia, no-conocido con
importe, «no aplica» sin motivo.

### 6. Doble contabilización

Concepto repetido · **estar dentro de algo que nadie ha declarado** (no cuenta en
ninguna parte) · dentro de sí mismo · ciclo · la suma recorre solo lo conocido · cada
concepto exactamente una vez. Y las tres instancias reales sobre base de datos: DDP
(arancel dentro del precio), estimador logístico (arancel dentro del transporte),
marketplace (pasarela dentro de la comisión).

### 7. FX sin tasa y con tasa caducada

`test_without_a_rate_the_analysis_is_not_evaluable_and_never_one_to_one`: no
evaluable, `exchange_rate` en lo que falta, margen `None`, y **no sale un `NO_GO`**.
`test_a_stale_rate_is_treated_as_no_rate_at_all`: una tasa pasada de los 30 días se
trata como si no hubiera ninguna. Más los unitarios: par que no aplica, tasa del
futuro, tasa entre una moneda y ella misma, tasa sin procedencia.

### 8. `own_web` frente a un marketplace

`test_a_marketplace_charges_a_commission_and_own_web_does_not`: el mismo producto,
margen y techo de CAC **menores** en el marketplace. En el humo, con precio de venta
de 20 €:

| | `own_web` | `marketplace:amazon` |
|---|---|---|
| Comisión del canal | *no aplica* | 5,10 € (fixture) |
| Pago / transacción | 0,83 € declarado | *dentro de la comisión* |
| Margen por unidad | **14,17 €** | **9,90 €** |
| CAC máximo | **12,50 €** | **8,23 €** |
| Procedencia más floja | `declared` | `simulated` |

### 9. Ejemplo completo con la procedencia de cada componente

Cotización real de 4,40 USD + 1,10 USD de logística, DDP, web propia, 2 unidades por
pedido, tasa declarada 1 USD = 0,915 EUR:

| Componente | Situación | Importe | Procedencia |
|---|---|---|---|
| Producto | conocido | 4,03 € | lo dice el proveedor · `manual:owner@amazona.local` |
| Logística | conocido | 1,01 € | lo dice el proveedor · `manual:owner@amazona.local` |
| Aranceles | **dentro del producto** | — | Incoterm DDP: el proveedor asume los derechos |
| Comisión del canal | **no aplica** | — | una web propia no paga comisión de marketplace |
| Pago | conocido | 0,83 € | declarado por nosotros |
| Otros variables | no declarado | — | opcional, se anota |

Margen/unidad **14,14 €** · margen/pedido (2 u.) **28,28 €** · fijo/pedido 3,33 € ·
**CAC máximo 24,94 €**. Conversiones registradas: `4.4000 USD → 4.0260 EUR` y
`1.1000 USD → 1.0065 EUR`, par `USD/EUR` a `0.91500000`, directa, vigente hoy,
declarada. Y al lado, sin tocar la aritmética: identidad no verificada, fiabilidad
sin valorar, precio sostenido por el proveedor.

## Verificación adicional

- **Humo real** sobre SQLite, nunca contra `backend/.env`: siete escenarios (web
  propia ×1 y ×3, marketplace, sin unidades declaradas, USD con tasa, tasa caducada,
  canal no transaccional).
- **Inspección visual**: la tarjeta «Economía unitaria» con los seis componentes y su
  procedencia, la cadena hasta el CAC, las dos conversiones y el bloque de los tres
  ejes; el estado **No evaluable** con la lista de lo que falta; y un tipo de cambio
  **dado de alta desde el formulario del navegador**, comprobado después en la base.
  Sin capturas: el panel arranca con viewport 0×0 y congela el repintado; la
  inspección se hizo leyendo el DOM.

## Qué es real, declarado, estimado, simulado o desconocido

| Dato | Clase |
|---|---|
| Precio, moneda, Incoterm de la cotización | **Real o declarado** (M39) |
| Tipo de cambio introducido a mano | **Declarado**, con fecha, fuente y procedencia |
| Precio de venta, costes fijos, unidades por pedido, coste de pago | **Declarado** por el operador |
| Comisión de marketplace | **Simulada** (fixtures) |
| Coste logístico del estimador | **Estimado** (`amazona_estimate`) |
| Tasa de fixture (solo donde la ADR 0008 lo admite) | **Simulada**, y lo dice |
| Coste de pasarela de la cadena de demostración | **Simulado** (2,9 % + 0,25 €) |
| Pedidos mensuales derivados de la señal de demanda | **Simulado**: la conversión es un marcador de posición |
| Margen, margen por pedido y CAC máximo | **Derivados**, y valen lo que el más flojo de sus sumandos |
| CAC real, `target_cac`, conversión real, LTV | **Desconocidos**, declarados como tales |

## Lo que NO cambia

`opportunity_score` · §12 Legal · eBay · el mock general (los proveedores siguen
dando las mismas cifras) · fuentes comerciales de demanda o CPC · el Decision Engine
· cero APIs, cuentas, credenciales y gasto.

## Limitaciones y deuda después del M40

1. **CAC real medido**: fuera. Exige plataformas de anuncios con gasto.
2. **`target_cac` / rentabilidad objetivo**: contrato preparado (`target_margin_per_order`),
   vacío hasta que se fije un número.
3. **Feed automático de tipos de cambio**: el BCE publica referencias diarias gratis y
   sin alta. Investigación aparte, con su matriz de derechos del M37. M40 no depende
   de ello.
4. **LTV y compra repetida**: una adquisición es un pedido, declarado.
5. **`Decimal` en el resto del repositorio**: `budgets` (que ya almacenaba `Numeric`
   y razonaba en `float`), `external_api_cost`, las columnas heredadas de
   `economic_analyses`, `scenarios.py` y el motor del navegador.
6. **Comisiones reales de marketplace**: hoy fixtures, así que un margen de
   marketplace es un margen simulado y lo dice.
7. **`units_per_order` medido** en vez de declarado: necesita pedidos reales.
8. **Aritmética exacta en el navegador**: el espejo usa coma flotante y está
   declarado como simulación de interfaz.
9. **Ledger del plan §20** (estimado / comprometido / devengado / pagado): M40 se
   queda en estimado.
10. Heredadas del M39: catálogo países↔mercado, certificaciones de proveedor,
    filtros de Incoterm y método de pago en pantalla, sin directorio real de
    proveedores.
