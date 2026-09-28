# Milestone 38 — Dónde se mide una señal

**Fecha:** 28-09-2026 · **ADR:** [0016](../architecture/adr-0016-signal-channel.md)
· **Depende de:** [0012](../architecture/adr-0012-product-intelligence-adapters.md)
· [0013](../architecture/adr-0013-signal-evidence-and-comparison.md)
· [0014](../architecture/adr-0014-entity-resolution.md)
· [0015](../architecture/adr-0015-multiple-real-sources-cost-and-usage-rights.md)

**Presupuesto: 0 €. Ninguna cuenta nueva, ninguna credencial, ningún servicio de
pago.**

El propietario fijó los canales prioritarios —**venta directa por webs propias**,
Amazon cuando convenga, otros marketplaces solo si aportan— y eBay pasó a
complementario. Esa corrección destapó una asimetría que ninguna ADR anterior había
visto, y este milestone la cierra.

## Lo que se encontró al revisar

`Signal` tenía `market` —una geografía— y **no tenía canal**. Mientras que:

- **Dos de los cinco puertos ya llevaban plataforma**: `MarketplaceDirectory` y
  `AdPerformanceDirectory`.
- **`PipelineRequest` ya decide el canal… en los pasos 7 y 8**: lleva
  `marketplace_platform` y `marketing_platform`. El paso de investigación, el 1, no
  recibía ninguno.

Así que el pipeline sabía en qué canal iba a publicar y a anunciar, e investigaba la
oportunidad como si el canal no existiera. Con la consecuencia de fondo: la única
competencia **medida** del sistema era un recuento de anuncios de eBay —el canal que
acababa de quedar declarado complementario— y nada en el dato impedía leerla como si
valiera para una web propia, donde la competencia es otra magnitud (dificultad
orgánica y coste del clic; el plan §17 lo dice al pedir `max CPC` y `max CAC`).

Y una tercera: el plan §8 distingue «Search demand» de «Marketplace demand», y el
contrato las había colapsado en un solo `DEMAND`.

## Qué cambia

### Cuatro tipos cerrados, plataformas abiertas, ninguna migración por marketplace

`own_web`, `marketplace`, `search`, `social` son **conceptos** y no crecen con cada
proveedor. Amazon, eBay, Etsy, Mercado Libre y TikTok Shop son **valores**: añadir
uno es **una línea en `channels.py`**.

La señal guarda **una** clave en una columna. El tipo lo da el catálogo, no un
`split(':')`, así que `keys_of_kind(MARKETPLACE)` responde «todos los marketplaces»
sin patrones de texto. Las claves son autodescriptivas para quien lea una fila cruda,
y una clave no declarada **falla al construir la señal**.

**TikTok no es TikTok Shop**: uno es una superficie social donde se descubre, el otro
un marketplace donde se cobra. Dos canales, dos tipos, dos valores de
`transactional`.

### Sin canal significa agnóstica, y nunca «válida para todos»

Competencia, demanda de búsqueda y demanda de marketplace **no significan nada sin
decir dónde se midieron**. El interés, la trayectoria, el riesgo regulatorio y la
escalabilidad son propiedades del producto y pueden no tener canal.

De ahí la regla: una señal ligada a canal sirve **solo** para su canal, y sin canal
declarado solo para una decisión igualmente sin canal. **Si valiera para todos, el
relleno de un fixture decidiría sobre Amazon.**

Consecuencias comprobadas: la competencia de eBay no puede entrar en un score
genérico, y el mock —que no mide en ningún sitio— sigue emitiendo sin canal y **dando
exactamente las mismas cifras** en una decisión agnóstica.

### El canal llega al paso 1, y el score dice para cuál vale

`discover()` recibe `channels`; un adaptador que solo sabe de un canal **calla**
cuando no se le pregunta por él. El score publica `channel`, y cuando no puede
calcularse distingue **cuál de los dos motivos** lo impidió: una licencia que no
permite puntuar o una señal que mide otro canal. Se arreglan de formas distintas, así
que se dicen aparte.

### El mercado español pasa de un 404 a una medición

El Milestone 36 midió el límite: `es.wikipedia` no tiene «Air fryer» (404) y sí
«Freidora de aire» (12.099 visitas). Ahora los *langlinks* de Wikimedia declaran la
equivalencia y el término local es el que se consulta.

Verificado contra la fuente real: «Air fryer» → `Freidora de aire` (es),
`Heißluftfritteuse` (de), `Friteuse à air chaud` (fr). El mercado `es` mide
**0,6805 de demanda con confianza 0,6491**, y el candidato **sigue llamándose «Air
fryer»** — porque si se llamara «Freidora de aire», la identidad del Milestone 36 lo
trataría como otro producto y medir cuatro mercados daría cuatro productos.

La equivalencia se guarda como alias con su motivo: `langlinks:es.wikipedia`. **Sin
equivalencia declarada, ese término no se mide**: no se traduce, no se transcribe y no
se busca el más parecido.

### Y la pantalla lo dice

Cada candidato dice para qué canal se puntuó —«Puntuado sin canal (agnóstico)» cuando
no hay— y, si lo medido es de otro canal, lo nombra. El informe de contraste dice en
qué canales midió cada proveedor.

## Lo que NO cambia, a propósito

- **`opportunity_score` intacto** (plan maestro §9). Separar los ejes de demanda
  **no** autoriza a tocar la fórmula; la dependencia queda escrita para su milestone.
- **Wikimedia sigue en `DEMAND`** y su `method` sigue diciendo lo mismo: proxy de
  **interés**, nunca intención de compra, nunca volumen de búsqueda comercial, nunca
  demanda. Ninguna señal existente cambia de casilla.
