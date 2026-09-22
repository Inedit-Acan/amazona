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

Paneles 2 a 12 (abajo).

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

---

## Panel 10 — Aprobaciones y decisiones (`/approvals`)

Referencia: `docs/design/aprobaciones y decisiones.png` + parte 2 §7. La spec quiere un
**Human Decision Center** con criticidad, cadena de aprobación, guardrails, reglas de
autoaprobación y workflow. Hoy una aprobación autoriza **una acción con un importe**, la
resuelve un único aprobador y no guarda criticidad, solicitante, motivo ni fecha de
solicitud. Este panel es de los que tienen acciones reales (aprobar y rechazar cambian el
presupuesto y la auditoría), así que se conservó toda la lógica existente y se probó que
sigue funcionando. Sigue incluyendo el interruptor de emergencia del pipeline en la cabecera
(decisión del Milestone 17).

### Qué se ve ahora

1. **KPIs**: pendientes, **críticas** (pendiente: sin criticidad), vencen en 24 h, aprobadas
   hoy y **tiempo medio** (pendiente: no se guarda cuándo se solicitó).
2. **Bandeja** (lista a la izquierda, detalle a la derecha, como el mockup): aprobaciones de
   gasto y revisiones de pipeline en una sola lista, con filtros Pendientes / Decididas /
   Todas, búsqueda, filtro por tipo y «Reglas» deshabilitado. Cada fila muestra el tipo, el
   proyecto, el importe y cuándo vence (o su estado, si ya se decidió). Las pendientes salen
   primero, las que vencen antes arriba.
3. **Detalle de una aprobación**: la tarjeta existente (importe, confianza, recomendación del
   CEO, estado financiero y legal, riesgo, evidencias y **Aprobar / Rechazar**) más el
   **estado de las validaciones** (`ProjectHealth`) y el **impacto de la decisión**: qué pasa
   si apruebas y si rechazas, según lo que hace el backend (aprobar compromete el importe del
   presupuesto, rechazar libera la reserva; ambas quedan en la auditoría).
4. **Detalle de una revisión de pipeline**: la tarjeta existente con sus motivos y las
   acciones de aprobar/rechazar.
5. Tarjeta «Human Decision Center — pendiente de backend».

### Componentes nuevos / tocados

- Reutilizados: `ApprovalCard`, `PipelineReviewCard`, `KillSwitchControl`, `ProjectHealth`,
  `KpiCard`, `StatusChip`, `PendingFeatures`, `EmptyState`, `DataProvenanceBadge`.
- `ApprovalCard`: vencimiento en texto relativo y en UTC («Vence en 3 h»), acción y importe
  con el formato del resto de paneles, y el encabezado ya no desborda en móvil (también en
  `PipelineReviewCard`).
- `lib/dates.ts` (nuevo): `parseUtc`, `relativeTime` e `isSameLocalDay`. **Corrige un fallo
  real**: el backend devuelve las fechas sin zona («…T21:49:34») y `new Date()` las tomaba
  como hora local, así que `isExpired` se equivocaba por el desfase horario del navegador. `lib/agents.ts` y
  `AgentCard` ahora usan el mismo `parseUtc`.
- `lib/approvals.ts` + tests: bandeja unificada, orden, estadísticas, etiqueta de vencimiento
  e impacto de la decisión.

### Qué se dejó fuera (y por qué)

- **Criticidad (Crítica/Alta/Media/Baja)**, tipos de solicitud más allá del texto de la
  acción, **solicitante**, **fecha de solicitud** (y por tanto la antigüedad y el tiempo
  medio de resolución) y **presupuesto visible** (asignado, gastado, comprometido,
  disponible) en la solicitud: el modelo no los guarda o no los expone.
- **Solicitar cambios**, **motivo de rechazo obligatorio** y el feedback a agentes: el
  rechazo solo envía el aprobador.
