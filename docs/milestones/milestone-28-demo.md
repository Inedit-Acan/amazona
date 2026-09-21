# Milestone 28 Demo — Rediseño de los paneles restantes

**Origen:** petición directa de Ivan — llevar al lenguaje visual del shell
rediseñado (Panel general, Director ejecutivo, Investigación) el resto de
paneles, en el orden de `nav-items.ts`, tomando los mockups de
`docs/design/*.png` como referencia principal de estructura y las specs
(`v0.5.md` / `parte2.md`) como fuente funcional. Un commit por panel.
**Sin ADR nueva.** Regla de oro: ninguna cifra, tendencia o gráfico que el
backend no proporcione realmente — lo que no tiene dato se marca
`DataProvenanceBadge status="pending"` o se omite.

Estado agregado de todos los paneles (hecho / fuera de alcance / backend que
faltaría): [`docs/design/AMAZONA_estado_paneles_rediseno.md`](../design/AMAZONA_estado_paneles_rediseno.md).

---

## Panel 1 — Proveedores y abastecimiento (`/sourcing`)

Mockup: `docs/design/panel proveedores.png`. Spec: `v0.5.md` §6.

### Qué se entrega

`app/sourcing/page.tsx` pasa de un formulario + lista de tarjetas a un panel
completo con la estructura del mockup, montado sobre `SourcingWorkspace`
(`app/sourcing/sourcing-workspace.tsx`). La página ahora es un Server Component
que carga los productos reales (`GET /api/products`, endpoint que existía pero
el frontend no consumía) y lee `?product_id=` de la URL — así el handoff desde
Investigación preselecciona el producto en lugar de pedir pegar un ID a mano.

Bloques del mockup y de dónde sale cada dato:

| Bloque | Datos reales que lo alimentan |
|---|---|
| Producto seleccionado | `Product` (nombre, categoría, estado, origen) + región de destino elegida |
| Parámetros de búsqueda | Solo lo que admite el backend: región de destino y nº de resultados. Precio/plazo/MOQ máx. son **filtros sobre los resultados reales** (cliente) |
| Resumen de la búsqueda | Contadores derivados de la respuesta: analizados, preseleccionados (tras filtros), verificados, descartados por filtros |
| Proveedores recomendados | Los 3 de menor coste entregado; gauge de fiabilidad, precio, coste entregado, MOQ, plazo, verificación; distinciones **calculadas** ("Menor coste entregado", "Más fiable", "Plazo más corto", "Menor MOQ") |
| Mapa de proveedores | Regiones de origen/destino del backend sobre geometría real de países (Natural Earth); ruta seleccionada con plazo y coste logístico reales |
| Listado de proveedores | `DataTable`: búsqueda, orden, selección, export CSV de las columnas reales |
| Coste total estimado | `unit_price` + `logistics_cost_per_unit` = `total_landed_cost_per_unit` (los 3 valores vienen del backend) |
| Compatibilidad con Amazona | 2 de 9 criterios con dato (verificado; MOQ contra el límite que fija el usuario); el resto, "Pendiente" |
| Score de proveedor | `RadarChart` con 5 ejes derivables: precio, logística, fiabilidad, flexibilidad (MOQ), rapidez (plazo) |
| Siguiente paso en el flujo | Navegación real a `/economics?product_id&supplier_quote_id` |

### Componentes nuevos (reutilizables en los demás paneles)

- `ScoreGauge` — medidor semicircular (ReadinessScore del catálogo §4). El número
  siempre va escrito; el color solo refuerza.
- `DataTable` — búsqueda, orden por columna, selección de fila, export CSV,
  estado vacío. Lo necesitarán Legal, Operaciones, Finanzas, Auditoría.
- `NextStepBar` — barra "Siguiente paso en el flujo" que cierra los mockups del
  pipeline.
- `RouteMap` — mapa mundial con puntos y rutas; puramente presentacional
  (recibe puntos/rutas y coordenadas, no conoce proveedores).
- Lógica pura y testeada en `lib/`: `sourcing.ts` (orden, filtros,
  distinciones, normalización del radar), `csv.ts`, `regions.ts`.
- `lib/api.ts`: `Product` + `listProducts()`, y `ApiError.detail` (extrae el
  `{"detail": "..."}` de FastAPI en vez de mostrar el JSON crudo).

Dependencias nuevas: `d3-geo`, `topojson-client`, `world-atlas` (datos
estáticos, sin claves ni llamadas externas) y sus `@types`.

### Decisiones de alcance (lo que el mockup muestra y NO se inventó)

- **Sin divisa.** El mockup usa €; el backend no especifica moneda. Los importes
  se muestran sin símbolo, con la aclaración explícita en el bloque de coste.
- **"Score proveedor 91/100" del mockup → "Fiabilidad".** El único score real
  por proveedor es `reliability_score` (valor nominal del directorio simulado).
  No se calculó ningún score compuesto: sería inventar una fórmula. Va marcado
  `estimated`.
- **"Proveedor recomendado / Mejor opción UE / Mejor precio" → distinciones
  calculadas** comparando los resultados reales (no hay recomendación por
  proveedor en el backend).
- **Resumen "127 / 18 / 5 / 104" → contadores reales** de esta búsqueda
  (3 / 3 / 2 / 0 con el fixture de electrónica). "Recomendados" pasa a
  "Verificados"; "Descartados" son solo los descartados por los filtros del usuario.
- **Sin imagen de producto, descripción, ciudad del proveedor, bandera,
  Incoterms, certificaciones, envío directo, transporte (aéreo/marítimo),
  almacén ni "Modo de búsqueda"** — ningún campo real los respalda. Certificaciones
  y compatibilidad quedan como "Pendiente" (una sola vez por bloque, no en cada
  tarjeta); los filtros avanzados aparecen deshabilitados con su badge.
- **Landed cost desglosado en 7 líneas → 2 líneas + total.** El backend solo
  persiste logística+aduana agregadas (aunque `estimate_logistics_cost` calcula
  flete y factor de aduana por separado, no se guardan). Reconstruirlos en el
  cliente habría duplicado constantes privadas del backend.
- **Investigación 92/100 → "Pendiente".** No existe endpoint que devuelva el
  score de investigación de un producto.
- **Mapa esquemático por región, no por ciudad.** El backend solo conoce
  regiones (`china`, `vietnam`, `mexico`, `eu`); el pin marca la región usando
  un ancla cartográfica fija (documentada en `lib/regions.ts`), no un dato del
  backend.
