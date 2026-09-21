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

Panel 2 (abajo), luego Panel 3 — Legal y cumplimiento.

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
