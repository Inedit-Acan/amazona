import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  CEO_NARROW_MAX_PX,
  CEO_NARROW_QUERY,
  CEO_PANEL_MIN_PX,
  CEO_PANEL_QUERY,
  CEO_PANEL_REM,
  CEO_TRIPTYCH_MIN_PX,
} from "./ceo-layout.ts";

// El contrato del layout del Director ejecutivo (M47, Commit 2): columna del CEO IA persistente desde 1440 px, drawer por debajo,
// tres tarjetas desde 1280 y pestañas por debajo. Tailwind necesita las clases literales; estas pruebas las atan a las constantes.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8").replace(/\r\n/g, "\n");
const CEO_FILES = readdirSync(join(ROOT, "components/ceo")).filter((name) => name.endsWith(".tsx")).map((name) => `components/ceo/${name}`);

test("los umbrales son los aprobados: panel desde 1440, tarjetas desde 1280 (xl de Tailwind), grafo 2D bajo 768", () => {
  assert.equal(CEO_PANEL_MIN_PX, 1440);
  assert.equal(CEO_PANEL_REM, 20);
  assert.equal(CEO_TRIPTYCH_MIN_PX, 1280);
  assert.equal(CEO_NARROW_MAX_PX, 767);
  assert.equal(CEO_PANEL_QUERY, "(min-width: 1440px)");
  assert.equal(CEO_NARROW_QUERY, "(max-width: 767px)");
});

test("las clases `min-[…px]:` de los componentes usan SOLO el umbral del panel", () => {
  const found = new Set<string>();
  for (const file of CEO_FILES) for (const match of read(file).matchAll(/min-\[(\d+)px\]:/g)) found.add(match[1]);
  assert.deepEqual([...found], [String(CEO_PANEL_MIN_PX)], "hay un umbral de panel distinto de CEO_PANEL_MIN_PX");
});

test("desktop ≥1440 conserva la columna del CEO IA: rejilla de dos zonas, 20 rem, pegajosa, y por debajo oculta", () => {
  const layout = read("components/ceo/ceo-layout.tsx");
  assert.match(layout, new RegExp(`min-\\[${CEO_PANEL_MIN_PX}px\\]:grid-cols-\\[minmax\\(0,1fr\\)_${CEO_PANEL_REM}rem\\]`));
  assert.match(layout, /<aside\b[^>]*className="hidden min-\[1440px\]:[^"]*sticky/, "la columna es un aside oculto por debajo de 1440 y pegajoso desde 1440");
  assert.match(layout, /min-\[1440px\]:block/);
});

test("por debajo de 1440 el CEO IA es un drawer: botón en la cabecera solo bajo el umbral, y el drawer usa la misma consulta", () => {
  const header = read("components/ceo/ceo-header.tsx");
  assert.match(header, /min-\[1440px\]:hidden[^>]*onClick=\{openAssistant\}/);
  const drawer = read("components/ceo/assistant-drawer.tsx");
  assert.match(drawer, /CEO_PANEL_QUERY/);
  assert.match(drawer, /<Sheet\b/);
  assert.match(drawer, /if \(wide && open\) setOpen\(false\)/, "un drawer abierto se cierra al ensanchar la ventana");
  assert.match(drawer, /open=\{open && !wide\}/);
});

test("Decisiones / Oportunidades / Riesgos: tres tarjetas desde xl y pestañas por debajo, por CSS (sin medir en JavaScript)", () => {
  const triptych = read("components/ceo/decision-triptych.tsx");
  assert.match(triptych, /hidden gap-4 xl:grid xl:grid-cols-3/);
  assert.match(triptych, /<Tabs\b[^>]*className="xl:hidden"/);
  assert.doesNotMatch(triptych, /useMediaQuery|window\.|innerWidth/);
});

test("KPI: 1 columna, 2×2 desde sm y 4 columnas desde xl; la fila inferior 1 → 2 → 3", () => {
  assert.match(read("components/ceo/kpi-row.tsx"), /grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4/);
  assert.match(read("components/ceo/bottom-row.tsx"), /grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3/);
});

test("el HUD y la leyenda del grafo solo se superponen desde xl (o a pantalla completa): por debajo fluyen bajo el lienzo", () => {
  const graph = read("components/neural-nexus/neural-nexus-graph.tsx");
  assert.match(graph, /xl:pointer-events-none xl:absolute xl:inset-0/);
  assert.match(graph, /xl:h-\[24rem\]/);
  assert.match(graph, /CEO_NARROW_QUERY/, "bajo 768 px el grafo se abre en 2D");
});

test("el layout no depende del shell: ningún componente del Director ejecutivo lo importa", () => {
  for (const file of [...CEO_FILES, "app/ceo/page.tsx"]) assert.doesNotMatch(read(file), /@\/components\/shell|\.\/shell["']/, file);
});
