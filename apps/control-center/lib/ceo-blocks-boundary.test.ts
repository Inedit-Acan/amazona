import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// FRONTERA de los tres bloques ejecutivos del Director ejecutivo (M47, Commit 3B): Decisiones pendientes, Candidatos detectados e
// Incidencias activas. Son pruebas de texto sobre el código, deliberadamente: lo que impiden es una línea concreta. Fijan que los
// bloques solo leen datos REALES de sus fuentes, que cada interpretación vive en SU módulo (y solo en él), que nada es de demostración
// ni del mockup, y que los dos rótulos aprobados no vuelven a decir «Oportunidades» ni «Riesgos».

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
const code = (file: string) => stripComments(read(file));

const DECISIONS = "lib/ceo-decisions.ts";
const CANDIDATES = "lib/ceo-opportunities.ts";
const RISKS = "lib/ceo-risks.ts";
const VIEW = "lib/ceo-block-view.ts";
const CONTRACTS = "lib/ceo-block-contracts.ts";
const READS = "lib/ceo-block-reads.ts";
const ROWS = "components/ceo/block-rows.tsx";
const TRIPTYCH = "components/ceo/decision-triptych.tsx";
const CARD = "components/ceo/block-card.tsx";

const DOMAIN = [DECISIONS, CANDIDATES, RISKS];
const BLOCK_FILES = [...DOMAIN, VIEW, CONTRACTS, READS, ROWS, TRIPTYCH, CARD];

test("la prueba ve los ficheros que tiene que vigilar", () => {
  for (const file of BLOCK_FILES) assert.ok(read(file).length > 100, `${file} no existe o está vacío`);
});

// --- Nada de demostración, nada del mockup, nada silencioso ---------------------------------------------------------------------