- **Sin paginación.** El directorio devuelve 2-3 proveedores por categoría;
  paginar 5 por página sería ruido.
- **Orden en el cliente.** `GET /api/sourcing/runs/{id}` no lleva `ORDER BY`; el
  ranking por coste entregado se reaplica en el cliente.

### Verificación

- `tsc --noEmit` limpio; `npm test` 17/17 (9 nuevos sobre la lógica pura:
  orden, filtros, distinciones con empates y con un único proveedor,
  normalización del radar y rango 0-1, CSV con comillas/comas/saltos de línea);
  `npm run build` correcto; `eslint` limpio sobre todos los archivos de este
  panel. El `eslint` global falla por un error preexistente en
  `components/top-header.tsx` (setState síncrono en un efecto; archivo sin
  commitear ajeno a este panel).
- **Verificado en navegador con datos reales del sistema** (no maquetas): backend
  aislado con SQLite (puerto 8001, sin tocar Supabase) + copia del frontend en
  otro puerto (3100). Búsqueda real para "Wireless earbuds pro" → 3 proveedores;
  probado: preselección por `?product_id=`, selección de proveedor (actualiza
  mapa, coste y radar), comparación de dos proveedores en el radar, filtro de
  MOQ (contadores y tarjetas se recalculan, la fila de compatibilidad evalúa el
  límite), búsqueda y orden de la tabla (`aria-sort`), estado "ningún proveedor
  cumple los filtros" + "Limpiar filtros", exportación CSV (contenido y nombre de
  fichero), y la ruta de error del backend (alerta con el `detail` legible).
  Layout revisado a 1440 px (escritorio, prioridad 1), y móvil 375 px sin
  desbordamiento horizontal.

### Qué sigue

Paneles 2 a 9 (abajo), luego Panel 10 — Aprobaciones.

---

## Panel 2 — Economía y rentabilidad (`/economics`)

Referencia: `docs/design/economia y rentabilidad.png` + v0.5 §7.

### Qué se ve ahora

1. **Producto y proveedor**: selector de producto (se recargan sus cotizaciones
   reales con `GET /api/products/{id}/suppliers`), selector de cotización
   (deduplicada por proveedor: cada nueva búsqueda de proveedores crea filas
   repetidas) y resumen de la cotización (precio, logística+aduana, coste
   entregado, plazo, MOQ). Preselección por `?product_id=&supplier_quote_id=`,
   que es lo que envía el botón «Analizar economía» de Proveedores.
2. **Supuestos del análisis**: precio de venta y costes fijos mensuales; «Ejecutar
   análisis» llama a `POST /api/economics/runs`.
3. Tras el análisis (todo sale de la respuesta del backend o de la cotización):
   - 6 KPIs: precio de venta, coste total por unidad, margen de contribución,
     beneficio estimado (mes), punto de equilibrio (**pendiente**), riesgo
     económico (la recomendación GO/REVIEW/NO_GO traducida).
   - **Comparativa de escenarios**: 3 `ScenarioCard` (conservador/base/optimista)
     + gráfico de barras del beneficio por escenario (el base, destacado).
   - **Desglose económico por unidad**: precio, producto/proveedor, logística y
     aduana, coste de entrega, margen de contribución, costes fijos; las líneas
     sin dato (pasarela, devoluciones, CAC, fulfillment) salen con badge
     «Pendiente».
   - **Viabilidad económica**: veredicto, beneficio por escenario (✓/✗), lista de
     riesgos (`RiskList`) y dos CTAs reales: «Enviar a revisión legal» y
     «Validar con el Director ejecutivo» (precarga el coste entregado real).
   - **Análisis avanzado**: simulador, sensibilidad, punto de equilibrio, riesgo y
     capital — tarjetas deshabilitadas con badge «Pendiente».
   - `NextStepBar`: Economía validada → Revisión legal → Plan de lanzamiento →
     Seguimiento de resultados.

### Componentes nuevos / tocados

- `ScenarioCard`, `BarChart` (una serie, valores negativos, extremo de datos
  redondeado, vista de tabla, etiqueta en cada barra) en `components/`.
- `KpiCard`: prop `provenanceTooltip`, y el badge de procedencia pasa a ir
  debajo del valor (con 6 tarjetas por fila el valor y el badge lado a lado no
  cabían). Cambia también las tarjetas del resto de paneles que lo usan.
- `lib/format.ts` (nuevo): `formatAmount`, `formatInteger`, `formatPercent`,
  todos con separador de miles (es-ES no lo pone en números de 4 cifras si no se
  fuerza `useGrouping`). Proveedores pasa a usarlos.
- `lib/economics.ts` + tests: lista de escenarios, contribución unitaria,
  etiquetas de recomendación, texto de viabilidad, deduplicado de cotizaciones.

### Qué se dejó fuera (y por qué)

Regla del Milestone 16: **el cliente no reimplementa el motor económico**. Por eso
no hay simulador, sensibilidad ni break-even aunque el mockup los muestre: habría
sido duplicar la lógica de `economics/` en el navegador.

- Punto de equilibrio (unidades, facturación, días, CAC máximo, precio mínimo).
- Simulador interactivo, análisis de sensibilidad, riesgo y capital.
- CAC, pasarela de pago, devoluciones y fulfillment en el desglose unitario.
- Los 3 escenarios del backend solo varían el **volumen** de ventas; el mockup
  muestra escenarios con precio/coste/CAC distintos. Se muestran tal cual, sin
  disfrazarlos.
- Score de investigación, imagen y descripción del producto; divisa.
- Persistir los supuestos (precio de venta, costes fijos): hoy solo viven en la
  ejecución del análisis.

### Verificación

- `tsc --noEmit` limpio; `npm test` 25/25 (8 nuevos: contribución unitaria, el
  caso de la spec §7.10, deduplicado, etiquetas, formato); `npm run build`
  correcto; `eslint` limpio sobre los archivos de este panel.
- **En navegador con datos reales** (mismo stack aislado que el panel 1): los
  importes en pantalla coinciden exactamente con la respuesta cruda de
  `POST /api/economics/runs` (margen 0,8026 → «80,3 %»; beneficios 4.665,57 /
  6.879,38 / 9.093,20; GO con confianza 85 %). Móvil 375 px sin desbordamiento,
  antes y después de ejecutar el análisis.

