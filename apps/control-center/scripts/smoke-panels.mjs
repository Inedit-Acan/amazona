#!/usr/bin/env node
// Smoke de regresión del Control Center y del backend (hardening pre-M44).
//
// Convierte en una prueba repetible lo que se comprobaba a mano: con backend y
// frontend YA arrancados (iniciar-amazona.bat, o `next start`), recorre los 15
// paneles y el backend y falla si algo no está en orden. Solo hace peticiones GET.
//
//   node scripts/smoke-panels.mjs
//   CONTROL_CENTER_URL=http://localhost:3000 BACKEND_URL=http://localhost:8000 \
//     EXPECT_MIGRATION=b6d2f8a41c93 node scripts/smoke-panels.mjs
//
// Sin dependencias: usa el fetch de Node (>= 22). No es un test de navegador.
// Lo que NO puede comprobar sin uno —errores de consola, hidratación, canvas— queda
// fuera, y `/ceo` es la excepción documentada de abajo.

const FRONTEND = (process.env.CONTROL_CENTER_URL ?? "http://localhost:3000").replace(/\/$/, "");
const BACKEND = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
const EXPECT_MIGRATION = process.env.EXPECT_MIGRATION ?? "";
const TIMEOUT_MS = Number(process.env.SMOKE_TIMEOUT_MS ?? 60_000);

// El aviso de `ApiErrorAlert` en sus dos redacciones: la del código commiteado (inglés) y la
// traducida. Cualquiera de las dos significa que la página no pudo hablar con el backend.
const CONNECTION_ERRORS = ["Could not reach the AMAZONA backend", "No se pudo conectar con el backend de AMAZONA"];
const NEXT_ERROR_MARKERS = ["Application error: a server-side exception", "Internal Server Error"];

/** Las 15 rutas del menú y el <h1> que cada una debe traer en su HTML.
 * `clientOnly`: la página es un componente de cliente tras un Suspense
 * (`useSearchParams`). En producción el servidor entrega un marco vacío y en
 * `next dev` una carga directa se revela con `requestAnimationFrame`, que no se
 * dispara en un documento oculto (React 19.2): su contenido solo se puede comprobar
 * con un navegador visible. Aquí solo se exige HTTP 200 y ausencia de error; no
 * se exige contenido, y no se toca la aplicación para que el test pase. */
const PANELS = [
  { path: "/dashboard", h1: "Panel" },
  { path: "/ceo", h1: "Director ejecutivo", clientOnly: true },
  { path: "/research", h1: "Investigación" },
  { path: "/sourcing", h1: "Proveedores y abastecimiento", withProduct: true },
  { path: "/economics", h1: "Economía y rentabilidad" },
  { path: "/legal", h1: "Legal y cumplimiento", withProduct: true },
  { path: "/ecommerce", h1: "Tienda y canales de venta" },
  { path: "/marketing", h1: "Marketing y adquisición" },
  { path: "/operations", h1: "Operaciones" },
  { path: "/cfo", h1: "Finanzas y control" },
  { path: "/projects", h1: "Proyectos" },
  { path: "/agents", h1: "Agentes" },
  { path: "/approvals", h1: "Aprobaciones y decisiones" },
  { path: "/audit", h1: "Auditoría y trazabilidad" },
  { path: "/status", h1: "Estado e infraestructura" },
];

/** Las rutas que dieron 500 cuando la base no estaba migrada (Fase B). */
const KEY_ENDPOINTS = [
  "/api/products",
  "/api/audit",
  "/api/jobs",
  "/api/pipeline/runs",
  "/api/suppliers",
  "/api/exchange-rates",
  "/api/regulatory-requirements",
  "/api/research/comparisons",
];

const failures = [];
const rows = [];

function record(area, name, ok, detail = "") {
  rows.push({ area, name, ok, detail });
  if (!ok) failures.push(`${area} ${name}: ${detail}`);
}

