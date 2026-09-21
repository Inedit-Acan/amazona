# Estado del rediseño de paneles — hecho, fuera de alcance y backend necesario

Documento vivo. Cada panel rediseñado (en el orden de `nav-items.ts`) añade su
sección con el mismo formato:

- **Hecho:** qué se construyó y con qué datos reales.
- **Fuera de alcance por falta de datos reales:** lo que el mockup/spec muestra
  y no se pudo construir sin inventar cifras.
- **Backend que faltaría:** qué habría que añadir para completarlo.

Regla que gobierna todo el documento (`AMAZONA_sistema_de_diseno_visual.md` §3):
nunca presentar como dato real algo que el backend no proporciona. Lo pendiente
se muestra con `DataProvenanceBadge status="pending"`.

Detalle de verificación por panel: `docs/milestones/milestone-28-demo.md`.

## Resumen

| # | Panel | Estado |
|---|---|---|
| 1 | Proveedores y abastecimiento | Rediseñado |
| 2 | Economía y rentabilidad | Rediseñado |
| 3 | Legal y cumplimiento | Rediseñado |
| 4 | Tienda y canales de venta | Rediseñado |
| 5 | Marketing y adquisición | Rediseñado |
| 6 | Operaciones | Rediseñado |
| 7 | Finanzas y control | Pendiente |
| 8 | Proyectos | Pendiente |
| 9 | Agentes | Pendiente |
| 10 | Aprobaciones | Pendiente |
| 11 | Auditoría | Pendiente |
| 12 | Estado | Pendiente |

## Componentes compartidos añadidos por este trabajo

| Componente | Primer uso | Reutilizable en |
|---|---|---|
| `ScoreGauge` | Proveedores | Legal (Legal Gate), Economía, Finanzas (Financial Health), Proyectos, Auditoría, Estado (los "*Health") |
| `DataTable` | Proveedores | Legal (matriz de requisitos), Operaciones (pedidos), Finanzas, Auditoría (eventos) |
| `NextStepBar` | Proveedores | Economía, Legal, Tienda (cierre de cada mockup del pipeline) |
| `RouteMap` | Proveedores | Operaciones (rutas de envío), si llegan datos de transporte |
| `ScenarioCard` | Economía | Finanzas (escenarios de caja), Marketing (escenarios de campaña) |
| `BarChart` | Economía | Finanzas, Marketing, Operaciones (series de una sola métrica) |
| `lib/format.ts` | Economía (extraído de Proveedores) | Todos los paneles con importes |
| `SectionNav` | Economía, Legal | Cualquier panel con las «tabs» del mockup (Tienda, Marketing, Operaciones, Finanzas…) |
| `PendingFeatures` | Economía, Legal | Todo panel cuyo mockup enseña datos que aún no existen |
| `VerdictBanner` | Economía, Legal | Tienda (estado de lanzamiento), Aprobaciones, Estado |
| `ProductHeader` | Economía, Legal | Tienda, Marketing (cabecera de producto de cada mockup del pipeline) |
| `KpiCard` `tone` | Legal | Tarjetas KPI cuyo valor es un veredicto |
| `lib/markets.ts` | Legal, Tienda | Marketing, Operaciones (etiquetas de mercado y «último por mercado») |
| `lib/product-channels.ts` | Tienda | Marketing, Operaciones (todo lo persistido de un producto) |

---

## 1. Proveedores y abastecimiento (`/sourcing`)

**Hecho.** Estructura completa del mockup (`panel proveedores.png`): producto
seleccionado (selector de productos reales), parámetros de búsqueda, resumen,
Top 3 con gauge de fiabilidad, mapa con geometría real y ruta seleccionada,
listado con búsqueda/orden/export CSV, coste total estimado, compatibilidad,
radar de score y barra de siguiente paso. Todo alimentado con campos reales de
`SupplierQuote`; filtros de precio/plazo/MOQ aplicados en cliente sobre los
resultados reales.

**Fuera de alcance por falta de datos reales.**

- Score compuesto de proveedor (91/100): solo existe `reliability_score`.
- Certificaciones, envío directo/dropshipping, Incoterms, métodos de pago,
  packaging neutro, tracking, sincronización de stock, dirección de
  devoluciones UE, SLA contractual, pago tras venta.
- Desglose del coste (transporte, arancel, fulfillment, pago/divisa,
  devoluciones): solo logística+aduana agregadas.
