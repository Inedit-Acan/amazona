import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { INGRESOS_CARD_MAX_PX, INGRESOS_LINES_MAX_REM } from "./ceo-kpis.ts";

// Frontera del Director ejecutivo (M47, Commit 2). Fija POR CÓDIGO FUENTE lo que este commit se compromete a no hacer:
// inventar datos, simular un CEO IA que no existe, tragarse un error de lectura o duplicar la acción de «Vista completa».
// Son pruebas de texto sobre el código, deliberadamente: lo que impiden es una línea concreta.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
/** Quita los comentarios: se prohíbe CÓDIGO y texto visible, no que un comentario explique por qué ya no existe. */
const code = (file: string) => read(file).replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

const CEO_DIR = readdirSync(join(ROOT, "components/ceo")).filter((name) => /\.tsx?$/.test(name)).map((name) => `components/ceo/${name}`);
const CEO_FILES = ["app/ceo/page.tsx", ...CEO_DIR, "lib/ceo-handoff.ts", "lib/ceo-blocks.ts", "lib/ceo-mission-view.ts", "lib/ceo-fullscreen.ts", "lib/ceo-layout.ts", "lib/ceo-kpis.ts"];

test("la página es un Server Component que solo compone: sin «use client», sin lecturas propias y sin datos; solo lee el periodo de la URL", () => {
  const page = code("app/ceo/page.tsx");
  assert.doesNotMatch(read("app/ceo/page.tsx"), /["']use client["']/);
  assert.doesNotMatch(page, /\.catch\s*\(|fetch\(|api\./);
  // El único `await` de la página es el de `searchParams` (el periodo); la lectura de ingresos la hace la tarjeta de Ingresos.
  assert.deepEqual([...page.matchAll(/await \w+/g)].map((m) => m[0]), ["await searchParams"]);
  assert.match(page, /parseRevenueDays\(\(await searchParams\)\.dias\)/);
  assert.match(page, /<KpiRow window=\{window\} days=\{days\} \/>/);
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

test("los KPI sin fuente no muestran 0, ni importes, ni porcentajes, ni tendencias; Ingresos es el único que lee", () => {
  const row = code("components/ceo/kpi-row.tsx");
  assert.doesNotMatch(row, /value=["'{]\s*[\d€$]|["'][\d.,]+\s?(%|€)|toFixed|formatEuro|formatPercent|Sparkline|sparkline/);
  // Los tres sin fuente salen de `lib/ceo-kpis.ts` como `unavailable`, y el de Ingresos es la tarjeta que lee.
  assert.match(row, /UNAVAILABLE_KPIS\.map\(/);
  assert.match(row, /<RevenueKpi window=\{window\} days=\{days\} \/>/);
  const lib = code("lib/ceo-kpis.ts");
  for (const label of ["Beneficio", "Margen neto", "Cash disponible"]) {
    assert.match(lib, new RegExp(`label: "${label}",\\s*state: unavailableState\\(`), `${label} debe ser «no disponible»`);
  }
  for (const file of ["lib/ceo-kpis.ts", "components/ceo/revenue-kpi.tsx"]) {
    assert.doesNotMatch(code(file), /Sparkline|sparkline|revenueSeries/, `${file}: sin sparkline hasta que se pueda dibujar un día sin actividad`);
  }
});

test("«sin leer» y «no disponible» no se mezclan: los bloques con fuente potencial son `unread`, los que no tienen fuente `unavailable`", () => {
  for (const file of ["components/ceo/decision-triptych.tsx", "components/ceo/bottom-row.tsx"]) {
    assert.doesNotMatch(code(file), /kind:\s*["']empty["']|kind:\s*["']loaded["']|\bempty\b.*NOT_CONNECTED/, `${file} presenta un bloque sin leer como vacío o cargado`);
  }
  assert.match(code("components/ceo/bottom-row.tsx"), /title="Próximos hitos" state=\{unavailableState\(/);
  // Desde el Commit 5 «Actividad registrada» y «Ejecuciones por área» SÍ leen su fuente (`readActivityNow`): ya no son `unread` por construcción.
  assert.doesNotMatch(code("components/ceo/bottom-row.tsx"), /NOT_CONNECTED_YET|unreadState\(/);
  assert.match(code("components/ceo/bottom-row.tsx"), /readActivityNow\(api\)/);
  // Desde el Commit 3B los tres bloques del tríptico SÍ leen su fuente: ya no son `unread` por construcción. Su estado sale de la lectura
  // (`readBlocksNow`) y se traduce con `blockStateOf`; «sin leer» solo existe si una lectura no se hizo, nunca como valor fijo.
  const triptych = code("components/ceo/decision-triptych.tsx");
  assert.doesNotMatch(triptych, /NOT_CONNECTED_YET|unreadState\(|unavailableState\(/);
  assert.match(triptych, /readBlocksNow\(api\)/);
  assert.match(triptych, /blockStateOf\(/);
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

test("Voz y Pantalla siguen deshabilitadas y dicen «No disponible»; el Chat es el chat real (M52)", () => {
  const panel = code("components/ceo/ceo-assistant-panel.tsx");
  const buttons = [...panel.matchAll(/<Button\b[^>]*>/g)].map((m) => m[0]);
  assert.ok(buttons.length >= 2);
  for (const button of buttons) assert.match(button, /\bdisabled\b/, `botón activo en el panel: ${button}`);
  assert.equal([...panel.matchAll(/<Unavailable>/g)].length, 2, "Voz y Pantalla");
  assert.match(panel, /No disponible|READ_UNAVAILABLE_VALUE/);
  for (const reason of ["voice", "screen"]) assert.match(panel, new RegExp(`ASSISTANT_REASONS\.${reason}`));
  assert.doesNotMatch(panel, /ASSISTANT_REASONS\.chat/, "el chat ya no es «no disponible»");
  assert.match(panel, /<TabsContent value="chat"[^>]*>\s*<CeoChat \/>/);
});

test("el chat con el CEO no confirma nada por su cuenta: confirmar y rechazar son solo los botones de una tarjeta", () => {
  const chat = code("components/ceo/ceo-chat.tsx");
  // La confirmación se hace en un único sitio, y solo la dispara el clic de «Confirmar».
  assert.equal([...chat.matchAll(/api\.confirmCeoAction\(/g)].length, 1);
  assert.equal([...chat.matchAll(/api\.rejectCeoAction\(/g)].length, 1);
  assert.match(chat, /onClick=\{\(\) => onConfirm\(proposal\)\}/);
  assert.match(chat, /onClick=\{\(\) => onReject\(proposal\)\}/);
  // El texto del modelo se enseña como TEXTO: ni HTML, ni evaluación, ni confirmar al recibir una respuesta.
  assert.doesNotMatch(chat, /dangerouslySetInnerHTML|innerHTML|\beval\(|new Function/);
  assert.doesNotMatch(chat, /useEffect\([^)]*confirm/);
  // La conversación vive en el servidor: nada de guardarla en el navegador.
  assert.doesNotMatch(chat, /localStorage|sessionStorage|indexedDB/);
  // Mismas palabras prohibidas que el panel (no finge audio ni presencia).
  assert.doesNotMatch(chat, FORBIDDEN_ASSISTANT_TEXT);
});

test("el chat enseña la tarjeta con motivo, efecto, riesgo, coste externo y Confirmar / Rechazar, y el estado «CEO analizando»", () => {
  const chat = code("components/ceo/ceo-chat.tsx");
  for (const piece of ["Confirmar", "Rechazar", "CEO analizando", "RISK_LABELS", "estimated_effects", "Coste externo", "costLabel", "sourcesLabel"]) {
    assert.match(chat, new RegExp(piece), piece);
  }
  assert.match(chat, /role="log"/);
  assert.match(chat, /data-chat-failure/, "si el modelo cae, el aviso está y el resto del panel sigue");
});

test("el chat con el CEO no tiene ningún control de voz", () => {
  const chat = code("components/ceo/ceo-chat.tsx");
  assert.doesNotMatch(chat, /\bMic\b|MicOff|voz|Voz|speech|audio/i);
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

// --- Ingresos y el selector 7 / 14 / 30 (M47 · Commit 3A) -------------------------------------------------------------------------

test("el selector 7/14/30 solo existe dentro de la tarjeta de Ingresos y ningún otro bloque depende del periodo", () => {
  const card = code("components/ceo/revenue-kpi.tsx");
  assert.match(card, /<PeriodSelect days=\{days\} \/>/);
  const dependsOnPeriod = /PeriodSelect|revenue-query|revenueWindow|parseRevenueDays|\bdays\b|\bdias\b|dias=/;
  const allowed = new Set(["components/ceo/revenue-kpi.tsx", "components/ceo/kpi-row.tsx", "app/ceo/page.tsx", "lib/ceo-kpis.ts"]);
  for (const file of CEO_FILES) {
    if (allowed.has(file)) continue;
    assert.doesNotMatch(code(file), dependsOnPeriod, `${file} depende del periodo de Ingresos`);
  }
  assert.doesNotMatch(code("components/ceo/ceo-header.tsx"), /PeriodSelect|\bdays\b/, "el selector no va en la cabecera: parecería gobernar todo");
  assert.equal(
    [...code("components/ceo/kpi-row.tsx").matchAll(/\bdays\b/g)].length,
    4,
    "kpi-row solo reenvía `days` a la tarjeta de Ingresos (su firma y la llamada a la tarjeta)",
  );
});

test("Ingresos se lee en el servidor con el token de la petición y sin tragarse el error", () => {
  const card = code("components/ceo/revenue-kpi.tsx");
  assert.match(card, /from "@\/lib\/api-server"/);
  assert.doesNotMatch(card, /from "@\/lib\/api"/);
  assert.match(card, /readIngresos\(api, window, days\)/);
  assert.doesNotMatch(read("components/ceo/revenue-kpi.tsx"), /["']use client["']/);
  const lib = code("lib/ceo-kpis.ts");
  assert.match(lib, /settle\(\(\) => source\.revenueSummary\(window\)\)/);
  assert.doesNotMatch(lib, /\.catch\s*\(|\?\?\s*0\b|\|\|\s*0\b|parseFloat|Number\(|toFixed/, "ni un cero por defecto ni un float");
});

test("la cifra de Ingresos sale de verified[]: nunca de consolidated_eur_by_origin ni de revenueKpis", () => {
  // Desde el Commit 3A.1 la cifra la construye el núcleo compartido (`lib/revenue-figures.ts`); `lib/ceo-kpis.ts` solo lo llama.
  const lib = code("lib/ceo-kpis.ts");
  const core = code("lib/revenue-figures.ts");
  assert.doesNotMatch(lib, /consolidated_eur|revenueKpis|summaryView/);
  assert.doesNotMatch(core, /consolidated_eur|revenueKpis|summaryView/);
  assert.match(lib, /revenueFigures\(settled\.data\)/);
  assert.match(core, /summary\.verified/);
  for (const file of ["components/ceo/revenue-kpi.tsx", "components/ceo/kpi-row.tsx"]) {
    assert.doesNotMatch(code(file), /consolidated_eur|revenueKpis|summaryView/, file);
  }
});

test("ninguna cifra del mockup aprobado aparece como dato de negocio en el Director ejecutivo", () => {
  const mockup = /184\.320|46\.280|25,1\s?%|128\.450|\+18\s?%|\+11\s?%|\+3,4\s?%|8,4 meses/;
  for (const file of CEO_FILES) assert.doesNotMatch(code(file), mockup, `${file} lleva una cifra del mockup`);
});

test("la tarjeta de Ingresos no elige una línea como principal cuando hay varias, ni suma, ni convierte", () => {
  const card = code("components/ceo/revenue-kpi.tsx");
  assert.match(card, /big=\{view\.lines\.length === 1\}/);
  assert.doesNotMatch(card, /\.reduce\(|\bsum\b|convert|Varios orígenes/i);
  // La cifra grande solo existe con UNA línea: `lines[0]` aparece una sola vez, dentro de esa rama.
  assert.equal([...card.matchAll(/lines\[0\]/g)].length, 1);
  assert.match(card, /view\.lines\.length === 1\) \{\s*return \(\s*<ul>\s*<Line line=\{view\.lines\[0\]\} big \/>/);
});

// --- Tarjeta compacta (M47 · 3A, ajuste visual): la altura no rompe la fila de KPI y NADA se esconde ------------------------------

test("la tarjeta de Ingresos es compacta: las líneas hacen scroll en un área de alto fijo atado a la constante, y lo de fuera de la cifra es un resumen", () => {
  const card = code("components/ceo/revenue-kpi.tsx");
  assert.equal(INGRESOS_LINES_MAX_REM, 6);
  assert.match(card, new RegExp(`max-h-\\[${INGRESOS_LINES_MAX_REM}rem\\]`));
  assert.ok(INGRESOS_CARD_MAX_PX <= 300, "el límite de altura de la tarjeta en desktop");
  // El área con scroll solo envuelve las líneas, y se alcanza y se ve con el teclado.
  assert.match(card, /tabIndex=\{0\}/);
  assert.match(card, /aria-label=\{`Ingresos por origen y moneda: \$\{linesCountText\(view\.lines\.length\)\}`\}/);
  assert.match(card, /focus-visible:ring-2/);
  // «Fuera de esta cifra» en la tarjeta es solo el resumen de una línea; las listas completas viven en el desglose.
  assert.match(card, /secondarySummary\(view\.secondary\)/);
  assert.doesNotMatch(card, /secondary\.underReview|secondary\.pending|secondary\.notes|\.pending\.map|\.underReview\.map/);

});

test("«Ver desglose» enseña TODAS las líneas y TODO lo de fuera de la cifra, se abre con el teclado y no suma", () => {
  const raw = read("components/ceo/revenue-breakdown.tsx");
  const breakdown = code("components/ceo/revenue-breakdown.tsx");
  assert.match(raw, /^"use client";/);
  // Un botón real (se abre con Intro o Espacio), dentro de un Sheet (foco atrapado, `Esc` cierra y devuelve el foco).
  assert.match(breakdown, /<SheetTrigger render=\{<Button type="button" variant="outline" size="xs" className="h-5 px-1\.5 text-\[11px\]" \/>\}>\s*Ver desglose\{view\.kind === "loaded" && view\.lines\.length > 1/);
  // Todas las líneas, con todos sus campos.
  assert.match(breakdown, /view\.lines\.map\(\(line\) => \(\s*<LineDetail key=\{line\.key\} line=\{line\} \/>/);
  for (const field of ["line.currency", "line.origin", "line.revenue", "line.refunds", "line.net", "line.captures", "line.refundCount"]) {
    assert.ok(breakdown.includes(field), `el desglose no enseña ${field}`);
  }
  // Y todo lo que queda fuera de la cifra, con sus importes y recuentos.
  for (const part of ["secondary.underReview.map", "secondary.pending.map", "secondary.notes.map", "secondary.pendingCount", "line.label", "line.amount", "line.count"]) {
    assert.ok(breakdown.includes(part), `el desglose no enseña ${part}`);
  }
  assert.match(breakdown, /<OutsideFigure secondary=\{view\.secondary\} \/>/);
  assert.doesNotMatch(breakdown, /\.reduce\(|\bsum\b|convert|Number\(|toFixed|parseFloat/i);
});

test("el modo compacto no deja ningún dato fuera: todo lo que la vista tiene está en la tarjeta o en el desglose", () => {
  const compact = code("components/ceo/revenue-kpi.tsx") + code("components/ceo/revenue-breakdown.tsx");
  const view = code("lib/revenue-figures.ts");
  // Cada campo de una línea del modelo se pinta en alguna de las dos superficies.
  for (const field of ["currency", "origin", "revenue", "refunds", "net", "captures", "refundCount"]) {
    assert.match(view, new RegExp(`\\b${field}[:,]`), `la vista ya no lleva ${field}`);
    assert.ok(compact.includes(`line.${field}`), `line.${field} no se enseña`);
  }
  // El botón existe siempre que haya algo más que la tarjeta: varias líneas o algo fuera de la cifra.
  assert.match(code("components/ceo/revenue-kpi.tsx"), /showBreakdown = view\.kind !== "error" && \(multi \|\| hasSecondary\(view\.secondary\)\)/);
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
  // M47 · Commit 3A.1: el núcleo compartido de los ingresos, sus primitivas de texto y sus pruebas.
  ...readdirSync(join(ROOT, "lib")).filter((name) => /^revenue-(figures|format|kpis|surfaces)(-boundary)?(\.test)?\.ts$/.test(name)).map((name) => `lib/${name}`),
  // M47 · Commit 4: la capa de datos, estado y HUD del Decision Engine (sin la escena 3D, que no se toca).
  ...readdirSync(join(ROOT, "lib")).filter((name) => /^nexus-(domains|mission|engine-state|honesty-boundary|test-support)(\.test)?\.ts$/.test(name) || /^nexus-(mission|engine-state)\.test\.ts$/.test(name)).map((name) => `lib/${name}`),
  "components/neural-nexus/neural-nexus-graph.tsx",
  "components/neural-nexus/nexus-hud.tsx",
  "components/neural-nexus/nexus-details.tsx",
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