- **Cadena de aprobación, separación de funciones, guardrails condicionados, reglas de
  autoaprobación, Workflow Builder y simulador de políticas**: no existe un modelo de política.
- **Documentos y comentarios** de la solicitud, y la pestaña «Reglas».
- **Aprobador fijo**: la interfaz aprueba siempre como `owner@amazona.local` (ya era así); no
  hay sesión de aprobador real.
- **Las revisiones de pipeline resueltas desaparecen de la bandeja**: `GET /api/pipeline/reviews`
  solo lista las pendientes, así que «Decididas» solo conserva las aprobaciones de gasto.
- **«Vencen pronto» = 24 h**: la spec no fija el umbral.

### Verificación

- `tsc --noEmit` limpio; `npm test` 68/68 (7 nuevos de la bandeja y `lib/dates.ts`, más los
  de la lógica de aprobación de antes, que siguen pasando); `npm run build` correcto; `eslint`
  limpio sobre los archivos del panel.
- **En navegador con datos reales** (stack aislado, sin Supabase; se lanzaron objetivos del CEO
  de 150, 1.500 y 39,90 y una ejecución del pipeline que dejó una revisión pendiente). Los
  KPI, la lista y los importes coinciden con `GET /api/approvals`. Probado de extremo a
  extremo **con acciones reales en la base aislada**: aprobar la de 39,90 (pasa a «Decididas»
  como Aprobado, «Aprobadas hoy» = 1) y rechazar la de 1.500 (Rechazado, `resolved_by`
  `owner@amazona.local` en la API); en una decidida los botones salen deshabilitados; aprobar la
  revisión de pipeline (la API deja de listarla, como esperado); el interruptor de emergencia
  sigue en la cabecera. Móvil 375 px: se corrigió el encabezado de las tarjetas (chip fuera de
  la tarjeta) y ya no desborda.

### Qué sigue

Panel 11 — Auditoría.

---

## Panel 11 — Auditoría y trazabilidad (`/audit`)

Referencia: `docs/design/auditoria.png` + parte 2 §8. La spec quiere un registro forense
e inmutable con criticidad, resultado, evidencias con hash, cadena de hashes, anomalías y
retención. El backend guarda `AuditLog` (actor, acción, recurso, estado antes/después, ID
de correlación, fecha): una tabla de eventos, sin hashes, evidencias ni criticidad. Es el
panel con más datos reales junto a Proyectos; se construye sobre eso y lo demás queda
pendiente. Se conserva el filtro `?correlation_id=` (enlazado desde Proyectos y Agentes).

### Qué se ve ahora

1. **KPIs**: eventos registrados, eventos hoy, aprobaciones, decisiones del CEO, errores
   (acciones que indican un fallo) y «acciones críticas» (**pendiente**: los eventos no
   tienen criticidad).
2. Siete pestañas, como en el mockup:
   - **Eventos**: tabla (fecha y hora, tipo, acción, actor, proyecto, recurso, correlación)
     con filtros de periodo, tipo, actor, proyecto y texto, paginación, orden y exportar
     CSV; **detalle del evento** (ID, tipo, actor, recurso, proyecto, correlación,
     **antes / después** del estado) y **Correlation Trace** con todo lo ocurrido bajo el
     mismo ID de correlación.
   - **Timeline**: los eventos de los últimos días con actividad, agrupados por día.
   - **Proyectos**: eventos por proyecto (atribuidos por el ID de correlación de la decisión).
   - **Agentes**: actividad por actor (tipo, eventos, errores, primer y último evento).
   - **Seguridad**: las acciones de personas del registro y qué falta por auditar.
   - **Integridad** y **Retención**: pendientes de backend.
3. Con `?correlation_id=` la pantalla muestra solo ese ID, con un aviso y el botón para
   volver a todo el registro.

### Componentes nuevos / tocados

- Reutilizados: `CorrelationTrace`, `DataTable`, `KpiCard`, `PendingFeatures`,
  `DataProvenanceBadge`, `EmptyState`, `Tabs` de shadcn.