- Ejes Calidad, Compliance y Escalabilidad del radar (spec §6.10).
- Score de investigación del producto, imagen y descripción del producto.
- Ciudad del proveedor, transporte, almacén, riesgo por ruta en el mapa.
- Divisa (los importes se muestran sin símbolo).
- Origen del proveedor / modelo logístico / certificaciones / Incoterms /
  métodos de pago como parámetros de búsqueda (aparecen deshabilitados).
- "Guardar búsqueda" y "Modo: búsqueda de proveedores".

**Backend que faltaría.**

1. Extender `MockSupplierDirectory` + `SupplierSourcingAgent` con los campos que
   faltan (mismo patrón que los 3 ejes nuevos de `MockTrendsProvider`,
   Milestone 26): `certifications`, `direct_ship`, `incoterms`,
   `payment_methods`, `city`, `currency`, y señales de calidad/compliance/
   escalabilidad. Persistirlos en `SupplierQuote.data` (sin migración: es JSON).
2. Persistir en la cotización el desglose que `estimate_logistics_cost` ya
   calcula y hoy descarta (`shipping_cost_per_unit`, `customs_factor`), y
   ampliarlo con fulfillment/pago/devoluciones si se quiere el desglose de 7
   líneas.
3. Aceptar en `POST /api/sourcing/runs` los filtros que hoy son solo de
   cliente/deshabilitados (origen, modelo logístico, certificaciones, precio,
   plazo, MOQ).
4. `GET /api/products/{id}` (hoy solo hay listado) devolviendo también el
   último `ProductAnalysis` de investigación (score), o pasar el score en el
   handoff de Investigación → Proveedores.
5. `ORDER BY total_landed_cost_per_unit` en `GET /api/sourcing/runs/{id}`
   (hoy el cliente reordena).
6. `Product.image_url` / `description` si se quiere la ficha visual del mockup.

---

## 2. Economía y rentabilidad (`/economics`)

**Hecho.** Selector de producto y de cotización real, supuestos (precio de venta,
costes fijos), y — tras ejecutar el análisis — 6 KPIs, comparativa de los 3
escenarios del backend con gráfico de beneficio, desglose unitario, veredicto de
viabilidad con riesgos, CTAs a Legal y al Director ejecutivo, y barra de siguiente
paso. Todos los números salen de `POST /api/economics/runs` o de la cotización.

**Fuera de alcance por falta de datos reales.**

- Punto de equilibrio, simulador, análisis de sensibilidad, riesgo y capital:
  el motor económico no los calcula y el cliente no debe duplicarlo (Milestone 16).
- CAC, pasarela de pago, devoluciones, fulfillment por unidad.
- Escenarios con precio/coste/CAC propios: los 3 del backend solo cambian el volumen.
- Score de investigación, imagen y descripción de producto, divisa.

**Backend que faltaría.**

1. Ampliar `economics/scenarios.py` con punto de equilibrio (unidades, días, CAC
   máximo tolerable, precio mínimo viable) y devolverlo en `EconomicAnalysis.data`.
2. `POST /api/economics/simulate` (sin persistir): recibe precio, coste, CAC,
   devoluciones y conversión y devuelve el resultado recalculado, para el
   simulador sin duplicar lógica en el cliente.
3. Análisis de sensibilidad: variación del beneficio por variable, desde el mismo
   motor.
4. Modelo de costes por unidad con CAC, pasarela, devoluciones y fulfillment
   (parámetros por canal/mercado) y capital comprometido/sin cobertura.
5. Persistir los supuestos (precio de venta, costes fijos) en el análisis y
   exponerlos; `Product.image_url`/`description`; divisa en `SupplierQuote`.
6. Deduplicar cotizaciones en el backend (una fila por proveedor y búsqueda) o
   exponer «última cotización por proveedor»; hoy el cliente deduplica.

---

## 3. Legal y cumplimiento (`/legal`)

**Hecho.** Selector de producto, contexto (proveedor y mercado reales), parámetros
del análisis, carga del último análisis guardado por producto y mercado, 6 KPIs
(con Legal Gate en tono de veredicto), matriz de requisitos por certificación
exigida, Legal Gate con motivos, riesgos, línea de tiempo de cambios normativos,
borrador de T&C y barra de siguiente paso. Todo sale de `LegalAnalysis`.

**Fuera de alcance por falta de datos reales.**

- Porcentaje de cumplimiento, criticidad por requisito, matriz probabilidad × impacto.
- Evidencias y documentos del producto (versión, fecha, hash, estado, revisión).
- Fuentes regulatorias reales y su última consulta.
- Rol en la operación y mapa de responsabilidades.
- Clasificación de cambios normativos por criticidad.
- Modelo logístico y canal previsto; imagen y descripción del producto.

