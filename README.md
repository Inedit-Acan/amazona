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
- **Milestone 33:** `ActionGate` — publicar, anunciar y gastar dejan de ocurrir
  solos ([ADR 0011](docs/architecture/adr-0011-action-gate.md)) — ver abajo.
- **Milestone 34:** señales con procedencia y el primer adaptador real
  ([ADR 0012](docs/architecture/adr-0012-product-intelligence-adapters.md)) —
  ver abajo.
- **Milestone 35:** la evidencia detrás de cada señal, y qué dice cada proveedor
  ([ADR 0013](docs/architecture/adr-0013-signal-evidence-and-comparison.md)) —
  ver abajo.
- **Milestone 36:** cuándo dos nombres son el mismo producto
  ([ADR 0014](docs/architecture/adr-0014-entity-resolution.md)) — ver abajo.
- **Milestone 37:** varias fuentes reales, el coste de llamarlas y qué permite
  cada licencia
  ([ADR 0015](docs/architecture/adr-0015-multiple-real-sources-cost-and-usage-rights.md))
  — ver abajo.
- **Milestone 38:** dónde se mide una señal, y el mismo producto en varios idiomas
  ([ADR 0016](docs/architecture/adr-0016-signal-channel.md)) — ver abajo.
- **Milestone 39:** quién sostiene un hecho sobre un proveedor, y por qué el riesgo
  no es un número
  ([ADR 0017](docs/architecture/adr-0017-supplier-facts-and-risk.md)) — ver abajo.
- **Milestone 40:** economía por canal, dinero con moneda y lo que no se puede
  evaluar
  ([ADR 0018](docs/architecture/adr-0018-money-conversion-and-not-evaluable.md))
  — ver abajo.
- **Milestone 41:** Legal con requisitos declarados por una persona y anclados en
  EUR-Lex
  ([ADR 0019](docs/architecture/adr-0019-legal-requirements-and-source-anchoring.md))
  — ver abajo.

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

## Qué no ocurre solo

Desde el Milestone 33 hay una raya entre **analizar** y **actuar**. Investigar,
cotizar, calcular márgenes o comprobar requisitos legales siguen ocurriendo pase
lo que pase: no le hacen nada a nadie. Las nueve acciones con efecto del plan
maestro §7 —publicar, anunciar, gastar, comprar, pagar, enviar, reembolsar,
cambiar un precio, comunicar— pasan antes por el `ActionGate`, que responde
`ALLOW`, `DENY` o `REQUIRE_APPROVAL` mirando la decisión legal, la económica, el
presupuesto, los permisos, el entorno, el kill switch y si alguien lo ha
autorizado.

- Un `NO_GO` legal **deniega** publicar y anunciar; el análisis termina igual.
- Un `REVIEW` **pregunta**: la ejecución se para en `WAITING_APPROVAL` y la
  petición aparece en `/approvals` diciendo qué acción y sobre qué paso.
  Aprobarla continúa la ejecución por ese mismo paso, sin repetir nada.
- **Ninguna firma levanta un veto**: una aprobación humana resuelve dudas, nunca
  un `NO_GO` legal, un presupuesto agotado o el kill switch.
- Gastar **nunca** es automático en `staging` ni en `production` (§33 del plan:
  todavía no hay autonomía económica).

Qué ha impedido el sistema y por qué se consulta en la auditoría:
`action_gate.deny`. El razonamiento, en la
[ADR 0011](docs/architecture/adr-0011-action-gate.md).

## Señales con procedencia

Desde el Milestone 34, cada señal que alimenta la investigación de productos
lleva de dónde salió: quién la produjo, de qué fuente, preguntando qué, en qué
mercado, cuándo, con qué método, con cuánta confianza, cómo volver al dato crudo
y **si es simulada**. Vive en la tabla `product_signals`, así que la pregunta
«¿esto es real o inventado?» se responde con una consulta.

El primer adaptador real es **Wikimedia Pageviews**: mide cuánta gente consultó
un artículo de una enciclopedia. Es un **proxy de interés — no demanda de compra,
no ventas**, y lo dice en el `method` de cada señal que emite.

```bash
PRODUCT_INTELLIGENCE_PROVIDER=mock       # por defecto: fixtures, como siempre
PRODUCT_INTELLIGENCE_PROVIDER=real       # solo lo medido; lo que no se sabe, ausente
PRODUCT_INTELLIGENCE_PROVIDER=composite  # lo real primero, fixtures para los huecos
```

`composite` no se admite en `staging` ni `production`: puede servir fixtures.
Ante un fallo de la fuente —404, límite de ritmo, timeout— **no hay señal, nunca
un cero**: un cero se leería como «no hay demanda» cuando lo cierto es «no lo
sabemos».

