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

## Seguridad

Desde el Milestone 29 el comportamiento depende del entorno
(`ENVIRONMENT`: `development`, `test`, `demo`, `staging`, `production`).

| | development / test / demo | staging / production |
|---|---|---|
| Rutas mutadoras | abiertas (o con `REQUIRE_AUTH=true`) | exigen token verificado |
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

**Límite conocido de esta versión:** solo están protegidas las rutas mutadoras.
En producción, quien tenga acceso de red al backend puede *leer* los datos de
negocio. Cerrar los `GET` es el Milestone 29.1.

## Notas

- Amazon SP-API: prohibido usar sus datos para entrenar modelos.
- No hay dinero real, pedidos, proveedores ni impuestos reales.
- El Agente 1 (Investigación de Productos) usa únicamente fuentes
  simuladas/mock — sin llamadas a APIs externas reales.
- Toda acción relevante debe quedar auditada; el CEO nunca puede saltarse permisos, límites de presupuesto ni aprobaciones humanas requeridas.