test("ningún fichero de los bloques importa datos de demostración ni la vista antigua del Panel", () => {
  for (const file of BLOCK_FILES) {
    assert.doesNotMatch(read(file), /lib\/demo\/|\.\/demo\/|\.\.\/demo\//, `${file} importa lib/demo`);
    assert.doesNotMatch(code(file), /\b(requestFromApproval|requestFromReview|decisionsView|decisionsKpiView|buildRows|isDemo|demoRequests|opportunitiesView|approvals-view|dashboard-view)\b/, `${file} usa la vista antigua o de demostración`);
  }
});

test("ninguna lectura traga un error: ni `.catch(() => [])` ni `.catch(` alguno", () => {
  for (const file of BLOCK_FILES) assert.doesNotMatch(code(file), /\.catch\s*\(/, `${file} traga un error`);
});

test("ningún literal del mockup, ni ejemplo de datos de la empresa, en ningún fichero de los bloques", () => {
  const mockup =
    /Alibaba|Aprobar proveedor|Revisar campa[nñ]a Meta|Lanzar producto X|producto X|Demanda creciente|Nuevo mercado|Tendencia emergente|Riesgo log[ií]stico|Margen descendente|Cambios regulatorios|Normativa UE|Proveedor actual \(China\)|Auriculares inal|Accesorios sostenibles|earbuds|owner@amazona|AMZ-2026/i;
  for (const file of BLOCK_FILES) assert.doesNotMatch(code(file), mockup, `${file} lleva un texto del mockup`);
  // `Meta` como nombre propio de la campaña del mockup (no como palabra suelta en «metadatos»).
  for (const file of BLOCK_FILES) assert.doesNotMatch(code(file), /["'`]Meta["'`]|Campa[nñ]a Meta/, file);
});

test("ninguna cifra de ejemplo hardcodeada: los bloques no escriben contadores ni importes literales", () => {
  for (const file of [...DOMAIN, ROWS, TRIPTYCH]) {
    assert.doesNotMatch(code(file), /\bcount:\s*\d|\bcountText:\s*["'`]\d|["'`]\d+ (candidatos|incidencias|decisiones)["'`]/, `${file} escribe un contador`);
  }
});

// --- Rótulos aprobados ---------------------------------------------------------------------------------------------------------

test("los tres rótulos aprobados: «Decisiones pendientes», «Candidatos detectados» e «Incidencias activas»", () => {
  assert.match(code(DECISIONS), /title: "Decisiones pendientes"/);
  assert.match(code(CANDIDATES), /title: "Candidatos detectados"/);
  assert.match(code(RISKS), /title: "Incidencias activas"/);
  const triptych = code(TRIPTYCH);
  for (const block of ["DECISIONS_BLOCK", "CANDIDATES_BLOCK", "INCIDENTS_BLOCK"]) assert.match(triptych, new RegExp(`\\b${block}\\b`), `${block} no se usa en el tríptico`);
});

test("ningún fichero de los bloques dice «Oportunidades detectadas», «Riesgos activos» ni «Sin riesgos»", () => {
  for (const file of BLOCK_FILES) {
    assert.doesNotMatch(code(file), /Oportunidades detectadas/, `${file}: el bloque de candidatos no puede llamarse así`);
    assert.doesNotMatch(code(file), /Riesgos activos|Sin riesgos|sin riesgos/, `${file}: el bloque de incidencias no puede llamarse así ni decir esto`);
  }
});

test("las palabras «oportunidad», «validada», «confirmada», score, demanda o tendencia no existen en el código de los bloques, salvo la línea secundaria fija", () => {
  const FOOTNOTE = 'Oportunidades validadas: no disponibles';
  assert.ok(code(CANDIDATES).includes(FOOTNOTE), "falta la línea secundaria aprobada");
  for (const file of BLOCK_FILES) {
    const text = code(file).replace(FOOTNOTE, "");
    assert.doesNotMatch(text, /oportunidad|validad[ao]s?\b|confirmad[ao]s?|\bscore\b|opportunity_score|demanda|tendencia/i, `${file} insinúa una oportunidad validada`);
  }
});

test("«Registrado» es el badge visible; «Verificado» queda reservado a los hechos contables", () => {
  assert.match(code(VIEW), /RECORDED_LABEL = "Registrado"/);
  for (const file of BLOCK_FILES) assert.doesNotMatch(code(file), /["'`]Verificad[oa]s?["'`]|status="(verified|ledger)"/, `${file} usa «verificado» para un dato registrado`);
});

// --- Prioridad y severidad -----------------------------------------------------------------------------------------------------

test("no existe ninguna prioridad: ni la palabra, ni un campo, ni una insignia «Alta/Media/Baja» fuera de la tabla de severidad real de las incidencias", () => {
  for (const file of BLOCK_FILES) assert.doesNotMatch(code(file), /\bpriority\b|prioridad|SEVERITY_ORDER|\bSLA_HOURS\b/i, `${file}: prioridad`);
  for (const file of BLOCK_FILES.filter((f) => f !== RISKS)) {
    assert.doesNotMatch(code(file), /["'`](Alta|Media|Baja|Crítica)["'`]|\b(Alta|Media|Baja|Crítica)\b/, `${file} nombra una severidad fuera de ceo-risks.ts`);
  }
  // En ceo-risks.ts, la tabla de traducción de la severidad REAL es la única mención.
  const risks = code(RISKS);
  assert.match(risks, /LOW: "Baja"/);
  assert.match(risks, /MEDIUM: "Media"/);
  assert.match(risks, /HIGH: "Alta"/);
  assert.match(risks, /CRITICAL: "Crítica"/);
  assert.equal([...risks.matchAll(/["'`](Alta|Media|Baja|Crítica)["'`]/g)].length, 4, "solo la tabla nombra severidades");
});

test("la severidad desconocida es un contrato roto: nunca un valor por defecto (`?? \"MEDIUM\"` y similares no existen)", () => {
  for (const file of [RISKS, CONTRACTS, VIEW]) assert.doesNotMatch(code(file), /\?\?\s*["'`](MEDIUM|HIGH|LOW|CRITICAL|Media|Alta|Baja)["'`]|\|\|\s*["'`](MEDIUM|Media)["'`]|default:\s*return\s*["'`]Media/, file);
  assert.match(code(CONTRACTS), /SEVERITIES/);
});

// --- Kill switch: polaridad ----------------------------------------------------------------------------------------------------

test("el kill switch avisa con `enabled === false` y NUNCA con `enabled === true`", () => {
  const risks = code(RISKS);
  assert.match(risks, /killSwitch\.data\.enabled === false|\.enabled === false/);
  assert.doesNotMatch(risks, /enabled === true|enabled !== false|=== true/);
  assert.doesNotMatch(risks, /!\s*\w*\.?enabled\b(?!\s*===)/, "no se niega `enabled` por su cuenta");
});

// --- Cada interpretación en SU módulo ------------------------------------------------------------------------------------------

test("los tres módulos de dominio son independientes: no se importan entre sí ni comparten reglas; solo comparten la mecánica", () => {
  for (const file of DOMAIN) {
    const imports = [...code(file).matchAll(/from "([^"]+)"/g)].map((m) => m[1]);
    for (const other of ["ceo-decisions", "ceo-opportunities", "ceo-risks"]) {
      if (file.includes(other)) continue;
      assert.ok(!imports.some((spec) => spec.includes(other)), `${file} importa ${other}`);
    }
    assert.ok(imports.includes("./ceo-block-view.ts"), `${file} no usa la mecánica común`);
  }
});

test("la mecánica común no interpreta: ni estados de aprobación, ni CANDIDATE, ni severidades, ni kill switch", () => {
  assert.doesNotMatch(code(VIEW), /PENDING|ACTION_GATE|POST_HOC|CANDIDATE|OPEN|LOW|MEDIUM|HIGH|CRITICAL|enabled|approval|incident|product/);
});

test("las reglas de significado de cada bloque están solo en su módulo", () => {
  assert.match(code(DECISIONS), /ACTION_GATE/);
  assert.match(code(DECISIONS), /POST_HOC/);
  for (const file of [CANDIDATES, RISKS, VIEW, ROWS, TRIPTYCH]) assert.doesNotMatch(code(file), /ACTION_GATE|POST_HOC|isActionable|isExpired/, `${file} interpreta decisiones`);
  assert.match(code(CANDIDATES), /CANDIDATE/);
  for (const file of [DECISIONS, RISKS, ROWS, TRIPTYCH]) assert.doesNotMatch(code(file), /\bCANDIDATE\b/, `${file} interpreta candidatos`);
  assert.match(code(RISKS), /"OPEN"/);
  for (const file of [DECISIONS, CANDIDATES, ROWS, TRIPTYCH]) assert.doesNotMatch(code(file), /\.severity\b|"OPEN"|\.enabled\b/, `${file} interpreta incidencias`);
});

test("ningún componente interpreta: el tríptico y las filas solo pintan lo que la vista ya decidió", () => {
  for (const file of [ROWS, TRIPTYCH, CARD]) {
    assert.doesNotMatch(code(file), /\.filter\(|\.sort\(|\.reduce\(|\.status\b|\.severity\b|\.kind === "(ACTION_GATE|POST_HOC)"|expires_at|created_at|parseUtc|Date\.now|new Date/, `${file} calcula o interpreta`);
  }
});

test("ni los módulos de dominio ni los componentes suman ni usan coma flotante con importes", () => {
  for (const file of [...DOMAIN, ROWS, TRIPTYCH]) assert.doesNotMatch(code(file), /\.reduce\(|\bparseFloat\b|\.toFixed\(|\bNumber\(/, `${file} hace aritmética`);
});

// --- Lecturas: cinco, una vez cada una, sin ventana -----------------------------------------------------------------------------

test("el lector hace exactamente cinco lecturas, una vez cada una, con `settle`/`readList` y sin ventana", () => {
  const reads = code(READS);
  for (const call of ["listApprovals", "listPipelineReviews", "listProducts", "listIncidents", "getPipelineKillSwitch"]) {
    assert.equal([...reads.matchAll(new RegExp(`source\\.${call}\\(`, "g"))].length, 1, `${call} debe leerse una vez`);
  }
  assert.match(reads, /readList\(/);
  assert.match(reads, /readOne\(/);
  assert.match(reads, /Promise\.all\(/);
});

test("el tríptico es un Server Component que lee UNA vez y entrega el mismo resultado a la rejilla y a las pestañas", () => {
  const source = read(TRIPTYCH);
  assert.doesNotMatch(source, /["']use client["']/);
  assert.match(source, /from "@\/lib\/api-server"/);
  assert.equal([...code(TRIPTYCH).matchAll(/readBlocksNow\(/g)].length, 1, "una sola lectura de los tres bloques");
  assert.match(code(READS), /export function readBlocksNow\(source: BlocksSource\)/);
  assert.match(code(TRIPTYCH), /<Suspense\b/);
  // La rejilla y las pestañas siguen siendo CSS, no JavaScript.
  assert.match(source, /hidden gap-4 xl:grid xl:grid-cols-3/);
  assert.match(source, /<Tabs\b[^>]*className="xl:hidden"/);
  assert.doesNotMatch(source, /useMediaQuery|window\.|innerWidth/);
});

// --- El selector 7/14/30 NO gobierna estos bloques ---------------------------------------------------------------------------------

test("el selector 7/14/30 no llega a los bloques: ni días, ni ventana, ni `?dias=`, ni PeriodSelect en ninguno de sus ficheros", () => {
  for (const file of BLOCK_FILES) {
    assert.doesNotMatch(code(file), /\b(dias|days|RevenueWindow|revenueWindow|parseRevenueDays|revenue-query|PeriodSelect|searchParams|useSearchParams)\b/, `${file} depende del periodo`);
  }
  const page = code("app/ceo/page.tsx");
  assert.match(page, /<DecisionTriptych \/>/, "el tríptico no recibe props");
  assert.match(page, /<KpiRow window=\{window\} days=\{days\} \/>/, "solo Ingresos recibe el periodo");
  assert.match(code(TRIPTYCH), /export function DecisionTriptych\(\)/);
});

// --- Cobertura de las fuentes: nada se lee de otra parte ------------------------------------------------------------------------

test("los bloques no leen nada de ingresos ni de agentes: cada bloque lee solo su fuente", () => {
  for (const file of [...DOMAIN, READS, VIEW, CONTRACTS]) assert.doesNotMatch(code(file), /revenueSummary|revenue-view|revenue-figures|listAgents|listPipelineRuns|listDecisions|getDecision\b/, `${file} lee una fuente que no es suya`);
});

test("el lector pide lo que dice: aprobaciones, revisiones, productos, incidencias y kill switch (y nada de /api/decisions por fila)", () => {
  assert.doesNotMatch(code(READS), /api\/decisions|projects|research\/runs/);
});