### Qué sigue

Panel 3 — Legal y cumplimiento.

---

## Panel 3 — Legal y cumplimiento (`/legal`)

Referencia: `docs/design/legal y cumplimiento.png` + v0.5 §8.

### Qué se ve ahora

1. **Producto y contexto**: selector de producto, cabecera del producto real y
   cuatro datos de contexto — proveedor (el de la cotización con la que se hizo el
   análisis) y mercado objetivo reales; modelo logístico y canal previsto con badge
   «Pendiente».
2. **Parámetros del análisis**: mercado (EE. UU. / UE / México) y la declaración
   «ya se cuenta con las certificaciones requeridas» → `POST /api/legal/runs`.
3. **Se muestra el último análisis guardado**: la página ya no arranca vacía; carga
   `GET /api/products/{id}/legal` y enseña el más reciente del mercado elegido
   (cambiar de mercado o de producto cambia el análisis mostrado sin volver a
   ejecutarlo).
4. Con análisis:
   - 6 KPIs: cumplimiento general (**pendiente**), riesgo legal (nº de riesgos),
     certificaciones (nº exigidas y si se declararon), evidencias documentales
     (**pendiente**), cambios regulatorios (nº y fecha del último) y **Legal Gate**
     (Bloqueado / Requiere revisión humana / Preparado, con color de veredicto).
   - **Matriz de requisitos legales**: una fila por certificación exigida (mercado,
     estado, evidencia, fuente) y si la categoría está restringida.
   - **Legal Gate y decisión**: veredicto, motivos «a resolver antes de continuar»
     (categoría restringida, certificaciones sin acreditar) y CTA «Validar con el
     Director ejecutivo» (el handoff a `/ceo` de siempre).
   - **Riesgos legales** (`RiskList`), **inteligencia regulatoria** (línea de tiempo
     de los cambios normativos), **borrador de términos y condiciones** (el que ya
     existía).
   - Tarjeta «Pendiente de backend» con lo que el mockup enseña y no hay de dónde
     sacar, y `NextStepBar` con «Generar tienda» (deshabilitado si el Legal Gate está
     bloqueado).

### Componentes nuevos / tocados

Este panel es el segundo en repetir patrones del primero, así que se extrajeron a
`components/` y **Economía se refactorizó para usarlos**:

- `SectionNav` (pestañas-ancla; las secciones sin datos salen deshabilitadas con
  motivo), `PendingFeatures` (tarjeta «pendiente de backend»), `VerdictBanner`
  (veredicto con tono; lo usan la viabilidad económica y el Legal Gate),
  `ProductHeader` (cabecera del producto).
- `KpiCard`: prop `tone` (success / warning / danger) para tarjetas cuyo valor es
  un veredicto.
- `lib/legal.ts` + tests: estados del Legal Gate, filas de requisitos, motivos,
  cambios ordenados, último análisis por mercado.

### Qué se dejó fuera (y por qué)

- **Cumplimiento general (82 %)**, **criticidad** por requisito (Crítico/Alto/…),
  filtros por criticidad y matriz **probabilidad × impacto**: el agente solo devuelve
  una recomendación GO/REVIEW/NO_GO, sin puntuar nada.
- **Evidencias y documentos** (declaración de conformidad, informes, manuales, hash,
  versión): no existe almacén de documentos. Las certificaciones se muestran como
  «Declarada por ti, sin evidencia», nunca como «Verificado».
- **Fuentes regulatorias** (Comisión Europea, Access2Markets, ECHA, Safety Gate,
  legislación nacional) con «última consulta»: hoy hay un único dataset simulado.
- **Rol en la operación** y **mapa de responsabilidades** (fabricante, importador…).
- **Clasificación de cambios** crítico/relevante/informativo y filtro «últimos 30
  días».
- Modelo logístico, canal previsto, imagen y descripción del producto.
- Los textos del dataset (riesgos, cambios) están en inglés en el backend; se
  muestran tal cual y se avisa.
- «Preparado» solo significa que el análisis simulado no bloquea; el texto lo dice y
  nunca se muestra «100 % legal» (spec §8.11).

### Verificación

- `tsc --noEmit` limpio; `npm test` 31/31 (6 nuevos: Legal Gate, certificaciones
  declaradas, filas, motivos, orden de cambios, análisis por mercado); `npm run build`
  correcto; `eslint` limpio sobre los archivos del panel y los componentes
  compartidos.
- **En navegador con datos reales** (stack aislado, sin Supabase): el análisis de
  «Wireless earbuds pro» en UE muestra exactamente lo que devuelve
  `POST /api/legal/runs` (2 certificaciones CE/RoHS pendientes, 3 riesgos, 1 cambio,
  Requiere revisión humana, proveedor mexicano de la cotización usada). Probado:
  cambio de producto (carga el historial guardado; «Minimalist phone case» en UE →
  Bloqueado con «Categoría restringida» + «REACH sin acreditar», y «Generar tienda»
  deshabilitado), declarar certificaciones y reanalizar (→ Preparado, fila
  «Declarada por ti»), cambio de mercado (estado vacío, luego «0 requeridas» sin
  motivos), recarga (se recupera el análisis guardado) y el error del backend
  (alerta legible, el análisis mostrado no se pierde). Economía se volvió a
  comprobar tras el refactor. Móvil 375 px sin desbordamiento de página (la tabla
  de requisitos desplaza dentro de su contenedor).

### Qué sigue

Panel 4 — Tienda y canales de venta.

---

## Panel 4 — Tienda y canales de venta (`/ecommerce`)

Referencia: `docs/design/tienda y canales de venta.png` + v0.5 §9. Esta pantalla ya
fusionaba «Tienda propia» y «Amazon» (Milestone 16); ahora se organiza como el
mockup: contexto, tarjetas de canal y el detalle del canal elegido.

### Qué se ve ahora

1. **Producto y contexto**: selector de producto y de mercado (EE. UU. / UE / México)
   y cinco datos de contexto: precio y proveedor del análisis económico más
   reciente, mercado objetivo, **Legal Gate** del mercado (desde `LegalAnalysis`) y
   modelo logístico (**pendiente**). Sin análisis económico o legal, enlace directo a
   Economía / Legal.
