import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// Frontera servidor / cliente para las llamadas a la API (Milestone 29.1).
//
// `api` resuelve el token de acceso de forma distinta según dónde se ejecute:
// en el navegador, de la sesión de Supabase; en servidor, de las cookies de la
// petición. Lo segundo solo ocurre si el módulo se importa desde
// "@/lib/api-server".
//
// Una página de servidor que importe `api` de "@/lib/api" manda sus peticiones
// SIN cabecera Authorization. En desarrollo no se nota —los GET están
// abiertos—; en staging/production devuelve 401. Es decir: un fallo silencioso
// justo donde más caro sale. De ahí este test.

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const IMPORTS_API_OBJECT = /^import \{[^}]*\bapi\b[^}]*\} from "@\/lib\/api";$/m;
const IMPORTS_SERVER_API = /from "@\/lib\/api-server"/;

function sourceFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(join(ROOT, directory), { withFileTypes: true })) {
    const relativePath = `${directory}/${entry.name}`;
    if (entry.isDirectory()) {
      if (entry.name === "node_modules") continue;
      found.push(...sourceFiles(relativePath));
    } else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".test.ts")) {
      found.push(relativePath);
    }
  }
  return found;
}

function isClientComponent(source: string): boolean {
  return source.trimStart().startsWith('"use client"');
}

test("ninguna página de servidor importa el objeto api del módulo de cliente", () => {
  const offenders: string[] = [];
  for (const file of [...sourceFiles("app"), ...sourceFiles("components")]) {
    const source = readFileSync(join(ROOT, file), "utf8");
    if (isClientComponent(source)) continue;
    if (IMPORTS_API_OBJECT.test(source)) offenders.push(file);
  }

  assert.deepEqual(
    offenders,
    [],
    `estos módulos se renderizan en servidor y llaman a la API sin token:\n  ${offenders.join("\n  ")}\n` +
      'Importa `api` desde "@/lib/api-server".',
  );
});

test("quien usa api-server se renderiza en servidor", () => {
  // Al revés también importa: "@/lib/api-server" arrastra `next/headers`, que en
  // un componente de cliente rompe el build.
  for (const file of [...sourceFiles("app"), ...sourceFiles("components")]) {
    const source = readFileSync(join(ROOT, file), "utf8");
    if (!IMPORTS_SERVER_API.test(source)) continue;
    assert.ok(
      !isClientComponent(source),
      `${file} es un componente de cliente y no puede importar "@/lib/api-server"`,
    );
  }
});

test("api-server es lo único que cambia el resolutor de token", () => {
  const callers = [...sourceFiles("app"), ...sourceFiles("components"), ...sourceFiles("lib")].filter((file) =>
    readFileSync(join(ROOT, file), "utf8").includes("setAccessTokenResolver("),
  );

  assert.deepEqual(
    callers.sort(),
    ["lib/api-server.ts", "lib/api.ts"],
    "el resolutor de token solo se define en lib/api.ts y se sustituye en lib/api-server.ts",
  );
});
