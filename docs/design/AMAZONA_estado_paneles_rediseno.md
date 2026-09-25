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

**Cambio de criterio (22-09-2026, decisión del propietario).** En la segunda
pasada, pantalla a pantalla, cada panel debe verse como su mockup aunque haya que
usar **datos de demostración** donde el backend aún no los da; se sustituirán por
los reales cuando el sistema esté completo. Reglas para que sigan siendo
reemplazables: los valores inventados viven en `lib/demo/<panel>.ts` (nunca
sueltos en los componentes), lo real se usa siempre que exista, y la pantalla
lleva la etiqueta `DataProvenanceBadge status="demo"` («Datos de demostración»)
con la lista de lo que es demo en su tooltip. Los apartados «Backend que
faltaría» siguen siendo la lista de lo que hay que sustituir.

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
| 7 | Finanzas y control | Rediseñado |
| 8 | Proyectos | Rediseñado |
| 9 | Agentes | Rediseñado |
| 10 | Aprobaciones | Rediseñado |
| 11 | Auditoría | Rediseñado |
| 12 | Estado | Rediseñado |

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
| `VerdictBanner` | Economía, Legal | Tienda (estado de lanzamiento), Aprobaciones, Estado |
| `ProductHeader` | Economía, Legal | Tienda, Marketing (cabecera de producto de cada mockup del pipeline) |
| `KpiCard` `tone` | Legal | Tarjetas KPI cuyo valor es un veredicto |
| `StackedBar` | Finanzas | Proyectos (lifecycle/health), Agentes (uso), Auditoría (eventos por tipo) |
| `RankedBars` | Finanzas | Agentes (rendimiento), Proyectos, Auditoría |
| `lib/markets.ts` | Legal, Tienda | Marketing, Operaciones (etiquetas de mercado y «último por mercado») |
| `lib/product-channels.ts` | Tienda | Marketing, Operaciones (todo lo persistido de un producto) |
| `LineChart` | Economía (2.ª pasada) | Estado (latencia, requests), Marketing, Finanzas (series temporales) |
| `SensitivityBars` | Economía (2.ª pasada) | Finanzas, Legal (impacto por variable con nivel) |
| `Flag` | Economía (2.ª pasada) | Proveedores, Legal, Tienda (mercados y orígenes) |
| `DataProvenanceBadge` `demo` / `compact` | Economía (2.ª pasada) | Todo panel con datos de demostración o filas densas |
| `KpiCard` `accent` / `footer` | Economía (2.ª pasada) | KPIs con importe en verde o con chip/barra inferior |
| `PageHeader` `actions` | Economía (2.ª pasada) | Cabeceras con fecha, selector o acciones a la derecha |
| `HeaderClock` / `HeaderTile` | Economía, Investigación | Cabecera de todos los paneles (fecha y selector/modo) |
| `Sparkline` | Investigación | Tablas con tendencia (Marketing, Tienda, Proveedores) |
| `LevelChip` | Investigación | Niveles Alta/Media/Baja o Bajo/Medio/Alto (Proveedores, Legal, Riesgos) |
| `InfoTile` / `ProductSummary` | Economía, Legal | Franja de producto de Tienda, Marketing, Operaciones |
| `RingGauge` | Legal | Porcentajes de cumplimiento o avance (Proyectos, Operaciones) |
| `RiskMatrix` | Legal | Riesgos probabilidad × impacto (Finanzas, Proyectos, Operaciones) |
| `KpiCard` `leading` | Legal | KPIs con icono o gráfico a la izquierda |
| `DonutChart` | Marketing (2.ª pasada) | Finanzas (reparto de ingresos/gastos), Operaciones, Estado |
| `LineChart` `xTicks` / `dots` | Marketing (2.ª pasada) | Series largas (30 días) sin saturar el eje ni los puntos |
| `lib/marketing-view.ts` | Marketing (2.ª pasada) | Operaciones y Finanzas (CAC, ROAS y funnel del mismo periodo) |
| `RouteMap` tono / detalle / leyenda | Operaciones (2.ª pasada) | Cualquier mapa con estado por nodo (Proveedores, Estado) |
| `lib/operations-view.ts` | Operaciones (2.ª pasada) | Finanzas y Panel (pedidos, entregas e incidencias del periodo) |
| `demoSku` | Tienda, Operaciones | Cualquier panel que enseñe el SKU mientras no haya catálogo |
| `CashFlowChart` | Finanzas (2.ª pasada) | Panel y Director ejecutivo (caja y previsión) |
| `lib/cfo-view.ts` | Finanzas (2.ª pasada) | Panel, Director ejecutivo (P&L, caja y salud financiera) |
| `lib/projects-view.ts` | Proyectos (2.ª pasada) | Panel y Director ejecutivo (cartera y fases por producto) |
| `AgentCard` (rediseñada) | Agentes (2.ª pasada) | Panel y Director ejecutivo (flota de agentes) |
| `lib/agents-view.ts` | Agentes (2.ª pasada) | Panel, Proyectos (actividad y salud de la flota) |
| `lib/approvals-view.ts` | Aprobaciones (2.ª pasada) | Panel y Director ejecutivo (bandeja de decisiones) |
| `lib/audit-view.ts` | Auditoría (2.ª pasada) | Panel y Proyectos (actividad y trazabilidad) |
| `lib/status.ts` | Estado | Cabecera y Panel (indicador «Sistema operativo» a partir de la señal real) |
| `ServiceMap` por niveles | Estado (2.ª pasada) | Cualquier topología con estado por nodo (Proyectos, Operaciones) |
| `ColumnChart` | Estado (2.ª pasada) | Series temporales en barras sin etiqueta por barra (Marketing, Finanzas) |
| `LineChart` `compact` | Estado (2.ª pasada) | Minigráficos con ejes legibles en tarjetas estrechas |
| `KpiCard` `provenanceCompact` | Estado (2.ª pasada) | Filas de muchas tarjetas KPI estrechas |
| `lib/status-view.ts` | Estado (2.ª pasada) | Panel y Director ejecutivo (salud de la plataforma y runtime de agentes) |
| `LineChart` eje derecho / `dashed` | Panel (2.ª pasada) | Cualquier gráfico con dos escalas (Finanzas, Marketing, Economía) |
| `KpiCard` `trailing` | Panel (2.ª pasada) | KPIs con minigráfico a la derecha del valor |
| `TEAM_ICON` | Panel (2.ª pasada, extraído de Agentes) | Todo panel que enseñe agentes por equipo |
| `lib/dashboard-view.ts` | Panel (2.ª pasada) | Director ejecutivo (mismo resumen del negocio) |
| `components/neural-nexus/` | Director ejecutivo (2.ª pasada) | Cualquier pantalla que necesite el mapa de la flota |
| `lib/neural-nexus.ts` | Director ejecutivo (2.ª pasada) | Panel y Agentes (jerarquía y estado de la flota) |
| `PrecisionNode` | Director ejecutivo (iteración 2) | Lenguaje visual común de cualquier nodo 3D |
| `lib/decision-engine.ts` | Director ejecutivo (iteración 3) | Cualquier vista que necesite la geometría del Decision Engine (la vista 2D ya la usa) |
| `lib/demo-boundary.test.ts` | Milestone 30 | Congela qué módulos dependen de `lib/demo`; la lista solo puede encoger |

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