2. **Canales de venta**: tarjetas de Tienda propia y Amazon con el estado real del
   último borrador del mercado (`launch_status` / `listing_status`) y su botón
   «Generar / Regenerar»; Google Shopping y TikTok Shop salen como «Pendiente»
   (sin integración). Se elige el canal pulsando su tarjeta.
3. **Tienda propia** (`Storefront`): constructor de página con vista previa real del
   texto generado y conmutador Desktop / Mobile, checkout y pagos (pasarela y pasos
   hasta salir en vivo del plan del agente), **Launch readiness** (veredicto,
   riesgos y checklist de la spec §9.10: producto, precio, página, checkout, legal
   con datos reales; analytics, tracking, dominio y emails como «Pendiente»),
   configuración por mercado (un borrador por mercado), contenido generado (qué
   piezas trae el borrador y cuáles no), producto maestro (SKU, categoría, plazo de
   entrega, categoría restringida) y consejos de conversión.
4. **Amazon** (`MarketplaceListing`): contenido del listado, comisiones del canal
   (con margen neto por unidad), análisis de competencia, estado, política de
   inventario y riesgos, y «Planificar campaña de marketing».
5. La página carga el historial guardado del producto (tiendas, listados, legal,
   economía y cotizaciones), así que ya no arranca vacía; `?product_id=&market=`
   preselecciona producto y mercado (los enlaces desde Economía y Legal siguen
   funcionando).

### Componentes nuevos / tocados

- Reutilizados de los paneles 1–3: `ProductHeader`, `SectionNav`, `PendingFeatures`,
  `VerdictBanner`, `DataTable`, `StatusChip`, `RiskList`, `NextStepBar`,
  `DataProvenanceBadge`.
- Nuevos módulos compartidos: `lib/markets.ts` (etiquetas de mercado y «último por
  mercado», movidos de `lib/legal.ts`) y `lib/product-channels.ts` (carga de todo lo
  persistido de un producto, usable desde servidor y cliente).
- `lib/ecommerce.ts` + tests: checklist de Launch Readiness, checklist de contenido
  generado y filas por mercado.
- La tarjeta de canal es local a la pantalla (`ChannelCard`): Marketing la puede
  extraer si le hace falta.

### Qué se dejó fuera (y por qué)

- **Imagen y descripción del producto, galería y multimedia**: el backend no guarda
  ni genera imágenes; la vista previa lo dice en lugar de dibujar una foto.
- **Score de investigación**, **% de readiness por canal** y **calidad del
  escaparate** (91/100 con siete sub-scores): el backend no calcula ninguno.
- **Funnel de compra estimado / real** y conversión: sin tráfico ni datos de
  mercado (el funnel del mockup no tiene fuente).
- **Modo de checkout y métodos de pago** elegibles (tarjeta, Apple Pay, Google Pay,
  PayPal…): el plan de pasarela es un texto por mercado, no una configuración.
- **Editar contenido, SEO, Diseño, Páginas y A/B testing** del constructor; «Generar
  con IA» (el generador es una plantilla determinista, no IA): el botón se llama
  «Generar tienda» y la vista previa lleva el badge de estimación.
- **Idioma y disponibilidad por mercado**, **EAN/GTIN, peso, dimensiones y stock del
  proveedor**, **analytics, tracking, dominio y emails**.
- **Google Shopping, TikTok Shop** y «Añadir canal»: sin integración.
- **«Solicitar aprobación de lanzamiento»**: no existe un endpoint que cree esa
  solicitud; el botón sale deshabilitado con badge «Pendiente». La acción real
  siguiente es «Planificar campaña de marketing».
- Los textos de la plantilla del agente (titular, viñetas, consejos, riesgos) están en
  inglés en el backend; se muestran tal cual y se avisa.

### Verificación

- `tsc --noEmit` limpio; `npm test` 37/37 (5 nuevos de `lib/ecommerce.ts` y 2 de
  `lib/markets.ts`, uno de ellos movido desde `lib/legal.test.ts`);
  `npm run build` correcto; `eslint` limpio sobre los archivos del panel.
- **En navegador con datos reales** (stack aislado, sin Supabase): «Wireless earbuds
  pro» en la UE. Contexto correcto (precio 20,00, proveedor Hanoi Circuit Works,
  Legal Gate «Requiere revisión humana»); generación de la tienda (vista previa con
  el texto del backend, pasarela Stripe/Adyen en modo prueba, «Requiere revisión»
  porque el legal pide revisión humana, checklist con Legal «requiere revisión
  humana»); el conmutador Desktop/Mobile cambia la vista previa (599 → 300 px);
  generación del listado de Amazon con cifras idénticas a
  `GET /api/products/{id}/marketplace-listings` (8 %, 3,50, margen neto 8,998 →
  «9,00», 120 competidores, 22,50, 4,2, buy-box «high»); cambio de mercado (estados
  vacíos por canal); cambio de producto («Minimalist phone case»: Legal Gate
  «Preparado», sin análisis económico → el riesgo «no economic analysis found»
  aparece y «Precio: falta el análisis económico»); el error del backend (alerta
  legible sin perder lo mostrado). Móvil 375 px sin desbordamiento.

### Qué sigue

Panel 5 — Marketing y adquisición.

---

## Panel 5 — Marketing y adquisición (`/marketing`)

Referencia: `docs/design/marketing.png` + v0.5 §11. Es el panel cuyo mockup está más
lejos de lo que el backend sabe: el mockup enseña rendimiento **real** de campañas
(inversión, ingresos atribuidos, CAC, funnel, atribución) y el agente solo genera una
**propuesta simulada** por producto, mercado y plataforma. Se construye lo que la
propuesta trae y lo demás queda como pendiente.

### Qué se ve ahora

1. **Producto y contexto**: selector de producto y de mercado; precio y margen de
   contribución del análisis económico más reciente, estado de la tienda (landing) y
   Legal Gate del mercado (con enlace a Economía / Tienda / Legal si faltan); CAC
   máximo (**pendiente**).
2. **Nueva campaña**: canal (Meta Ads / Google Ads) y presupuesto diario →
   `POST /api/marketing/runs`. El canal elegido también decide qué propuesta se
   muestra abajo. Los campos del mockup que el agente no acepta (objetivo, evento de
   conversión, duración, CAC objetivo/máximo) se anuncian como no configurables.