**Backend que faltaría.**

1. Ampliar `MockRegulatoryDirectory` / `LegalComplianceAgent` para devolver, por
   requisito: `criticality`, `status` (verificado / revisar / incompleto / pendiente /
   no aplica), `source` y `evidence_ids`; y por riesgo: `probability` e `impact`.
2. Guardar en `LegalAnalysis` los parámetros con los que se ejecutó
   (`certification_available`, hoy solo se deduce de la recomendación) y `created_at`
   en `LegalAnalysisOut`.
3. Modelo de documentos de producto (`ProductDocument`: tipo, versión, fecha,
   proveedor, hash, estado de revisión) con subida y endpoint de listado; sin él no
   puede haber evidencias.
4. Determinación del rol en la operación (fabricante / importador / distribuidor /
   vendedor / marketplace / representante) a partir del modelo logístico y de origen,
   y con ello el mapa de responsabilidades.
5. Fuentes regulatorias reales (Comisión Europea, Access2Markets, ECHA, Safety Gate)
   con registro de última consulta, y clasificación de los cambios (crítico /
   relevante / informativo) con filtro por fecha.
6. `Product.logistics_model` y `Product.channel` (o tomarlos del proyecto) para el
   contexto del producto.
7. Traducir/normalizar los textos del dataset (hoy en inglés).

---

## 4. Tienda y canales de venta (`/ecommerce`)

**Hecho.** Contexto del producto (precio y proveedor del análisis económico, Legal
Gate del mercado), tarjetas de canal con estado real, y por canal: tienda propia
(vista previa Desktop/Mobile del texto generado, checkout y plan de pasarela,
Launch readiness, configuración por mercado, contenido generado, producto maestro,
consejos de conversión) y Amazon (contenido, comisiones, competencia, estado,
inventario, riesgos). Carga el historial guardado del producto.

**Fuera de alcance por falta de datos reales.**

- Imagen, descripción y multimedia del producto; galería.
- Score de investigación, % de readiness por canal, calidad del escaparate.
- Funnel de compra (estimado / real) y conversión.
- Modo de checkout y métodos de pago configurables.
- Edición de contenido, SEO, diseño, páginas, A/B testing; generación con IA real.
- Idioma y disponibilidad por mercado; EAN/GTIN, peso, dimensiones, stock proveedor.
- Analytics, tracking, dominio, emails transaccionales.
- Google Shopping, TikTok Shop, «Añadir canal».
- Solicitud de aprobación de lanzamiento.

**Backend que faltaría.**

1. `POST /api/launch-requests` (o equivalente) que cree la solicitud de aprobación
   de lanzamiento de un producto+mercado y la deje en la bandeja de Aprobaciones,
   con los checks de Launch Readiness como cuerpo.
2. Ampliar `EcommerceStorefrontAgent` con: SEO (meta title/description, datos
   estructurados), FAQ, idioma por mercado y disponibilidad; y persistir el
   contenido editable (`PATCH /api/storefronts/{id}`).
3. Modelo de canal (`SalesChannel`: tipo, estado, % readiness calculado, config) y
   agentes para Google Shopping / TikTok Shop; hoy solo hay tienda propia y Amazon.
4. Configuración de checkout: modo (embebido / externo / personalizado) y métodos
   de pago habilitados por mercado, guardados con la tienda.
5. Media de producto (`ProductMedia`: URL, tipo, orden) y `Product.description`,
   `Product.image_url`; ficha maestra con EAN/GTIN, peso, dimensiones y stock.
6. Score de calidad del escaparate (contenido, conversión, SEO, confianza, legal,
   mobile, velocidad) calculado en el backend, y un funnel estimado con su fuente
   (mismo criterio «estimado vs real» que Economía).
7. Integración de analytics/tracking, dominio y email transaccional (o al menos su
   estado de configuración) para los tres últimos checks de Launch Readiness.
8. Traducir/normalizar los textos de las plantillas (hoy en inglés).

---

## 5. Marketing y adquisición (`/marketing`)

**Hecho.** Contexto del producto (precio, margen, landing, Legal Gate), formulario de
campaña (canal y presupuesto), plan por canal con la última propuesta de cada
plataforma, y por propuesta: 6 KPIs estimados, audiencias, creatividad con vista
previa Meta/Google, recomendación del agente, presupuesto asignado y reglas que
aplica el agente. Carga el historial guardado.

