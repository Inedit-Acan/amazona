import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import type { AuditEntry, Decision, Project, Task } from "./api.ts";
import { RESULT_LABEL, resultLabel } from "./audit-view.ts";
import { DECISION_VERDICT, projectedFinance } from "./projects.ts";
import { PLAN_ABSENCE_TEXT, formatPlanAmount, projectCard, type ProjectSource } from "./projects-view.ts";
import { NO_DATA, UNREAD } from "./revenue-view.ts";
import { signalsMode, type ResearchRow } from "./research-view.ts";

// La interfaz no puede elevar el nivel de certeza de los datos (M46, Commit 8, ADR 0031 §30).
//
// Una convención («no escribas "real" para decir "existe en el backend"») se olvida; una prueba que lee el código, no. Esta
// guarda NO es una lista negra de palabras: «real» tiene usos legítimos (una negación, «tiempo real» de un simulador, el
// nombre de una norma). Por eso cada aparición se juzga EN SU CONTEXTO —un fragmento concreto, de un fichero concreto— y
// solo en los ficheros que este commit gobierna. Lo que no está en la lista cerrada de abajo falla.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
/** Siempre con saltos `\n`: en Windows el árbol de trabajo tiene CRLF y en el CI LF. */
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) =>
  source.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " ")).replace(/(^|[^:])\/\/.*$/gm, (_m, lead: string) => lead);

/** Los ficheros cuyo vocabulario de certeza gobierna este commit. Lista cerrada: no es «todo el repositorio». */
const GOVERNED = [
  "app/agents/agents-panels.tsx",
  "app/agents/agents-workspace.tsx",
  "app/approvals/approvals-panels.tsx",
  "app/approvals/approvals-workspace.tsx",
  "app/audit/audit-panels.tsx",
  "app/audit/audit-workspace.tsx",
  "app/ceo/page.tsx",
  "components/ceo/agent-network-card.tsx",
  "components/ceo/assistant-drawer.tsx",
  "components/ceo/block-card.tsx",
  "components/ceo/bottom-row.tsx",
  "components/ceo/ceo-assistant-panel.tsx",
  "components/ceo/ceo-context.tsx",
  "components/ceo/ceo-header.tsx",
  "components/ceo/ceo-layout.tsx",
  "components/ceo/decision-triptych.tsx",
  "components/ceo/fullscreen-button.tsx",
  "components/ceo/kpi-row.tsx",
  "components/ceo/mission-drawer.tsx",
  "components/ceo/mission-form.tsx",
  "lib/ceo-blocks.ts",
  "lib/ceo-mission-view.ts",
  "app/dashboard/dashboard-panels.tsx",
  "app/dashboard/dashboard-workspace.tsx",
  "app/ecommerce/amazon-panels.tsx",
  "app/ecommerce/copy.ts",
  "app/ecommerce/ecommerce-workspace.tsx",
  "app/ecommerce/store-builder.tsx",
  "app/economics/copy.ts",
  "app/economics/economics-workspace.tsx",
  "app/legal/legal-workspace.tsx",
  "app/marketing/marketing-panels.tsx",
  "app/marketing/marketing-workspace.tsx",
  "app/projects/projects-panels.tsx",
  "app/projects/projects-workspace.tsx",
  "app/research/research-workspace.tsx",
  "app/sourcing/sourcing-workspace.tsx",
  "app/status/copy.ts",
  "app/status/status-panels.tsx",
  "app/status/status-workspace.tsx",
  "components/data-provenance-badge.tsx",
  "components/economics-activity-chart.tsx",
  "components/neural-nexus/neural-nexus-graph.tsx",
  "components/neural-nexus/nexus-details.tsx",
  "components/supplier-entry-form.tsx",
  "components/version-card.tsx",
  "lib/approvals-view.ts",
  "lib/demo/marketing.ts",
  "lib/economics-baseline.ts",
  "lib/marketing-view.ts",
  "lib/projects-view.ts",
  "lib/projects.ts",
  "lib/research-view.ts",
  "lib/storefront-view.ts",
];