3. **Plan de adquisición por canal**: una fila por plataforma con la última propuesta
   del mercado (presupuesto diario, ROAS proyectado, estado); pulsar una fila la
   selecciona.
4. Con propuesta:
   - 6 KPIs: presupuesto diario (supuesto tuyo), ROAS proyectado, CPC, CTR y
     conversión **estimados** (todos con badge de estimación y el `data_origin` del
     backend) y estado general con tono de veredicto.
   - **Audiencias propuestas** (segmentos reales con edad, intereses y alcance
     relativo) y **creatividad y vista previa** (titular, texto, CTA y brief de imagen
     reales, con vista previa del texto en formato Meta feed o Google búsqueda).
   - **Recomendación del agente** (veredicto, recomendación de presupuesto y riesgos)
     con la acción real de aprobar el gasto: «Validar inversión con el Director
     ejecutivo» (handoff a `/ceo` con `spend_amount`, el de siempre).
   - **Presupuesto y guardrails**: presupuesto asignado y las reglas que el agente
     aplica hoy (NO_GO económico/legal, ROAS < 1, falta de análisis, listado
     bloqueado, plazo > 45 días).
   - Tarjeta «Rendimiento real — pendiente de backend» y `NextStepBar` con «Simular
     operaciones».
5. Carga el historial guardado del producto; `?product_id=&market=` (que envían
   Tienda y Amazon) preselecciona producto y mercado.

### Componentes nuevos / tocados

- Reutilizados: `ProductHeader`, `KpiCard` (con `tone`), `PendingFeatures`,
  `VerdictBanner`, `DataTable`, `StatusChip`, `RiskList`, `NextStepBar`,
  `DataProvenanceBadge`.
- `lib/product-channels.ts`: `loadProductMarketingData` (lo de Tienda + campañas).
- `lib/marketing.ts` + tests: etiquetas de plataforma, última propuesta por
  plataforma/mercado, plan por canal, barras de audiencia, veredicto y reglas del
  agente.

### Qué se dejó fuera (y por qué)

- **Inversión, ingresos atribuidos, CAC/CPA, conversiones, ROAS reales, funnel de
  conversión, rendimiento por canal y atribución**: no hay integración con Meta,
  Google ni TikTok Ads, y por tanto no hay gasto ni tráfico. Mostrar cualquier cifra
  aquí sería inventarla.
- **Distribución del presupuesto en % por canal**, Creators/Influencers y TikTok Ads:
  el backend genera una propuesta por plataforma (solo Meta y Google) sin repartir
  presupuesto.
- **Score, intención y fuente de las audiencias**; remarketing y lookalike.
- **Vídeos, imágenes, Creative Score, variantes y estado de aprobación de las
  creatividades**: el agente genera un único texto con un brief de imagen, nunca un
  bitmap. Las pestañas Instagram y TikTok de la vista previa salen deshabilitadas.
- **CAC máximo y CAC objetivo**: el motor económico no los calcula.
- **Pacing, gastado y restante**, y los guardrails que necesitan gasto real (pausar
  por CAC, limitar subidas bruscas, bloquear claims y mercados no autorizados).
- **Recomendaciones de IA basadas en rendimiento real** (subir inversión en Meta,
  A/B de creatividades…): solo existe la recomendación de presupuesto del agente, que
  sale de su ROAS proyectado.
- **«Solicitar aprobación de inversión»**: no existe un endpoint que cree esa
  solicitud; el camino real es validar el gasto con el Director ejecutivo.
- Los textos de la plantilla (creatividad, recomendación, riesgos) están en inglés en
  el backend; se muestran tal cual y se avisa.

### Verificación

- `tsc --noEmit` limpio; `npm test` 41/41 (4 nuevos de `lib/marketing.ts`); `npm run
  build` correcto; `eslint` limpio sobre los archivos del panel.
- **En navegador con datos reales** (stack aislado, sin Supabase): «Wireless earbuds
  pro» en la UE. La propuesta de Meta con 20 de presupuesto coincide con
  `GET /api/products/{id}/campaigns` (ROAS 0,4706 → «0,47 x», CPC 0,85, CTR 1,2 %,
  conversión 2,0 %, estado BLOQUEADA, mismo riesgo y misma recomendación, alcances
  250.000 y 120.000). Probado: pestañas de la vista previa (Meta/Google), canal sin
  propuesta (estado vacío), generar la de Google con 50 de presupuesto (ROAS 0,55 y
  la vista previa se abre en formato Google), selección de fila en el plan (vuelve a
  Meta) y el error del backend (alerta legible sin perder lo mostrado). Móvil 375 px
  sin desbordamiento.

### Qué sigue

Panel 6 — Operaciones.

---

## Panel 6 — Operaciones (`/operations`)

Referencia: `docs/design/operaciones.png` + parte 2 §3. La spec define este panel
como el **Control Tower operativo** («no debe ser un generador manual de informes»),
pero el backend solo tiene un agente que **simula un pedido de muestra**: no existen
pedidos, clientes, transportistas, incidencias de pedido ni ticketing reales. Es el
panel con más distancia entre mockup y datos: se construye lo que el informe trae y
el resto se declara pendiente, sin rellenar un Control Tower con cifras inventadas.

### Qué se ve ahora

1. **Producto y contexto**: selector de producto y mercado, botón «Generar
   simulación operativa» (→ `POST /api/operations/runs`) y cinco datos de contexto:
   precio, proveedor (con región y plazo) y Legal Gate reales, estado de la campaña
   del mercado, y «Pedidos reales» como **pendiente**.
2. Con informe (uno por producto y mercado; carga el historial guardado):
   - 6 KPIs: estado de la operación (tono de veredicto), pedido de muestra (id y
     unidades), entrega prevista (día N desde el pedido), ventana de devolución,
     cargo de reposición y reembolso estimado.
   - **Seguimiento del pedido de muestra**: línea de tiempo con las cinco etapas del
     agente (pedido, proveedor procesa, despachado, en reparto, entregado) y sus días,
     más los tiempos derivados de esas diferencias (procesamiento, hasta el despacho,
     tránsito, total).
   - **Proveedor y modelo sin stock**: proveedor, plazo usado y plazo real, si está
     verificado, y el cobro al cliente / pago al proveedor / logística del pedido de
     muestra (precio de venta y cotización reales).
   - **Devoluciones** (política del mercado), **soporte postventa** (triaje IA vs
     persona de un ticket de ejemplo) y **estado y riesgos**.
   - Tarjeta «Control Tower — pendiente de backend» con las diez piezas del mockup que
     no tienen fuente, y `NextStepBar` hacia Finanzas y control.