- `CorrelationTrace`: las horas se interpretan como UTC (`parseUtc`), igual que el resto.
- `lib/audit.ts` + tests: categoría de la acción (por prefijo), tipo de actor (por nombre),
  filtros, resumen, actividad por actor y por proyecto, agrupación por día y diferencias
  antes/después. El «tipo» y el «tipo de actor» son clasificaciones de presentación, no
  campos guardados.
- `/audit` carga proyectos y decisiones en servidor para atribuir eventos a proyectos.

### Qué se dejó fuera (y por qué)

- **Criticidad, resultado (éxito/error/creado) y acciones críticas por evento**, y las
  **anomalías** (precio sin aprobación, acción fuera de política…): el registro no clasifica
  ni evalúa los eventos.
- **Integridad demostrable**: hash por evento, cadena de hashes, verificación y «eventos
  modificados = 0». La interfaz no edita ni borra eventos, pero el backend no puede
  demostrar que nadie los tocó, así que **no se afirma integridad** ni se muestra un
  «100 %».
- **Evidencias asociadas** (informes, Legal Gate, presupuesto, documentos con hash y versión),
  **provenance por evento**, **historial de versiones** y **auditoría IA** (modelo, coste,
  herramientas).
- **Origen del evento, IP y user agent**; **vista por proyecto como expediente forense**;
  **retención**; **exportación** a JSON/PDF y **paquete de auditoría** (solo hay CSV).
- **Seguridad real** (inicios de sesión, permisos, API keys, integraciones): no se registran.
- **El proyecto de cada evento** se deduce por el ID de correlación de la decisión: los
  eventos de análisis por producto (investigación, economía, legal…) y de memoria quedan sin
  proyecto. Se leen las decisiones de los 40 primeros proyectos.
- **Límite de 500 eventos, los más antiguos primero**: `GET /api/audit` ordena por fecha
  ascendente y corta en 500, así que en un sistema con historia larga **los eventos más
  recientes no llegarían a la pantalla**. Con esa cifra el KPI avisa; hace falta paginación y
  orden descendente en el backend.
- La exportación CSV incluye solo la página visible de la tabla.

### Verificación

- `tsc --noEmit` limpio; `npm test` 75/75 (7 nuevos de `lib/audit.ts`); `npm run build`
  correcto; `eslint` limpio sobre los archivos del panel.
- **En navegador con datos reales** (stack aislado, sin Supabase): los 98 eventos de la base
  aislada coinciden con `GET /api/audit` (37 de hoy, 6 aprobaciones, 5 decisiones, 0
  errores). Probado: filtro por tipo (6 eventos de aprobación, con el proyecto atribuido y
  el antes/después `PENDING → APPROVED`), Correlation Trace de 13 eventos, paginación, filtro
  por actor (3 del CEO), búsqueda sin resultados, las siete pestañas (con clics reales), y
  `?correlation_id=` (12 eventos, aviso y pestañas de proyectos/actores coherentes; un ID
  inexistente muestra el estado vacío con enlace para volver). Móvil 375 px sin desbordamiento
  de página (la tabla desplaza dentro de su contenedor).

### Qué sigue

Panel 12 — Estado.

## Panel 12 — Estado e infraestructura (`/status`)

Referencia: `docs/design/estado de AMAZONA.png` + parte 2 §9. El mockup es un «System
Operations Center» con 18 servicios, uptime, percentiles, colas, cron, integraciones,
despliegues y costes técnicos. El backend solo expone `GET /health/detailed` (base de datos,
versión de migración y si Supabase está configurado), los incidentes registrados a mano y el
log de ejecuciones de agentes. El panel muestra esa señal real, medida en cada carga de la
página, y deja todo lo demás como pendiente: no aparece ningún uptime, percentil ni
«18/18 servicios operativos».

### Qué se ve ahora

