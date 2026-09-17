# AMAZONA — Especificación de UI/UX y arquitectura de paneles aprobados (v0.5)

**Proyecto:** AMAZONA  
**Objetivo del documento:** servir como referencia de implementación para Claude Code y como fuente de verdad visual/funcional de los paneles ya aprobados.  
**Fecha:** 17 de septiembre de 2026  
**Estado:** mitad inicial de paneles aprobada; pendiente diseñar la mitad restante.

---

## 1. Principios globales de diseño

### 1.1. Identidad visual aprobada

AMAZONA debe percibirse como un **sistema operativo empresarial de IA**, no como un backoffice genérico ni como una tienda de dropshipping.

La dirección visual aprobada es:

- Fondo general: **negro / negro azulado muy oscuro**.
- Tarjetas/paneles: **verde esmeralda oscuro**, con variaciones de profundidad.
- Acentos activos: **esmeralda / turquesa brillante**.
- Texto principal: blanco.
- Texto secundario: gris frío.
- Advertencias: ámbar.
- Bloqueos / errores críticos: rojo.
- Bordes: finos, oscuros, con glow esmeralda muy contenido.
- Profundidad: estilo **2.5D premium** mediante sombras suaves, capas, bordes, transparencias controladas y brillos sutiles.
- No usar un estilo “gaming”; debe ser **empresarial, sobrio, tecnológico y premium**.
- Mantener alta densidad de información sin perder jerarquía.
- Layout pensado prioritariamente para escritorio, con comportamiento responsive posterior.

### 1.2. Regla sobre 3D

- **Toda la aplicación usa 2.5D**.
- **Solo el grafo visual de agentes del panel “Director ejecutivo” usa 3D real**.
- El 3D debe ser funcional, no decorativo:
  - nodos de agentes;
  - conexiones;
  - estado de ejecución;
  - flujos de datos;
  - Decision Engine como núcleo central;
  - aprobación/rechazo como salidas.
- Recomendación técnica:
  - UI general: React / Next.js / Tailwind o equivalente.
  - Grafo operativo 2D de respaldo: React Flow.
  - Grafo 3D: React Three Fiber + Three.js.
  - Fallback 2D/2.5D si el dispositivo no soporta bien 3D.

### 1.3. Colores de referencia (orientativos)

Estos valores son sugerencias de implementación y pueden ajustarse para reproducir mejor los mockups:

```css
--bg-0: #050808;
--bg-1: #07110f;
--panel: #08241c;
--panel-2: #0a2f24;
--panel-hover: #0d3b2d;

--emerald: #00d69a;
--emerald-bright: #15f0b2;
--emerald-soft: #22c997;
--cyan-accent: #28e5d0;

--text-primary: #f5f7f7;
--text-secondary: #9ca9a5;
--border: rgba(21, 240, 178, 0.18);

--warning: #f3b63f;
--danger: #ef5a5a;
--success: #24d69a;
```

### 1.4. Lenguaje de componentes

Todos los paneles comparten:

- sidebar izquierda fija;
- barra superior con búsqueda global;
- indicador de estado del sistema/agente;
- avatar/usuario;
- cards KPI;
- tablas con filtros;
- chips de estado;
- tabs;
- tooltips;
- paneles “drill-down”;
- acciones primarias en esmeralda;
- acciones peligrosas o bloqueos en rojo;
- breadcrumbs o contexto del producto/proyecto cuando proceda.

### 1.5. Separación de datos

En todo el sistema se debe distinguir visualmente:

- **Dato verificado**
- **Dato proporcionado por proveedor / tercero**
- **Estimación AMAZONA**
- **Pendiente / no validado**

No presentar estimaciones como hechos confirmados.

---

# 2. Orden aprobado del menú principal

## 2.1. Arquitectura actual aprobada

