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
| 2 | Economía y rentabilidad | Pendiente |
| 3 | Legal y cumplimiento | Pendiente |
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