**Fuera de alcance por falta de datos reales.**

- Inversión, ingresos atribuidos, CAC/CPA, conversiones y ROAS reales; funnel;
  rendimiento por canal; atribución.
- Reparto de presupuesto en % por canal, Creators/Influencers, TikTok Ads.
- Score/intención/fuente de audiencias; remarketing y lookalike.
- Vídeo, imágenes, Creative Score, variantes y estado de creatividades.
- CAC objetivo y máximo; pacing, gastado, restante.
- Guardrails que dependen de gasto real; recomendaciones basadas en rendimiento real.
- Objetivo, evento de conversión y duración de la campaña.
- Solicitud de aprobación de inversión.

**Backend que faltaría.**

1. Integración de solo lectura con Meta Ads / Google Ads / TikTok Ads (o al menos un
   modelo `CampaignMetrics` diario: impresiones, clics, gasto, conversiones,
   ingresos) con `data_origin` real vs simulado; de ahí salen KPIs, funnel,
   rendimiento por canal y atribución.
2. Ampliar `MarketingCampaignAgent` para aceptar objetivo, evento de conversión,
   duración, CAC objetivo y CAC máximo, y devolver un reparto de presupuesto por
   canal (`channel_plan: [{platform, share, amount, objective}]`).
3. El motor económico debe exponer el **CAC máximo tolerable** (ver Economía) y el
   agente comprobarlo contra el CAC proyectado; sin él no hay guardrail de CAC.
4. Puntuación de audiencias (`score`, `intent`, `source`) y de creatividades
   (`creative_score`, `status`), más generación de variantes y de medios (imagen/
   vídeo) o un brief de storyboard.
5. `POST /api/marketing/investment-requests` que cree la solicitud de aprobación de
   inversión en la bandeja de Aprobaciones con los guardrails evaluados.
6. Motor de guardrails activo (pausar/alertar por CAC o ROAS reales, limitar aumentos
   de presupuesto, bloquear claims/mercados no autorizados) y recomendaciones de IA
   derivadas del rendimiento real.
7. Traducir/normalizar los textos de las plantillas (hoy en inglés).

---

## 6. Operaciones (`/operations`)

**Hecho.** Contexto del producto y mercado, generación de la simulación operativa y,
por informe: KPIs de la simulación, seguimiento del pedido de muestra con tiempos
derivados, proveedor y modelo sin stock (cobro/pago del pedido de muestra),
devoluciones (política), soporte (triaje IA/humano de un ticket de ejemplo), estado y
riesgos. Carga el historial guardado.

**Fuera de alcance por falta de datos reales.**

- Todo el Control Tower: KPIs de operación, pipeline con conteos, pedidos recientes,
  mapa logístico, Operational Health.
- Incidencias de pedido; rendimiento de proveedores y transportistas.
- Devoluciones y soporte reales; automatizaciones y modo operativo.
- Capital adelantado, desfase cobro-pago y cobertura.

**Backend que faltaría.**

1. Modelo de pedidos reales: `Order` (canal, producto, cliente, importes, estado,
   fechas), `OrderEvent` (etapa, timestamp, fuente) y `Shipment` (transportista,
   tracking, estado). Sin esto no hay ninguno de los KPIs ni el pipeline.
2. Endpoint de listado y agregados (`GET /api/operations/orders`,
   `/api/operations/summary`) con conteos por etapa, % a tiempo, entrega media y tasa
   de devoluciones.
3. Incidencias de pedido (`OrderIncident`: pedido, proveedor, prioridad, SLA,
   responsable, acción recomendada) o extender `Incident` con `order_id`/`supplier_id`/
   `sla_due_at`.
4. Métricas de proveedor y transportista calculadas desde los pedidos, que también
   alimenten a Proveedores y abastecimiento (aceptación, despacho en SLA, defectos,
   tracking válido, score operativo).
5. Devoluciones (`ReturnRequest`: motivo, estado, importes) y tickets de soporte reales
   con el mismo triaje IA/humano.
6. Reglas de automatización (`AutomationRule`: disparador, acción, estado) y el modo
   operativo, con su registro en Auditoría.
7. Fechas de cobro y pago para calcular capital adelantado, desfase y cobertura.
8. Relacionar explícitamente el `OperationsRecord` con la cotización usada
   (`supplier_quote_id`) para no depender de «la más reciente».
9. Traducir/normalizar los textos de las plantillas (hoy en inglés).