```text
1. Panel
2. Director ejecutivo
3. Investigación
4. Proveedores y abastecimiento
5. Economía y rentabilidad
6. Legal y cumplimiento
7. Tienda y canales de venta
8. Marketing y adquisición
9. Operaciones
10. Director de Finanzas
11. Proyectos
12. Agentes
13. Aprobaciones
14. Auditoría
15. Estado
```

## 2.2. Cambio arquitectónico aprobado

Se elimina **“Mercado”** como módulo independiente.

Sus capacidades se redistribuyen:

- listings/marketplaces → **Tienda y canales de venta**
- competencia/precios/market intelligence → **Investigación**
- comisiones/margen por canal → **Economía y rentabilidad**
- stock/fulfillment/inventario → **Operaciones**

Principio: **una única fuente funcional de verdad por dominio**.

---

# 3. Panel 1 — Panel general

## 3.1. Propósito

Vista ejecutiva de toda AMAZONA. Debe responder en 5 segundos:

- qué está haciendo la empresa;
- qué está funcionando;
- dónde existe riesgo;
- qué requiere decisión humana;
- estado económico básico;
- actividad de agentes.

## 3.2. Estructura aprobada

### Cabecera
- Título: `Panel`
- buscador global;
- fecha/hora;
- botón `+ Nuevo objetivo`;
- estado general.

### KPIs superiores
Ejemplos:
- Ventas
- Beneficio estimado
- Agentes en línea
- Aprobaciones pendientes

Cada KPI:
- cifra principal;
- variación;
- mini sparkline;
- icono;
- estado.

### Actividad empresarial
Tabla/stream con:
- agente;
- última actividad;
- estado;
- timestamp.

Estados:
- Activo
- Analizando
- Esperando aprobación
- Bloqueado
- Pendiente

### Decisiones necesarias
Lista de decisiones humanas:
- proveedor;
- lanzamiento;
- contrato;
- cambios críticos.

### Oportunidades
Tabla resumida:
- producto;
- demanda;
- margen;
- riesgo;
- estado.

### Gráfico
`Ventas / margen · últimos 30 días`

## 3.3. Referencia visual
Inspiración:
- Vercel
- Linear
- Ramp
- Stripe
- Shopify
- Datadog

## 3.4. Reglas
- No saturar.
- Priorizar contexto ejecutivo.
- No mostrar detalle técnico salvo drill-down.

---

# 4. Panel 2 — Director ejecutivo

## 4.1. Propósito

Centro de orquestación multiagente.

Flujo conceptual:

```text
Objetivo
  ↓
CEO
  ↓
Agentes especializados
  ↓
Decision Engine
  ↓
Aprobar / Rechazar
```

## 4.2. Elementos principales

### Crear objetivo
Campos:
- objetivo;
- solicitado por;
- mercado objetivo;
- prioridad;
- tipo de análisis;
- contexto avanzado desplegable.

Acciones:
- Guardar borrador
- Ejecutar objetivo

### Grafo visual de agentes — 3D
Único componente 3D real de toda la aplicación.

Debe mostrar:
- CEO como nodo iniciador;
- Product Hunter;
- Market Analyst;
- Supplier Finder;
- CFO / Finanzas;
- Legal;
- Marketing;
- E-commerce;
- Decision Engine central;
- salidas: Aprobar / Rechazar.

Comportamiento:
- zoom;
- orbit/drag moderado;
- click en nodo;
- estado en tiempo real;
- conexiones luminosas;
- pulsos cuando un agente transmite resultados;
- nodos atenuados cuando están esperando;
- ámbar si hay bloqueo;
- rojo solo para error/bloqueo crítico.

### Vista previa de ejecución
Tabla:
- agente;
- responsabilidad;
- estado;
- inicio estimado;
- duración;
- dependencias.

### Resumen de misión
- agentes seleccionados;
- procesos en paralelo;
- dependencias;
- riesgo estimado;
- ejecución estimada;
- coste aproximado/tokens;
- resultado esperado.

### Impacto esperado
- alcance;
- horizonte temporal;
- confianza estimada.