1. **Banner de estado general** (`VerdictBanner`) con prioridad visual superior: backend
   caído > base de datos con error > incidentes abiertos > operativo.
2. **Seis KPIs**: estado general, servicios con señal (operativos / medibles), latencia de la
   API (una sola medida de la comprobación de salud desde el servidor del frontend, no un
   p95), incidentes activos (con los resueltos), migración (pendiente si no hay versión) y
   ejecuciones de agentes (con las fallidas, de las últimas 100).
3. **Servicios**: tabla de los cuatro con señal real (frontend, API, base de datos,
   Supabase) con estado con icono y texto (no solo color, §9.4), latencia donde la hay y el
   motivo de cada estado.
4. **Mapa de servicios** (`ServiceMap`): verde con señal, rojo si falla, gris sin telemetría
   (cola, procesos, integraciones, usuarios).
5. **Incidentes**: formulario para reportar (`IncidentReportForm`) y tarjetas abiertas /
   resueltas (`IncidentCard`) con el botón para resolverlas.
6. **Base de datos**: estado, migración y Supabase; métricas del motor como pendientes.
7. **Ejecuciones recientes de agentes**: las diez últimas (cuándo, agente, capacidad,
   duración, estado).
8. **System Operations Center — pendiente de backend** (`PendingFeatures`) con todo lo que
   enseña el mockup y no existe.
9. **Backend caído**: si la API no responde, el banner lo dice, la base de datos y Supabase
   pasan a «sin telemetría» y los incidentes y ejecuciones muestran «—» / «no se pudieron
   cargar» (nunca un «0» verificado).

### Componentes nuevos / tocados

- Reutilizados: `VerdictBanner`, `KpiCard` (con `tone`), `ServiceMap`, `IncidentCard`,
  `IncidentReportForm`, `StatusChip`, `DataProvenanceBadge`, `PendingFeatures`,
  `lib/format.ts` y `parseUtc`.
- `lib/status.ts` + tests: filas de servicios a partir de la señal real, resumen
  (operativos / caídos / con señal) y estado general con su prioridad.
- `ServiceStateBadge` (local de la página): estado con icono y texto.
- `IncidentCard`: las fechas se interpretan como UTC (`parseUtc`, salían con 2 h de
  desfase) y la cabecera se ajusta en móvil (antes se salía de la tarjeta a 375 px).

### Qué se dejó fuera (y por qué)

- **Uptime, latencias p50/p95/p99, requests/min, 2xx/4xx/5xx y error budget**: no hay
  métricas ni series temporales; la latencia que se ve es una medida puntual.
- **Los otros 14 servicios** (Auth, Storage, Realtime, Edge Functions, Workers, Queue, Cron,
  Email, Monitoring, Logs, Backup, CDN, DNS, certificados): sin telemetría. Supabase solo
  consta como *configurado*; no se comprueba que responda.
- **Colas, dead-letter, workers y cron**; **integraciones y rate limits** (Stripe, Ads,
  SP-API, OpenAI…).
- **Métricas de base de datos** (CPU, memoria, conexiones, cache hit, queries lentas, locks,
  storage, IOPS).
- **Deployments** (versión, commit, fecha) y **migraciones** anteriores / pendientes /
  fallidas: solo existe la versión actual (y en la base aislada es `null`).
- **Coste técnico**, **Logs Explorer** y **página de estado pública**.
- **Incidentes con causa, impacto y duración** y **apertura automática**: se registran a mano.

### Verificación

- `tsc --noEmit` limpio; `npm test` 79/79 (4 nuevos de `lib/status.ts`); `npm run build`
  correcto; `eslint` limpio sobre `app/status`, `lib` e `incident-card.tsx`.