**Segunda pasada (22-09-2026), fiel al mockup.** Estructura del mockup completa:
cabecera con fecha y selector de producto, franja de producto (score, proveedor,
mercado, modelo logístico), 6 KPIs, pestañas-ancla, escenarios con gráfico de
evolución, desglose de 8 costes por unidad con su origen, simulador interactivo,
sensibilidad, punto de equilibrio con gráfico y tabla, viabilidad y barra final
con «Guardar análisis» (real, `POST /api/economics/runs`) y menú «…». Todo se
calcula en `lib/economics-model.ts` a partir de un único conjunto de supuestos,
así que las cifras son coherentes y el simulador las recalcula en vivo. Real:
producto, cotización (proveedor, precio, logística, MOQ), último análisis
guardado (precio, costes fijos, pedidos del escenario base; antes se perdía al
recargar). Demo (`lib/demo/economics.ts`): proveedor si no hay cotización,
reparto transporte/arancel, fulfillment, pasarela, devoluciones, CAC, otros
costes, conversión, variación de precio de los escenarios, score, mercado,
modelo logístico y descripción. Lo de abajo describe la primera pasada; su
«Backend que faltaría» sigue vigente y además hace falta que el motor del
backend calcule lo que hoy hace `lib/economics-model.ts`.

**Primera pasada — Hecho.** Selector de producto y de cotización real, supuestos (precio de venta,
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

---

## 7. Finanzas y control (`/cfo`)

**Hecho.** Generación y carga de informes CFO, 6 KPIs (salud, productos analizados,
% NO_GO, uso de presupuesto, campañas, presupuesto diario), presupuesto global con
reparto real de reservas, salud financiera con reglas del agente, cartera y
rentabilidad por producto (estimada), historial de informes.

**Fuera de alcance por falta de datos reales.**

- Caja, ingresos, beneficio neto, margen neto, gasto, runway; cash flow y forecast.
- P&L consolidado; Budget vs Real vs Forecast por áreas; variance analysis.
- Tesorería, cuentas a pagar y a cobrar, Working Capital.
- Fiscalidad, contabilidad, capital y financiación.
- CFO Copilot y Financial Health de siete componentes; alertas basadas en datos reales.
- Reparto del presupuesto por áreas; rentabilidad por canal/país/proveedor/campaña/proyecto.

**Backend que faltaría.**

1. Libro de movimientos (`LedgerEntry`: fecha, cuenta, categoría, importe, moneda,
   origen, conciliado) alimentado por pedidos reales, gastos publicitarios y pagos a
   proveedores; de él salen caja, ingresos, gasto, P&L y runway.
2. Integraciones de solo lectura con pasarelas y bancos (Stripe, PayPal, Amazon,
   cuenta operativa) para tesorería y cuentas a cobrar; `Payable` para cuentas a pagar.
3. Presupuesto por área (`Budget.area`, presupuesto vs real) y periodo, con endpoint de
   Budget vs Real vs Forecast y variance analysis con causas.
4. Motor de forecast (escenarios y horizontes de 3/6/12 meses) sobre el libro, sin
   duplicar el motor económico de producto.
5. Working Capital: cobro cliente vs pago a proveedor por pedido (ver Operaciones) y
   objetivo de cobertura 75–90 %.
6. Fiscalidad y contabilidad: IVA/impuestos estimados, obligaciones, conciliación,
   distinguiendo borrador de declaración presentada (la facturación real sigue en un
   sistema Verifactu de terceros).
7. Endpoint agregado de la última decisión económica por producto
   (`GET /api/economics/analyses/latest`) para no hacer una petición por producto, y
   `created_at` en `CFOReportOut` para poder ordenar y fechar el historial.
8. CFO Copilot con fuente, periodo y cálculo en cada respuesta, y un Financial Health
   score explicable por componentes.
9. Traducir/normalizar los textos de riesgos y evidencias (hoy en inglés).

---

## 8. Proyectos (`/projects`, `/projects/[id]`)

**Hecho.** Portfolio con KPIs, filtros por estado, tabla con progreso y beneficio
previsto, y expediente con Project Health, pipeline de las cuatro fases validadas,
próxima decisión (con la aprobación pendiente), riesgos reales, actividad de auditoría,
hitos, grafo de tareas y evidencia.

**Fuera de alcance por falta de datos reales.**

- Beneficio real, previsto vs real, aprendizajes del proyecto.
- Fases de preparación / lanzamiento / operativo / escala, pausado, descartado, próximo gate.
- Mercado, categoría, producto, modelo logístico, fecha de inicio; beneficio por mercado.
- Tienda, Marketing, Operaciones y Escala en el pipeline; salud de canal/marketing/
  operaciones; score numérico de salud; CAC máximo.
- Hitos comerciales (primera venta, 100 ventas, break-even), agentes trabajando en vivo,
  vistas Pipeline/Timeline y pestañas de métricas/finanzas/documentos.

**Backend que faltaría.**

1. Enlazar el proyecto con su producto y mercado (`Project.product_id`, `Project.market`)
   y guardar `created_at` en `ProjectOut`; con eso salen las tablas por producto, mercado y
   fecha, y los datos de tienda, marketing y operaciones pasan a colgar del proyecto.
2. Ciclo de vida real (`BORRADOR → VALIDACIÓN → PREPARACIÓN → LANZAMIENTO → OPERATIVO →
   ESCALA`, más pausado/bloqueado/descartado/cerrado) con las transiciones que hoy no
   existen; el orquestador solo produce `VALIDATING/APPROVED/REJECTED`.
3. Project Health como score explicable (`GET /api/projects/{id}/health`) con las ocho
   dimensiones de la spec y su fuente, en lugar de derivarlo en el cliente de la evidencia.
4. Resultados reales por proyecto (ventas, ingresos, CAC, margen, devoluciones, entrega) y
   comparativa previsto vs real; hitos comerciales derivados de pedidos reales.
5. Aprendizajes del proyecto (`ProjectLearning`) que alimenten la memoria del sistema
   (`MemoryService`) y un endpoint de lectura.
6. `GET /api/projects/summary` con conteos y agregados para no hacer una petición de tareas
   y de decisiones por proyecto al montar el portfolio.
7. Traducir/normalizar los textos de riesgos de los agentes (hoy en inglés).

---

## 9. Agentes (`/agents`)

**Hecho.** KPIs de la flota, tarjetas por equipo (con búsqueda y filtro), actividad con
exportación y alertas por fallos, rendimiento por agente con ventana de tiempo y gráficos de
reparto, y versiones vigentes.

**Fuera de alcance por falta de datos reales.**

- Costes medidos (coste del día, tokens, API calls, búsquedas), Evaluation Suite y score.
- Estado «Ejecutando», proyecto/tarea en curso y progreso de la tarjeta.
- Historial de versiones, staging/producción, rollback; herramientas y permisos; handoffs;
  trazas operativas; vista de detalle; «Nueva versión de agente».
- Alertas por umbral (error rate, coste, latencia, versión degradada).
- Filtros por proyecto y modelo; actividad en tiempo real.
- Ejecuciones de los agentes de la Fase 3 (no escriben en el log).

**Backend que faltaría.**

1. Que todos los agentes (no solo el CEO) registren `AgentExecutionLog` con `project_id`,
   `task_id`, `model`, `input_tokens`/`output_tokens`, `cost` y `error`, para poder filtrar
   por proyecto y modelo y medir costes reales.
2. Estado en vivo del agente (`RUNNING`, `WAITING`, `PAUSED`, `ERROR`, `NEEDS_REVIEW`) con
   la tarea actual y su progreso, en `AgentOut`.
3. `Agent.team` en el registro (hoy el cliente lo deduce del rol) y reorganizar el pool a
   los 13 agentes operativos de la spec (Product Hunter, Market Analyst, Supplier Finder…).
4. Evaluation Suite (`AgentEvaluation`: versión, métricas de relevancia, errores, grounding,
   coste, latencia, cumplimiento; umbral de despliegue) con endpoint de lectura.
5. Versionado (`AgentVersion`: versión, fecha, evaluación, entorno producción/staging,
   comparación) y rollback.
6. Herramientas y permisos por agente (`AgentTool`, `AgentPermission`: disponible vs
   otorgado) y registro de handoffs entre agentes.
7. Alertas de agentes con umbrales configurables (error rate, coste, latencia, degradación)
   y su endpoint.
8. Quitar el límite fijo de 100 en `GET /api/agent-executions` (paginación) o añadir
   `GET /api/agents/summary` con agregados por ventana de tiempo (24 h/7 d/30 d) para no
   traer todo el log al cliente.

---

## 10. Aprobaciones y decisiones (`/approvals`)

**Hecho.** KPIs (pendientes, vencen en 24 h, aprobadas hoy), bandeja lista+detalle con
aprobaciones de gasto y revisiones de pipeline, filtros y búsqueda, detalle con las
validaciones y el impacto de aprobar/rechazar, y las acciones reales (aprobar, rechazar,
interruptor de emergencia) intactas. Corrige el manejo de fechas UTC (`isExpired`).

**Fuera de alcance por falta de datos reales.**

- Criticidad, solicitante, fecha de solicitud (antigüedad, tiempo medio), presupuesto visible.
- Solicitar cambios, motivo de rechazo obligatorio y feedback a agentes.
- Cadena de aprobación, separación de funciones, guardrails condicionados, reglas de
  autoaprobación, Workflow Builder, simulador de políticas.
- Documentos y comentarios; pestaña «Reglas»; sesión de aprobador real.
- Historial de revisiones de pipeline ya resueltas.

**Backend que faltaría.**

1. Ampliar `Approval` con `requested_by`, `requested_at`, `priority` (crítica/alta/media/baja),
   `kind` (presupuesto, lanzamiento, proveedor, stock, excepción legal, campaña, canal, pago
   extraordinario, reembolso, deploy de agente, automatización), `conditions` (guardrails:
   importe máximo, CAC, mercado, duración) y `project_id`; con `requested_at` salen la
   antigüedad y el tiempo medio de resolución.
2. `POST /api/approvals/{id}/request-changes` y `reason`/`reason_code` obligatorio en el
   rechazo (riesgo, presupuesto, documentación, política, alternativa, otro), con el feedback
   guardado para los agentes.
3. Modelo de política de aprobación (`ApprovalPolicy`: tipo, importe, riesgo, canal, proyecto,
   aprobadores en cadena, autoaprobación) y motor que la evalúe, con separación de funciones
   (`requested_by != resolved_by`), más un endpoint de simulación de políticas y un editor de
   workflow.
4. Autenticación real del aprobador: hoy la interfaz envía siempre `owner@amazona.local`; el
   backend debería tomar el actor de la sesión (`authenticated_actor`) y validarlo.
5. Presupuesto en la solicitud: `GET /api/approvals/{id}/budget` con asignado, gastado,
   comprometido, disponible e impacto, desde el `BudgetEngine`.
6. Documentos y comentarios de la solicitud (`ApprovalAttachment`, `ApprovalComment`).
7. `GET /api/pipeline/reviews?status=` para listar también las revisiones resueltas y poder
   mostrarlas en «Decididas» / historial.
8. `GET /api/approvals/summary` (pendientes, críticas, vencen pronto, aprobadas hoy, tiempo
   medio) para no calcular los KPI en el cliente.

---

## 11. Auditoría y trazabilidad (`/audit`)

**Hecho.** KPIs, siete pestañas (eventos con filtros, paginación y detalle antes/después con
Correlation Trace; timeline; actividad por proyecto y por actor; acciones de personas;
integridad y retención como pendientes) y el filtro por ID de correlación.

**Fuera de alcance por falta de datos reales.**

- Criticidad, resultado y acciones críticas por evento; anomalías.
- Hash por evento, cadena de hashes y verificación de integridad; evidencias con hash y
  versión; provenance; historial de versiones; auditoría IA (modelo, coste, herramientas).
- Origen del evento, IP y user agent; expediente forense por proyecto.
- Retención; exportación JSON/PDF; paquete de auditoría.
- Eventos de seguridad reales (login, permisos, API keys, integraciones).

**Backend que faltaría.**

1. `GET /api/audit` con paginación y orden descendente (`?limit=&before=`), filtros
   (`actor`, `action_prefix`, `project_id`, `from`/`to`) y total; hoy corta en 500 los más
   antiguos.
2. Campos en `AuditLog`: `project_id`, `event_type`, `severity` (criticidad), `result`,
   `source`, `ip`, `user_agent`; con ellos las columnas y el KPI de acciones críticas son
   reales y el proyecto no hay que deducirlo por correlación.
3. Registro append-only con integridad: `prev_hash` y `hash` por evento (cadena), endpoint
   `GET /api/audit/integrity` (última verificación, eventos íntegros, modificados) y
   restricciones de base de datos que impidan `UPDATE`/`DELETE`.
4. Evidencias (`AuditEvidence`: tipo, hash, versión, origen, estado, evento) y su endpoint, y
   provenance por evento.
5. Detector de anomalías (precio sin aprobación, acción fuera de política, cambios de
   configuración inusuales) que escriba eventos propios.
6. Auditoría de seguridad (inicios de sesión, cambios de permisos, API keys, integraciones,
   políticas) y de IA (versión, modelo, herramientas, coste, duración).
7. Política de retención por tipo de evento y `POST /api/audit/package` que genere el
   paquete por proyecto/periodo (eventos, aprobaciones, evidencias, versiones, hashes) y las
   exportaciones JSON/PDF.
8. `GET /api/audit/summary` (eventos del día, aprobaciones, errores…) para no contarlos en el
   cliente.

## 12. Estado e infraestructura (`/status`)

**Hecho.** Banner de estado general con prioridad visual, seis KPIs (estado general,
servicios con señal, latencia de la API medida en la carga, incidentes activos, migración,
ejecuciones de agentes), tabla de los servicios con señal real con icono y texto, mapa de
servicios, incidentes (reportar y resolver), tarjeta de base de datos, últimas diez
ejecuciones de agentes y el estado «backend caído» sin cifras inventadas.

**Fuera de alcance por falta de datos reales.**

- Uptime, p50/p95/p99, requests/min, 2xx/4xx/5xx, error budget.
- Los otros 14 servicios del mockup; disponibilidad real de Supabase (solo se sabe si está
  configurado).
- Colas, dead-letter, workers, cron; integraciones y rate limits.
- Métricas de base de datos; deployments; migraciones anteriores/pendientes/fallidas.
- Coste técnico; Logs Explorer; página de estado pública.
- Causa, impacto y duración de incidentes; apertura automática.

**Backend que faltaría.**

1. Endpoint de métricas (`GET /api/infra/metrics?window=`): uptime, latencias p50/p95/p99,
   requests/min, 2xx/4xx/5xx y error budget, con serie temporal.
2. `GET /api/infra/services`: estado, latencia y último chequeo por servicio (Auth, Storage,
   Realtime, Edge Functions, Workers, Queue, Cron, Email, Monitoring, Logs, Backup, CDN,
   DNS, certificados), comprobando de verdad Supabase y no solo su configuración.
3. Colas: tareas pendientes, en curso, dead-letter y la más antigua; workers activos.
4. Cron: tareas programadas con última ejecución, resultado y próxima.
5. Integraciones y rate limits: estado, latencia, errores y consumo del límite de Stripe,
   Google/Meta Ads, Amazon SP-API, OpenAI…
6. Deployments: versión, commit, fecha, autor y estado del despliegue actual y anteriores.
7. Migraciones: aplicadas (con fecha), pendientes y fallidas, no solo la versión actual.
8. Métricas de base de datos: CPU, memoria, conexiones, cache hit, queries lentas, locks,
   storage e IOPS.
9. Coste técnico por concepto (inferencia de IA, base de datos, storage, functions, APIs).
10. Logs técnicos consultables por servicio, nivel, request y correlación.
11. Incidentes con causa, impacto, servicios afectados, duración y responsable; apertura
    automática cuando un chequeo falla y cierre enlazado a la recuperación.

## Investigación (`/research`) — segunda pasada

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real:
productos y las señales del agente de los productos investigados en la sesión
(persistidas en la URL con `?runs=`). Demo (`lib/demo/research.ts`): el resto.

**Backend que faltaría (para sustituir la demo).**

1. `GET /api/research/runs` (o `GET /api/products/{id}/research`) para listar las
   investigaciones pasadas y no depender de la URL.
2. Señales reales (sustituir `MockTrendsProvider`): demanda, competencia, futuro,
   riesgo regulatorio, escalabilidad y logística por mercado.
3. Serie temporal de interés por producto y por fuente (Google, marketplaces,
   e-commerce, redes) y crecimiento a 3/6/12 meses.
4. Margen preliminar estimado, subcategoría, imagen y descripción del producto.
5. Filtros de mercado y modelo de negocio en `POST /api/research/runs`.
6. Seguimiento de productos en el backend (hoy «Seguir» es local del navegador) y
   descartes automáticos con motivo.
7. Insights generados por el agente.

## 1 (segunda pasada). Proveedores y abastecimiento

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real:
cotizaciones del producto (se cargan al entrar). Demo (`lib/demo/sourcing.ts`):
proveedores de ejemplo cuando no hay cotizaciones y el perfil de cada proveedor.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 1 y además:

1. `SupplierQuote` con país y ciudad, certificaciones (y su estado), envío directo,
   plazo de entrega al destino, modo de transporte, Incoterms y métodos de pago.
2. Scores de calidad, compliance y escalabilidad por proveedor, y un score global
   calculado en el backend.
3. Criterios de compatibilidad (packaging neutro, tracking, stock sincronizable,
   devoluciones UE, SLA, pago tras venta) como campos del proveedor.
4. Landed cost desglosado (transporte, arancel/IVA, fulfillment, pago/divisa,
   devoluciones) desde el motor, no con supuestos del cliente.
5. Búsquedas guardadas en el backend y fecha de cada cotización.

## 3 (segunda pasada). Legal y cumplimiento

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real: lo que
devuelve el agente legal (certificaciones exigidas, restricción, riesgos, cambios,
recomendación). Demo (`lib/demo/legal.ts`): el resto.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 3 y además:

1. Catálogo de requisitos por categoría y mercado con criticidad, fuente y estado
   por producto (verificado, revisar, incompleto, no aplica, pendiente).
2. Almacén de documentos y evidencias por requisito (versión, fecha, hash, estado).
3. Consulta real y fecha de las fuentes regulatorias (Comisión Europea,
   Access2Markets, ECHA, Safety Gate, legislación nacional).
4. Rol de AMAZONA en la operación y mapa de responsabilidades por actor.
5. Riesgos legales con probabilidad e impacto.
6. Cambios normativos con relevancia (crítico, relevante, informativo).
7. Modelo logístico y canal previsto del producto.

## 4 (segunda pasada). Tienda y canales de venta

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real:
borradores de tienda y de Amazon, análisis económico y legal. Demo
(`lib/demo/storefront.ts`): el resto.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 4 y además:

1. Integraciones de Google Shopping y TikTok Shop, y alta de canales.
2. Readiness por canal calculado en el backend.
3. Configuración de checkout persistida (modo y métodos de pago) y conexión real con
   la pasarela.
4. Analítica de la tienda: visitas, embudo y conversión reales; puntuaciones de SEO,
   rendimiento y mobile.
5. Contenido completo del generador: FAQ, multimedia, meta title/description y
   schema.org; páginas del sitio y experimentos A/B.
6. Mercados por país (precio, idioma, estado) y ficha maestra del producto (EAN,
   peso, dimensiones, stock del proveedor).

## 5 (segunda pasada). Marketing y adquisición

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real:
propuestas de campaña del agente (canal, presupuesto diario, audiencias,
creatividad, CTR y conversión estimados, recomendación) y los supuestos de Economía
(precio, margen, CAC objetivo y CAC máximo). Demo (`lib/demo/marketing.ts`): todo lo
que exige gasto real en plataformas y el resto del panel.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 5 y además:

1. Métricas diarias por campaña y canal (impresiones, clics, gasto, conversiones,
   ingresos) con `data_origin`, de donde saldrían KPIs, funnel, rendimiento y
   atribución; hoy todas esas cifras son simuladas.
2. Reparto de presupuesto por canal devuelto por el agente (`channel_plan`) y canales
   más allá de Meta y Google (TikTok, creators, display).
3. Modelos de atribución (último clic, primer clic, lineal, data driven) calculados
   con datos reales.
4. Puntuación de audiencias (`score`, `intent`, `source`) y creatividades con medios
   (vídeo/imagen), `creative_score`, estado y variantes.
5. Objetivo, evento de conversión y duración aceptados por `POST /api/marketing/runs`.
6. Presupuesto asignado y gasto real del periodo, con pacing y guardrails activos
   (pausar por CAC o ROAS, limitar subidas de presupuesto).
7. `POST /api/marketing/investment-requests` para la aprobación de inversión.

## 6 (segunda pasada). Operaciones

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real: catálogo,
cotizaciones de proveedor, precio de Economía y, si existe, el informe del agente de
operaciones (seguimiento, política de devoluciones y ticket de soporte). Demo
(`lib/demo/operations.ts`): pedidos, clientes, canales, transportistas, incidencias,
devoluciones, mapa, salud operativa y automatizaciones.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 6 y además:

1. Pedidos reales (cliente, canal, importe, estado, fechas prometida y real) y su
   histórico, que es de donde saldrían KPIs, pipeline y tabla.
2. Incidencias con prioridad, responsable, SLA y acciones (resolver, investigar,
   gestionar) que hoy no tienen endpoint.
3. Tracking real del transportista por pedido y catálogo de transportistas con
   puntualidad y tiempos medidos.
4. Devoluciones con motivo y estado, y su tasa sobre pedidos entregados.
5. Métricas de proveedor operativas (aceptación, despacho en SLA, cancelaciones,
   defectos) en vez de derivarlas de la fiabilidad de la cotización.
6. Operational Health calculado en el backend, con su explicación por eje.
7. Motor de automatizaciones (reglas, modo operativo) persistido y auditable.

## 7 (segunda pasada). Finanzas y control

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real: los
análisis económicos (la cuenta de resultados usa los mismos supuestos que Economía),
las cotizaciones, los escenarios del agente económico y, del informe del agente CFO,
el veredicto de salud, las reservas y los riesgos. Demo (`lib/demo/cfo.ts`): caja,
tesorería, cash flow, presupuesto anual sin límite del BudgetEngine, fiscalidad,
subvenciones y copiloto; los cobros y pagos vienen de los pedidos de Operaciones.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 7 y además:

1. Contabilidad real: asientos, cuenta de resultados y balance por periodo.
2. Tesorería conectada (banco y pasarelas) con saldos y movimientos.
3. Cuentas a cobrar y pagar reales, con vencimientos y estado de cada factura.
4. Presupuesto anual por categoría en el BudgetEngine (hoy solo hay límite global,
   reservas y comprometido) y aprobación de ampliaciones.
5. Fiscalidad: IVA e impuesto de sociedades calculados sobre facturación real
   (la facturación debe pasar por un sistema certificado Verifactu de terceros).
6. Forecast financiero del backend, no derivado en el cliente.
7. Endpoint conversacional del agente CFO para el copiloto.

## 8 (segunda pasada). Proyectos

**Hecho.** Estructura completa del mockup en una sola pantalla maestro-detalle (ver
milestone-28-demo.md); `/projects/[id]` redirige a la selección. Real: cada producto
del catálogo como proyecto con sus fases (Investigación, Proveedores, Economía,
Legal, Tienda, Marketing, Operaciones), la auditoría y los agentes; también los
proyectos del Director ejecutivo si existen. Demo (`lib/demo/projects.ts`): los
proyectos de ejemplo que dan volumen a la cartera, los documentos y el capital
adelantado; el beneficio real sale de los pedidos de Operaciones.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 8 y además:

1. Enlazar el proyecto con su producto, mercado y modelo logístico, y guardar su
   fase de negocio (no solo el grafo de tareas).
2. Salud del proyecto, progreso y capital expuesto calculados en el backend.
3. Beneficio real del proyecto a partir de ventas reales.
4. Hitos con fecha propia (hoy se leen de la auditoría) y documentos del proyecto.
5. Decisiones pendientes accionables desde el proyecto (aprobar o rechazar) y su
   trazabilidad.
6. Aprendizajes guardados y aplicables al sistema.

## 9 (segunda pasada). Agentes

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real: el
registro de agentes y, si tiene filas, el log de ejecuciones (éxito, latencia,
actividad, distribución y alertas). Demo (`lib/demo/agents.ts`): descripción,
evaluación, coste por ejecución, tarea en curso, herramientas, versiones anteriores
y, mientras el log esté vacío, las propias ejecuciones.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 9 y además:

1. Registrar ejecuciones reales de cada agente (hoy el log está vacío) con su coste
   y tokens, no solo duración y éxito.
2. Descripción, equipo y herramientas/permisos en el registro de agentes.
3. Suite de evaluación con su puntuación por agente y versión.
4. Tarea en curso del agente y su progreso.
5. Histórico de versiones con notas y despliegue de una nueva versión.
6. Umbrales de alerta configurables y su estado.

## 10 (segunda pasada). Aprobaciones y decisiones

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real: las
aprobaciones y revisiones de pipeline del backend (con aprobar y rechazar
conectados), los agentes registrados y los análisis del producto que alimentan
validaciones, importes, hallazgos y riesgos. Demo (`lib/demo/approvals.ts`): las
solicitudes de ejemplo mientras la bandeja esté vacía, severidad, SLA,
estadísticas, documentos, flujo y comentarios.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 10 y además:

1. Tipo, severidad, proyecto, producto y agente solicitante en cada aprobación.
2. Validaciones y análisis de agentes asociados a la solicitud, no recalculados.
3. SLA y vencimiento por severidad, y métricas de resolución (tiempo medio,
   aprobadas y rechazadas por periodo).
4. Pedir cambios como acción, además de aprobar y rechazar.
5. Hilo de comentarios y documentos adjuntos por solicitud.
6. Reglas de aprobación consultables (qué exige aprobación humana y con qué límite).

## 11 (segunda pasada). Auditoría y trazabilidad

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real: las
entradas de `AuditLog` con su tipo, actor, resultado, proyecto, cambios de estado y
cadena de correlación. Demo (`lib/demo/audit.ts`): los eventos que llenan la ventana
de 30 días, la criticidad, la IP, el user agent, las evidencias, el hash, las
anomalías y la retención.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 11 y además:

1. Registrar de verdad todos los eventos (hoy solo se auditan las ejecuciones de
   agentes), con criticidad y resultado propios.
2. Proyecto y producto en la entrada, no deducidos del recurso.
3. Origen del evento: IP, user agent y sesión.
4. Evidencias documentales asociadas al evento.
5. Hash encadenado y firma de integridad, con verificación periódica.
6. Detección de anomalías y política de retención configurable.
7. Paquete de auditoría exportable (CSV, JSON y PDF firmado).

## 12 (segunda pasada). Estado e infraestructura

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). Real: la
comprobación de salud `/health/detailed` (base de datos, migración aplicada y
configuración de Supabase) con su latencia cronometrada desde el servidor del
frontend, el registro de agentes, el log de ejecuciones (de donde salen el estado
de los workers, su puntuación de System Health, los jobs fallidos de hoy y el
coste de inferencia) y los incidentes registrados a mano. Demo
(`lib/demo/status.ts`): el estado de los doce servicios sin telemetría, el uptime
de 30 días y la latencia p95 de los dieciocho, las series de las últimas 24 horas,
las colas y el runtime, las tareas programadas, las integraciones externas, las
métricas del motor de base de datos, los despliegues y el coste de
infraestructura. Se retira `PendingFeatures`, que quedaba sin uso: ahora cada
tarjeta declara al pie qué parte suya es de demostración.