### Contexto avanzado
Ocultar por defecto:
- JSON;
- fuentes;
- restricciones;
- parámetros de agentes;
- datos simulados.

## 4.3. Regla principal
El usuario no debería trabajar directamente con JSON en el flujo normal.

## 4.4. Referencias
- Palantir AIP
- n8n
- LangGraph / LangSmith
- Linear

---

# 5. Panel 3 — Investigación

## 5.1. Propósito
Centro de descubrimiento, clasificación y priorización de oportunidades de producto.

Debe separar:
- señales preliminares;
- datos reales;
- estimaciones;
- oportunidades realmente viables.

## 5.2. Cabecera de búsqueda
- buscador: productos, problemas, categorías o tendencias;
- mercado;
- categoría;
- periodo;
- modelo de negocio;
- filtros avanzados;
- botón `Analizar mercado`.

## 5.3. Radar de oportunidades
Top 3 productos con tarjetas:
- imagen;
- producto;
- categoría;
- score de oportunidad;
- demanda;
- competencia;
- margen preliminar;
- crecimiento 12m;
- señales;
- botón Analizar;
- botón Seguir.

## 5.4. Radar multidimensional AMAZONA
Ejes:
- Demanda
- Futuro
- Rentabilidad
- Logística
- Regulación
- Escalabilidad

Debe permitir comparar:
- producto analizado;
- media de mercado.

## 5.5. Resultados
Tabla:
- producto;
- categoría;
- demanda;
- tendencia;
- competencia;
- margen;
- riesgo;
- score.

## 5.6. Resumen de investigación
- oportunidades encontradas;
- tras filtros;
- en seguimiento;
- descartadas automáticamente.

## 5.7. Tendencia por fuente
Gráfico por:
- Google;
- marketplaces;
- ecommerce;
- redes sociales;
- otras fuentes.

## 5.8. Insight AMAZONA
Bloque de síntesis:
- hallazgos;
- riesgos;
- señales relevantes.

## 5.9. Referencias
- Jungle Scout
- Exploding Topics
- Similarweb
- Helium 10
- Semrush

---

# 6. Panel 4 — Proveedores y abastecimiento

## 6.1. Propósito
Encontrar, validar y comparar proveedores para un producto ya seleccionado.

Debe recibir automáticamente el producto desde Investigación/Proyecto.

## 6.2. Contexto del producto
- producto seleccionado;
- score de Investigación;
- mercado objetivo;
- modelo logístico;
- categoría;
- cambiar producto.

## 6.3. Parámetros de búsqueda
- región de destino;
- origen del proveedor;
- modelo logístico;
- precio objetivo;
- plazo máximo;
- MOQ máximo;
- certificaciones;
- Incoterms;
- métodos de pago;
- filtros avanzados.

## 6.4. Resumen de búsqueda
- proveedores analizados;
- preseleccionados;
- recomendados;
- descartados.

## 6.5. Proveedores recomendados
Top 3:
- nombre;
- país;
- precio unitario;
- MOQ;
- entrega;
- direct ship;
- certificaciones;
- score proveedor;
- analizar;
- comparar.

## 6.6. Mapa de proveedores
Mapa global con:
- proveedor;
- almacén;
- destino;
- rutas;
- coste;
- tiempo estimado;
- transporte;
- riesgo.

## 6.7. Listado profesional
Tabla:
- proveedor;
- país;
- precio;
- MOQ;
- entrega;
- envío directo;
- certificaciones;
- riesgo;
- score;
- acciones.

## 6.8. Coste total estimado (Landed Cost)
Debe desglosar:
- producto;
- transporte;
- arancel;
- fulfillment;
- pago/divisa;
- devoluciones;
- otros costes.

## 6.9. Compatibilidad con AMAZONA
Checklist:
- dropshipping / direct ship;
- MOQ bajo;
- packaging neutro;
- tracking automático;
- stock sincronizable;
- API/CSV;
- devoluciones UE;
- SLA contractual;
- pago tras venta, si aplica.