async function get(url) {
  const started = Date.now();
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS), redirect: "follow" });
    return { status: response.status, body: await response.text(), ms: Date.now() - started };
  } catch (error) {
    return { status: 0, body: "", ms: Date.now() - started, error: String(error?.cause?.code ?? error?.message ?? error) };
  }
}

function h1Of(html) {
  const match = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/);
  return match ? match[1].replace(/<[^>]+>/g, "").trim() : null;
}

async function checkBackend() {
  for (const path of ["/health", "/health/ready"]) {
    const res = await get(BACKEND + path);
    record("backend", path, res.status === 200, `HTTP ${res.status || res.error}`);
  }

  const detailed = await get(BACKEND + "/health/detailed");
  let migration = null;
  let database = null;
  try {
    ({ migration, database } = JSON.parse(detailed.body));
  } catch {
    /* lo recoge el registro de abajo */
  }
  record("backend", "/health/detailed", detailed.status === 200 && database === "ok", `HTTP ${detailed.status} database=${database}`);
  record(
    "backend",
    "migration",
    Boolean(migration) && (!EXPECT_MIGRATION || migration === EXPECT_MIGRATION),
    `${migration}${EXPECT_MIGRATION ? ` (esperada ${EXPECT_MIGRATION})` : ""}`,
  );

  for (const path of KEY_ENDPOINTS) {
    const res = await get(BACKEND + path);
    record("endpoint", path, res.status === 200, `HTTP ${res.status || res.error}`);
  }

  // Todas las rutas GET sin parámetros: ninguna puede dar 5xx. Un 422 es un parámetro obligatorio
  // que el contrato exige, no un fallo.
  const spec = await get(BACKEND + "/openapi.json");
  let paths = [];
  try {
    const schema = JSON.parse(spec.body).paths;
    paths = Object.entries(schema)
      .filter(([path, ops]) => ops.get && !path.includes("{"))
      .map(([path]) => path);
  } catch {
    record("backend", "openapi", false, `HTTP ${spec.status}`);
  }
  const bad = [];
  for (const path of paths) {
    const res = await get(BACKEND + path);
    if (res.status === 0 || res.status >= 500) bad.push(`${path} -> ${res.status || res.error}`);
  }
  record("backend", `GET sweep (${paths.length} routes)`, paths.length > 0 && bad.length === 0, bad.join("; ") || "no 5xx");
}

async function firstProductId() {
  const res = await get(BACKEND + "/api/products");
  try {
    return JSON.parse(res.body)[0]?.id ?? null;
  } catch {
    return null;
  }
}

async function checkPanels() {
  const productId = await firstProductId();
  for (const panel of PANELS) {
    const query = panel.withProduct && productId ? `?product_id=${productId}` : "";
    const res = await get(FRONTEND + panel.path + query);
    const problems = [];
    if (res.status !== 200) problems.push(`HTTP ${res.status || res.error}`);
    const shown = CONNECTION_ERRORS.find((text) => res.body.includes(text));
    if (shown) problems.push(`muestra el aviso de conexión «${shown}»`);
    for (const marker of NEXT_ERROR_MARKERS) if (res.body.includes(marker)) problems.push(`marcador de error de Next: ${marker}`);
    if (!panel.clientOnly) {
      const h1 = h1Of(res.body);
      if (h1 !== panel.h1) problems.push(`h1 «${h1}», esperado «${panel.h1}»`);
    }
    const note = panel.clientOnly ? "cliente: solo HTTP y ausencia de error" : "";
    record("panel", panel.path, problems.length === 0, problems.join("; ") || `HTTP 200 en ${res.ms} ms ${note}`.trim());
  }
}

await checkBackend();
await checkPanels();

for (const row of rows) console.log(`${row.ok ? "OK  " : "FAIL"} ${row.area.padEnd(8)} ${row.name.padEnd(34)} ${row.detail}`);
console.log(`\n${rows.length - failures.length}/${rows.length} comprobaciones correctas.`);
if (failures.length > 0) {
  console.error(`\n${failures.length} fallo(s):\n - ${failures.join("\n - ")}`);
  process.exit(1);
}
