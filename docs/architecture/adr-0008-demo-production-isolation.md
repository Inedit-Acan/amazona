# ADR 0008: Aislamiento entre datos de demostración y datos reales

- **Estado:** Aceptada
- **Fecha:** 2026-09-25
- **Depende de:** [ADR 0007](adr-0007-production-security.md)
- **Milestone:** 30

## Contexto

AMAZONA funciona hoy sobre datos inventados a propósito: cinco directorios mock
en `backend/app/ai/` (tendencias, proveedores, normativa, publicidad y
marketplaces) y quince módulos de demostración en
`apps/control-center/lib/demo/`. Es lo correcto para construir el sistema sin
gastar dinero ni llamar a APIs reales, y el plan maestro pide explícitamente
**no** borrarlos: deben quedarse como proveedores de desarrollo y demo.

Lo que no puede quedarse es la ambigüedad. Antes de este milestone:

- Cada agente **construía su propio mock** en el constructor
  (`self._directory = directory or MockSupplierDirectory()`), tipado
  directamente contra la clase mock. No había contrato, no había forma de
  sustituirlo por configuración y no había nada que impidiera a un despliegue de
  producción tomar decisiones sobre precios de proveedor inventados.
- Nada registraba qué proveedor estaba activo.
- `lib/demo` lo importan 41 módulos del frontend, y nada impedía que el número
  creciera.

## Decisión

### 1. Un contrato por dominio, y los agentes dependen de él

`app/integrations/ports.py` declara cinco `Protocol` —`ProductSignalProvider`,
`SupplierDirectory`, `RegulatoryDirectory`, `AdPerformanceDirectory`,
`MarketplaceDirectory`— y los cinco agentes pasan a depender de ellos en lugar
de la clase mock.

Los paquetes por dominio que propone el plan maestro
(`app/integrations/product_intelligence/`, etc.) **no se crean todavía**: cinco
carpetas con un Protocol de diez líneas cada una serían infraestructura por la
infraestructura. Llegan con el primer adaptador real, en el Milestone 34.

### 2. El proveedor activo es configuración, no un valor por defecto escondido

`ProviderRegistry` resuelve, para cada dominio, la implementación indicada por
`PRODUCT_INTELLIGENCE_PROVIDER`, `SUPPLIERS_PROVIDER`, `REGULATORY_PROVIDER`,
`ADS_PROVIDER` y `MARKETPLACES_PROVIDER` (`mock` | `sandbox` | `real`).

### 3. Pedir un adaptador inexistente es un error, nunca un mock silencioso

Es el modo de fallo que de verdad hace daño: un despliegue que pidió datos
reales y recibió fixtures sin enterarse. `ProviderNotAvailableError` se lanza al
arrancar, en cualquier entorno.

### 4. Un entorno real no arranca sobre fixtures

`validate_providers()` corre al importar `app.main`. En `staging` y
`production`, cualquier dominio en `mock` aborta el arranque. Se comprueba al
inicio y no en la primera llamada: un proceso que descubre a mitad del pipeline
que servía precios inventados ya ha hecho el daño.

Las dos comprobaciones —«sigue en mock» y «ese adaptador no existe»— se reportan
por separado, para que una no tape a la otra.

### 5. La procedencia se publica

`GET /health/detailed` devuelve el entorno y, por dominio, qué proveedor está
activo y si es simulado. El Control Center lo tiene tipado
(`DetailedHealth.providers`), de modo que el panel Estado pueda decirlo en vez
de suponerlo.

### 6. En el frontend, un trinquete en vez de una promesa

El plan maestro pide un test que falle si el código de producción importa
`lib/demo`. Hoy lo importan 41 módulos, y quitarlos **no es un cambio
mecánico**: los paneles se diseñaron con datos de demostración marcados con
`DataProvenanceBadge`, y suprimirlos obliga a decidir, panel a panel, qué se
enseña cuando no hay dato real. Eso es diseño, no refactor.

`lib/demo-boundary.test.ts` fija por tanto la superficie exacta: un módulo nuevo
no puede depender de datos de demostración sin aparecer en la lista, la lista
solo puede encoger, y hay un núcleo (`api.ts`, `auth.ts`, `format.ts`,
`dates.ts`, `utils.ts`) que no puede tocarlos jamás. Además, lo que vive en
`lib/demo` no puede importar del resto de la aplicación.

## Consecuencias

**A favor**

- Ningún agente conoce ya a su proveedor concreto: sustituirlo es configuración.
- `production` y `staging` no pueden arrancar sobre datos inventados. Es el
  criterio de aceptación del plan maestro, y cubre los cinco dominios, no solo
  los tres que nombra.
- Qué es simulado deja de ser conocimiento tribal y pasa a ser un dato que la
  API publica.
- La deuda de `lib/demo` está medida (41 módulos) y no puede crecer sin que
  alguien lo escriba.

**En contra**

- Configurar `real` o `sandbox` hoy hace fallar el arranque, porque esos
  adaptadores no existen. Es deliberado, y es lo que hace honesto el Milestone
  34.
- El trinquete del frontend documenta la deuda, no la paga. Producción sigue
  dependiendo de `lib/demo` y ese criterio del plan maestro queda abierto en el
  Milestone 30.1.
- Un sexto dominio nuevo hay que darlo de alta en tres sitios (Protocol,
  `IMPLEMENTATIONS`, Settings). Hay un test que falla si se olvida el segundo.

## Alternativas descartadas

- **Borrar los mocks.** El plan maestro lo prohíbe explícitamente y con razón:
  son la única forma de ejecutar el sistema entero sin gastar dinero.
- **Caer al mock cuando el adaptador real no existe.** Es exactamente el fallo
  silencioso que este milestone existe para impedir.
- **Quitar `lib/demo` de los 41 módulos ahora.** Rediseñar 25 paneles bajo el
  mismo commit que endurece el backend habría mezclado dos trabajos sin
  relación, y ninguno de los dos se habría podido revisar bien.
- **Una variable `USE_MOCKS` global.** Una sola palanca para cinco dominios
  impide migrar uno a datos reales sin migrarlos todos.
