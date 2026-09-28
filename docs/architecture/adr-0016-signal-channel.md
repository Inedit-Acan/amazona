# ADR 0016: Dónde se mide una señal, y el mismo producto en varios idiomas

- **Estado:** Aceptada
- **Fecha:** 2026-09-28
- **Depende de:** [ADR 0012](adr-0012-product-intelligence-adapters.md), [ADR 0013](adr-0013-signal-evidence-and-comparison.md), [ADR 0014](adr-0014-entity-resolution.md), [ADR 0015](adr-0015-multiple-real-sources-cost-and-usage-rights.md)
- **Milestone:** 38

## Contexto

El propietario fijó los canales prioritarios del proyecto: **venta directa por webs
propias de KOVA**, Amazon cuando convenga, y otros marketplaces solo cuando aporten
valor al producto concreto. eBay pasa a complementario.

Esa corrección destapó una asimetría que llevaba tiempo latente y que **ninguna ADR
anterior había visto**:

`Signal` tiene `market` —una geografía, «us», «es»— y **no tiene canal**. Mientras
que dos de los cinco puertos hermanos sí llevan plataforma
(`MarketplaceDirectory.get_marketplace_data(category, platform)` y
`AdPerformanceDirectory.get_performance_estimate(category, platform)`), y
`PipelineRequest` ya decide `marketplace_platform` y `marketing_platform`… en los
pasos 7 y 8. **El pipeline sabe en qué canal va a publicar y a anunciar, e investiga
la oportunidad en el paso 1 como si el canal no existiera.**

Y eso hace que `SignalKind.COMPETITION` signifique cosas incompatibles sin que nada
en el dato lo avise:

- Dentro de un marketplace, competencia es cuántos vendedores u anuncios compiten
  por la misma búsqueda.
- Para una web propia **no existen anuncios competidores**: la competencia es
  dificultad orgánica y coste del clic. El plan maestro §17 lo dice con sus propias
  palabras cuando pide límites de `max CPC` y `max CAC`.

La única competencia medida que el sistema tiene hoy es un recuento de anuncios de
eBay — es decir, **del canal que acaba de quedar declarado complementario**, y nada
en el dato impedía leerla como si valiera para la web propia.

Hay una tercera cosa: el plan maestro §8 distingue «Search demand» de «Marketplace
demand», y el contrato las había colapsado en un solo `DEMAND`. Con la venta directa
como prioridad, esa distinción deja de ser académica: interés enciclopédico y
volumen de búsqueda comercial son magnitudes distintas y una no se puede usar como
si fuera la otra.

## Decisión

### 1. Cuatro tipos cerrados y una lista abierta de plataformas

`ChannelKind` tiene cuatro valores y **no crece con cada marketplace**: `own_web`,
`marketplace`, `search`, `social`. Son conceptos —las cuatro formas en que un
producto se encuentra con quien lo compra—, no proveedores. Un tipo nuevo
significaría una manera de vender que el sistema no contemplaba, y eso merece una
decisión.

Las **plataformas son valores**: Amazon, eBay, Etsy, Mercado Libre, TikTok Shop.
Añadir una es **una línea en `channels.py` y ninguna migración**, porque lo que se
persiste es una clave en una columna `String(64)`.

### 2. Una sola columna, un catálogo declarado, y ninguna lógica que parsee

La señal guarda **una** clave. El **tipo** lo da el catálogo, no un `split(':')`: si
mañana una clave cambiara de forma, cambiaría en un sitio y no en los cinco que la
interpretaban. `keys_of_kind(MARKETPLACE)` responde «todos los marketplaces» sin
patrones de texto.

Las claves son **autodescriptivas** —`own_web`, `marketplace:amazon`,
`search:google`, `social:tiktok`— por la misma razón por la que `method` viaja con
cada número: una fila cruda de `product_signals` tiene que entenderse sin consultar
nada. El prefijo es para quien lee, no para el código.

Una clave **no declarada falla al construir la señal**. Un typo se convertiría en un
canal fantasma con sus propias señales, invisible para cualquier consulta que
buscara el canal de verdad.

Es el mismo patrón que este repositorio ya usa cuatro veces: `terms.py`,
`aliases.py`, `usage_rights.py` y las políticas de coste. Catálogos declarados, en
git, con su procedencia.

### 3. TikTok no es TikTok Shop

Uno es una superficie social donde se descubre y se anuncia; el otro un marketplace
donde se cobra. Comparten marca y no comparten naturaleza, así que son dos canales
con dos tipos distintos y con `transactional` distinto.