## 6.10. Supplier Score
Radar:
- precio;
- logística;
- fiabilidad;
- calidad;
- compliance;
- flexibilidad;
- escalabilidad.

## 6.11. Referencias
- SAP Ariba
- GEP
- ImportYeti
- Coupa

---

# 7. Panel 5 — Economía y rentabilidad

## 7.1. Propósito
Motor de viabilidad económica por producto/oportunidad.

No duplicar funciones del Director de Finanzas.

## 7.2. Contexto
- producto;
- proveedor;
- mercado;
- modelo logístico;
- score de Investigación.

## 7.3. KPIs
- precio de venta;
- coste total por unidad;
- margen de contribución;
- beneficio estimado mensual;
- punto de equilibrio;
- riesgo económico.

## 7.4. Tabs
- Escenarios
- Desglose de costes
- Simulación
- Sensibilidad
- Punto de equilibrio
- Riesgo y capital
- Resumen y decisión

## 7.5. Comparativa de escenarios
- Conservador
- Base
- Optimista

Variables:
- precio;
- pedidos/mes;
- CAC;
- devoluciones;
- coste proveedor.

Resultados:
- ingresos;
- beneficio;
- margen neto.

## 7.6. Simulador interactivo
Sliders/inputs:
- precio venta;
- coste proveedor;
- CAC;
- devoluciones;
- conversión;
- pedidos mensuales.

Recalcular en tiempo real:
- ingresos;
- beneficio;
- margen;
- break-even.

## 7.7. Análisis de sensibilidad
Debe mostrar qué variable puede destruir la oportunidad:
- CAC;
- coste proveedor;
- devoluciones;
- precio;
- transporte;
- conversión.

## 7.8. Punto de equilibrio
- unidades;
- facturación;
- días estimados;
- CAC máximo tolerable;
- precio mínimo viable.

## 7.9. Riesgo de capital
Especialmente importante para el modelo sin stock:
- capital comprometido;
- capital sin cobertura;
- cobertura de riesgo;
- desfase temporal entre cobro y pago;
- alertas si la cobertura cae por debajo del umbral preferido.

## 7.10. Viabilidad económica
Conclusión:
- rentabilidad;
- robustez;
- capital necesario;
- riesgo;
- supuestos pendientes.

Nunca mostrar “rentable” sin:
> Rentable bajo estas hipótesis.

## 7.11. Referencias
- Pigment
- Stripe
- Ramp
- Shopify

---

# 8. Panel 6 — Legal y cumplimiento

## 8.1. Propósito
Gate legal/regulatorio antes del lanzamiento y monitorización continua.

## 8.2. Contexto
- producto;
- proveedor;
- mercado;
- origen;
- modelo logístico;
- canal previsto.

## 8.3. KPIs
- cumplimiento general;
- riesgo legal;
- certificaciones;
- evidencias;
- cambios regulatorios;
- Legal Gate.

## 8.4. Matriz de requisitos legales
Columnas:
- requisito;
- mercado;
- estado;
- evidencia;
- fuente;
- criticidad;
- acciones.

Estados:
- Verificado
- Revisar
- Incompleto
- Pendiente
- No aplica

## 8.5. Fuentes regulatorias
Integrar/representar:
- Comisión Europea;
- Access2Markets;
- ECHA / REACH / SCIP;
- Safety Gate;
- legislación nacional;
- otras fuentes por categoría.

## 8.6. Rol en la operación
Determinar:
- fabricante;
- importador;
- distribuidor;
- vendedor al consumidor;
- marketplace;
- representante autorizado.

Debe advertir cuando AMAZONA pueda asumir obligaciones adicionales.

## 8.7. Mapa de responsabilidades
Cadena:
- proveedor;
- AMAZONA;
- cliente.

Mostrar obligaciones por actor.

## 8.8. Matriz de riesgos
Probabilidad × impacto.

Priorizar:
- crítico;
- alto;
- medio;
- bajo.

