import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// Frontera demo / producción (Milestone 30, ADR 0008).
//
// El plan maestro pide un test que falle si el código de producción importa
// `lib/demo`. Hoy lo importan 41 módulos: los paneles se construyeron a
// propósito con datos de demostración, marcados con `DataProvenanceBadge`, y
// quitarlos no es un cambio mecánico —es decidir panel a panel qué se enseña
// cuando no hay dato real—. Eso es el Milestone 30.1.
//
// Así que este test es un TRINQUETE: fija exactamente la superficie actual. Un
// módulo nuevo no puede empezar a depender de datos de demostración sin
// aparecer aquí, y la lista solo puede encoger. Además hay un núcleo que no
// puede tocarlos nunca.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SCANNED = ["app", "components", "lib"];
const IMPORTS_DEMO = /from\s+"(@\/lib\/demo\/[^"]+|\.{1,2}\/(?:\.\.\/)*demo\/[^"]+)"/;

/** Módulos que hoy presentan datos de demostración. Solo puede menguar. */
const ALLOWED = [
  "app/agents/agents-panels.tsx",
  "app/agents/agents-workspace.tsx",
  "app/approvals/approvals-panels.tsx",
  "app/approvals/approvals-workspace.tsx",
  "app/audit/audit-panels.tsx",
  "app/audit/audit-workspace.tsx",
  "app/cfo/cfo-panels.tsx",
  "app/cfo/cfo-workspace.tsx",
  "app/dashboard/dashboard-panels.tsx",
  "app/dashboard/dashboard-workspace.tsx",
  "app/ecommerce/ecommerce-workspace.tsx",
  "app/ecommerce/store-builder.tsx",
  "app/economics/economics-workspace.tsx",
  "app/legal/legal-workspace.tsx",
  "app/marketing/marketing-panels.tsx",
  "app/marketing/marketing-workspace.tsx",
  "app/operations/operations-panels.tsx",
  "app/operations/operations-workspace.tsx",
  "app/projects/projects-panels.tsx",
  "app/projects/projects-workspace.tsx",
  "app/research/research-workspace.tsx",
  "app/sourcing/sourcing-workspace.tsx",
  "app/status/status-panels.tsx",
  "app/status/status-workspace.tsx",
  "components/neural-nexus/nexus-hud.tsx",
  "components/product-summary.tsx",
  "lib/agents-view.ts",
  "lib/approvals-view.ts",
  "lib/audit-view.ts",
  "lib/cfo-view.ts",
  "lib/dashboard-view.ts",
  "lib/economics-baseline.ts",
  "lib/legal-view.ts",
  "lib/marketing-view.ts",
  "lib/neural-nexus.ts",
  "lib/operations-view.ts",
  "lib/projects-view.ts",
  "lib/research-view.ts",
  "lib/sourcing-view.ts",
  "lib/status-view.ts",
  "lib/storefront-view.ts",
];

/** El núcleo: nada de esto puede depender jamás de datos inventados. */
const NEVER = ["lib/api.ts", "lib/auth.ts", "lib/format.ts", "lib/dates.ts", "lib/utils.ts"];

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(join(ROOT, directory), { withFileTypes: true })) {
    const relativePath = `${directory}/${entry.name}`;
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "demo") continue;
      found.push(...sourceFiles(relativePath));
    } else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
      found.push(relativePath);
    }
  }
  return found;
}

function importersOfDemo(): string[] {
  const importers: string[] = [];
  for (const directory of SCANNED) {
    for (const file of sourceFiles(directory)) {
      if (IMPORTS_DEMO.test(readFileSync(join(ROOT, file), "utf8"))) importers.push(file);
    }
  }
  return importers.sort();
}

test("la superficie de datos de demostración es exactamente la registrada", () => {
  const actual = importersOfDemo();
  const expected = [...ALLOWED].sort();

  const added = actual.filter((file) => !expected.includes(file));
  const removed = expected.filter((file) => !actual.includes(file));

  assert.deepEqual(
    added,
    [],
    `módulos nuevos que dependen de lib/demo: ${added.join(", ")}.\n` +
      "Si es deliberado, añádelos a ALLOWED y marca el dato con DataProvenanceBadge.",
  );
  assert.deepEqual(
    removed,
    [],
    `módulos que ya no dependen de lib/demo: ${removed.join(", ")}.\n` +
      "Enhorabuena: quítalos de ALLOWED para que el trinquete no retroceda.",
  );
});

test("el núcleo de la aplicación nunca depende de datos de demostración", () => {
  for (const file of NEVER) {
    assert.ok(
      !IMPORTS_DEMO.test(readFileSync(join(ROOT, file), "utf8")),
      `${file} importa lib/demo: el núcleo no puede depender de datos inventados`,
    );
  }
});

test("lo que vive en lib/demo se queda en lib/demo", () => {
  // Un módulo de demostración no puede importar desde fuera de su carpeta ni
  // ser reexportado por un barrel: la dependencia tiene que verse en el import.
  for (const entry of readdirSync(join(ROOT, "lib", "demo"), { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith(".ts")) continue;
    const source = readFileSync(join(ROOT, "lib", "demo", entry.name), "utf8");
    for (const match of source.matchAll(/from\s+"([^"]+)"/g)) {
      const target = match[1];
      const isSibling = target.startsWith("./");
      const isTypeOnlyFromApi = target === "../api.ts" || target === "@/lib/api";
      assert.ok(
        isSibling || isTypeOnlyFromApi,
        `lib/demo/${entry.name} importa ${target}: los datos de demostración no dependen del resto`,
      );
    }
  }
});

test("todos los módulos registrados existen", () => {
  const files = new Set(SCANNED.flatMap(sourceFiles));
  for (const file of ALLOWED) {
    assert.ok(files.has(file), `${file} está en ALLOWED pero ya no existe: quítalo de la lista`);
  }
});