Es el ejemplo que mejor explica por qué **el tipo no se puede deducir del nombre de
la plataforma**, y por eso está en el catálogo con esa nota.

### 4. Sin canal significa agnóstica, y nunca «válida para todos»

Esta es la regla que hace que lo demás sirva de algo.

Algunas señales **no significan nada sin decir dónde se midieron**: competencia,
demanda de búsqueda y demanda de marketplace. Otras son propiedades del producto y
no del sitio donde se vende —interés, trayectoria, riesgo regulatorio,
escalabilidad—, y pueden no tener canal sin perder sentido.

De ahí la regla, deliberadamente estrecha:

- Una señal **no** ligada a canal sirve para cualquier decisión.
- Una señal **ligada** a canal sirve **solo** si declara exactamente ese canal. Una
  competencia medida en eBay no dice nada sobre una web propia.
- Una señal ligada a canal **sin** canal declarado sirve solo para una decisión
  igualmente sin canal. **Si valiera para todos, el relleno de un fixture decidiría
  sobre Amazon**, y eso es precisamente la lectura que había que impedir.

Consecuencia que conviene ver de frente: la competencia de eBay **no puede** entrar
en un score genérico. Y el mock, que no mide en ningún sitio, sigue emitiendo
señales sin canal — honesto, porque atribuirle uno sería afirmar que midió allí — y
por tanto **sigue dando exactamente las mismas cifras que hoy** en una decisión
agnóstica.

### 5. El canal llega al paso de investigación

`discover()` recibe `channels`. Un adaptador que solo sabe de un canal **calla**
cuando no se le pregunta por él, en vez de responder de otro sitio y dejar que quien
lea lo confunda. `None` significa una investigación agnóstica del canal — el
comportamiento de siempre, y por eso nada existente cambia.

El score dice **para qué canal** se calculó, y cuando no puede calcularse dice
**cuál de los dos motivos** lo impidió: una licencia que no permite puntuar (ADR
0015) o una señal que mide otro canal. Se separan porque se arreglan de formas
distintas — uno leyendo un contrato y el otro consiguiendo una fuente del canal que
falta — y confundirlos manda a quien lo lea a resolver el problema equivocado.

### 6. `SEARCH_DEMAND` y `MARKETPLACE_DEMAND` se declaran, y nadie las emite

El plan maestro §8 las distingue y el contrato las había juntado. Se separan ahora
porque con la venta directa como prioridad la confusión deja de ser teórica: el día
que entre una fuente de volumen de búsqueda comercial, su cifra **no puede** caer en
la misma casilla que unas visitas a una enciclopedia.

**Y hay que decirlo claro: nadie las emite todavía.** No hay fuente gratuita fiable
de volumen de búsqueda comercial. Es una extensión declarada y sin emisor, que es
justamente lo que la [ADR 0008 §1](adr-0008-demo-production-isolation.md) aconseja no
hacer, y lo que el Milestone 37 rechazó para `PRICE`. Se hace aquí por una razón
distinta y explícita —evitar que un dato futuro contamine una medida existente— y
con la aprobación expresa del propietario.

**Wikimedia sigue en `DEMAND`**, y su `method` sigue diciendo lo que siempre dijo:
es un proxy de **interés**, nunca intención de compra, nunca volumen de búsqueda
comercial, nunca demanda. Ninguna señal existente se mueve de casilla.

### 7. La equivalencia entre idiomas la declara la fuente

El Milestone 36 dejó escrito y **medido** el límite: aliasar «Freidora de aire» a
«Air fryer» a mano habría cambiado una medición que funciona por un 404, porque
`es.wikipedia` no tiene artículo «Air fryer» y sí tiene «Freidora de aire» con 12.099
visitas en doce meses. Y nombró el mecanismo honesto: los *langlinks* de Wikimedia.

Eso es lo que se implementa. La [ADR 0014](adr-0014-entity-resolution.md) admite dos
vías para la identidad —determinista o declarada— y un langlink es **declarado**: lo
declara Wikimedia, no lo deduce este código de que dos cadenas se parezcan. Cambia
quién firma la declaración, no la regla.

- El **nombre del candidato sigue siendo el canónico**. Si se llamara «Freidora de
  aire», la identidad del Milestone 36 lo trataría como otro producto, y medir cuatro
  mercados daría cuatro productos en vez de uno.
