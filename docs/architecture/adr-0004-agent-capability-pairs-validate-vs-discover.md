# ADR 0004: Pares de capacidades "validar uno" vs "descubrir muchos" en Fase 3

- **Estado:** Aceptada
- **Fecha:** 2026-09-16
- **Depende de:** [ADR 0002](adr-0002-agent-messaging-protocol.md)

## Contexto

Milestone 1 introdujo `SupplierAgent` (capability `supplier_sourcing`):
dado un proveedor ya elegido (unit_cost, lead_time_days,
supplier_verified), decide `GO|REVIEW|NO_GO` sobre ESA cotización
concreta. Milestone 2 introdujo un patrón distinto para productos:
`ProductResearchAgent` (capability `product_research`) no valida un
producto dado — descubre y rankea VARIOS candidatos a partir de
criterios de búsqueda (categoría, keywords), coexistiendo con el
`ProductAgent` de Milestone 1 (capability `product`) sin sustituirlo.
Esa decisión se tomó de forma implícita en Milestone 2, sin dejarla
documentada como convención general.

Milestone 3 (Agente 2, Proveedores y Sourcing) necesita exactamente el
mismo fork para proveedores: `SupplierSourcingAgent` (capability
`supplier_sourcing_research`) descubre y rankea N proveedores globales
por coste total aterrizado, mientras que `SupplierAgent` (capability
`supplier_sourcing`) sigue validando UNA cotización ya elegida dentro
del grafo de tareas de un objetivo. Antes de construir sobre este
patrón por tercera vez (y de cara a los Agentes 3-8 de Fase 3, que
previsiblemente lo necesitarán para canal de venta, campañas, etc.),
hace falta fijarlo como decisión de arquitectura explícita.

## Decisión

Cuando Fase 3 necesita tanto "validar una opción ya elegida" como
"descubrir/rankear N opciones" para la misma entidad de dominio, se
modelan como **dos agentes con dos capabilities distintas**, nunca como
un único agente con un flag de modo (`mode: "validate" | "discover"`).

**Convención de nombrado:** `<dominio>` para validar-uno (p. ej.
`product`, `supplier_sourcing`), `<dominio>_research` para
descubrir-muchos (p. ej. `product_research`, `supplier_sourcing_research`).

**Reparto de responsabilidades:**
- El agente "validar-uno" es el que el planner/`decision_engine.py`
  invoca dentro del grafo de tareas de un `Objective`, sintetizando su
  `AgentResult` en la decisión GO/REVIEW/NO_GO/HUMAN_APPROVAL — su
  contrato de entrada nunca cambia de forma por esta convención.
- El agente "descubrir-muchos" se expone por su propio flujo de
  discovery: un servicio (`ResearchService`, `SourcingService`, ...) que
  persiste cada candidato como entidad de dominio de primera clase, una
  API propia (`POST /api/research/runs`, `POST /api/sourcing/runs`, ...),
  y una página en el Control Center con un puente hacia el flujo de
  validación existente (precargar `context` en `/ceo`) — nunca se
  cablea directamente en el grafo de tareas del planner ni en
  `decision_engine.py`.

## Razonamiento

1. **Los dos modos tienen contratos de entrada/salida incompatibles.**
   "Validar uno" recibe los datos de UNA opción concreta y devuelve un
   veredicto sobre ella; "descubrir muchos" recibe criterios de
   búsqueda y devuelve una lista rankeada. Forzarlos a un solo agente
   con un `mode` ensuciaría `input_schema`/`output_schema` (ADR 0002)
   con la unión de dos formas incompatibles, y complicaría la
   validación de esquema por capability que el `AgentManager` ya hace.
2. **No toca el contrato que el planner y `decision_engine.py` ya
   asumen** para los agentes de Milestone 1 — el agente "validar-uno"
   nunca cambia de forma cuando se añade su contraparte "descubrir-muchos".
3. **Consistente con lo que Milestone 2 ya hizo** para productos sin
   una ADR explícita en su momento; esta ADR cierra ese hueco
   retroactivamente y deja la regla escrita para que los Agentes 3-8 no
   tengan que volver a discutirla desde cero.
4. **El agente "descubrir-muchos" nunca sustituye la aprobación
   humana.** Es puramente informativo/advisory — comprometerse con una
   opción concreta (elegir un proveedor, aprobar un producto) sigue
   pasando por el flujo de validación y aprobación ya existente, sin
   excepciones nuevas.

## Consecuencias

- `SupplierAgent` (capability `supplier_sourcing`, Milestone 1) no se
  modifica al añadir `SupplierSourcingAgent` (capability
  `supplier_sourcing_research`, Milestone 3) — mismo patrón que
  `ProductAgent`/`ProductResearchAgent`.
- Los Agentes 3-8 de Fase 3 deben evaluar, al diseñarse, si necesitan
  este fork (p. ej. "elegir un canal de venta ya decidido" vs
  "descubrir canales de venta candidatos") y, si es así, seguir esta
  misma convención de nombrado y reparto de responsabilidades sin abrir
  una ADR nueva por cada agente.
- Si en el futuro un agente "descubrir-muchos" necesita alimentar
  directamente `decision_engine.py` (por ejemplo, para descartar
  automáticamente candidatos por debajo de un umbral), esa integración
  es un cambio de alcance que debe revisarse en una ADR propia — no se
  asume aquí.
