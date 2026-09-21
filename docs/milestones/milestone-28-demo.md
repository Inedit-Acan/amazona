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

Paneles 2 a 4 (abajo), luego Panel 5 — Marketing y adquisición.

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