- **En navegador con datos reales** (stack aislado, sin Supabase): KPIs y tabla coinciden con
  `/health/detailed` (base de datos ok, migración `null`), `/api/incidents` y
  `/api/agent-executions` (20 ejecuciones, 0 fallidas; horas en local correctas). Creado un
  incidente desde el formulario: aparecen el banner ámbar «1 incidente activo» y el KPI; se
  resolvió desde la tarjeta y todo vuelve a «Operativo» con «1 resuelto». **Backend caído**
  probado parando el backend aislado: banner rojo, API caída, base de datos y Supabase sin
  telemetría, incidentes y ejecuciones «—» como pendientes; al rearrancarlo, todo vuelve.
  Móvil 375 px sin desbordamiento (las tablas desplazan dentro de su contenedor).

### Qué sigue

Los doce paneles están rediseñados. Lo siguiente es el backend que falta por panel
(`docs/design/AMAZONA_estado_paneles_rediseno.md`).

## Segunda pasada — Panel 2: Economía y rentabilidad (`/economics`)

Tras los 12 paneles, el propietario revisa pantalla a pantalla contra su mockup.
Nuevo criterio (22-09-2026): cada pantalla debe verse como el mockup, con datos
de demostración donde el backend aún no los da (en `lib/demo/`, señalados con la
etiqueta «Datos de demostración»). Antes de esta pasada se corrigió el tema
global (commit `4e1f09f`): la fuente caía a Times New Roman y la paleta no era la
de los mockups.

### Qué se ve ahora

1. Cabecera con fecha y hora, etiqueta «Datos de demostración» (el tooltip dice
   qué es demo) y selector «Producto activo».
2. Franja de producto: ficha, score de investigación, proveedor seleccionado (con
   selector si hay varias cotizaciones reales), mercado objetivo y modelo logístico.
3. Seis KPIs: precio (chip «Editable» que lleva al simulador), coste total por
   unidad, margen de contribución, beneficio del mes, punto de equilibrio con meses
   de recuperación, y riesgo con barra de nivel.
4. Pestañas-ancla de las siete secciones.
5. Escenarios conservador/base/optimista con precio, pedidos, margen y beneficio,
   y el gráfico «Evolución del beneficio estimado» con tooltip.
6. Desglose de los 8 costes por unidad con su origen (Verificado / Proveedor /
   Estimación) y el margen de contribución.
7. Simulador (precio, coste proveedor, CAC, devoluciones, conversión, pedidos) con
   resultados en tiempo real y «Restablecer». Toda la pantalla se recalcula con él.
8. Sensibilidad (6 variables, nivel Alto/Medio/Bajo), punto de equilibrio (gráfico
   con el punto marcado y tabla: unidades, facturación, recuperación, CAC máximo,
   precio mínimo) y viabilidad con veredicto «bajo estas hipótesis».
9. Barra final con «Guardar análisis» (real) y menú «…» (validar con el Director
   ejecutivo, buscar más proveedores).
10. Carga el último análisis guardado del producto (antes se perdía al recargar).

### Componentes nuevos / tocados

- Nuevos: `LineChart`, `SensitivityBars`, `Flag`; `lib/economics-model.ts`,
  `lib/economics-baseline.ts` (real + demo) y `lib/demo/economics.ts`, con tests;
  `formatEuro` en `lib/format.ts`.
- Ampliados sin romper a los demás paneles: `DataProvenanceBadge` (`demo`,
  `compact`), `KpiCard` (`accent`, `footer`, icono opcional), `SectionNav`
  (`active`, `onClick`), `ScenarioCard` (`icon`), `PageHeader` (`actions`).

### Verificación

- `tsc --noEmit` limpio; `npm test` 90/90 (11 nuevos); `eslint` limpio en los
  archivos tocados; `next build` correcto (en copia temporal, sin tocar el `.next`
  del entorno del propietario).