/** Lo que una persona lee en pantalla: los literales de texto y las líneas de prosa del JSX (sin etiquetas ni código). */
function visibleTexts(source: string): string[] {
  const code = stripComments(source);
  const texts: string[] = [];
  for (const m of code.matchAll(/"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`/g)) texts.push(m[1] ?? m[2] ?? m[3] ?? "");
  for (const line of code.split("\n")) {
    const prose = line.replace(/<[^<>]*>/g, " ").trim();
    // Una clave de objeto en minúscula (`series: real,`) es código; «Real: los agentes…» con mayúscula es prosa.
    const isCode = /[=;(){}]/.test(prose) || /^[a-z$_][\w$]*\??:\s/.test(prose) || /^(import|export|return|const|let|type|interface)\b/.test(prose);
    if (/[A-Za-zÁ-ú]{3}/.test(prose) && !isCode) texts.push(prose);
  }
  return texts;
}

test("la prueba ve los ficheros que tiene que vigilar", () => {
  for (const file of GOVERNED) assert.ok(existsSync(join(ROOT, file)), `${file} ya no existe: actualiza la lista`);
  assert.ok(GOVERNED.length >= 35, "la lista de ficheros gobernados se ha vaciado");
});

// --- 1. «real» no significa «no es demo» ni «existe en el backend» ------------------------------------------------------------

/** Los únicos usos legítimos de «real» en lo que se lee en pantalla de estos ficheros: un fragmento, en un fichero, con su porqué. */
const REAL_ALLOWED: { file: string; fragment: string; why: string }[] = [
  { file: "components/ceo/mission-drawer.tsx", fragment: "sin dinero, pedidos ni proveedores reales", why: "negación: dice lo que NO hay" },
  { file: "components/ceo/mission-form.tsx", fragment: "sin dinero, pedidos ni proveedores reales", why: "negación: dice lo que NO hay" },
  { file: "components/ceo/mission-form.tsx", fragment: "Sin gasto, pedidos ni proveedores reales", why: "negación: dice lo que NO hay" },
  { file: "components/ceo/mission-form.tsx", fragment: "Proveedores y costes reales: pendiente de integrar", why: "marca lo pendiente" },
  { file: "app/dashboard/dashboard-panels.tsx", fragment: "todavía no tiene costes ni ventas reales", why: "negación: dice lo que NO hay" },
  { file: "app/economics/economics-workspace.tsx", fragment: "en tiempo real", why: "el simulador recalcula al escribir (inmediatez de la interfaz)" },
  { file: "app/status/status-panels.tsx", fragment: "No hay telemetría de tráfico real todavía", why: "negación: dice lo que NO hay" },
  { file: "components/supplier-entry-form.tsx", fragment: "Fábrica Real S.L.", why: "marcador de posición: el nombre de una sociedad de ejemplo" },
];

test("«real» solo aparece como negación, como «tiempo real» del simulador o como dato estructurado, nunca como «no es demo»", () => {
  const used = new Set<number>();
  for (const file of GOVERNED) {
    for (const text of visibleTexts(read(file))) {
      if (!/\breal(es|mente|idad)?\b/i.test(text)) continue;
      if (/^real$/.test(text.trim())) continue; // el valor estructurado de un dato (`provenance === "real"`), no un texto
      const allowed = REAL_ALLOWED.findIndex((entry) => entry.file === file && text.includes(entry.fragment));
      assert.notEqual(allowed, -1, `${file} dice «real» sin respaldo: ${text.slice(0, 160)}`);
      used.add(allowed);
    }
  }
  const unused = REAL_ALLOWED.filter((_entry, index) => !used.has(index)).map((entry) => `${entry.file}: ${entry.fragment}`);
  assert.deepEqual(unused, [], "hay usos permitidos que ya no existen: quítalos de la lista");
});

test("ninguna superficie gobernada afirma beneficio, ingresos, ventas, cobros o dinero «reales»", () => {
  const claims = /beneficio real|realmente cobrad|ingresos? reales?|dinero real|transacci[oó]n real|cobros? reales?|pagos? reales?|ventas? real\b/i;
  for (const file of GOVERNED) {
    for (const text of visibleTexts(read(file))) assert.ok(!claims.test(text), `${file} afirma dinero o beneficio real: ${text.slice(0, 160)}`);
  }
});

// --- 2. «Verificado» solo cuando alguien lo verificó ---------------------------------------------------------------------------

test("la insignia `verified` solo describe una verificación de un tercero; lo que el backend guarda es `recorded`", () => {
  const badge = read("components/data-provenance-badge.tsx");
  assert.match(badge, /\| "recorded"/);
  const recorded = badge.slice(badge.indexOf("  recorded: {"), badge.indexOf("  // `verified` queda"));
  assert.match(recorded, /label: "Registro del backend"/);
  assert.ok(!/verificad|verified/i.test(recorded.replace(/Que exista no lo hace verificado\./, "")), "`recorded` se llama o se describe como verificado");
  const verified = badge.slice(badge.indexOf("  verified: {"), badge.indexOf("  third_party: {"));
  assert.match(verified, /label: "Verificado por un tercero"/);
  assert.ok(!/Dato verificado contra su fuente original/.test(badge), "alguna insignia sigue diciendo «verificado contra su fuente original»");
  // Lo proyectado y lo inventado se siguen llamando PLAN y Demo: su etiqueta no puede perderse.
  const planned = badge.slice(badge.indexOf("  planned: {"), badge.indexOf("  // M46, Commit 8: lo que el backend GUARDA"));
  assert.match(planned, /label: "Proyección \(PLAN\)"/);
  assert.match(planned, /short: "PLAN"/);
  const demo = badge.slice(badge.indexOf("  demo: {"));
  assert.match(demo, /label: "Datos de demostración"/);
  assert.match(demo, /short: "Demo"/);
  // Lo declarado no sube a verificado: son dos entradas distintas con dos etiquetas distintas.
  const declared = badge.slice(badge.indexOf("  declared: {"), badge.indexOf("  planned: {"));
  assert.match(declared, /label: "Declarado"/);
  assert.ok(!/verificad/i.test(declared.replace(/No es un pago comprobado\./, "")), "«declarado» se describe como verificado");
});

test("ninguna pantalla pinta `verified` sobre un registro: solo el CFO (hechos de pago, ADR 0030) y el coste de un proveedor verificado por un tercero", () => {
  const offenders: string[] = [];
  for (const file of GOVERNED.filter((candidate) => candidate.endsWith(".tsx"))) {
    const code = stripComments(read(file));
    if (/(status|provenance)=(\{[^}]*)?["']verified["']|\?\s*["']verified["']|:\s*["']verified["']/.test(code)) offenders.push(file);
  }
  assert.deepEqual(offenders, [], "una pantalla vuelve a decir «Verificado» de un registro del backend");
  // El único origen legítimo de `verified` en la insignia: un coste cuyo proveedor consta como verificado por un tercero.
  const baseline = stripComments(read("lib/economics-baseline.ts"));
  assert.match(baseline, /supplier\?\.verification === "third_party_verified" \? "verified" : "third_party"/);
});

test("la auditoría no llama «verificado» a una entrada que el backend solo guarda, ni «verificación» a una integridad de demostración", () => {
  const forbidden = /Evento verificado|Eventos verificados|Última verificación\b(?! \(demo\))|última verificación hace/;
  for (const file of ["app/audit/audit-panels.tsx", "app/audit/audit-workspace.tsx"]) {
    for (const text of visibleTexts(read(file))) assert.ok(!forbidden.test(text), `${file}: ${text.slice(0, 140)}`);
  }
  assert.match(read("app/audit/audit-workspace.tsx"), /"Evento del registro"/);
  assert.match(read("app/audit/audit-panels.tsx"), /Última comprobación \(demo\)/);
});

test("el resultado de una entrada de auditoría se dice «Sin error registrado»: el backend no guarda ningún «Éxito»", () => {
  assert.equal(resultLabel("Éxito"), "Sin error registrado");
  assert.equal(resultLabel("Error"), "Error");
  assert.equal(resultLabel("Creado"), "Creado");
  assert.ok(!Object.values(RESULT_LABEL).includes("Éxito"), "alguna etiqueta de resultado vuelve a decir «Éxito»");
  for (const file of ["app/audit/audit-panels.tsx", "app/audit/audit-workspace.tsx"]) {
    assert.ok(!/\{row\.result\}/.test(stripComments(read(file))), `${file} pinta el resultado inferido sin pasar por resultLabel`);
  }
  assert.match(stripComments(read("lib/audit-view.ts")), /value: resultLabel\(row\.result\)/);
});

test("«de verdad» no certifica nada en lo que se lee en pantalla (ni partido en dos líneas)", () => {
  for (const file of GOVERNED) {
    const code = stripComments(read(file)).replace(/\s+/g, " ");
    assert.ok(!/\bde verdad\b/i.test(code), `${file} dice «de verdad»`);
  }
});

test("la configuración por mercado de Tienda dice que los estados de mercado son de demostración", () => {
  const workspace = read("app/ecommerce/ecommerce-workspace.tsx");
  const start = workspace.indexOf("<CardTitle>Configuración por mercado</CardTitle>");
  assert.notEqual(start, -1);
  assert.match(workspace.slice(start, workspace.indexOf("<CardContent", start)), /<DataProvenanceBadge status="demo"/);
});

test("el contenido no se presenta como «basado en datos verificados» ni con «calidad verificada»", () => {
  const forbidden = /datos verificados|calidad verificada|dato verificado contra/i;
  for (const file of GOVERNED) {
    for (const text of visibleTexts(read(file))) {
      // «Ingresos verificados» del registro de pagos es otra cosa y no está entre los ficheros gobernados.
      assert.ok(!forbidden.test(text), `${file} afirma verificación: ${text.slice(0, 140)}`);
    }
  }
});

// --- 3. Una recomendación no es una aprobación; un estado técnico no es «activo» ---------------------------------------------------

test("una decisión GO/NO_GO del motor es una recomendación: no se llama aprobada ni rechazada (la aprobación humana es otro estado)", () => {
  assert.equal(DECISION_VERDICT.GO.title, "Favorable");
  assert.equal(DECISION_VERDICT.NO_GO.title, "No viable");
  assert.match(DECISION_VERDICT.GO.detail, /recomienda/);
  assert.match(DECISION_VERDICT.GO.detail, /no una aprobación humana/);
  for (const status of ["GO", "NO_GO"] as const) assert.doesNotMatch(DECISION_VERDICT[status].title, /aprob|rechaz/i);
  // La aprobación humana sigue siendo humana.
  assert.match(DECISION_VERDICT.HUMAN_APPROVAL.title, /aprobación humana/);
  const ceo = read("components/ceo/mission-form.tsx");
  assert.match(ceo, /GO: "Favorable \(GO\)"/);
  assert.match(ceo, /NO_GO: "No viable \(NO_GO\)"/);
});

test("las validaciones derivadas de un análisis dicen «sin bloqueo» o «favorable», no «aprobado»", () => {
  const view = stripComments(read("lib/approvals-view.ts"));
  assert.ok(!/detail:[^\n]*"Aprobado"/.test(view), "una validación vuelve a decir «Aprobado» de una recomendación");
  assert.match(view, /legalOk \? "Sin bloqueo"/);
  assert.match(view, /recommendation === "GO" \? "Favorable"/);
  assert.ok(!/ready: \{ label: "Aprobado"/.test(stripComments(read("app/ecommerce/ecommerce-workspace.tsx"))), "la puerta legal vuelve a decir «Aprobado»");
  assert.ok(!/label="Precio aprobado"/.test(read("app/ecommerce/ecommerce-workspace.tsx")), "el precio vuelve a llamarse «aprobado»");
});

test("un veredicto fijo es de demostración: la tarjeta de análisis de agentes lo rotula DEMO y no lo hace pasar por derivado", () => {
  const view = stripComments(read("lib/approvals-view.ts"));
  assert.ok(!/verdict: "Oportunidad validada"|verdict: "Capacidad operativa confirmada"/.test(view), "un veredicto constante vuelve a afirmar una validación");
  assert.equal((view.match(/verdict: "Veredicto de demostración"/g) ?? []).length, 2);
  const panels = read("app/approvals/approvals-panels.tsx");
  const card = panels.slice(panels.indexOf("export function AgentAnalysisCard"), panels.indexOf("export function FindingsCard"));
  assert.match(card, /<DataProvenanceBadge status="demo"/);
  assert.ok(!/status="estimated"/.test(card), "la tarjeta vuelve a decir «estimación» de un veredicto fijo");
});

test("«READY» de una tienda es «Preparada», no «Activo»: no hay nada publicado", () => {
  const view = stripComments(read("lib/storefront-view.ts"));
  assert.match(view, /READY: \{ label: "Preparada"/);
  assert.ok(!/READY: \{ label: "Activo"/.test(view));
});

test("«Economía analizada» y «Proveedor seleccionado»: que exista un análisis o una selección no es una validación", () => {
  assert.match(read("app/economics/economics-workspace.tsx"), /label: "Economía analizada"/);
  assert.match(read("app/sourcing/sourcing-workspace.tsx"), /label: "Proveedor seleccionado"/);
  for (const file of ["app/economics/economics-workspace.tsx", "app/sourcing/sourcing-workspace.tsx"]) {
    assert.ok(!/label: "(Economía|Proveedor) validad[ao]"/.test(read(file)), `${file} vuelve a decir «validada»`);
  }
  assert.match(read("app/economics/economics-workspace.tsx"), /Beneficio anual estimado/);
});

test("una puntuación de demostración no «aprueba» una creatividad", () => {
  const view = stripComments(read("lib/marketing-view.ts"));
  assert.match(view, /export type CreativeStatus = "Puntuación alta" \| "En revisión" \| "Ajustar";/);
  assert.ok(!/"Aprobado"/.test(view));
});

test("las señales medidas de un tercero son un proxy de interés, no «real» ni «verificado»", () => {
  const row = (provenance: ResearchRow["provenance"]) => ({ provenance }) as ResearchRow;
  const mode = signalsMode([row("real"), row("real")]);
  assert.equal(mode.label, "Señales medidas (proxy de interés)");
  assert.equal(mode.status, "third_party");
  assert.doesNotMatch(mode.label, /real|verific/i);
  assert.match(read("app/research/research-workspace.tsx"), /chart\.provenance === "real" \? "third_party" : "demo"/);
});

// --- 4. DEMO siempre etiquetado como DEMO ---------------------------------------------------------------------------------------

test("cada KPI y cada tarjeta de rendimiento de Marketing (cifras de demostración) lleva su insignia DEMO", () => {
  const workspace = read("app/marketing/marketing-workspace.tsx");
  const section = workspace.slice(workspace.indexOf('aria-label="Indicadores de marketing"'), workspace.indexOf("{/* Plan · Nueva campaña · Audiencias */}"));
  const kpis = section.split("<KpiCard").slice(1);
  assert.equal(kpis.length, 6, "Marketing ya no tiene seis KPI: actualiza la prueba");
  for (const kpi of kpis) assert.match(kpi, /provenance="demo"/, `un KPI de Marketing sin DEMO: ${kpi.slice(0, 80)}`);
  const panels = read("app/marketing/marketing-panels.tsx");
  for (const card of ["FunnelCard", "PerformanceCard", "AttributionCard"]) {
    const body = panels.slice(panels.indexOf(`export function ${card}`), panels.indexOf("<CardContent", panels.indexOf(`export function ${card}`)));
    assert.match(body, /<DataProvenanceBadge status="demo"/, `${card} no dice que es de demostración`);
  }
});

test("las certificaciones y los documentos de Legal salen de una matriz de demostración y lo dicen", () => {
  const legal = read("app/legal/legal-workspace.tsx");
  for (const label of ["Certificaciones", "Evidencias documentales"]) {
    const start = legal.indexOf(`label="${label}"`);
    assert.notEqual(start, -1, `Legal ya no tiene «${label}»`);
    const next = legal.indexOf("<KpiCard", start);
    assert.match(legal.slice(start, next === -1 ? legal.length : next), /provenance="demo"/, `«${label}» sin DEMO`);
  }
  assert.ok(!/PREPARADO PARA LANZAMIENTO/.test(legal), "Legal vuelve a decir «preparado para lanzamiento» de una matriz de demostración");
});

test("toda pantalla gobernada que usa datos de demostración lo dice en un texto o en una insignia", () => {
  for (const file of GOVERNED.filter((candidate) => candidate.endsWith(".tsx") && !candidate.startsWith("components/"))) {
    const code = stripComments(read(file));
    const usesDemo = /from "@\/lib\/demo\/|\bisDemo\b|\bDEMO_[A-Z_]+/.test(code);
    if (!usesDemo) continue;
    assert.ok(/status=(\{[^}]*)?"demo"|provenance=(\{[^}]*)?"demo"|[Dd]emostración|\(demo\)/.test(code), `${file} usa datos de demostración y no los rotula`);
  }
});

// --- 5. PLAN, declarado, registro: nada se mezcla ni sube de nivel ----------------------------------------------------------------

test("el CFO enseña tres zonas distintas —Registro verificado, Declarado y PLAN— y cada una lleva su procedencia", () => {
  const workspace = stripComments(read("app/cfo/cfo-workspace.tsx"));
  assert.match(workspace, /title=\{`Registro verificado · \$\{period\}`\} provenance="verified"/);
  assert.match(workspace, /title=\{`Coste y margen declarados · \$\{period\}`\} provenance="declared"/);
  assert.match(workspace, /title="Proyección \(PLAN\)" provenance="planned"/);
  assert.equal((workspace.match(/<ZoneHeading /g) ?? []).length, 3);
});

test("la proyección de un proyecto es PLAN, no lleva símbolo monetario y no se llama beneficio real", () => {
  assert.doesNotMatch(formatPlanAmount(1234.5), /[€$£¥]|EUR|USD/);
  const decision = {
    evidence: [{ source: "finance_validation", summary: "", data: { monthly_profit: 820.25, margin: 0.31 } }],
  } as unknown as Decision;
  assert.deepEqual(Object.keys(projectedFinance(decision) ?? {}).sort(), ["margin", "monthlyProfit"]);
  for (const file of ["app/projects/projects-panels.tsx", "app/projects/projects-workspace.tsx", "lib/projects-view.ts", "lib/projects.ts"]) {
    for (const text of visibleTexts(read(file))) assert.ok(!/beneficio real|ingresos? reales?|ventas? reales?/i.test(text.replace(/Beneficio, ingresos y ventas por proyecto/, "")), `${file}: ${text.slice(0, 120)}`);
  }
});

test("la proyección de Proyectos se rotula PLAN en la cartera y en el detalle, y no queda ninguna columna de PLAN sin su insignia", () => {
  const workspace = read("app/projects/projects-workspace.tsx");
  const cartera = workspace.slice(workspace.indexOf("<CardTitle>Cartera</CardTitle>"), workspace.indexOf("<CardTitle>Proyectos por estado</CardTitle>"));
  assert.match(cartera, /status="planned"/, "la cartera ya no rotula su columna de proyección como PLAN");
  assert.match(cartera, /Proyección \(PLAN\)/, "la columna ya no se llama «Proyección (PLAN)»");
  assert.match(read("app/projects/projects-panels.tsx"), /<DataProvenanceBadge status="planned" tooltip=\{PLAN_NOTE\} \/>/);
});

test("la vista previa de la tienda dice que las reseñas, los distintivos, las páginas y las pruebas A/B son de ejemplo", () => {
  const builder = stripComments(read("app/ecommerce/store-builder.tsx"));
  assert.match(builder, /reseñas de ejemplo\)/);
  assert.match(builder, /De ejemplo:/);
  assert.ok((builder.match(/<DataProvenanceBadge status="demo"/g) ?? []).length >= 2, "las pestañas de páginas y de pruebas A/B no llevan su insignia DEMO");
});

test("los ingresos del Panel hablan de hechos de pago registrados, no de una transacción comercial real", () => {
  const forbidden = /venta real|transacci[oó]n (comercial )?real|compra real|dinero real|cliente real|ingresos? reales?/i;
  for (const file of ["app/dashboard/dashboard-workspace.tsx", "app/dashboard/revenue-panels.tsx", "app/dashboard/copy.ts"]) {
    for (const text of visibleTexts(read(file))) assert.ok(!forbidden.test(text), `${file}: ${text.slice(0, 140)}`);
  }
});

// --- 6. Un error o una lectura sin hacer no es «Sin datos» -----------------------------------------------------------------------

test("un proyecto con lecturas fallidas dice «No se pudo leer», no «Sin datos»", () => {
  const project: Project = { id: "p-1", objective_id: "o-1", name: "Proyecto", status: "VALIDATING", created_at: "2026-09-12T10:00:00Z" };
  const source: ProjectSource = {
    project,
    tasks: [] as Task[],
    decision: null as Decision | null,
    audit: [] as AuditEntry[],
    unread: ["tasks", "decision", "audit"],
  };
  const card = projectCard(source);
  assert.equal(card.planAbsence, "decision_unread");
  assert.match(PLAN_ABSENCE_TEXT.decision_unread, /No se pudo leer/);
  assert.notEqual(UNREAD, NO_DATA);
  assert.deepEqual([...card.unread].sort(), ["audit", "decision", "tasks"]);
  assert.doesNotMatch(PLAN_ABSENCE_TEXT.decision_unread, new RegExp(NO_DATA, "i"));
});
