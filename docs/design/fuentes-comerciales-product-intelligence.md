# Fuentes comerciales para Product Intelligence — candidatas para el Milestone 36

**Fecha:** 27-09-2026 · **Contexto:** [ADR 0012](../architecture/adr-0012-product-intelligence-adapters.md) · [ADR 0013](../architecture/adr-0013-signal-evidence-and-comparison.md)

**No se ha contratado ni conectado nada.** Este documento existe para que la
decisión de gasto se tome con datos y para que el Milestone 36 no arranque
investigando proveedores desde cero.

## Por qué hace falta, en una línea

El Milestone 34 conectó la primera fuente real (Wikimedia Pageviews) y el 35 la
contrastó contra el mock. El informe, medido y no supuesto, dice esto:

| | Fixtures | Wikimedia |
|---|---|---|
| Candidatos | 3 | 4 |
| Con señal de demanda | 3 | 4 |
| **Con señal de competencia** | **3** | **0** |
| Puntuables | 3 | **0** |
| Confianza media | 0,30 | **0,71** |
| Señales medidas | 0 | 8 |

Lo medido es más fiable y **no alcanza para puntuar**: sin competencia no hay
`opportunity_score`. Falta una segunda fuente real, y esa segunda fuente ya no
es gratis.

## Cómo leer las fichas

- **Qué evidencia aporta**: qué se podría medir de verdad con ella, no qué
  promete su página.
- **Limitaciones**: lo que NO resuelve. Es la parte que suele descubrirse tarde.
- **Cobertura**: mercados y catálogo.
- **Credenciales**: qué hay que dar de alta, y qué requisitos previos hay.
- **Coste**: **verificado** cuando se ha comprobado en la fuente el 27-09-2026;
  **sin verificar** cuando no. Un coste sin verificar no se estima.

---

## 1. Discovery — encontrar candidatos que nadie ha pensado

Hoy: un catálogo de términos escrito a mano. No descubre; mide lo que ya
sabíamos buscar.

### Jungle Scout / Helium 10 (bases de datos de productos Amazon)

- **Evidencia**: catálogo de productos con ventas estimadas, categoría, reseñas
  y competidores; filtros del tipo «categoría X, ventas > N, menos de M
  reseñas». Es discovery de verdad: propone productos que no le has nombrado.
- **Limitaciones**: las ventas son **estimaciones propietarias** del proveedor,
  no cifras de Amazon; su método no es auditable. Sustituir un número inventado
  por uno estimado y opaco solo mejora si se guarda como lo que es (nuestro
  `method` está preparado para decirlo).
- **Cobertura**: los marketplaces de Amazon principales; fuera de Amazon, nada.
- **Credenciales**: cuenta de pago; el acceso por API suele ser un plan aparte
  del acceso web.
- **Coste**: **sin verificar** (el acceso a su API no tiene precio público
  claro; hay que pedirlo).

### DataForSEO — Google Trends y keyword data

- **Evidencia**: volúmenes de búsqueda y tendencias por término y país, por API.
  Para discovery sirve por sus endpoints de *keyword ideas*: términos
  relacionados que nadie escribió a mano.
- **Limitaciones**: mide **búsqueda**, no compra; y sigue necesitando una
  semilla por categoría, aunque expande mucho más que una lista manual.
- **Cobertura**: amplia por país e idioma.
- **Credenciales**: alta y saldo prepago.
- **Coste**: **verificado** — pago por uso, depósito mínimo de **50 USD**, sin
  cuota recurrente; del orden de **0,60 USD/1.000 peticiones** SERP estándar
  (dataforseo.com/pricing, 27-09-2026).

---

## 2. Intención / búsqueda comercial — cuánta gente busca para comprar

Es el hueco más directo sobre lo que tenemos: Wikimedia mide interés
enciclopédico; esto mediría intención.

### Google Ads Keyword Planner API

- **Evidencia**: volumen de búsqueda mensual y competencia **de anunciantes**
  por término y país, que es lo más cercano a intención comercial que existe de
  forma barata. Además da pujas orientativas: señal de precio del tráfico.
- **Limitaciones**: los volúmenes vienen **en rangos** salvo que la cuenta tenga
  gasto activo; y la «competencia» es competencia publicitaria, no de vendedores.
- **Cobertura**: global, por país e idioma.
- **Credenciales**: cuenta de Google Ads + *developer token* aprobado por
  Google. El token de prueba solo funciona contra cuentas de prueba.
- **Coste**: la API no se cobra aparte; el requisito real es tener una cuenta de
  Ads con actividad. **Sin verificar** cuánta actividad exige hoy.

### SerpApi (y equivalentes de scraping de resultados)

- **Evidencia**: la página de resultados real: quién aparece, anuncios,
  *shopping*, preguntas relacionadas. Señal de competencia y de intención.
- **Limitaciones**: es una foto de resultados, no una serie histórica; para
  tendencia hay que construir la serie uno mismo, consultando periódicamente.
- **Cobertura**: global.
- **Credenciales**: alta y clave de API.
- **Coste**: **verificado** — desde **25 USD/mes** por 1.000 búsquedas
  (serpapi.com/pricing, 27-09-2026).

---

## 3. Ventas — cuánto se vende de verdad

### Amazon SP-API (Selling Partner API)

- **Evidencia**: la única fuente de **ventas reales** a la que se puede aspirar…
  **de tus propias ventas**. No dice cuánto vende un competidor.
- **Limitaciones**: exige ser vendedor con cuenta activa. No sirve para
  investigar un producto que todavía no vendes, que es justo lo que hace el
  pipeline hoy. Entra en escena cuando AMAZONA venda.