- En navegador (entorno del propietario, solo lectura): a 1536 y 1896 px la
  estructura coincide con el mockup; el simulador recalcula KPIs, escenarios,
  punto de equilibrio y viabilidad (precio 35 € → 10.500 € de ingresos y 4.213 €
  de beneficio; precio 12 € → margen negativo, «No se alcanza», riesgo Alto y
  «No rentable bajo estas hipótesis»); «Restablecer», menú «…» y cambio de
  producto funcionan; 375 px sin desbordamiento; consola sin errores. Los tres
  productos de esa base no tienen cotizaciones ni análisis, así que se vio el
  camino demo; el camino con datos reales lo cubren los tests de
  `lib/economics-baseline.ts`.

## Segunda pasada — Investigación (`/research`)

Referencia: `docs/design/investigacion.png` (enviada por el propietario el 22-09-2026).
Antes era un formulario con una lista de candidatos que se perdía al recargar.

### Qué se ve ahora

1. Cabecera con fecha y hora, etiqueta «Datos de demostración» y el recuadro «Modo»
   (Simulación: el agente usa señales de fixtures).
2. Buscador grande con «Analizar mercado» (lanza el agente real,
   `POST /api/research/runs`, en la categoría elegida o en las tres) y filtros:
   mercado, categoría, periodo, modelo de negocio y «Filtros avanzados» (score mínimo
   y resultados por categoría).
3. «Radar de oportunidades»: los tres mejores candidatos con score, barra,
   minigráfico de crecimiento, demanda / competencia / margen, cuatro ideas clave y
   los botones «Analizar» (va a Economía) y «Seguir».
4. «Radar de oportunidad AMAZONA» (6 ejes) del producto seleccionado frente a la media.
5. «Resultados»: tabla con demanda, tendencia, competencia, margen, riesgo y score,
   orden, exportación CSV, selección de fila y menú «…» (economía, proveedores,
   Director ejecutivo, seguir).
6. «Resumen de investigación» (encontradas, tras filtros, en seguimiento,
   descartadas), «Tendencia de interés por fuente» e «Insight AMAZONA».
7. Las investigaciones lanzadas se guardan en la URL (`?runs=`), así que sus señales
   reales sobreviven a una recarga.

### Datos reales y de demostración

- Reales: productos, y las cinco señales del agente (demanda, competencia, futuro,
  riesgo regulatorio, escalabilidad) de los productos investigados en la sesión.
- Demo (`lib/demo/research.ts`, deterministas por producto): señales de los productos
  no investigados, tendencia y crecimiento, margen preliminar, subcategoría, ideas
  clave, eje de logística, interés por fuente y los filtros de mercado y modelo de
  negocio (aún no se envían al agente).
- El score 0–100 es una media ponderada de las cinco señales (el `opportunity_score`
  del agente solo combina demanda y competencia).

### Componentes nuevos / tocados

- Nuevos: `Sparkline`, `LevelChip`, `HeaderClock`, `HeaderTile` (los dos últimos
  también en Economía); `lib/research-view.ts` con tests; `api.getResearchRun`.
- `RadarChart`: etiquetas laterales alineadas hacia fuera y lienzo con margen (antes
  se montaban sobre el polígono). `LineChart`: `formatX`.

### Verificación

- `tsc` limpio; `npm test` 95/95 (6 nuevos); `eslint` limpio; `next build` correcto
  (copia temporal).
- En navegador (entorno del propietario, sin lanzar «Analizar mercado» para no
  escribir en su base): estructura del mockup a 1672 px; «Seguir» se guarda y cuenta
  en el resumen; periodo 6 meses cambia minigráficos, crecimiento y meses del
  gráfico; categoría sin productos muestra el vacío; seleccionar una fila cambia el
  radar; 375 px sin desbordamiento; consola sin errores. El camino con señales reales
  lo cubren los tests de `lib/research-view.ts`.

## Segunda pasada — Panel 1: Proveedores y abastecimiento (`/sourcing`)

Referencia: mockup enviado por el propietario el 22-09-2026
(`docs/design/panel proveedores.png`). Antes todo quedaba vacío hasta pulsar
«Buscar proveedores» y el score, las certificaciones, el envío directo, el
desglose del coste y la compatibilidad salían como «pendiente».