## 8.9. Documentación del producto
- declaración de conformidad;
- informes;
- manuales;
- etiquetas;
- packaging;
- certificaciones.

Guardar:
- versión;
- fecha;
- proveedor;
- revisión;
- hash;
- estado.

## 8.10. Inteligencia regulatoria
Timeline de cambios normativos:
- críticos;
- relevantes;
- informativos.

## 8.11. Legal Gate
Estados:
- Bloqueado;
- Requiere revisión humana;
- Preparado.

Nunca mostrar “100 % legal”.

## 8.12. Referencias
- Vanta
- Drata
- OneTrust

---

# 9. Panel 7 — Tienda y canales de venta

## 9.1. Propósito
Crear, optimizar y desplegar la oferta comercial en canales propios y marketplaces.

Nombre aprobado:
**Tienda y canales de venta**

## 9.2. Contexto
- producto;
- score;
- precio aprobado;
- proveedor;
- mercados;
- Legal Gate;
- modelo logístico.

## 9.3. Constructor de página
Preview visual de tienda propia:
- desktop;
- mobile;
- contenido;
- SEO;
- diseño;
- páginas;
- A/B testing.

Debe poder generar con IA:
- título;
- propuesta de valor;
- descripción;
- beneficios;
- FAQ;
- CTA;
- meta title/description;
- datos estructurados.

## 9.4. Canales
Tarjetas:
- Tienda propia
- Amazon
- Google Shopping
- TikTok Shop
- futuros canales

Cada canal:
- estado;
- % readiness;
- botón configurar.

## 9.5. Checkout y pagos
- embebido;
- externo;
- personalizado;
- tarjeta;
- Apple Pay;
- Google Pay;
- PayPal;
- otros.

## 9.6. Funnel previsto/real
- visitas;
- producto;
- carrito;
- checkout;
- compra;
- conversión.

Distinguir estimado vs real.

## 9.7. Calidad del escaparate
Score:
- contenido;
- conversión;
- SEO;
- confianza;
- legal;
- mobile;
- velocidad.

## 9.8. Configuración por mercado
Por país:
- precio;
- idioma;
- estado;
- disponibilidad.

## 9.9. Producto maestro
Ficha central:
- SKU;
- EAN/GTIN;
- peso;
- dimensiones;
- stock proveedor;
- entrega;
- certificaciones;
- contenido;
- media.

El producto maestro alimenta todos los canales.

## 9.10. Launch Readiness
Checklist:
- producto;
- precio;
- página;
- checkout;
- legal;
- analytics;
- tracking;
- dominio;
- emails.

## 9.11. Acción final
`Solicitar aprobación de lanzamiento`

## 9.12. Referencias
- Shopify
- Webflow
- Stripe
- BigCommerce

---

# 10. Panel eliminado — Mercado

## 10.1. Estado
**ELIMINADO COMO MÓDULO INDEPENDIENTE**

## 10.2. Redistribución
- listings → Tienda y canales de venta;
- competencia → Investigación;
- comisiones/margen → Economía y rentabilidad;
- inventario/fulfillment → Operaciones.

## 10.3. Marketplaces
Deben existir como subcanales dentro de:
**Tienda y canales de venta**

Ejemplo:
- Amazon España
- Amazon Francia
- Google Shopping
- TikTok Shop
- eBay
- Miravia

## 10.4. Marketplace Intelligence
Capacidad transversal, no pantalla principal.

---

# 11. Panel 8 — Marketing y adquisición

## 11.1. Propósito
Generar, distribuir, medir y optimizar la demanda.

Nombre aprobado:
**Marketing y adquisición**

## 11.2. Contexto
- producto;
- mercado;
- precio;
- margen contribución;
- CAC máximo;
- landing;
- Legal Gate.

## 11.3. KPIs
- inversión;
- ingresos atribuidos;
- CAC / CPA;
- ROAS;
- conversiones;
- score/estado general.

Distinguir:
- estimado;
- real.

