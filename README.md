# AMAZONA

Sistema de e-commerce impulsado por IA con agentes especializados
deterministas (sin LLM en el camino de decisión). Simula, de principio a
fin, la operación de un negocio: detectar una oportunidad de producto,
analizarla, sourcear proveedores, evaluar rentabilidad y legalidad,
lanzar canales de venta y campañas, operarla, y controlar la salud
financiera agregada — con controles humanos obligatorios en los puntos
de riesgo o gasto. No hay dinero real, pedidos, proveedores ni impuestos
reales.

**Punto de entrada recomendado para entender el sistema completo:**
[`docs/architecture/system-overview.md`](docs/architecture/system-overview.md)
— arquitectura de las dos capas de orquestación, catálogo de los 13
agentes, modelo de datos, controles humanos, y el índice completo de
ADRs y milestones. Este README cubre solo cómo arrancarlo en local.

## Arquitectura de agentes (resumen — ver `system-overview.md` para el detalle)

- **Orquestador (Agente 9) + Agente CEO:** `CEOOrchestrator` — grafo fijo
  de 4 agentes "validar-uno" (Milestone 1) con decisión determinista,
  permisos/presupuesto, y aprobación humana.
- **`PipelineOrchestrator`:** cadena automática de los 9 agentes
  "descubrir-muchos" de Fase 3 (Research → ... → CFO) sobre un producto
  real del catálogo — un orquestador nuevo y separado (Milestone 12),
  con revisión humana obligatoria y kill switch sobre ejecuciones de
  riesgo (Milestone 14).
- **8 agentes operativos de Fase 3** (investigación, proveedores,
  análisis económico, legal, e-commerce, marketplaces, marketing,
  atención al cliente) **+ Agente CFO:** control económico agregado;
  nunca emite facturas propias — se integraría con un software de
  facturación certificado Verifactu si el proyecto aborda facturación.

## Stack técnico

- Frontend: Next.js, React, TypeScript, Tailwind CSS, shadcn/ui
- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic
- Datos: PostgreSQL / Supabase (proyecto en región UE), Redis
- Infra: Docker, GitHub Actions

## Desarrollo local

```bash
# Infraestructura (PostgreSQL + Redis)
docker compose -f infra/docker-compose.yml up -d

# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate  # Windows; usar `source .venv/bin/activate` en Unix
pip install -e ".[dev]"
alembic upgrade head
pytest
uvicorn app.main:app --reload

# Control Center (otra terminal)
cd apps/control-center
npm install
npm run dev
```

`GET http://localhost:8000/health` debe responder `{"status": "ok", "service": "amazona-backend"}`.
El Control Center queda disponible en http://localhost:3000.

Guías de demo, una por milestone (1-15): ver el índice completo en
[`system-overview.md`](docs/architecture/system-overview.md) (sección
"Índice de milestones"). Para probar el sistema completo de un vistazo:
Control Center → **Pipeline** → un formulario, un clic → los 9 agentes
de Fase 3 encadenados.