### Qué se ve ahora

1. Cabecera con fecha y hora, «Datos de demostración» y «Modo: Búsqueda de
   proveedores».
2. Producto seleccionado (con «Cambiar»), su score de investigación y mercado
   objetivo; parámetros de búsqueda (destino, origen, modelo logístico, precio
   mín./máx., plazo, MOQ, certificaciones, «Más filtros»: solo verificados y
   resultados por búsqueda) con «Guardar búsqueda» (queda en la URL); resumen
   (analizados, preseleccionados, recomendados, descartados) y «Buscar proveedores»
   (agente real, `POST /api/sourcing/runs`).
3. Tres proveedores recomendados: país y ciudad con bandera, «Ver perfil», score
   (medidor), precio, MOQ, entrega, envío directo, certificaciones, «Analizar»
   (Economía con esa cotización), «Comparar» y distintivo (recomendado, mejor
   opción UE, mejor precio).
4. Mapa con rutas y panel de ruta (tiempo, transporte, coste, «Ver detalles de
   logística»).
5. Listado con país, precio, MOQ, entrega, envío directo, certificaciones, riesgo,
   score y acciones (economía, comparar, Director ejecutivo), búsqueda, orden y CSV.
6. Coste total estimado (landed cost en 6 partidas, con los mismos supuestos que
   Economía), compatibilidad con Amazona (8 criterios) y score de proveedor (radar
   de 7 ejes con el score en el centro, frente a la media o al comparado).
7. Barra final con «Enviar a análisis económico».

### Datos reales y de demostración

- Reales: productos y cotizaciones del producto (precio, logística, MOQ, plazo,
  fiabilidad, verificación). Se cargan al entrar; antes solo tras buscar.
- Demo (`lib/demo/sourcing.ts`): 5 proveedores de ejemplo si el producto no tiene
  cotizaciones, y para todos los proveedores país/ciudad, certificaciones, envío
  directo, plazo de entrega al destino, transporte, calidad, compliance,
  escalabilidad y compatibilidad; el desglose del landed cost usa los supuestos de
  `lib/demo/economics.ts`.
- Coherencia entre pantallas: el score de investigación es el mismo en
  Investigación, Proveedores y Economía, y el proveedor de ejemplo de Economía es
  el que Proveedores recomienda.

### Componentes nuevos / tocados

- `lib/sourcing-view.ts` con tests (ranking por score de 7 ejes, riesgo,
  distintivos, landed cost, compatibilidad, filtros); `lib/demo/sourcing.ts`;
  `lib/demo/random.ts` compartido con Investigación.
- `lib/sourcing.ts`: queda solo `supplierRadarValues`; se retiraron las funciones
  (y sus tests) que usaba la versión anterior de la pantalla.
- `RadarChart` (`centerLabel`) y `ScoreGauge`/`RadarChart` redondean coordenadas
  (antes el SVG podía diferir entre servidor y navegador y romper la hidratación);
  `RouteMap`: países visibles con la paleta nueva; `Flag`: Polonia y Hong Kong.
- Economía: el capital inicial es el del primer pedido de stock (500 uds o el MOQ).

### Verificación

- `tsc` limpio; `npm test` 96/96; `eslint` limpio en los archivos tocados (el único
  error es el previo de `top-header.tsx`); `next build` correcto (copia temporal).
- En navegador (entorno del propietario, sin pulsar «Buscar proveedores» para no
  escribir en su base): estructura del mockup a 1536 px; origen UE deja 2
  proveedores y el resumen cuadra (5 analizados, 3 descartados); «Comparar» pone al
  comparado en el radar; «Guardar búsqueda» escribe los parámetros en la URL; 375 px
  sin desbordamiento; consola sin errores. Economía e Investigación siguen bien y
  muestran el mismo score (61) para el mismo producto.
