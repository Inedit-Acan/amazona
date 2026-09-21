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
| 4 | Tienda y canales de venta | Pendiente |
| 5 | Marketing y adquisición | Pendiente |
| 6 | Operaciones | Pendiente |
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