- **Cobertura**: los marketplaces donde tengas cuenta.
- **Credenciales**: cuenta de Seller Central + aplicación registrada + revisión
  de Amazon. Trámite, no formulario.
- **Coste**: la API es gratuita; el coste es la cuenta de vendedor.

### Amazon Creators API (antes Product Advertising API)

- **Evidencia**: catálogo, precios y disponibilidad de Amazon por ASIN.
- **Limitaciones**: **PA-API 5 está descontinuada** y devuelve 403 remitiendo a
  Creators API. Y el acceso exige ventas de afiliado: **10 ventas cualificadas
  en los últimos 30 días** (documentación de Amazon Associates, 27-09-2026).
  Es decir: hay que tener ya un negocio de afiliación en marcha.
- **Cobertura**: marketplaces de Amazon.
- **Credenciales**: alta en Amazon Associates del mercado correspondiente.
- **Coste**: gratuita; el requisito es la actividad, no el dinero.

---

## 4. Competencia — cuántos venden esto y cómo de fuerte

**Este es el hueco que impide puntuar.**

### Keepa

- **Evidencia**: histórico de precio, *Buy Box*, rango de ventas y número de
  vendedores por ASIN, con años de profundidad. Para competencia y precio es
  probablemente la mejor relación evidencia/coste del mercado.
- **Limitaciones**: solo Amazon. El *sales rank* es un ranking, no unidades: la
  conversión a ventas es una estimación, y si se usa hay que guardarla como
  estimación.
- **Cobertura**: los marketplaces de Amazon, con histórico largo.
- **Credenciales**: suscripción de API con clave.
- **Coste**: **verificado** — el plan de API más pequeño es **49 €/mes** (20
  *tokens*/minuto), y sube por tramos hasta miles de euros
  (keepa.com/api-docs/plans-tokens, 27-09-2026). La suscripción web (≈19-29 €/mes)
  **no** incluye API.

### SERP / *shopping results* (SerpApi, DataForSEO)

- **Evidencia**: cuántos vendedores y qué marcas aparecen para una consulta
  comercial. Competencia fuera de Amazon.
- **Limitaciones**: foto puntual; hay que construir el histórico.
- **Coste**: ver §2 y §1.

---

## 5. Precios — a cuánto se vende realmente

- **Keepa** (§4) para Amazon, con histórico.
- **DataForSEO / SerpApi** *shopping* para distribución de precios fuera de
  Amazon.
- **Limitación común**: el precio de escaparate no es el precio al que se cierra
  una venta, y ninguno da coste de adquisición. El margen sigue dependiendo del
  dato de proveedor, que es otro dominio (`suppliers`, plan maestro §10).

---

## 6. Reviews y tendencias — qué problema tiene el producto

- **Evidencia**: minería de reseñas para encontrar quejas recurrentes, que es
  una de las fuentes de oportunidad más honestas que hay (el §8 del plan lo
  llama *review/problem mining*).
- **Candidatas**: Keepa y las bases de datos de Amazon dan recuento y media;
  **el texto** de las reseñas lo dan raspadores comerciales (Oxylabs, Bright
  Data, Traject) o el propio SP-API para tus productos.
- **Limitaciones**: raspar reseñas tiene condiciones de uso que hay que leer
  antes, no después; y analizar texto mete un LLM en el camino, con su coste y
  su necesidad de trazabilidad (plan maestro §26).
- **Gratis y real, para tendencias sociales**: la API pública de Reddit permite
  lectura básica identificándose. Es señal social de verdad y sin coste, aunque
  ruidosa y sesgada por comunidad. Es la candidata natural a **segundo
  adaptador gratuito** si se quiere posponer el gasto.
- **Coste**: **sin verificar** para los raspadores comerciales.

---

## 7. Marketplace data — qué pasa dentro de cada canal

- **Amazon**: Keepa (§4), SP-API (§3), Creators API (§3).
- **eBay**: Browse y Marketplace Insights APIs; la segunda —precios de venta
  reales— requiere aprobación caso por caso.
- **Etsy, AliExpress, Mercado Libre**: APIs propias, cada una con su alta.
- **Limitación común**: un adaptador por marketplace, cada uno con su modelo de
  datos. Es donde más se nota tener un contrato de señales (ADR 0012): cada uno
  aporta lo suyo y dice de dónde sale.
- **Coste**: **sin verificar**.

---

## Lectura recomendada de todo esto

1. **Si el objetivo es poder puntuar** (cerrar el hueco de competencia con el
   menor gasto y el menor trámite): **Keepa**, 49 €/mes verificados, señal de
   competencia y precio con histórico. Es un adaptador, una clave y ningún
   requisito previo de negocio.
2. **Si el objetivo es intención comercial** más que competencia: **Google Ads
   Keyword Planner** si ya hay cuenta de Ads con actividad, o **DataForSEO** a
   50 USD de saldo si no.
3. **Si el objetivo es no gastar todavía**: **Reddit** como segundo adaptador
   —señal social real y gratuita— aceptando que no cierra el hueco de
   competencia y que el score seguirá sin poder calcularse.

**Antes de conectar cualquiera de las tres hace falta resolver la identificación
de entidades** (ADR 0013): con dos fuentes reales, componer sin resolver
duplica candidatos en vez de enriquecerlos.

Ninguna de estas fuentes cambia por sí sola el `opportunity_score`: esa fórmula
tiene su propio milestone (plan maestro §9) y no se toca al añadir datos.
