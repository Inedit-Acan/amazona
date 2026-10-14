import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// Frontera del Director ejecutivo (M47, Commit 2). Fija POR CÓDIGO FUENTE lo que este commit se compromete a no hacer:
// inventar datos, simular un CEO IA que no existe, tragarse un error de lectura o duplicar la acción de «Vista completa».
// Son pruebas de texto sobre el código, deliberadamente: lo que impiden es una línea concreta.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
/** Quita los comentarios: se prohíbe CÓDIGO y texto visible, no que un comentario explique por qué ya no existe. */
const code = (file: string) => read(file).replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

const CEO_DIR = readdirSync(join(ROOT, "components/ceo")).filter((name) => /\.tsx?$/.test(name)).map((name) => `components/ceo/${name}`);
const CEO_FILES = ["app/ceo/page.tsx", ...CEO_DIR, "lib/ceo-handoff.ts", "lib/ceo-blocks.ts", "lib/ceo-mission-view.ts", "lib/ceo-fullscreen.ts", "lib/ceo-layout.ts"];

test("la página es un Server Component que solo compone: sin «use client», sin lecturas y sin datos", () => {
  const page = code("app/ceo/page.tsx");
  assert.doesNotMatch(read("app/ceo/page.tsx"), /["']use client["']/);
  assert.doesNotMatch(page, /\.catch\s*\(|await |fetch\(|api\./);
  for (const part of ["CeoProvider", "CeoHeader", "CeoLayout", "KpiRow", "DecisionTriptych", "AgentNetworkCard", "BottomRow", "MissionDrawer", "AssistantDrawer"]) {
    assert.match(page, new RegExp(`<${part}\\b`), `${part} falta en la página`);
  }
});

test("el formulario de misión sigue ahí: «Crear misión», con su clave de intención (REG-01)", () => {
  assert.match(code("components/ceo/ceo-header.tsx"), /Crear misión/);
  const form = code("components/ceo/mission-form.tsx");
  assert.match(form, /OPERATIONS\.objectiveRun/);
  assert.match(form, /intent\.run\(/);
  assert.match(form, /api\.createObjective\(/);
  assert.match(form, /api\.runObjective\(/);
});

test("nada del Director ejecutivo importa datos de demostración", () => {
  for (const file of CEO_FILES) assert.doesNotMatch(read(file), /lib\/demo\/|\.\/demo\//, `${file} importa lib/demo`);
});

test("no hay filas inventadas del antiguo «Resumen de la misión» ni el «4 agentes…» obsoleto", () => {
  const invented = [
    /Agentes implicados/,
    /4 \+ Decision Engine/,
    /Riesgo estimado/,
    /Ejecución estimada/,
    /Resultado esperado/,
    /Sin coste \(simulado\)/,
    /Notificaciones/,
    /Al completar/,
    /Parámetros de agentes/,
    /\b4 agentes\b/i,
    /Fase 3/,
    /Market Analyst/,
  ];
  for (const file of CEO_FILES) {
    const source = code(file);
    for (const pattern of invented) assert.doesNotMatch(source, pattern, `${file} vuelve a decir ${pattern}`);
  }
});

test("no hay ningún dato de ejemplo como si fuera de la empresa: ni título ni solicitante inventados", () => {
  for (const file of CEO_FILES) {
    assert.doesNotMatch(code(file), /earbuds|owner@amazona|AMZ-2026|Alibaba|Auriculares inal/i, file);
  }
  assert.doesNotMatch(code("components/ceo/mission-form.tsx"), /useState\(["']owner/);
});

test("los KPI sin fuente no muestran 0, ni importes, ni porcentajes, ni tendencias", () => {
  const row = code("components/ceo/kpi-row.tsx");
  assert.doesNotMatch(row, /value=["'{]\s*[\d€$]|["'][\d.,]+\s?(%|€)|toFixed|formatEuro|formatPercent|Sparkline|sparkline/);
  // Ingresos tiene una fuente potencial aún sin leer (`unread`); los otros tres no tienen fuente (`unavailable`).
  assert.match(row, /key: "ingresos", label: "Ingresos", state: NOT_CONNECTED_YET/);
  for (const label of ["Beneficio", "Margen neto", "Cash disponible"]) {
    assert.match(row, new RegExp(`label: "${label}",?\\s*(?:\\n\\s*)?state: unavailableState\\(`), `${label} debe ser «no disponible»`);
  }
});

test("«sin leer» y «no disponible» no se mezclan: los bloques con fuente potencial son `unread`, los que no tienen fuente `unavailable`", () => {
  for (const file of ["components/ceo/decision-triptych.tsx", "components/ceo/bottom-row.tsx"]) {
    assert.doesNotMatch(code(file), /kind:\s*["']empty["']|kind:\s*["']loaded["']|\bempty\b.*NOT_CONNECTED/, `${file} presenta un bloque sin leer como vacío o cargado`);
  }
  assert.match(code("components/ceo/bottom-row.tsx"), /title="Próximos hitos" state=\{unavailableState\(/);
  assert.match(code("components/ceo/bottom-row.tsx"), /title="Actividad reciente"\s+state=\{NOT_CONNECTED_YET\}/);
  assert.match(code("components/ceo/decision-triptych.tsx"), /key: "decisiones", title: "Decisiones pendientes", tab: "Decisiones", state: NOT_CONNECTED_YET/);
});

test("un error de lectura no se convierte en dato ni en demostración: el aviso del bloque lo dice", () => {
  const card = code("components/ceo/block-card.tsx");
  assert.match(card, /error: \{ icon: TriangleAlert/);
  assert.match(card, /state\.kind === "loaded" \? children : <BlockNotice/);
});

/** Lo que el panel del CEO IA no puede decir mientras no exista un servicio real de conversación o de voz. Es una constante con su
 * propia prueba (abajo) porque una expresión regular rota no falla: simplemente no comprueba nada. */
const FORBIDDEN_ASSISTANT_TEXT = /\bonline\b|escuchando|hablando|waveform|\bondas?\b|respuesta del ceo/i;

test("el patrón de lo prohibido en el CEO IA SÍ reconoce lo que dice prohibir (y no lo que está permitido)", () => {
  for (const forbidden of ["Online", "online", "Escuchando…", "Estás hablando", "waveform", "ondas", "una onda", "Respuesta del CEO"]) {
    assert.match(forbidden, FORBIDDEN_ASSISTANT_TEXT, `no reconoce «${forbidden}»`);
  }
  for (const allowed of ["No disponible", "Chat no disponible", "Voz", "Pantalla", "Asistente del Director ejecutivo", "ni historial", "ondulado"]) {
    assert.doesNotMatch(allowed, FORBIDDEN_ASSISTANT_TEXT, `reconoce «${allowed}», que está permitido`);
  }
  assert.doesNotMatch(FORBIDDEN_ASSISTANT_TEXT.source, /[\u0000-\u001f]/, "la expresión lleva un carácter de control");
});

test("el CEO IA no dice «Online», «Escuchando», ni enseña ondas, mensajes, historial ni micrófono activo", () => {
  const panel = code("components/ceo/ceo-assistant-panel.tsx");
  assert.doesNotMatch(panel, FORBIDDEN_ASSISTANT_TEXT);
  assert.doesNotMatch(panel, /animate-|<canvas|<svg|<audio|<video/, "una onda o un anillo animado fingirían que hay audio");
  assert.doesNotMatch(panel, /\bTú\b|CEO IA\s*19:|\d{2}:\d{2}/, "ningún mensaje ficticio con hora");
  assert.match(panel, /MicOff/, "el micrófono se enseña tachado");
  // El único `Mic` es el icono decorativo de la pestaña «Voz»; fuera de ella no hay ningún micrófono activo.
  const mics = [...panel.matchAll(/<Mic\b/g)].length;
  assert.equal(mics, 1, "no hay un micrófono activo");
  assert.match(panel, /<TabsTrigger value="voz"[^>]*>\s*<Mic aria-hidden/);
});

test("todo lo funcional del CEO IA está deshabilitado y dice «No disponible»", () => {
  const panel = code("components/ceo/ceo-assistant-panel.tsx");
  assert.match(panel, /<input[\s\S]*?\bdisabled\b/);
  const buttons = [...panel.matchAll(/<Button\b[^>]*>/g)].map((m) => m[0]);
  assert.ok(buttons.length >= 3);
  for (const button of buttons) assert.match(button, /\bdisabled\b/, `botón activo en el panel: ${button}`);
  assert.equal([...panel.matchAll(/<Unavailable>/g)].length, 3, "Chat, Voz y Pantalla");
  assert.match(panel, /No disponible/);
  for (const reason of ["chat", "voice", "screen"]) assert.match(panel, new RegExp(`ASSISTANT_REASONS\\.${reason}`));
});

test("ningún componente del Director ejecutivo toca micrófono, audio, reconocimiento de voz ni captura de pantalla", () => {
  for (const file of CEO_FILES) {
    assert.doesNotMatch(code(file), /getUserMedia|getDisplayMedia|MediaRecorder|AudioContext|SpeechRecognition|speechSynthesis|WebSocket|EventSource/, file);
  }
});

test("«Vista completa» y «Abrir vista completa» comparten la MISMA acción: un único botón y una única llamada a la pantalla completa", () => {
  const header = code("components/ceo/ceo-header.tsx");
  const card = code("components/ceo/agent-network-card.tsx");
  assert.match(header, /<FullscreenButton label=\{FULLSCREEN_LABEL\}/);
  assert.match(card, /<FullscreenButton label=\{FULLSCREEN_CARD_LABEL\}/);
  const button = code("components/ceo/fullscreen-button.tsx");
  assert.match(button, /onClick=\{openGraphFullscreen\}/);
  assert.match(button, /disabled=\{blocked\}/);
  assert.match(button, /title=\{fullscreenBlocker \?\? undefined\}/);
  // La acción vive en el contexto y llama al asa del grafo; no hay otra implementación de pantalla completa.
  assert.match(code("components/ceo/ceo-context.tsx"), /graphRef\.current\?\.toggleFullscreen\(\)/);
  const callers: string[] = [];
  for (const dir of ["app", "components"]) {
    const walk = (directory: string) => {
      for (const entry of readdirSync(join(ROOT, directory), { withFileTypes: true })) {
        const path = `${directory}/${entry.name}`;
        if (entry.isDirectory()) walk(path);
        else if (/\.tsx?$/.test(entry.name) && /requestFullscreen\s*\?*\.?\(/.test(code(path))) callers.push(path);
      }
    };
    walk(dir);
  }
  assert.deepEqual(callers, ["components/neural-nexus/neural-nexus-graph.tsx"], "solo el grafo pide la pantalla completa");
  assert.doesNotMatch([header, card].join("\n"), /requestFullscreen|href="\/ceo\/|router\.push\(["']\/ceo\//, "no hay una ruta duplicada ni otra pantalla completa");
});

test("sin Fullscreen API el botón queda deshabilitado con texto accesible; no se simula nada", () => {
  const button = code("components/ceo/fullscreen-button.tsx");
  assert.match(button, /aria-describedby=\{blocked \? noteId : undefined\}/);
  assert.match(button, /className="sr-only"/);
  assert.match(code("lib/ceo-fullscreen.ts"), /Vista completa no disponible en este navegador/);
  assert.match(code("components/ceo/ceo-context.tsx"), /fullscreenSupported\(document\)/);
});

test("las tres lecturas silenciosas de /ceo desaparecieron y no pueden volver", () => {
  const swallow = /\.catch\s*\(\s*(?:\(\s*\)|\w+)\s*(?::\s*[^)]*)?=>\s*(?:\[\]|null|undefined|0|\{\}|false)\s*\)/;
  for (const file of CEO_FILES) assert.doesNotMatch(code(file), swallow, `${file} vuelve a tragarse un error`);
  assert.doesNotMatch(code("components/ceo/mission-form.tsx"), /\.catch\(/);
  const ratchet = read("lib/read-boundary.test.ts");
  assert.doesNotMatch(ratchet, /"app\/ceo\/page\.tsx"\s*:/, "el trinquete ya no admite lecturas silenciosas en /ceo");
  assert.doesNotMatch(ratchet, /"components\/ceo\/[^"]*"\s*:\s*[1-9]/);
  // Las tres lecturas posteriores a una misión traen ahora su estado.
  const form = code("components/ceo/mission-form.tsx");
  assert.match(form, /readList\(\(\) => api\.listAgentExecutions\(\)/);
  assert.match(form, /readList\(\(\) => api\.listAgents\(\)/);
  assert.match(form, /settle\(\(\) => api\.getDecision\(/);
});

test("el estado de un formulario cerrado no se pierde: vive en el drawer, no en su contenido", () => {
  const drawer = code("components/ceo/mission-drawer.tsx");
  assert.match(drawer, /const mission = useMission\(initial\)/);
  assert.match(drawer, /<MissionForm mission=\{mission\} \/>/);
});

test("el selector temporal 7/14/30 NO está en el Commit 2: no aparenta cambiar datos que no cambia", () => {
  for (const file of CEO_DIR) assert.doesNotMatch(code(file), /PeriodSelect|7 días|14 días|30 días|dias=/, file);
});

// --- Bytes de control y finales de fichero (M47 · Commit 2, enmienda) -----------------------------------------------------------
// Un script de edición convirtió una vez `\b` (el límite de palabra de una expresión regular) en el carácter de retroceso 0x08, y dos
// alternativas de una prueba dejaron de comprobar nada sin que ninguna otra lo notara; otra edición dejó una línea en blanco al final
// de un fichero (`git diff --check` rc=2). Estas pruebas cierran esa clase de fallo: ningún fichero de código lleva bytes de control
// (salvo tabulador, salto de línea y retorno de carro) y los ficheros de este commit no terminan en una línea en blanco.

/** Los bytes de control (0x00–0x1F) que un fichero de texto no debe llevar. Tabulador, LF y CR son legítimos. */
function controlBytes(source: Uint8Array): number[] {
  return [...new Set(source)].filter((byte) => byte < 0x20 && byte !== 0x09 && byte !== 0x0a && byte !== 0x0d).sort((a, b) => a - b);
}

/** ¿El texto termina en una línea en blanco (más de un salto de línea final)? Es lo que `git diff --check` llama «new blank line at EOF». */
function endsWithBlankLine(text: string): boolean {
  return /\n[ \t]*\r?\n$/.test(text);
}

function sourceFilesUnder(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(join(ROOT, directory), { withFileTypes: true })) {
    const path = `${directory}/${entry.name}`;
    if (entry.isDirectory()) {
      if (entry.name !== "node_modules") found.push(...sourceFilesUnder(path));
    } else if (/\.tsx?$/.test(entry.name)) found.push(path);
  }
  return found;
}

/** Los ficheros que este commit crea o gobierna: el contenido de `components/ceo/`, los `lib/ceo-*`, el almacén de salud y el estado del backend. */
const COMMIT_FILES = [
  ...CEO_FILES,
  ...readdirSync(join(ROOT, "lib")).filter((name) => /^ceo-.*\.tsx?$/.test(name) || /^backend-health-store(\.test)?\.ts$/.test(name)).map((name) => `lib/${name}`),
  "components/backend-status.tsx",
  "components/use-backend-health.ts",
  "components/use-media-query.ts",
];

test("el detector de bytes de control reconoce un 0x08 y deja pasar tabulador, LF y CR", () => {
  assert.deepEqual(controlBytes(new TextEncoder().encode("a\tb\r\nc\n")), []);
  assert.deepEqual(controlBytes(Uint8Array.from([0x2f, 0x08, 0x6f, 0x00, 0x1b])), [0x00, 0x08, 0x1b]);
  assert.deepEqual(controlBytes(new TextEncoder().encode("/\\bonline\\b/")), [], "`\\b` escrito como texto de regex es correcto");
});

test("el detector de línea en blanco final reconoce lo que `git diff --check` rechaza", () => {
  assert.equal(endsWithBlankLine("a\n"), false);
  assert.equal(endsWithBlankLine("a\r\n"), false);
  assert.equal(endsWithBlankLine("a\n\n"), true);
  assert.equal(endsWithBlankLine("a\r\n\r\n"), true);
  assert.equal(endsWithBlankLine("a\n  \n"), true);
});

test("ningún fichero de código de la aplicación lleva bytes de control (un 0x08 convertiría `\\b` en una expresión que no comprueba nada)", () => {
  const offenders: string[] = [];
  for (const file of ["app", "components", "lib"].flatMap(sourceFilesUnder)) {
    const bytes = controlBytes(readFileSync(join(ROOT, file)));
    if (bytes.length > 0) offenders.push(`${file}: ${bytes.map((byte) => `0x${byte.toString(16).padStart(2, "0")}`).join(", ")}`);
  }
  assert.deepEqual(offenders, []);
});

test("los ficheros de este commit no terminan en una línea en blanco y acaban en un salto de línea", () => {
  assert.ok(COMMIT_FILES.length >= 30, "la lista de ficheros del commit se ha vaciado");
  const offenders: string[] = [];
  for (const file of COMMIT_FILES) {
    const text = readFileSync(join(ROOT, file), "utf8");
    if (endsWithBlankLine(text)) offenders.push(`${file}: línea en blanco al final`);
    else if (!/\n$/.test(text)) offenders.push(`${file}: no termina en un salto de línea`);
  }
  assert.deepEqual(offenders, []);
});
