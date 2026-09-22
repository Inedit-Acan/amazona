import assert from "node:assert/strict";
import { test } from "node:test";
import { DEMO_CHANNELS, DEMO_OWNED_AUDIENCES, DEMO_PERIOD } from "./demo/marketing.ts";
import {
  acquisitionPlan,
  attribution,
  audienceRows,
  channelPerformance,
  conversionFunnel,
  creativeRows,
  creativeStatus,
  funnelFor,
  marketingSummary,
  metricSeries,
  optimizePlan,
  planTotal,
  profitabilityGuard,
  recommendations,
} from "./marketing-view.ts";

const close = (a: number, b: number, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≈ ${b}`);

test("acquisitionPlan: reparto demo del presupuesto base y propuesta real por días del periodo", () => {
  const demo = acquisitionPlan([], 1500);
  assert.deepEqual(
    demo.map((r) => [r.key, r.amount]),
    [
      ["meta", 525],
      ["google", 450],
      ["tiktok", 300],
      ["creators", 150],
      ["other", 75],
    ],
  );
  close(demo.reduce((s, r) => s + r.share, 0), 1);
  assert.ok(demo.every((r) => !r.isReal));

  const withReal = acquisitionPlan([{ platform: "google", daily_budget: 20 }], 1500);
  const google = withReal.find((r) => r.key === "google")!;
  assert.equal(google.amount, 20 * DEMO_PERIOD.days);
  assert.equal(google.isReal, true);
  assert.equal(planTotal(withReal), 1500 - 450 + 600);
});

test("optimizePlan: mismo total y más peso a los canales con CAC relativo más bajo", () => {
  const plan = acquisitionPlan([], 1000);
  const optimized = optimizePlan(plan);
  close(planTotal(optimized), planTotal(plan), 0.05);
  const share = (rows: typeof plan, key: string) => rows.find((r) => r.key === key)!.share;
  assert.ok(share(optimized, "google") > share(plan, "google"));
  assert.ok(share(optimized, "other") < share(plan, "other"));
});

test("channelPerformance: determinista, un punto por día y gasto cercano al plan", () => {
  const plan = acquisitionPlan([], 1000);
  const input = { productId: "p1", plan, cacObjective: 3.2, price: 29.9 };
  const a = channelPerformance(input);
  assert.deepEqual(a, channelPerformance(input));
  assert.deepEqual(a.map((b) => b.key), ["meta", "google", "tiktok", "other"]);
  for (const b of a) assert.equal(b.days.length, DEMO_PERIOD.days);
  const spend = a.reduce((s, b) => s + b.spend, 0);
  assert.ok(spend > 800 && spend < 1100, `gasto ${spend}`);
  // Ingresos = conversiones × precio.
  close(a[0].revenue, a[0].conversions * 29.9, 1e-6);
});

test("channelPerformance: CTR y conversión reales de la propuesta del agente", () => {
  const plan = acquisitionPlan([], 1000);
  const perf = channelPerformance({
    productId: "p1",
    plan,
    cacObjective: 3.2,
    price: 29.9,
    estimates: { meta: { avg_ctr: 0.02, conversion_rate: 0.03 } },
  });
  assert.equal(perf[0].ctr, 0.02);
  assert.equal(perf[0].conversionRate, 0.03);
  assert.equal(perf[1].ctr, DEMO_CHANNELS[1].ctr);
});

test("metricSeries: ROAS y CAC diarios coherentes con gasto e ingresos", () => {
  const perf = channelPerformance({ productId: "p1", plan: acquisitionPlan([], 1000), cacObjective: 3.2, price: 29.9 });
  const day = perf[0].days[4];
  const roas = metricSeries(perf[0], "roas")[4].y;
  const cac = metricSeries(perf[0], "cac")[4].y;
  close(roas, Math.round((day.revenue / day.spend) * 100) / 100);
  close(cac, Math.round((day.spend / day.conversions) * 100) / 100);
  assert.equal(metricSeries(perf[0], "spend")[4].y, day.spend);
});

test("marketingSummary: KPIs, deltas frente a lo previsto y estado general", () => {
  const perf = channelPerformance({ productId: "p1", plan: acquisitionPlan([], 960), cacObjective: 3.2, price: 29.9 });
  const s = marketingSummary(perf, { budget: 960, cacObjective: 3.2, maxCac: 12.5, price: 29.9 });
  close(s.revenue, s.conversions * 29.9, 0.01);
  close(s.cac, Math.round((s.spend / s.conversions) * 100) / 100);
  close(s.spendVsPlan, s.spend / 960 - 1);
  close(s.targetRoas, 29.9 / 3.2);
  assert.ok(s.cacVsMax < 0);
  assert.ok(s.health >= 0 && s.health <= 100);

  const over = marketingSummary(perf, { budget: 960, cacObjective: 3.2, maxCac: 1, price: 29.9 });
  assert.equal(over.healthLabel, "CAC por encima del máximo");
});

test("conversionFunnel: nunca crece de un paso al siguiente y el CTR es el del canal", () => {
  const steps = conversionFunnel(266, 0.033, 0.045);
  assert.deepEqual(steps.map((s) => s.label), ["Impresiones", "Clics", "Landing", "Añadir carrito", "Checkout", "Compras"]);
  for (let k = 1; k < steps.length; k++) assert.ok(steps[k].value <= steps[k - 1].value, steps[k].label);
  assert.equal(steps[0].rate, null);
  close(steps[1].rate!, 0.033, 0.001);
  assert.equal(steps.at(-1)!.value, 266);
  // Una conversión alta no deja el checkout por debajo de las compras.
  const high = conversionFunnel(100, 0.05, 0.5);
  for (let k = 1; k < high.length; k++) assert.ok(high[k].value <= high[k - 1].value);
  assert.deepEqual(conversionFunnel(0, 0, 0).map((s) => s.value), [0, 0, 0, 0, 0, 0]);
});

test("funnelFor: el total suma las compras de todos los canales", () => {
  const perf = channelPerformance({ productId: "p1", plan: acquisitionPlan([], 1000), cacObjective: 3.2, price: 29.9 });
  const total = Math.round(perf.reduce((s, b) => s + b.conversions, 0));
  assert.equal(funnelFor(perf, "all").at(-1)!.value, total);
  assert.equal(funnelFor(perf, "google").at(-1)!.value, Math.round(perf[1].conversions));
});

test("attribution: reparte el total entero y el último clic sigue a los ingresos por canal", () => {
  const perf = channelPerformance({ productId: "p1", plan: acquisitionPlan([], 1000), cacObjective: 3.2, price: 29.9 });
  const total = 5000;
  for (const model of ["last_click", "first_click", "linear", "data_driven"] as const) {
    const slices = attribution(perf, model, total);
    close(slices.reduce((s, x) => s + x.share, 0), 1);
    close(slices.reduce((s, x) => s + x.revenue, 0), total, 0.05);
  }
  const last = attribution(perf, "last_click", total);
  const revenue = perf.reduce((s, b) => s + b.revenue, 0);
  close(last[0].share, perf[0].revenue / revenue);
  assert.equal(last[3].label, "Directo / Otros");
  assert.ok(attribution(perf, "first_click", total)[2].share > last[2].share);
});

test("audienceRows: segmentos reales primero, demo hasta tres y luego remarketing y lookalike", () => {
  const demo = audienceRows(undefined, "home");
  assert.equal(demo.length, 5);
  assert.ok(demo.every((a) => a.isDemo));
  assert.deepEqual(demo.slice(3).map((a) => a.name), DEMO_OWNED_AUDIENCES.map((a) => a.name));

  const rows = audienceRows(
    [
      { name: "A", age_range: "25-44", interests: ["x", "y", "z"], estimated_reach: 200 },
      { name: "B", age_range: "35-54", interests: [], estimated_reach: 100 },
    ],
    "home",
  );
  assert.equal(rows.length, 5);
  assert.deepEqual(rows.slice(0, 2).map((r) => [r.name, r.detail, r.score, r.isDemo]), [
    ["A", "25-44 · x / y", 90, false],
    ["B", "35-54", 80, false],
  ]);
  assert.equal(rows[2].isDemo, true);
});

test("creativeRows y creativeStatus: el primer vídeo lleva la creatividad real", () => {
  assert.equal(creativeStatus(90), "Aprobado");
  assert.equal(creativeStatus(82), "En revisión");
  assert.equal(creativeStatus(70), "Ajustar");
  const demo = creativeRows("p1", "home", undefined);
  assert.equal(demo.length, 4);
  assert.equal(demo[0].primaryText, null);
  const real = creativeRows("p1", "home", { headline: "H", primary_text: "T", cta: "Compra", image_brief: "B" });
  assert.deepEqual([real[0].headline, real[0].primaryText, real[0].cta], ["H", "T", "Compra"]);
  assert.equal(real[1].headline, demo[1].headline);
});

test("recommendations: la del agente primero y escalar el canal con menor CAC", () => {
  const perf = channelPerformance({ productId: "p1", plan: acquisitionPlan([], 1000), cacObjective: 3.2, price: 29.9 });
  const creatives = creativeRows("p1", "home", undefined);
  const list = recommendations({ performance: perf, cacObjective: 3.2, creatives, agentAdvice: "Start small" });
  assert.equal(list[0].kind, "agent");
  assert.ok(["scale", "reduce"].includes(list[1].kind));
  assert.ok(list.some((r) => r.kind === "abtest" && r.detail.includes("Video 02")));
  assert.equal(recommendations({ performance: perf, cacObjective: 3.2, creatives }).some((r) => r.kind === "agent"), false);
  // Con un CAC objetivo muy bajo, ni el mejor canal lo cumple.
  assert.equal(recommendations({ performance: perf, cacObjective: 0.5, creatives })[0].kind, "reduce");
});

test("profitabilityGuard: compara el CAC previsto con el máximo de Economía", () => {
  assert.equal(profitabilityGuard(5, 8.1).ok, true);
  assert.equal(profitabilityGuard(9, 8.1).ok, false);
});