- **El mock, con sus mismas cifras.**
- **eBay no se desarrolla más**: sigue aparcado (ver abajo).
- **`UNKNOWN` → denegado**, ausencia ≠ cero, identidad determinista o declarada,
  proveedores reversibles, gasto controlado.
- **No se simula la analítica de la web propia**: no hay ninguna con tráfico real.

## eBay: relectura acotada, y aparcado

Autorizada una relectura gratuita para intentar resolver `STORAGE` y `SCORING`. **No
se resolvieron**, y apareció algo nuevo en los requisitos oficiales de las Buy APIs:

> Many of the Buy APIs are a **(Limited Release)**. The use of eBay's Buy APIs **in
> production is intended for eBay partners only**. You must **apply for production
> access through the eBay Partner Network**. Acceptance of applications is based on
> the proposed business model…

El keyset gratuito sirve para el **sandbox**; producción exige aprobación con revisión
del modelo de negocio. Eso son permisos especiales, así que **eBay queda aparcado**
como implementación de referencia, con su fila de derechos intacta en `UNKNOWN` →
denegado. **No se ha inferido ningún permiso.**

## Límites que hay que tener presentes

1. **Dos tipos de señal declarados y sin emisor.** `SEARCH_DEMAND` y
   `MARKETPLACE_DEMAND` son casillas vacías, y una casilla vacía invita a rellenarla
   con lo que haya a mano. Se mitiga con el `method` y la ADR, no con código.
2. **El canal prioritario es hoy el peor medido.** No hay webs propias con tráfico, y
   no se inventa nada.
3. **La competencia sigue sin medirse para ningún canal que importe**: eBay aparcado,
   Amazon sin camino gratuito. Un candidato real sigue sin score — y ahora se sabe
   exactamente por qué.
4. **Los langlinks son una dependencia de red más**, con su cuota y su contador.
5. **`LANGUAGE_FOR_MARKET_PROJECT` duplica al revés** lo que ya está en
   `PROJECT_FOR_MARKET`: una cosa más que mantener coherente.
6. **El catálogo de canales envejece** como todo catálogo declarado.

## Deuda funcional registrada: el CAC

**La evaluación económica de venta directa no puede considerarse completa sin coste de
adquisición.** `EconomicAnalysis` tiene `sale_price`, `monthly_fixed_costs` y
`margin_percent`, y **no tiene CAC**: un producto con 40 % de margen y un coste de
adquisición del 60 % del precio pierde dinero, y hoy el sistema no puede verlo.

El plan maestro lo roza en §17 (límites de `max CPC` y `max CAC` para campañas) y en
§18 (el embudo devolviendo datos a Economics), y **no le da ubicación inequívoca**.
Queda registrada en
[system-overview §19](../architecture/system-overview.md#19-deuda-funcional-registrada)
con un milestone propio propuesto. No es de este milestone: es del dominio Economics.

## Probarlo

```bash
cd backend && alembic upgrade head
```

```bash
curl -X POST localhost:8000/api/research/runs -H 'Content-Type: application/json' -d '{"category":"home","keywords":["Air fryer"],"market":"es","max_results":1}'
```

## Verificación

- Backend: `ruff` y `mypy` limpios · **1463 tests** (1384 antes, +79).
- Frontend: `tsc` y `eslint` limpios · **328 tests** (312 antes, +16).
- `next build --webpack` en una copia, sin tocar el `.next` de desarrollo.
- **Migración nueva arriba y abajo con datos**, y en cadena con las dos del M37.
- **Humo real contra Wikimedia**, sin credenciales y sin gasto: tres equivalencias
  declaradas, el mercado `es` medido de verdad, **un solo producto** con señales de
  `es` y `us`, el alias guardado con su motivo, los canales declarados con TikTok y
  TikTok Shop distinguidos, y el libro de costes con 3 unidades de langlinks y 2 de
  pageviews a **0,00 €**.
- Los tests de inventario del Milestone 29, en verde: este milestone **no añade
  rutas**.

## No verificado

- **El recorrido real contra eBay**: aparcado por permisos, no solo por credenciales.
- **La pantalla no se ha visto en un navegador** con datos de canal dentro. Su lógica
  está cubierta por tests de `lib`; el render a ojo, no. Se acumula con el pendiente
  equivalente del Milestone 37.
- **`AI_INGESTION` de Wikimedia y de langlinks**: la licencia no lo aborda, sigue
  `UNKNOWN` → denegado.
- **Migraciones sobre PostgreSQL real**: las aplica CI.
- **La incidencia del test intermitente del M35** no ha reaparecido.

## Lo que queda abierto

1. **Resolución jurídica exacta de eBay Browse / `Restricted APIs`**, y ahora también
   el acceso de producción vía eBay Partner Network.
2. **`AI_INGESTION`** de las dos fuentes de Wikimedia.
3. **Humo real de eBay** con credenciales gratuitas — bloqueado además por permisos.
4. **Inspección visual en navegador** de la tarjeta de Estado del M37 y de las notas
   de canal del M38.
5. **Una fuente de intención comercial** para el canal prioritario: es el hueco que sí
   cuesta dinero, y ahora tiene casilla (`SEARCH_DEMAND`) y canal (`search:google`)
   donde aterrizar.
6. **El CAC en Economics** (arriba).
7. **`opportunity_score` v2** del §9, que tendrá que decidir **por canal**.
8. **`SignalKind.PRICE`**, la tabla de identificadores externos, discovery real, los
   otros cuatro dominios, la caducidad de `WAITING_APPROVAL` y la limpieza de Redis.