**Backend que faltaría (para sustituir la demo).** Lo de la sección 12 y además:

1. Disponibilidad de 30 días y percentiles de latencia (p50/p95/p99) por servicio,
   con su serie temporal.
2. Comprobación de salud de los otros doce servicios (Realtime, Edge Functions,
   Queue, Cron, Email, Monitoring, Logs, Backup, CDN, DNS y certificados).
3. Series de requests por minuto, respuestas por código y tasa de errores 5xx.
4. Cola de trabajos: profundidad por cola, dead-letter, tarea más antigua, tiempo
   medio en cola, workers activos/ocupados y jobs en ejecución.
5. Estado, latencia, errores y consumo de límites de las integraciones externas.
6. Planificador consultable: tareas programadas, última ejecución, resultado y
   fallos de las últimas 24 h.
7. Métricas del motor de base de datos (CPU, memoria, conexiones, cache hit,
   queries lentas, locks, storage e IOPS).
8. Registro de despliegues (versión, entorno, commit, fecha y resultado) y estado
   de las migraciones (anterior, pendientes y fallidas).
9. Coste de infraestructura medido por partida, no estimado.
10. Detección automática de incidentes (hoy se abren a mano) y página de estado
    pública.

## Panel (segunda pasada). Panel de inicio

**Hecho.** Estructura completa del mockup (ver milestone-28-demo.md). El Panel no
calcula nada propio: reúne lo que ya calculan las demás pantallas, para que ninguna
cifra se contradiga con la suya. Ventas, beneficio y la serie de ventas/margen
salen del mismo P&L que Finanzas (`lib/cfo-view.ts`) sobre los análisis económicos
reales; el reparto por día lo dan los pedidos de Operaciones (`buildOrders`); el
margen de cada oportunidad es el `contributionMargin` del mismo modelo que Economía
(`lib/economics-model.ts`), no el `margin_percent` del análisis, que ninguna otra
pantalla usa; el orden de las oportunidades es el score de Investigación
(`buildRows`); la actividad viene de `agentCards` de Agentes; y las decisiones, de
las mismas solicitudes que Aprobaciones (reales del backend más las de
demostración). La fase de cada producto («En observación» → «Lanzamiento») sale de
hasta dónde ha llegado de verdad su pipeline.