Los términos que se preguntan están versionados en
`backend/app/integrations/product_intelligence/terms.py`. **Son un arranque, no
un mecanismo de descubrimiento**: una lista escrita a mano solo mide lo que
alguien ya pensó. El razonamiento completo, en la
[ADR 0012](docs/architecture/adr-0012-product-intelligence-adapters.md).

Desde el Milestone 35, cada señal guarda además **las medidas que la componen**
—doce meses de visitas detrás de un 0,7483— con el valor crudo de la fuente, y
hay un informe que contrasta lo real con el mock:

```bash
curl -X POST localhost:8000/api/research/comparisons \
  -H 'Content-Type: application/json' -d '{"category":"home","market":"us"}'
```

Lo que ese informe dice hoy, medido: el mock puntúa el 100 % de sus candidatos
con confianza 0,30 y la fuente real el 0 % con confianza 0,71 — **no hay señal
de competencia**, así que no hay score. Y **ningún candidato en común**: los
nombres del mock no existen fuera de la demo. Por eso hace falta una segunda
fuente real y, antes, resolver la identificación de entidades
([candidatas y costes](docs/design/fuentes-comerciales-product-intelligence.md)).

La comparación **no se puede ejecutar en `staging` ni `production`**: exige
correr el mock, y ahí los datos simulados no se admiten.

### Cuándo dos nombres son el mismo producto (Milestone 36)

Dos nombres se unen por **normalización determinista** —sin diacríticos, en
minúsculas, sin puntuación, sin el paréntesis de desambiguación de Wikipedia— o por
**alias escrito a mano** en `aliases.py`, versionado en git. **Por nada más: no hay
umbral de parecido**, porque un 0,85 de similitud uniría «Air fryer» con «Air
dryer» algún día y nadie sabría qué día empezó.

Hacía falta antes de la segunda fuente real, y resultó hacer falta ya con una sola.
Medido contra Wikimedia: preguntar `air fryer` en minúsculas y tener `Air fryer` en
el catálogo consultaba **dos artículos distintos** —30.897 visitas contra 5— y
persistía dos productos para un solo objeto, uno con 0,7483 de demanda y un gemelo
con 0,1297. Ahora se pregunta una vez, con la forma del catálogo, y una
investigación que vuelve a encontrar un producto **no crea otra fila**: sus señales
y sus doce observaciones mensuales se acumulan sobre el que ya estaba.

Cada fusión guarda su motivo —`normalised` o `alias:<versión>`—, incluida la
palabra que escribió quien pidió la investigación, y la pantalla de Investigación lo
dice: una fusión que no se ve es indistinguible de un error.

Lo que **no** resuelve son las traducciones: medido, aliasar «Freidora de aire» a
«Air fryer» cambiaría 12.099 visitas reales de `es.wikipedia` por un 404, porque eso
necesita un nombre **por mercado** y no un nombre canónico único
([ADR 0014](docs/architecture/adr-0014-entity-resolution.md)).

Y tres consecuencias que conviene saber: los **datos anteriores al milestone**
conservan la clave que se deduce de su nombre —el relleno de la migración no aplica
el catálogo de alias— así que un duplicado preexistente no se resuelve solo;
`identity_key` es **nulable** (nula = «no resuelta») y **no única**, porque aquí
también hay productos dados de alta a mano; y **dos ejecuciones sobre la misma
categoría aterrizan en el mismo producto**, que acumula varios análisis y comparte
`store_slug`, de modo que Tienda y Marketing lo ven distinto a antes. El detalle, en
[milestone-36-demo.md](docs/milestones/milestone-36-demo.md).

### Medido, estimado y simulado (Milestone 37)

Una señal ya no es «simulada o no». Son **tres** cosas, porque un número que una
fuente **observó** y uno que una fuente **modeló** vienen los dos del mundo y no
valen lo mismo:

- `measured` — la fuente lo observó y lo reporta.
- `estimated` — la fuente lo derivó, quizá sin decir cómo. **No es una observación.**
- `simulated` — un fixture. No viene del mundo.

Cada base tiene un **techo de confianza** —1,0 / 0,6 / 0,4— y exceder el techo
**falla al construir la señal** en vez de recortarse en silencio. Y a la hora de
elegir entre señales del mismo tipo, lo medido gana a lo estimado y lo estimado a lo
inventado. Una estimación propietaria se puede usar; lo que no se puede es
presentarla como un hecho medido.

### Cada llamada externa se cuenta, y de pago sin autorización no se llama

El plan maestro §25 lo pedía **antes** de introducir LLM o APIs comerciales, y no
existía. Ahora `external_api_costs` guarda por llamada el proveedor, la operación,
las unidades y de qué, el coste estimado, el real —**nulo cuando el proveedor
todavía no lo ha dicho, que no es cero**—, la moneda y el `correlation_id`. **Una
denegación también deja fila**: es lo que explica por qué una investigación volvió
sin señales.

