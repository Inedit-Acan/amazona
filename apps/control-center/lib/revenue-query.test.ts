import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEFAULT_REVENUE_DAYS,
  REVENUE_ENTRIES_PAGE_SIZE,
  REVENUE_PERIODS,
  parseRevenueDays,
  revenuePath,
  revenueWindow,
} from "./revenue-query.ts";

// Cómo se piden los agregados de ingresos (M45, ADR 0030): rutas de lectura y ventana en UTC. Nada aleatorio.

test("parseRevenueDays: solo acepta los periodos que ofrece el Panel", () => {
  assert.deepEqual([...REVENUE_PERIODS], [7, 14, 30]);
  assert.equal(parseRevenueDays("7"), 7);
  assert.equal(parseRevenueDays("14"), 14);
  assert.equal(parseRevenueDays(["7", "30"]), 7);
});

test("parseRevenueDays: lo que no es un periodo permitido vuelve al de por defecto", () => {
  for (const bad of [undefined, "", "0", "5", "31", "366", "abc", "-7", "7.5", "1e1"]) {
    assert.equal(parseRevenueDays(bad), DEFAULT_REVENUE_DAYS, `«${bad}» no debe abrir una ventana arbitraria`);
  }
});

test("revenueWindow: los últimos N días naturales UTC, hoy incluido, con el fin exclusivo", () => {
  const now = Date.UTC(2026, 9, 3, 15, 30, 12);
  assert.deepEqual(revenueWindow(now, 7), { from: "2026-09-27T00:00:00.000Z", to: "2026-10-04T00:00:00.000Z" });
  assert.deepEqual(revenueWindow(now, 30), { from: "2026-09-04T00:00:00.000Z", to: "2026-10-04T00:00:00.000Z" });
});

test("revenueWindow: justo a medianoche UTC el día que empieza ya cuenta", () => {
  const midnight = Date.UTC(2026, 9, 3, 0, 0, 0);
  assert.equal(revenueWindow(midnight, 7).to, "2026-10-04T00:00:00.000Z");
  const lastMs = Date.UTC(2026, 9, 3, 23, 59, 59, 999);
  assert.equal(revenueWindow(lastMs, 7).to, "2026-10-04T00:00:00.000Z");
});

test("revenueWindow: abarca exactamente N días", () => {
  for (const days of REVENUE_PERIODS) {
    const window = revenueWindow(Date.UTC(2026, 0, 15, 8), days);
    assert.equal((Date.parse(window.to) - Date.parse(window.from)) / 86_400_000, days);
  }
});

test("revenuePath: la ruta y los parámetros en orden alfabético, sin vacíos", () => {
  assert.equal(revenuePath("summary"), "/api/revenue/summary");
  assert.equal(
    revenuePath("entries", { limit: 25, from: "2026-09-27T00:00:00.000Z", cursor: undefined, currency: "", kind: null }),
    "/api/revenue/entries?from=2026-09-27T00%3A00%3A00.000Z&limit=25",
  );
});

test("revenuePath: la misma petición da siempre la misma URL", () => {
  const a = revenuePath("series", { granularity: "day", from: "a", to: "b" });
  const b = revenuePath("series", { to: "b", from: "a", granularity: "day" });
  assert.equal(a, b);
  assert.equal(a, "/api/revenue/series?from=a&granularity=day&to=b");
});

test("el tamaño de página del Panel cabe en lo que admite el backend (1..200)", () => {
  assert.ok(REVENUE_ENTRIES_PAGE_SIZE >= 1 && REVENUE_ENTRIES_PAGE_SIZE <= 200);
});