`backend/.env.example` documenta las variables de Supabase
(`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`DATABASE_URL`) — copia a `backend/.env` (gitignored) y rellena con
credenciales reales para conectar a Postgres real en vez del valor local
por defecto.

## Calidad

CI (`.github/workflows/ci.yml`) ejecuta en cada push/PR:

- Backend: `ruff check`, `mypy`, `alembic upgrade head` contra PostgreSQL limpio, `pytest`.
- Control Center: `eslint`, `tsc --noEmit`, `npm test`, `next build`.

Para ejecutar los mismos checks en local:

```bash
cd backend && ruff check . && mypy app && pytest
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

## Estado

**Fase 4 completa (Milestones 1-15).** Detalle completo en
[`system-overview.md`](docs/architecture/system-overview.md); resumen:

- **Milestone 1:** `CEOOrchestrator` + 4 agentes "validar-uno" + decisión
  determinista + permisos/presupuesto + aprobación humana + auditoría.
- **Milestone 2:** Supabase real, memoria compartida, protocolo de
  mensajería, grafo de tareas persistido, auth/roles opcionales, primer
  agente de Fase 3 (Research).
- **Milestones 3-9:** los 8 agentes operativos de Fase 3 completos
  (proveedores, análisis económico, legal, e-commerce, marketplaces,
  marketing, atención al cliente).
- **Milestone 10-11:** Agente CFO + persistencia real de reservas de
  presupuesto (`BudgetLedgerService`).
- **Milestones 12-15 (Fase 4 — Integración y pruebas):**
  `PipelineOrchestrator` encadena los 9 agentes de Fase 3 automáticamente,
  validado contra el espacio combinatorio real, con revisión humana
  obligatoria + kill switch sobre ejecuciones de riesgo.
- RLS activado con deny-all explícito en toda tabla pública desde su
  propia migración (ADR 0003, Milestone 2 en adelante) — el linter de
  seguridad de Supabase reporta 0 hallazgos, verificado en cada
  milestone que añade una tabla.
- **Milestones 16-28:** rediseño completo del Control Center (12 paneles,
  Panel de inicio y el grafo 3D de agentes del Director ejecutivo). Detalle
  en `docs/milestones/` y en
  [`AMAZONA_estado_paneles_rediseno.md`](docs/design/AMAZONA_estado_paneles_rediseno.md).
- **Milestone 29:** base de seguridad para producción
  ([ADR 0007](docs/architecture/adr-0007-production-security.md)) — ver abajo.
- **Milestone 30:** aislamiento entre datos de demostración y datos reales
  ([ADR 0008](docs/architecture/adr-0008-demo-production-isolation.md)) — ver abajo.
- **Milestone 31:** runtime de trabajos asíncronos
  ([ADR 0009](docs/architecture/adr-0009-async-job-runtime.md)) — ver abajo.
- **Milestone 32:** el pipeline se ejecuta en ese runtime, con cada paso
  persistido y con reintentar, reanudar y cancelar
  ([ADR 0010](docs/architecture/adr-0010-async-resumable-pipeline.md)) — ver abajo.

## Qué es real y qué está simulado

Conviene decirlo sin rodeos: **AMAZONA es hoy un sistema de simulación y
orquestación funcional, no una empresa autónoma en producción.**

**Real:** la orquestación (CEO, pipeline, decision engine), la persistencia, las
aprobaciones humanas, el ledger de presupuesto, el kill switch, la auditoría con
`correlation_id`, los estados de los agentes y, desde el Milestone 29, la
identidad y los permisos.

**Simulado** (proveedores mock en `backend/app/ai/mock_*.py`): tendencias de
mercado, proveedores y sus precios, normativa y cambios regulatorios,
rendimiento publicitario, pedidos, tracking, clientes, devoluciones,
contabilidad, facturación, pagos, marketplaces y logística.

El Control Center marca cada dato de demostración con su badge
`DataProvenanceBadge`. Ningún módulo que use fixtures se describe como "real".

Desde el Milestone 30, **qué proveedor respalda cada dominio es configuración
explícita**, y `staging`/`production` se niegan a arrancar si alguno sigue en
`mock`:

| Variable | Dominio | Hoy |
|---|---|---|
| `PRODUCT_INTELLIGENCE_PROVIDER` | tendencias y demanda | `mock` |
| `SUPPLIERS_PROVIDER` | proveedores y sus condiciones | `mock` |
| `REGULATORY_PROVIDER` | normativa aplicable | `mock` |
| `ADS_PROVIDER` | rendimiento publicitario | `mock` |
| `MARKETPLACES_PROVIDER` | competencia en marketplaces | `mock` |

Los valores posibles son `mock`, `sandbox` y `real`. Los adaptadores reales
llegan en los Milestones 34-35; hasta entonces pedir `real` hace **fallar el
arranque** con un mensaje claro, en vez de caer en silencio al mock.
`GET /health/detailed` publica cuál está activo en cada dominio.

**Deuda conocida:** 41 módulos del Control Center todavía importan `lib/demo`.
Está medido y congelado por `lib/demo-boundary.test.ts`, que impide que la lista
crezca; quitarlos panel a panel es el Milestone 30.1.

## Seguridad

Desde el Milestone 29 el comportamiento depende del entorno
(`ENVIRONMENT`: `development`, `test`, `demo`, `staging`, `production`).

| | development / test / demo | staging / production |
|---|---|---|
| Rutas mutadoras | abiertas (o con `REQUIRE_AUTH=true`) | exigen token verificado |
| Rutas de lectura | abiertas | exigen token verificado |
| Rol | no se comprueba | decide cada acción |
| `actor` en el cuerpo | se acepta | se ignora |
| Arranque | siempre | falla si falta Supabase o si CORS apunta a localhost |

Los siete roles son `OWNER`, `ADMIN`, `OPERATOR`, `ANALYST`, `REVIEWER`,
`VIEWER` y `SYSTEM`. La matriz está en `backend/app/permissions/policies.py` y
sus tests en `tests/unit/test_permission_matrix.py`. El kill switch solo lo
accionan OWNER y ADMIN.

**Antes de desplegar en staging o production** hay que crear el primer OWNER,
porque no hay ningún endpoint que conceda roles:

```bash
cd backend
alembic upgrade head
AMAZONA_BOOTSTRAP=1 python -m app.cli grant-role --email tu@correo.com --role OWNER
python -m app.cli list-users
```

La persona queda vinculada a su cuenta de Supabase en su primer inicio de sesión
verificado.

### Lectura (Milestone 29.1)

Las rutas de lectura también exigen identidad, con tres categorías:

| Categoría | Rutas | Quién |
|---|---|---|
| Sondas | `/health`, `/health/ready` | **públicas** — un balanceador no puede llevar un token |
| Negocio | 32 rutas | los 7 roles |
| Diagnóstico | `/health/detailed` | los 7 roles |
| Auditoría | `/api/audit` | OWNER, ADMIN y REVIEWER |

`/health` y `/health/ready` no revelan versión de esquema, entorno ni
proveedores: eso es huella dactilar del despliegue y vive en `/health/detailed`,
que sí pide identidad.

La auditoría es más estrecha que el resto de lecturas porque no es información
del negocio sino de las personas que lo operan: lleva el correo de quien hizo
cada cosa.

### Configuración de la sesión en el Control Center

Desde el Milestone 29.1 la sesión vive en **cookies** y no en `localStorage`,
para que el renderizado en servidor pueda mandar el token. Necesita, en
`apps/control-center/.env.local`:

```bash
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Sin esas dos primeras, el Control Center funciona sin login, como hasta ahora.

## Trabajos asíncronos

Desde el Milestone 31 el trabajo largo no vive dentro de la petición HTTP. Hay
una cola en PostgreSQL y un worker:

```bash
cd backend
python -m app.jobs.worker          # bucle; se pueden levantar varios
python -m app.jobs.worker --once   # trata un trabajo y termina
```

Encolar es `POST /api/jobs` con un tipo de `GET /api/jobs/types`. Hoy hay tres:
`research.run` (una investigación de producto de verdad), `pipeline.run` (una
ejecución completa de la cadena de Fase 3 — se encola por
`POST /api/pipeline/runs`, no a mano) y `diagnostic.echo` (comprueba el runtime
sin tocar negocio; con `{"fail": true}` falla a propósito para ver los
reintentos).

Un trabajo reintenta con espera exponencial y, al agotar sus intentos, queda en
`FAILED` — que es la cola de mensajes muertos: se vacía con
`POST /api/jobs/{id}/requeue`. El panel **Estado** lo enseña todo.

Encolar, cancelar y reencolar requieren el rol OWNER, ADMIN, OPERATOR o SYSTEM;
mirar la cola, cualquiera.

Un trabajo también puede quedar en `BLOCKED` cuando una condición externa
impide seguir y esperar no la arregla —hoy, el kill switch apagado—: no gasta
intentos y vuelve con el mismo `requeue`.

**Redis no se usa**: PostgreSQL es la cola y la fuente de verdad, por las
razones de la [ADR 0009](docs/architecture/adr-0009-async-job-runtime.md) §2.

## El pipeline, paso a paso

Desde el Milestone 32 `POST /api/pipeline/runs` **encola**: responde 202 con la
ejecución en `QUEUED` y sus nueve pasos en `PENDING`, y un worker la recorre
escribiendo cada paso al empezar y al terminar. Un fallo a mitad deja los pasos
anteriores hechos y visibles en vez de huérfanos.

```bash
curl -X POST localhost:8000/api/pipeline/runs -H 'Content-Type: application/json' \
  -d '{"category":"electronics","sale_price":45.0,"destination_region":"mexico"}'
curl -s localhost:8000/api/pipeline/runs/<correlation_id> | python -m json.tool
```

- `POST /api/pipeline/runs/{correlation_id}/resume` continúa por el paso que
  falló, sin repetir lo que ya estaba bien; con `{"from_step": "economics"}`
  rehace ese paso y los siguientes a propósito.
- `POST /api/pipeline/runs/{correlation_id}/cancel` la para; una ejecución en
  marcha se entera entre dos pasos.

`PARTIAL` (un paso no pudo entregar nada al siguiente) y `FAILED` (un paso
reventó) dejan de ser lo mismo: el primero no se reintenta solo y va a la
bandeja de revisión; el segundo lo reintenta el runtime. El razonamiento
completo, en la [ADR 0010](docs/architecture/adr-0010-async-resumable-pipeline.md).

## Notas

- Amazon SP-API: prohibido usar sus datos para entrenar modelos.
- No hay dinero real, pedidos, proveedores ni impuestos reales.
- El Agente 1 (Investigación de Productos) usa únicamente fuentes
  simuladas/mock — sin llamadas a APIs externas reales.
- Toda acción relevante debe quedar auditada; el CEO nunca puede saltarse permisos, límites de presupuesto ni aprobaciones humanas requeridas.
- Cuatro verificaciones no se pueden cerrar en una máquina de desarrollo
  (migraciones sobre PostgreSQL real, la conversión del `steps` histórico,
  la concurrencia de `SKIP LOCKED` y el login/refresco/cierre de sesión real).
  Están registradas en
  [system-overview §15](docs/architecture/system-overview.md#15-pendientes-de-integración):
  no bloquean el desarrollo, sí bloquean producción.