## 11.4. Plan de adquisición por canal
Ejemplo:
- Meta Ads;
- Google Ads;
- TikTok Ads;
- Creators / Influencers;
- Otros.

Mostrar:
- % presupuesto;
- importe;
- objetivo.

## 11.5. Nueva campaña
Campos:
- objetivo;
- canal;
- mercado;
- evento de conversión;
- presupuesto diario;
- duración;
- CAC objetivo;
- CAC máximo.

Regla:
Marketing no debe superar límites económicos sin aprobación.

## 11.6. Audiencias propuestas
- deportistas urbanos;
- usuarios de auriculares sport;
- running frecuente;
- remarketing;
- lookalike/compradores.

Mostrar:
- score;
- intención;
- fuente.

## 11.7. Creatividades generadas por IA
Cards con:
- preview;
- tipo;
- Creative Score;
- estado:
  - Aprobado
  - En revisión
  - Ajustar

Generar:
- hook;
- copy;
- CTA;
- storyboard;
- brief;
- variantes.

## 11.8. Vista previa multiplataforma
Tabs:
- Meta;
- Instagram;
- TikTok;
- Google.

Formatos:
- feed;
- story;
- reel;
- search;
- display.

## 11.9. Funnel de conversión
- impresiones;
- clics;
- landing;
- carrito;
- checkout;
- compra.

## 11.10. Rendimiento por canal
Gráfico:
- inversión;
- ingresos;
- ROAS;
- CAC.

## 11.11. Atribución
Modelos:
- último clic;
- primer clic;
- lineal;
- data-driven.

Mostrar ingresos atribuidos por canal.

## 11.12. Recomendaciones IA
Deben estar basadas en datos concretos:
- subir/bajar inversión;
- A/B creatives;
- activar canal;
- revisar segmentación.

Evitar recomendaciones genéricas.

## 11.13. Presupuesto y control
- asignado;
- gastado;
- restante;
- pacing;
- CAC actual;
- CAC objetivo;
- CAC máximo.

## 11.14. Guardrails
Ejemplos:
- alertar/pausar si CAC > máximo;
- alertar si ROAS < umbral;
- impedir gasto fuera de presupuesto;
- bloquear claims no aprobados;
- bloquear mercados no autorizados;
- limitar aumentos bruscos de presupuesto.

## 11.15. Acción final
`Solicitar aprobación de inversión`

## 11.16. Referencias
- Google Ads
- Meta Ads Manager
- TikTok Ads Manager
- HubSpot

---

# 12. Flujo transversal aprobado hasta ahora

```text
DIRECTOR EJECUTIVO
        │
        ▼
INVESTIGACIÓN
        │
        ▼
PROVEEDORES Y ABASTECIMIENTO
        │
        ▼
ECONOMÍA Y RENTABILIDAD
        │
        ▼
LEGAL Y CUMPLIMIENTO
        │
        ▼
TIENDA Y CANALES DE VENTA
        │
        ▼
MARKETING Y ADQUISICIÓN
        │
        ▼
[OPERACIONES — pendiente de diseño]
        │
        ▼
[DIRECTOR DE FINANZAS — pendiente de diseño]
```

Los módulos no deben funcionar como silos.

Cada módulo consume resultados anteriores y devuelve nueva información al sistema.

---

# 13. Propiedad funcional por dominio

| Dominio | Módulo responsable |
|---|---|
| Orquestación multiagente | Director ejecutivo |
| Descubrimiento / demanda / competencia | Investigación |
| Proveedores / sourcing / landed cost | Proveedores y abastecimiento |
| Unit economics / margen / break-even / CAC máximo | Economía y rentabilidad |
| Regulación / certificaciones / legal gate | Legal y cumplimiento |
| Storefront / catálogo / canales / marketplaces | Tienda y canales de venta |
| Captación / anuncios / creatividades / atribución | Marketing y adquisición |
| Inventario / pedidos / fulfillment / devoluciones | Operaciones |
| Finanzas corporativas / tesorería / impuestos | Director de Finanzas |
| Flujo de trabajo | Proyectos |
| Gestión de agentes | Agentes |
| Decisiones humanas | Aprobaciones |
| Trazabilidad | Auditoría |
| Salud técnica del sistema | Estado |

