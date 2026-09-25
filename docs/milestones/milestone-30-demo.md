# Milestone 30 — Demo / Production Isolation

**Fecha:** 25-09-2026 · **ADR:** [0008](../architecture/adr-0008-demo-production-isolation.md)
· **Anterior:** [Milestone 29](milestone-29-demo.md)

Segunda fase del plan maestro (§5 y §32). Objetivo: que los datos simulados
sigan existiendo para desarrollo y demos, pero que **no puedan sostener una
decisión operativa** ni colarse en un despliegue real sin que nadie se entere.

---

## Qué cambia

### Backend

1. **Cinco contratos, uno por dominio externo** (`app/integrations/ports.py`):
   `ProductSignalProvider`, `SupplierDirectory`, `RegulatoryDirectory`,
   `AdPerformanceDirectory` y `MarketplaceDirectory`. Los cinco agentes pasan a
   depender del `Protocol`, no de la clase mock.
2. **El proveedor activo es configuración.** `ProviderRegistry` lo resuelve
   desde `PRODUCT_INTELLIGENCE_PROVIDER`, `SUPPLIERS_PROVIDER`,
   `REGULATORY_PROVIDER`, `ADS_PROVIDER` y `MARKETPLACES_PROVIDER`
   (`mock` | `sandbox` | `real`). Antes cada agente construía su mock en el
   constructor.
3. **`staging` y `production` no arrancan sobre fixtures.** Cualquier dominio
   en `mock` aborta el arranque, con los nombres de los dominios afectados.
4. **Pedir un adaptador que no existe es un error, no un mock silencioso.** Es
   el fallo que de verdad hace daño: pedir datos reales y recibir inventados.
5. **La procedencia se publica.** `GET /health/detailed` devuelve el entorno y,
   por dominio, qué proveedor está activo y si es simulado. El Control Center lo
   tiene tipado (`DetailedHealth.providers`).

### Frontend

6. **Trinquete sobre `lib/demo`** (`lib/demo-boundary.test.ts`): fija los 41
   módulos que hoy dependen de datos de demostración, prohíbe que la lista
   crezca, protege un núcleo (`api.ts`, `auth.ts`, `format.ts`, `dates.ts`,
   `utils.ts`) que no puede tocarlos nunca, y comprueba que lo que vive en
   `lib/demo` no importa del resto de la aplicación.

## Criterios de aceptación del plan maestro

| Criterio | Estado |
|---|---|
| `production` no arranca con `MockTrendsProvider` | ✅ `test_enforcing_environments_refuse_to_start_on_mock_data` |
| `production` no arranca con `MockSupplierDirectory` | ✅ mismo test |
| `production` no arranca con `MockRegulatoryDirectory` | ✅ mismo test |
| frontend production no importa `lib/demo` | ❌ **abierto** — ver abajo |

Los otros dos dominios que el plan no nombra (publicidad y marketplaces) están
cubiertos igual.

## El criterio que queda abierto, y por qué

`lib/demo` lo importan **41 módulos** de producción. Quitarlos no es un cambio
mecánico: los paneles se construyeron a propósito con datos de demostración
marcados con `DataProvenanceBadge`, y suprimirlos obliga a decidir, panel a
panel, qué se enseña cuando no hay dato real —un estado vacío, una estimación
declarada como tal, o nada—. Eso es diseño de producto, no refactor, y mezclarlo
con el endurecimiento del backend habría hecho irrevisables las dos mitades.

Lo que sí queda hecho es que **la deuda está medida y no puede crecer**. El
trinquete falla si un módulo nuevo empieza a depender de datos de demostración,
y también si uno deja de hacerlo sin actualizar la lista (para que no retroceda).

Queda como **Milestone 30.1**, con los 41 módulos ya inventariados en el propio
test.

## Probarlo

```bash
cd backend

# Desarrollo: todo mock, arranca igual que siempre
uvicorn app.main:app --reload
curl -s localhost:8000/health/detailed | python -m json.tool

# Producción sobre fixtures: no arranca
ENVIRONMENT=production SUPABASE_URL=https://x.supabase.co SUPABASE_ANON_KEY=k \
  CORS_ORIGINS='["https://kova.example"]' uvicorn app.main:app
# RuntimeError: production cannot run on simulated data; still on a mock
# provider: ads, marketplaces, product_intelligence, regulatory, suppliers

# Pedir un adaptador que no existe: falla claro, no cae al mock
SUPPLIERS_PROVIDER=real uvicorn app.main:app
# ProviderNotAvailableError: configured providers that do not exist yet: suppliers=real
```

El trinquete del frontend:

```bash
cd apps/control-center && node --test lib/demo-boundary.test.ts
```

## Verificación

- Backend: `ruff` y `mypy` limpios · **674 tests** (652 antes, +22).
- Frontend: `tsc` limpio · **234 tests** (230 antes, +4) · `eslint` limpio.
- El trinquete se probó en negativo: se añadió un módulo que importaba
  `lib/demo`, el test falló nombrándolo, y se retiró. Un trinquete que no muerde
  es peor que ninguno.
- `next build` correcto en copia temporal, sin tocar el `.next` del propietario.
- **No verificado aquí:** `alembic upgrade head` contra PostgreSQL (este
  milestone no añade migraciones) y el comportamiento con adaptadores reales,
  que todavía no existen.

## Lo que queda abierto

1. **Milestone 30.1:** quitar `lib/demo` de los 41 módulos de producción, panel
   a panel.
2. **Milestone 29.1:** los `GET` del backend siguen abiertos.
3. **Milestones 34-35:** los primeros adaptadores reales. Hasta entonces,
   configurar `real` o `sandbox` hace fallar el arranque a propósito.
4. El panel Estado **puede** ya leer `providers` de `/health/detailed`, pero
   todavía no lo enseña.
