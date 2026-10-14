import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// Frontera de integridad del Director ejecutivo (M47, Commit 1). Fija POR CÓDIGO FUENTE las tres violaciones corregidas,
// para que no puedan volver sin que un test falle:
//   1. un error del backend no se convierte en una lista vacía ni en datos de demostración;
//   2. el estado de un agente no se traduce a estados que el backend no envía;
//   3. la cabecera no afirma «Sistema operativo» sin una comprobación real.
// Son pruebas de texto sobre el código, deliberadamente: el fallo que impiden es una línea concreta.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (file: string) => readFileSync(join(ROOT, file), "utf8");
/** Quita los comentarios: lo que se prohíbe es CÓDIGO, no que un comentario explique por qué ya no existe. */
const code = (file: string) => read(file).replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

test("V1 · el grafo no traga el error del backend con `.catch(() => …)`", () => {
  const graph = code("components/neural-nexus/neural-nexus-graph.tsx");
  assert.doesNotMatch(graph, /\.catch\s*\(/, "el grafo vuelve a tragar errores");
  assert.match(graph, /readNexus\(/, "el grafo debe leer con readNexus (ReadState)");
});

test("V1 · ni el grafo ni su HUD usan datos de demostración como relleno", () => {
  for (const file of [
    "components/neural-nexus/neural-nexus-graph.tsx",
    "components/neural-nexus/nexus-hud.tsx",
    "components/neural-nexus/nexus-details.tsx",
    "lib/neural-nexus.ts",
  ]) {
    const source = code(file);
    for (const forbidden of ["CANONICAL_AGENTS", "DEMO_PROJECT", "DEMO_CORE_METRICS", "AMZ-2026-003"]) {
      assert.equal(source.includes(forbidden), false, `${file} usa ${forbidden}`);
    }
  }
  assert.doesNotMatch(code("components/neural-nexus/nexus-hud.tsx"), /lib\/demo/, "el HUD no puede importar lib/demo");
});

test("V1 · el grafo distingue los cuatro estados de lectura y no dibuja nada sin registro", () => {
  const graph = code("components/neural-nexus/neural-nexus-graph.tsx");
  assert.match(graph, /reads\.agents\.kind === "error"/);
  assert.match(graph, /reads\.agents\.kind === "empty"/);
  assert.match(graph, /reads === null/);
});

test("V2 · el estado de un agente no se traduce con OFFLINE/ERROR ni cae en «disponible» por defecto", () => {
  const model = code("lib/neural-nexus.ts");
  assert.doesNotMatch(model, /OFFLINE/, "neural-nexus.ts vuelve a conocer un estado OFFLINE que el backend no envía");
  assert.doesNotMatch(model, /STATUS_FROM_REGISTRY/);
  // El único `?? "available"` que puede quedar es el del estado del propio núcleo (que siempre existe), no el de un agente.
  const fallbacks = model.split("\n").filter((line) => /\?\?\s*"available"/.test(line) && !line.includes("core?.status"));
  assert.deepEqual(fallbacks, [], "un estado desconocido no puede caer en «available»");
  assert.match(model, /readAgentStatus\(/);
});

test("V3 · la cabecera no dice «Sistema operativo» ni tiene un punto verde fijo", () => {
  const raw = read("components/top-header.tsx");
  assert.doesNotMatch(raw, /Sistema operativo/i);
  const header = code("components/top-header.tsx");
  assert.match(header, /HealthMonitor/, "la cabecera debe usar el monitor de salud");
  assert.match(header, /getReadiness/, "la cabecera debe consultar /health/ready");
  // El único `bg-success` está dentro del estilo del veredicto `ready`, no suelto en el JSX.
  const loose = header.split("\n").filter((line) => line.includes("bg-success") && !/ready:\s*\{/.test(line));
  assert.deepEqual(loose, [], "hay un bg-success fuera del estilo del veredicto `ready`");
});

test("V3 · la cabecera consulta el endpoint público sin token", () => {
  const api = code("lib/api.ts");
  const start = api.indexOf("getReadiness");
  assert.ok(start > 0);
  const body = api.slice(start, api.indexOf("\n  },", start));
  assert.match(body, /\/health\/ready/);
  assert.doesNotMatch(body, /authHeader|Authorization|request</, "/health/ready es público: no debe llevar token");
});