---

# 14. Paneles pendientes de diseño

A partir de este punto faltan:

1. Operaciones
2. Director de Finanzas
3. Proyectos
4. Agentes
5. Aprobaciones
6. Auditoría
7. Estado

Estos deben respetar el lenguaje visual y las fronteras funcionales definidas en este documento.

---

# 15. Reglas de implementación para Claude Code

## 15.1. Arquitectura de componentes

Recomendación:

```text
src/
├── app/
│   ├── dashboard/
│   ├── executive/
│   ├── research/
│   ├── sourcing/
│   ├── economics/
│   ├── legal/
│   ├── commerce/
│   ├── marketing/
│   ├── operations/
│   ├── finance/
│   ├── projects/
│   ├── agents/
│   ├── approvals/
│   ├── audit/
│   └── status/
│
├── components/
│   ├── layout/
│   ├── cards/
│   ├── charts/
│   ├── tables/
│   ├── forms/
│   ├── status/
│   ├── product/
│   ├── agents/
│   └── graph3d/
│
├── lib/
│   ├── api/
│   ├── calculations/
│   ├── permissions/
│   └── formatters/
│
└── styles/
```

No es obligatorio seguir exactamente esta estructura, pero sí separar dominios y componentes reutilizables.

## 15.2. Componentes comunes sugeridos

- `AppSidebar`
- `GlobalSearch`
- `StatusChip`
- `KpiCard`
- `MetricSparkline`
- `ProductContextCard`
- `DataProvenanceBadge`
- `RiskBadge`
- `ReadinessScore`
- `AgentStatus`
- `Timeline`
- `DataTable`
- `FilterBar`
- `ApprovalCTA`
- `EmptyState`
- `SourceBadge`
- `ScenarioCard`
- `RadarChart`
- `FunnelChart`
- `AgentGraph3D`

## 15.3. Estados de carga

Cada panel debe contemplar:
- loading;
- sin datos;
- error;
- datos simulados;
- datos reales;
- parcialmente verificado;
- bloqueado;
- esperando aprobación.

## 15.4. Accesibilidad
- contraste AA mínimo;
- no depender solo del color;
- tooltips para iconos;
- keyboard navigation;
- labels en inputs;
- soporte de reducción de movimiento;
- fallback 2D para grafo 3D.

## 15.5. Responsive
Prioridad:
1. desktop 1440–1920;
2. laptop;
3. tablet;
4. móvil.

En móvil:
- sidebar colapsable;
- tablas → cards/listas;
- gráficos simplificados;
- el grafo 3D debe tener modo simplificado.

## 15.6. Seguridad UX
Acciones con impacto real:
- gastar dinero;
- lanzar campañas;
- publicar producto;
- aprobar proveedor;
- cambiar precios;
- activar un canal;
- asumir stock;
- modificar datos legales;

deben requerir:
- confirmación;
- permisos;
- trazabilidad;
- cuando proceda, aprobación humana.

---

# 16. Mockups aprobados disponibles

Los diseños visuales aprobados durante la fase actual corresponden a:

- Panel general
- Director ejecutivo
- Investigación
- Proveedores y abastecimiento
- Economía y rentabilidad
- Legal y cumplimiento
- Tienda y canales de venta
- Marketing y adquisición

El documento describe su estructura y debe considerarse la referencia funcional. Las imágenes sirven como referencia visual, pero no deben tomarse como especificaciones pixel-perfect si contradicen este documento.

---

# 17. Estado general

**Paneles aprobados:** 8  
**Módulos eliminados como pantalla independiente:** 1 (`Mercado`)  
**Paneles pendientes:** 7  

La siguiente fase continuará desde **Operaciones**.

---

## Fin del documento