3. `?product_id=&market=` (que envía Marketing con «Simular operaciones») preselecciona
   producto y mercado.

### Componentes nuevos / tocados

- Todo reutilizado de los paneles 1–5: `ProductHeader`, `KpiCard` (con `tone`),
  `PendingFeatures`, `VerdictBanner`, `StatusChip`, `RiskList`, `NextStepBar`,
  `DataProvenanceBadge`.
- `lib/product-channels.ts`: `loadProductOperationsData` (lo de Marketing + informes
  de operaciones).
- `lib/operations.ts` + tests: etiquetas de etapa y de tipo de ticket, diferencias
  entre etapas, veredicto de operación.

### Qué se dejó fuera (y por qué)

- **KPIs de la operación** (pedidos activos, en tránsito, entregados hoy, % a tiempo,
  entrega media, tasa de devoluciones, SLA de proveedor), **pipeline con conteos y
  cuellos de botella**, **pedidos recientes con filtros**, **mapa logístico**,
  **Operational Health**: requieren pedidos reales; no hay ninguna tabla de pedidos.
- **Centro de incidencias de pedido** (prioridad, proveedor, SLA, responsable, acción
  recomendada): la API de incidentes existente (Milestone 25) es de incidencias del
  sistema, sin pedido/proveedor/SLA y con su sitio natural en Estado, así que no se
  mezcla aquí.
- **Rendimiento de proveedores y transportistas**: no hay pedidos ni tracking con los
  que medirlos; tampoco hay transportistas en el modelo.
- **Devoluciones reales** (abiertas, en revisión, recibidas, tasa y motivos) y
  **soporte real**: solo existe la política simulada y un ticket de ejemplo.
- **Modelo sin stock completo**: capital adelantado, desfase entre cobro y pago y
  cobertura necesitan fechas de cobro y pago.
- **Automatizaciones operativas y modo operativo**, «Configurar reglas», exportar
  informe, sincronización en vivo.
- El «Proveedor» que se muestra es el de la cotización del análisis económico, mientras
  que el plazo y la verificación que usa el agente salen de la cotización más reciente;
  suelen coincidir, pero no hay un vínculo explícito.
- Los textos de riesgos y el motivo de escalado están en inglés en el backend; se
  muestran tal cual y se avisa.

### Verificación

- `tsc --noEmit` limpio; `npm test` 44/44 (3 nuevos de `lib/operations.ts`);
  `npm run build` correcto; `eslint` limpio sobre los archivos del panel.
- **En navegador con datos reales** (stack aislado, sin Supabase): «Wireless earbuds
  pro» en la UE. El informe en pantalla coincide con
  `GET /api/products/{id}/operations` (pedido ORD-5696f77bdf, etapas día 0/1/12/14/15,
  plazo 12 días, proveedor no verificado, ventana 14 días, reembolso 20,00, ticket de
  cumplimiento escalado, mismo riesgo, «Requiere revisión» con confianza 40 %).
  Probado: mercado sin informe (estado vacío y CTA deshabilitado), cambio de producto
  (contexto sin economía/legal/campaña con enlaces a cada panel), generar el informe
  de un producto sin análisis económico (riesgo «no economic analysis», reembolso
  «—») y el error del backend (alerta legible). Móvil 375 px sin desbordamiento.

### Qué sigue

Panel 7 — Finanzas y control (CFO).

---

## Panel 7 — Finanzas y control (`/cfo`)

Referencia: `docs/design/CFO.png` + parte 2 §4. El mockup es el de una empresa con
contabilidad, tesorería, cobros y forecast; el backend solo tiene un agente CFO que
**agrega** las últimas decisiones económicas, las campañas y las reservas del
`BudgetEngine` en un informe de salud financiera de todo el catálogo. Es, con
Operaciones, el panel donde más cosas quedan pendientes; nada de caja, P&L, tesorería
o forecast se dibuja.

### Qué se ve ahora

1. **Informe de salud financiera**: botón para generar uno nuevo (`POST /api/cfo/runs`).
   La página ya no arranca vacía: carga los informes guardados y muestra el más reciente.
2. 6 KPIs: salud financiera (tono de veredicto), productos analizados (con GO / REVISIÓN /
   NO_GO), % de decisiones NO_GO, uso del presupuesto (real si hay reservas; «pendiente»
   si no), campañas listas y presupuesto diario propuesto.
3. **Presupuesto global**: límite máximo total y reparto en gastado / comprometido /
   reservado / disponible (barra apilada con leyenda), a partir de las reservas reales
   del `BudgetEngine`. Sin presupuestos registrados, lo dice y explica por qué.
4. **Salud financiera**: veredicto, riesgos y evidencias del informe y las cuatro
   reglas fijas que aplica el agente.
5. **Cartera de productos**: barra GO / Revisión / NO_GO y **rentabilidad por producto**
   (beneficio mensual estimado del escenario base de la última decisión de cada producto,
   ranking con soporte de negativos).
6. **Historial de informes** (estado, productos, % NO_GO y uso de presupuesto de cada uno)
   y tarjeta «Finanzas de empresa — pendiente de backend».

### Componentes nuevos / tocados

- `StackedBar` (barra apilada de una sola serie con leyenda, para partes de un total) y
  `RankedBars` (ranking horizontal de una métrica con negativos): nada similar existía;
  reutilizables en Proyectos, Agentes y Auditoría.
- Reutilizados: `KpiCard` (con `tone`), `VerdictBanner`, `SectionNav`, `PendingFeatures`,
  `DataTable`, `RiskList`, `StatusChip`, `EmptyState`.
- `lib/finance.ts` + tests: desglose del presupuesto, filas de cartera, veredicto y reglas.
- `/cfo` deja de ser una página de cliente pura: pasa a cargar los datos en servidor.

### Qué se dejó fuera (y por qué)

- **Caja disponible, ingresos, beneficio neto, margen neto, gasto del mes y runway**,
  **cash flow**, **forecast** (Base/Conservador/Expansión), **P&L consolidado**,
  **Budget vs Real vs Forecast por áreas**, **variance analysis**, **tesorería**,
  **cuentas a pagar y a cobrar**, **Working Capital**, **fiscalidad**, **contabilidad**,
  **capital y financiación**, **alertas financieras** de datos reales, **CFO Copilot** y el
  **Financial Health** de siete componentes: no existen movimientos de caja, ingresos
  reales, bancos, pasarelas de cobro, facturas ni impuestos.