Tres reglas: un proveedor de pago **sin límite de gasto autorizado no se llama**;
**gratis no es sin límite** (eBay publica 5.000 llamadas/día, Wikimedia pide ≤200/s);
y cuando no cabe, **no hay señal** — nunca un cero.

```bash
curl -s localhost:8000/api/costs/api-usage | python -m json.tool
```

Los límites viven en configuración (`API_SPEND_LIMITS`) porque son dinero del
propietario, no una preferencia de la aplicación. Hoy están vacíos: **el presupuesto
es 0 €**.

### Tener el dato no es tener permiso

Una matriz por proveedor declara ocho usos —almacenamiento, retención,
transformación, métricas derivadas, scoring, IA/LLM, redistribución, uso comercial—
más la atribución, cada uno con su fuente y su fecha de lectura. **Lo que no se sabe
no se permite**: un `UNKNOWN` pesa igual que un «no», porque que una licencia no
prohíba algo expresamente no es lo mismo que autorizarlo.

Y se aplica, no solo se documenta: una señal cuya licencia no permite puntuar **no
entra en el score** —y la pantalla dice quién la retuvo—, y una cuya licencia no
permite almacenar **no se persiste**, con la auditoría contándolo.

### eBay Browse: implementado, medido y sin usar

Es la primera señal de **competencia medida** del sistema, que era el único hueco que
impedía puntuar un candidato real. Gratis con un keyset de desarrollador —sin cuenta
de vendedor—, con sandbox propio y varios mercados.

**Sus datos no se usan.** Su contrato define «Restricted APIs» por lo que la API
aporta —tendencias de mercado, estrategias de precio, volúmenes de venta— y prohíbe
para ellas alimentar IA ajena o construir herramientas de precios sin consentimiento
escrito. No se ha podido determinar si Browse entra ahí, así que su fila está casi
entera sin resolver y sus señales se leen sin guardarse ni puntuar
([ADR 0015](docs/architecture/adr-0015-multiple-real-sources-cost-and-usage-rights.md)).

**Y desde el Milestone 38 está aparcado**, no solo bloqueado: los requisitos oficiales
de las Buy APIs dicen que el uso en producción «is intended for eBay partners only» y
exige aprobación del eBay Partner Network con revisión del modelo de negocio. eBay es
un canal **complementario** de KOVA, así que su adaptador queda como implementación de
referencia y la arquitectura no depende de él.

### Dónde se mide una señal (Milestone 38)

`market` dice en qué **geografía**; `channel` dice en qué **canal**. Sin lo segundo,
«cuánta competencia hay» significaba cosas incompatibles: dentro de un marketplace es
cuántos vendedores compiten, y para una web propia —el canal prioritario de KOVA— es
dificultad orgánica y coste del clic.

**Cuatro tipos cerrados y plataformas abiertas**: `own_web`, `marketplace`, `search`,
`social` son conceptos; Amazon, eBay, Etsy, Mercado Libre o TikTok Shop son **valores**,
y añadir uno es una línea de catálogo y **ninguna migración**. La clave se lee sola
(`marketplace:amazon`) y el tipo lo da el catálogo, no un `split(':')`. Y **TikTok no
es TikTok Shop**: uno descubre, el otro cobra.

**Sin canal significa agnóstica, nunca «válida para todos».** Una señal ligada a canal
—competencia, demanda de búsqueda, demanda de marketplace— sirve **solo** para su
canal; sin canal declarado, solo para una decisión igualmente sin canal. Si valiera
para todos, el relleno de un fixture decidiría sobre Amazon. El score dice para qué
canal se calculó y, cuando no puede calcularse, si lo impidió una **licencia** o un
**canal equivocado** — se arreglan de formas distintas.

**El mismo producto en varios idiomas.** Los *langlinks* de Wikimedia declaran la
equivalencia que el Milestone 36 dejó pendiente y midió como un 404: «Air fryer» es
«Freidora de aire» en `es.wikipedia`, y el mercado español pasa de no medirse a
**0,6805 de demanda**. El candidato conserva su nombre canónico —si no, medir cuatro
mercados daría cuatro productos— y la equivalencia se guarda con su motivo. Sin
equivalencia declarada, ese término **no se mide**: no se traduce ni se aproxima.

`SEARCH_DEMAND` y `MARKETPLACE_DEMAND` se separan de `DEMAND` como pedía el plan §8, y
**nadie las emite todavía**. Wikimedia sigue en `DEMAND` y sigue significando
**interés**: nunca intención de compra, nunca volumen de búsqueda comercial, nunca
demanda.

### Quién sostiene un hecho sobre un proveedor (Milestone 39)