**Backend que faltaría (para sustituir la demo).** Lo que ya piden las secciones de
Economía, Finanzas, Operaciones y Aprobaciones y, además:

1. Ventas y beneficio medidos, no modelados: AMAZONA no factura ni cobra.
2. Serie diaria real de ingresos y margen, en vez del reparto de un P&L mensual.
3. Un endpoint agregado del Panel: hoy cada producto cuesta cinco peticiones y solo
   se leen los ocho primeros.
4. Tarea en curso de cada agente (la actividad se deduce del log de ejecuciones).
5. Objetivos: «Nuevo objetivo» lleva a Director ejecutivo porque no hay alta desde
   aquí.

## Director ejecutivo (segunda pasada). Grafo de agentes (Neural Nexus)

**Hecho.** El grafo 3D de la pantalla se rehace entero según
`docs/design/KOVA_Neural_Nexus_especificacion_Claude_Code.md`: cuatro niveles
(CEO → Decision Engine → 8 dominios → 13 agentes), layout determinista y estable,
tres modos (Arquitectura, Ejecución e Incidencias), vista 3D con alternativa 2D
sobre el mismo dataset, HUD del Decision Engine, leyenda de estados y panel de
detalle por nodo. Real: los 13 agentes del registro con su estado —que encajan
exactamente en los 8 dominios de la especificación vía `teamOf`—, su log de
ejecuciones y la decisión del CEO con sus evidencias, que es lo que pone a un
agente a ejecutar, a esperar o bloqueado (el veto financiero y el NO_GO legal son
bloqueos reales). Demo (`lib/demo/neural-nexus.ts`): la tarea en curso, el
progreso, los handoffs entre dominios y las métricas del núcleo. El resto de la
pantalla del Director ejecutivo no se toca.