- **Distribución del presupuesto por áreas**: el `BudgetEngine` guarda un total, no áreas.
- **Rentabilidad por canal, país, proveedor, campaña o proyecto**: no hay ventas reales
  que agrupar. Solo por producto, con datos estimados del análisis económico (y sin
  recalcular unit economics, que es de Economía).
- **Periodo, entidad, escenario y exportar informe** de la cabecera del mockup.
- Los riesgos y evidencias del agente están en inglés en el backend; se muestran tal cual.
- La rentabilidad por producto lee la última decisión de cada producto con una petición
  por producto y se limita a los 20 primeros; no hay un endpoint agregado.
- Para probar la barra de presupuesto se sembraron un presupuesto y una reserva **solo en
  la base de datos SQLite aislada**; ningún dato se escribió en Supabase.

### Verificación

- `tsc --noEmit` limpio; `npm test` 47/47 (3 nuevos de `lib/finance.ts`); `npm run build`
  correcto; `eslint` limpio sobre los archivos del panel.
- **En navegador con datos reales** (stack aislado, sin Supabase): informe generado desde
  la UI; las cifras coinciden con `GET /api/cfo/runs` (1 producto GO, 0 % NO_GO, campañas
  0/1, sin presupuesto → KPI «pendiente» y el riesgo del agente) y la rentabilidad por
  producto con el beneficio base del análisis económico (3.835,13). Con un presupuesto
  sembrado en la base aislada (límite 1.000, reservado 150, comprometido 250, gastado 300)
  el uso pasa a «70 %» (igual que `budget_utilization` del informe), la barra reparte
  300 / 250 / 150 / 300 disponible y el historial muestra los dos informes. Móvil 375 px
  sin desbordamiento.

### Qué sigue

Panel 8 — Proyectos.

---

## Panel 8 — Proyectos (`/projects` y `/projects/[id]`)

Referencia: `docs/design/proyectos.png` + parte 2 §5. La spec quiere el proyecto como
«expediente completo» de una oportunidad (del objetivo CEO al aprendizaje, con fases de
lanzamiento y operación, beneficio real y previsto vs real). Hoy un proyecto es **una
validación del Director ejecutivo**: nombre, estado, grafo de tareas y decisión con
evidencias; no está enlazado a producto, mercado, ventas ni fechas. Se construye sobre eso.
Es uno de los paneles con más datos reales.

### Qué se ve ahora

**Portfolio (`/projects`)**

1. 6 KPIs: proyectos, en validación, activos, rechazados, en riesgo (alguna validación
   NO_GO) y beneficio previsto del mes (suma de los proyectos vivos).
2. **Portfolio**: tabla con búsqueda, orden y exportar CSV; filtros por estado (Todos /
   En validación / Activos / Rechazados / Otros con su contador); columnas de proyecto,
   estado, salud, score, progreso (tareas completadas) y beneficio previsto. Pulsar una
   fila abre el expediente.
3. Proyectos por estado (barra apilada) y tarjeta «pendiente de backend».

**Expediente (`/projects/[id]`)**

1. 6 KPIs: Project Health (riesgo bajo/medio/alto, el peor de las cuatro validaciones),
   progreso, score de oportunidad, confianza, beneficio previsto (mes, con su margen) y
   capital expuesto (importe de la solicitud de gasto).
2. **Pipeline del proyecto**: las cuatro fases que valida el CEO (Investigación,
   Proveedores, Economía, Legal) con su estado en el grafo y su recomendación real, cada una
   enlazada a su módulo; Tienda, Marketing, Operaciones y Escala salen como pendientes.
3. **Próxima decisión**: veredicto de la decisión, su justificación, la solicitud de
   aprobación (acción, importe, estado) y botones a Aprobaciones y a la trazabilidad.
4. **Salud y riesgos** (`ProjectHealth` + los riesgos reales que dejó cada especialista),
   **actividad reciente** (los eventos de auditoría de la decisión con `CorrelationTrace`),
   **hitos y tareas** (los hitos que se leen del grafo, recuento por situación), grafo de
   tareas y evidencia de la decisión (los dos que ya existían).

### Componentes nuevos / tocados

- Reutilizados: `KpiCard`, `DataTable`, `StackedBar`, `PendingFeatures`, `VerdictBanner`,
  `ProjectHealth`, `CorrelationTrace`, `StatusChip`, `DataProvenanceBadge`.
- `lib/projects.ts` + tests: grupos de estado, progreso, recuentos de tareas, pasos del
  pipeline, riesgos por fase, hitos, veredicto de la decisión y `projectedFinance` (lee
  `monthly_profit` y `margin` de la evidencia estructurada `finance_validation`; no
  parsea el texto del resumen).
- `/projects` y `/projects/[id]` siguen cargando en servidor; el portfolio pasa a
  componente de cliente por los filtros.

### Qué se dejó fuera (y por qué)

- **Beneficio real, previsto vs real y aprendizajes**: no hay ventas ni resultados reales
  enlazados al proyecto. El beneficio previsto es el que calculó el especialista de
  finanzas con los supuestos del objetivo (estimación, con badge), no un resultado.
- **Fases de preparación, lanzamiento, operativo y escala**, «Pausado», «Descartado» y el
  próximo gate: el orquestador solo pasa un proyecto por validando → aprobado / rechazado.
  Por eso los KPI «Lanzamiento» y «Operativos» del mockup se sustituyen por «Activos».
- **Beneficio previsto por mercado, mercado, categoría, producto, modelo logístico y
  fecha de inicio**: el proyecto no guarda producto, mercado ni fecha (`ProjectOut` no trae
  `created_at`).
- **Tienda, Marketing, Operaciones y Escala en el pipeline del proyecto** y las
  dimensiones de salud canal/marketing/operaciones: esas piezas se generan por producto y
  mercado, sin vínculo con el proyecto.
- **Score numérico de Project Health**, **CAC máximo** de la solicitud, hitos comerciales
  (primera venta, 100 ventas, break-even), **agentes trabajando** en vivo (solo se ve el
  estado de las tareas) y las vistas Pipeline/Timeline, métricas, finanzas y documentos.
