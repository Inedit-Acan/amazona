import assert from "node:assert/strict";
import { test } from "node:test";
import { latestForMarket, marketLabel } from "./markets.ts";

test("latestForMarket devuelve el primero (más reciente) del mercado", () => {
  const list = [
    { id: "new", market: "us" },
    { id: "old", market: "us" },
    { id: "eu1", market: "eu" },
  ];
  assert.equal(latestForMarket(list, "us")?.id, "new");
  assert.equal(latestForMarket(list, "eu")?.id, "eu1");
  assert.equal(latestForMarket(list, "mx"), undefined);
});

test("marketLabel etiqueta los mercados conocidos y cae al código en mayúsculas", () => {
  assert.equal(marketLabel("eu"), "Unión Europea");
  assert.equal(marketLabel("jp"), "JP");
});