- La consulta que se manda a la fuente es el **título local**, y queda en el `query`
  de cada señal.
- La equivalencia se guarda como alias con su motivo: `langlinks:es.wikipedia`. Una
  fusión sin motivo escrito es indistinguible de un error.
- **Sin equivalencia declarada, ese término no se mide.** Ni se traduce, ni se
  transcribe, ni se busca el artículo más parecido: eso sería la resolución por
  similitud que la ADR 0014 prohíbe.

Verificado contra la fuente real el 28-09-2026: «Air fryer» → `Freidora de aire`
(es), `Heißluftfritteuse` (de), `Friteuse à air chaud` (fr). Y el mercado español
pasa de no medirse a medir **0,6805 de demanda con confianza 0,6491**.

### 8. La fórmula del score no se toca

Separar los ejes de demanda invita a usarlos, y el plan maestro §9 lo prohíbe fuera
de su milestone. La fórmula sigue siendo `demanda × factor de competencia`.

Lo que este milestone **añade como dependencia escrita** para ese milestone futuro:
la fórmula v2 tendrá que decidir **por canal**, porque un factor de competencia sin
canal no significa lo mismo para una web propia que para Amazon; y tendrá que decidir
qué hace con `SEARCH_DEMAND` frente a `DEMAND`.

## Consecuencias

**A favor**

- Una competencia medida en un marketplace ya **no puede** leerse como válida para
  una web propia, ni entrar en un score genérico.
- El mercado español pasa de 404 a medición real, y el mismo producto medido en
  cuatro idiomas sigue siendo **un** producto.
- Añadir un marketplace es una línea de catálogo: **ninguna migración por
  plataforma**, que era la propiedad que había que conservar.
- Un score ausente dice **cuál** de los dos motivos lo impidió.
- El día que exista una fuente de intención comercial, su cifra tiene una casilla
  propia y un canal donde vivir.

**En contra**

- **Dos tipos de señal declarados y sin emisor.** `SEARCH_DEMAND` y
  `MARKETPLACE_DEMAND` son hoy casillas vacías, y una casilla vacía invita a
  rellenarla con lo que haya a mano. El riesgo se mitiga con el `method` y con esta
  ADR, no con código.
- **El canal de la web propia no tiene datos y no los tendrá pronto**: no hay ninguna
  web propia con tráfico real, y no se simula ninguna. El canal prioritario del
  proyecto es hoy el peor medido.
- **La competencia sigue sin medirse para ningún canal que importe.** eBay está
  aparcado y Amazon no tiene camino gratuito, así que un candidato real sigue sin
  score — y ahora además se sabe por qué con precisión.
- **Los langlinks son una dependencia de red más** en el camino de una investigación,
  con su cuota y su contador. Una equivalencia que no llega deja un término sin medir.
- **`LANGUAGE_FOR_MARKET_PROJECT` duplica información** que ya está en
  `PROJECT_FOR_MARKET`, al revés. Escrito aparte a propósito para no invertir un
  diccionario en tiempo de ejecución, y es una cosa más que mantener coherente.
- **El catálogo de canales envejece** como cualquier catálogo declarado: una
  plataforma que cambia de naturaleza —un marketplace que abre superficie social— hay
  que reflejarla a mano.

## Alternativas descartadas

- **Un solo campo con convención y `split(':')` en la lógica.** Es lo que el
  propietario propuso literalmente y funciona; se refinó con el catálogo porque así
  el tipo es un dato y no el resultado de parsear una cadena en cinco sitios.
- **Dos columnas: tipo y plataforma.** Enforzaría el invariante en el esquema, a
  cambio de una columna más y de un campo que solo tiene sentido para algunos tipos.
  Una columna y un catálogo dan lo mismo con menos.
- **Enumerar los marketplaces en el enum.** Cada plataforma nueva sería un cambio de
  contrato, que es exactamente lo que había que evitar.
- **Tratar «sin canal» como «válido para todos los canales».** Es la lectura cómoda y
  la que deja que un fixture decida sobre Amazon.
- **Aliasar los idiomas a mano en el catálogo del Milestone 36.** Medido: cambiaría
  12.099 visitas reales por un 404.
- **Traducir o transcribir un título cuando la fuente no declara equivalencia.**
  Resolución por similitud con otro nombre.
- **Mover Wikimedia a `SEARCH_DEMAND`** ahora que existe la casilla. Mide interés, no
  búsqueda comercial; moverla sería mentir con un nombre nuevo.
