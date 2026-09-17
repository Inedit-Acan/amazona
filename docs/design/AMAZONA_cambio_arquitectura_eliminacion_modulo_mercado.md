# Cambio de arquitectura — Eliminación del módulo independiente «Mercado»

## Proyecto
**AMAZONA — Sistema empresarial multiagente de comercio electrónico**

## Fecha
17 de septiembre de 2026

## Decisión arquitectónica

Se elimina **«Mercado» como módulo independiente del menú principal de AMAZONA**.

La eliminación afecta únicamente a la existencia de una pantalla separada llamada «Mercado». **No se eliminan sus capacidades funcionales**. Sus responsabilidades se redistribuyen entre los módulos que ya tienen la competencia natural para ejecutarlas, evitando duplicidad de lógica, datos y decisiones.

## Motivo del cambio

El módulo «Mercado» del prototipo actual concentra funciones que ya pertenecen a otros agentes y pantallas:

- creación y optimización de listings en marketplaces;
- análisis de competencia;
- cálculo de comisiones y margen neto;
- definición de políticas de inventario.

Mantener estas funciones dentro de un módulo independiente provocaría duplicaciones en el sistema, especialmente entre Investigación, Economía y rentabilidad, Tienda y canales de venta y Operaciones.

La nueva arquitectura adopta el principio de **una única fuente funcional de verdad por dominio**.

## Redistribución de responsabilidades

| Función anterior de «Mercado» | Nuevo módulo responsable | Motivo |
|---|---|---|
| Crear y optimizar listings de Amazon, eBay, Miravia, TikTok Shop u otros marketplaces | **Tienda y canales de venta** | Es una función de publicación, catálogo, contenido y despliegue comercial por canal. |
| Analizar competencia, precios, intensidad competitiva y evolución del mercado | **Investigación** | Pertenece a Market Intelligence y debe utilizar una única capa de datos competitivos. |
| Calcular comisiones del marketplace, costes del canal y margen neto | **Economía y rentabilidad** | Todo cálculo de rentabilidad debe ejecutarse mediante un único motor económico. |
| Gestionar inventario, fulfillment, disponibilidad, pedidos y stock | **Operaciones** | Son procesos operativos posteriores a la publicación y venta. |

## Nueva arquitectura del menú principal

### Arquitectura anterior

```text
Panel
Director ejecutivo
Investigación
Proveedores y abastecimiento
Economía y rentabilidad
Legal y cumplimiento
Tienda y canales de venta
Mercado
Marketing
Operaciones
Director de Finanzas
Proyectos
Agentes
Aprobaciones
Auditoría
Estado
```

### Arquitectura aprobada

```text
Panel
Director ejecutivo
Investigación
Proveedores y abastecimiento
Economía y rentabilidad
Legal y cumplimiento
Tienda y canales de venta
Marketing
Operaciones
Director de Finanzas
Proyectos
Agentes
Aprobaciones
Auditoría
Estado
```

## Tratamiento de marketplaces dentro de la nueva arquitectura

Los marketplaces pasan a ser **canales configurables dentro de «Tienda y canales de venta»**.

Ejemplo:

```text
Tienda y canales de venta
│
├── Tienda propia
├── Amazon España
├── Amazon Francia
├── Google Shopping
├── TikTok Shop
├── eBay
├── Miravia
└── Otros canales futuros
```

Cada canal puede disponer de una subvista especializada con información y configuración propias, sin crear un módulo independiente adicional.

## Ejemplo de subvista «Amazon España»

```text
AMAZON ESPAÑA

Listing
██████████████████ 96 %

Contenido
✓ Título
✓ Bullet points
✓ Descripción
✓ Imágenes
✓ Keywords
✓ GTIN
✓ Categoría

Precio
32,90 €

Comisión estimada
4,94 €

Margen neto previsto
27,8 %

Fulfillment
● FBM / proveedor
○ FBA

Estado
⚠ 1 requisito pendiente
```

## Marketplace Intelligence

La inteligencia sobre marketplaces **se mantiene**, pero pasa a ser una capacidad transversal y no una pantalla principal independiente.

Ejemplo:

```text
INTELIGENCIA AMAZON

Competidores activos            17
Precio medio                  34,20 €
Nuestro precio                32,90 €
Cambios de precio 7d            12
Nivel competitivo             Medio
```

Los datos competitivos procederán principalmente del agente **Investigación**, mientras que los cálculos económicos derivados se enviarán a **Economía y rentabilidad**.

## Flujo funcional resultante

```text
                   INVESTIGACIÓN
            demanda / competencia
                      │
                      ▼
               PRODUCTO MAESTRO
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
 TIENDA Y CANALES           ECONOMÍA
 listings / feeds           comisiones
 marketplaces               rentabilidad
          │                       │
          └───────────┬───────────┘
                      ▼
                 OPERACIONES
          stock / pedidos / logística
```

## Principios de diseño derivados

1. **No duplicar datos ni cálculos.** La competencia se analiza en Investigación; la rentabilidad en Economía y rentabilidad; el inventario en Operaciones.
2. **Producto maestro único.** Todas las tiendas y marketplaces consumen una ficha maestra de producto compartida.
3. **Canales como extensiones del mismo sistema comercial.** Amazon, Google Shopping, TikTok Shop y otros canales se gestionan como destinos de publicación, no como módulos empresariales independientes.
4. **Una única fuente de verdad económica.** Las comisiones y costes de cada canal deben alimentar el motor de Economía y rentabilidad, evitando cálculos paralelos.
5. **Separación entre inteligencia y ejecución.** Investigación detecta cambios del mercado; Tienda y canales ejecuta la publicación; Operaciones gestiona el cumplimiento de pedidos.

## Impacto esperado

La modificación simplifica la navegación, reduce duplicidades, mejora la mantenibilidad del backend, facilita la automatización entre agentes y permite añadir nuevos marketplaces sin crear nuevas secciones principales.

También favorece una arquitectura más escalable: un nuevo marketplace se implementará como un nuevo adaptador o canal dentro de **Tienda y canales de venta**, mientras que seguirá consumiendo los mismos servicios centrales de investigación, economía, legal y operaciones.

## Estado de la decisión

**APROBADO**

El módulo independiente **«Mercado» debe retirarse de la arquitectura principal de AMAZONA** y sus capacidades deben redistribuirse según este documento.