Un proveedor estaba `verified: bool` y su fiabilidad valía `0.0` cuando nadie la había
valorado. El plan maestro §10 pide cuatro niveles y dice «No marcar un proveedor como
"verified" sin explicar qué significa»; §11 pide que el riesgo siga siendo explicable
por dimensiones; §16 pide que cada proveedor **declare** si soporta envío directo,
dropshipping, envío ciego, embalaje propio, tracking, devoluciones, retorno en la UE y
SLA. Nada de eso existía: las ocho capacidades las inventaba un generador
pseudoaleatorio en el frontend.

**Cada hecho dice quién lo sostiene**: verificado por un tercero, dicho por el
proveedor, estimado por AMAZONA, simulado, o **desconocido** — que no se guarda,
porque una fila que dice «no se sabe» afirma lo mismo que no tener fila. Un
«verificado por un tercero» **sin emisor falla al construirse**.

**Una cotización lleva sus condiciones**: moneda, MOQ, Incoterm, condiciones de pago,
preparación y transporte por separado, coste logístico, mercado de destino y vigencia.
Todo puede faltar, y lo que falta **no vale cero**: sin coste logístico no hay coste de
aterrizaje aunque haya precio, porque sumar cero diría que el transporte es gratis.

**No se convierte entre monedas.** No hay fuente de tipos de cambio y no se inventa
ninguno: dos precios en monedas distintas no se comparan, y el panel lo dice en vez de
enseñar un total con símbolo de euro que no son euros.

**El riesgo son ocho respuestas, no un número**, con un cuarto nivel además de
bajo/medio/alto: **sin evaluar**. Un riesgo de fraude «bajo» porque nadie miró es una
compra a ciegas que parece hecha con los ojos abiertos.

**Y los proveedores reales se introducen a mano**, que es el camino que este milestone
abre y que se sostiene permanentemente: un precio negociado no lo publica ninguna API.

### Economía por canal, moneda y techo de CAC (Milestone 40)

Un margen se calculaba restando un coste en dólares de un precio en euros, sin decir
en qué canal se vendía, y el techo de CAC que la pantalla enseñaba salía de confundir
una unidad con un pedido.

**Un importe no existe sin su moneda**, y restar dos monedas distintas falla al
construir el resultado. Convertir exige un tipo de cambio con fecha, fuente y
procedencia, y **sin tasa no se convierte: el análisis queda sin evaluar**. Nunca se
supone 1:1. La tasa la escribe una persona —el cambio que aplicó el banco—, que es la
fuente que cuesta cero euros.

**«No evaluable» no es un resultado negativo.** Un margen negativo se sabe y es malo;
esto es que no se sabe, y nunca bloquea el sistema como si fuera un «no».

**Cada coste está en una de cinco situaciones**, y las cuatro que suman cero euros
significan cosas distintas: está dentro de otro coste, no aplica en este canal, nadie
lo ha dicho y hace falta, o nadie lo ha dicho y da igual. Con eso, contar un arancel
dos veces deja de ser posible.

**Unidad, pedido y adquisición son tres cosas.** Si cada pedido lleva tres unidades,
el margen que financia esa adquisición es el de tres. Y un «una unidad por pedido»
que nadie ha declarado no vale: deja el techo de CAC sin evaluar.

El CAC máximo dice **cuánto podríamos permitirnos pagar** por un cliente, no cuánto
costará: eso se mide con campañas reales y queda fuera.

### Requisitos legales declarados y anclados en EUR-Lex (Milestone 41)

Ninguna fuente pública dice a qué productos se aplica una norma: EUR-Lex publica su
texto y su vigencia, y «una freidora de aire necesita CE» es un juicio jurídico.
**Legal no lo infiere.** Tres cuestiones que no se rellenan una con otra:

- **Aplicabilidad** — la declara una persona (solo OWNER y ADMIN; REVIEWER lee y el
  sistema no puede).
- **Existencia y vigencia** — la comprueba EUR-Lex sobre la norma que se nombró, con
  fecha, y las fechas de la fuente se enseñan **sin interpretar**.
- **Evidencia de cumplimiento** — la aporta una persona, con emisor si la emitió un
  tercero.

El resultado son **cuatro estados**: `PASS`, `REVIEW_REQUIRED`, `BLOCKED` y `UNKNOWN`.
**`PASS` solo significa que, dentro de lo declarado y comprobado, Legal no ha
encontrado un bloqueo — nunca «producto legal».** Lo que nadie declaró no se ha
mirado, y `UNKNOWN` jamás asciende a `PASS`. Una directiva sola no basta: hace falta
la transposición nacional. Solo cubre Derecho de la UE, y con el proveedor por
defecto (`mock`) todo sigue exactamente como antes. Requiere `REGULATORY_PROVIDER=real`.

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
  [system-overview §20](docs/architecture/system-overview.md#20-pendientes-de-integración):
  no bloquean el desarrollo, sí bloquean producción.