- Los riesgos de los especialistas están en inglés en el backend; se muestran tal cual.

### Verificación

- `tsc --noEmit` limpio; `npm test` 54/54 (7 nuevos de `lib/projects.ts`); `npm run build`
  correcto; `eslint` limpio sobre los archivos del panel.
- **En navegador con datos reales** (stack aislado, sin Supabase; se lanzaron tres objetivos
  del CEO por la API: uno en REVIEW, uno en HUMAN_APPROVAL y uno NO_GO). Los tres proyectos,
  sus estados, scores, salud y progreso 5/5 coinciden con la API; el beneficio previsto
  (4.000,00) coincide con `finance_validation.data.monthly_profit` y el KPI del portfolio
  suma solo los proyectos vivos. Probado: filtros por estado (contadores y filas), clic en
  fila (abre el expediente), y en el expediente la aprobación pendiente de 150 (capital
  expuesto), los 12 eventos de auditoría de la decisión, los hitos y las cuatro fases con
  su recomendación. Móvil 375 px sin desbordamiento en ambas pantallas.

### Qué sigue

Panel 9 — Agentes.

---

## Panel 9 — Agentes (`/agents`)

Referencia: `docs/design/agentes.png` + parte 2 §6. La spec quiere un **Agent Control
Center** (agentes, ejecuciones, versiones, herramientas, permisos, evaluaciones, costes,
errores y rendimiento). Hoy el backend tiene el registro de agentes (nombre, rol,
capacidades, estado, versión y un coste nominal) y el log de ejecuciones del CEO
(`AgentExecutionLog`: agente, capacidad, duración, éxito, traza). Se construye sobre eso.

### Qué se ve ahora

1. 6 KPIs: agentes registrados, disponibles (con los ocupados), ejecuciones registradas,
   tasa de éxito, latencia media (con badge de estimación: los agentes son deterministas y
   duran fracciones de milisegundo) y agentes con errores.
2. Cinco pestañas, como en el mockup:
   - **Agentes**: tarjetas (`AgentCard`, reutilizada) agrupadas por equipo (Investigación,
     Abastecimiento, Economía, Legal, Comercio, Marketing, Operaciones, Finanzas), con
     búsqueda por nombre o capacidad y filtro por equipo.
   - **Actividad**: ejecuciones recientes (agente, capacidad, resultado, duración, cuándo y
     enlace a la traza en Auditoría) con búsqueda, orden y exportar CSV, y alertas por
     ejecuciones fallidas.
   - **Rendimiento**: tabla por agente (runs, éxito, latencia, errores, última actividad)
     con filtro de periodo (todo, 24 h, 7 días, 30 días) y dos gráficos de reparto
     (ejecuciones por equipo y por agente).
   - **Evaluaciones**: pendiente de backend.
   - **Versiones**: versión vigente y coste nominal por tarea de cada agente, más la lista
     de lo que falta (historial, staging, rollback, herramientas, permisos, handoffs).

### Componentes nuevos / tocados

- Reutilizados: `AgentCard`, `KpiCard`, `DataTable`, `StackedBar`, `RankedBars`,
  `PendingFeatures`, `DataProvenanceBadge`, y las pestañas de shadcn (`Tabs`).
- `AgentCard`: la latencia usa `formatDuration` (antes «0ms» para ejecuciones de
  0,01 ms) y la hora de última actividad interpreta las fechas del backend como UTC.
- `lib/format.ts`: `formatDuration`. `lib/agents.ts` + tests: equipo por rol, agrupación,
  estadísticas por agente, resumen de la flota, ventana de tiempo y ejecuciones por equipo.

### Qué se dejó fuera (y por qué)

- **Coste del día, coste por agente, tokens, llamadas a API y búsquedas**: el registro solo
  declara un coste nominal simulado por tarea (todos a 0); no hay coste medido.
- **Evaluación (score), Evaluation Suite y umbral de despliegue**: no existe evaluación de
  agentes.
- **Estado «Ejecutando», proyecto/tarea en curso y progreso de la tarjeta**: el registro
  solo informa `AVAILABLE`; no guarda el proyecto o la tarea que trabaja cada agente.
- **Versionado con historial, producción/staging, comparación y rollback**; **herramientas y
  permisos**; **handoffs**; **trazas operativas**; **vista de detalle del agente** y «Nueva
  versión de agente»; «Actividad en tiempo real» en streaming y los recursos de la
  columna derecha.
- **Alertas por umbral** (error rate alto, coste anómalo, latencia alta, versión
  degradada): solo se alerta de ejecuciones fallidas.
- **Filtros por proyecto y modelo**: la ejecución no guarda ni el proyecto ni el modelo.
- **«Todo el histórico» son las 100 últimas ejecuciones**: `GET /api/agent-executions` está
  limitado a 100 filas, así que los KPI y el rendimiento no cuentan más allá de eso.
- **Solo el CEO registra ejecuciones**: los agentes de la Fase 3 (Investigación, Proveedores,
  Economía, Legal, Tienda…) se invocan desde sus paneles y hoy no escriben en el log, así que
  aparecen con 0 ejecuciones aunque se usen.
- **Los 13 agentes son los del registro actual** (4 de validación del CEO + 9 de la Fase 3),
  no la arquitectura de 13 agentes reorganizados de la spec (Product Hunter, Market Analyst…);
  se agrupan por equipo con un mapa de rol → equipo del cliente.

### Verificación

- `tsc --noEmit` limpio; `npm test` 61/61 (7 nuevos de `lib/agents.ts` y 1 de
  `lib/format.ts`); `npm run build` correcto; `eslint` limpio sobre los archivos del panel.
- **En navegador con datos reales** (stack aislado, sin Supabase; tras lanzar 3 objetivos del
  CEO): 13 agentes en 8 equipos, 12 ejecuciones (3 por especialista), éxito 100 %, latencia
  «<1 ms», sin agentes con errores; la actividad, el rendimiento y el reparto por equipo
  coinciden con `GET /api/agent-executions`; el filtro de 24 h, las cinco pestañas y la
  búsqueda funcionan. Se corrigió un desbordamiento de 20 px de la barra de pestañas en
  móvil (ahora hace scroll dentro de su contenedor): 375 px sin desbordamiento en las cinco
  pestañas.

### Qué sigue

Panel 10 — Aprobaciones.