**Iteración 3: el Decision Engine.** El núcleo deja de ser un elipsoide y pasa a
ser un cerebro digital de dos hemisferios, según
`docs/design/KOVA_Decision_Engine_especificacion_visual_tecnica_final.md`. Seis
capas independientes (silueta cerebral, red neural, nodos sinápticos, poliedro de
decisión, anillo técnico y un halo mínimo), toda la geometría en
`lib/decision-engine.ts` —matemática pura, determinista y con tests— y los
componentes de `components/neural-nexus/scene/decision-engine/` solo presentando.
Cada dominio entra ahora por SU zona del cerebro en vez de por el centro, y el
anillo de dominios gira 45° para que cada uno caiga del lado que le asigna el
mapeo dominio → cerebro de la especificación.

**Backend que faltaría (para sustituir la demo).**

1. Tarea en curso y progreso de cada agente (el registro no los guarda).
2. Bus de eventos en tiempo real (`agent.status.changed`, `agent.handoff`,
   `decision.*`, `incident.*`) por WebSocket, SSE o Supabase Realtime: hoy el
   grafo es una foto del momento de cargarlo.
3. Handoffs reales entre agentes y dominios, con su dirección y su momento.
4. Métricas del Decision Engine: eventos activos, latencia, decisiones recientes,
   dependencias y Human Gates pendientes.
5. Human Gate como evento contextual, no como nodo permanente.
6. Incidencias y bloqueos con su causa, no deducidos de la evidencia de la decisión.
