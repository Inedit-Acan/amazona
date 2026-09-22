import assert from "node:assert/strict";
import { test } from "node:test";
import type { Storefront } from "./api.ts";
import { contentChecklist, launchReadiness } from "./ecommerce.ts";

function storefront(overrides: Partial<Storefront> = {}): Storefront {
  return {
    correlation_id: "c1",
    product_id: "p1",
    market: "eu",
    store_slug: "earbuds-p1-store",
    launch_status: "NEEDS_REVIEW",
    recommendation: "REVIEW",
    confidence: 0.4,
    data: {
      landing_page_copy: {
        headline: "Earbuds",
        subheadline: "A carefully sourced pick",
        price_display: "$29.90",
        bullets: ["a", "b"],
        cta: "Shop now",
      },
      catalog_entry: { sku: "earbuds-p1-store", price: 29.9, category: "electronics", market: "eu", restricted: false, lead_time_days: 12 },
    },
    ...overrides,
  };
}

const states = (items: ReturnType<typeof launchReadiness>) => Object.fromEntries(items.map((i) => [i.key, i.state]));

test("launchReadiness sin nada generado: solo el producto está hecho y lo demás falta o no existe", () => {
  assert.deepEqual(states(launchReadiness({})), {
    product: "done",
    price: "todo",
    page: "todo",
    checkout: "todo",
    legal: "todo",
    analytics: "pending",
    tracking: "pending",
    domain: "pending",
    emails: "pending",
  });
});

test("launchReadiness con economía viable, tienda y legal GO", () => {
  const result = states(
    launchReadiness({
      economic: { recommendation: "GO" },
      storefront: { launch_status: "READY" },
      legal: { recommendation: "GO" },
    }),
  );
  assert.equal(result.price, "done");
  assert.equal(result.page, "done");
  assert.equal(result.legal, "done");
  // el checkout nunca se da por hecho: solo hay un plan en modo prueba
  assert.equal(result.checkout, "todo");
});

test("launchReadiness: economía NO_GO y legal bloqueado o en revisión no cuentan como hechos", () => {
  const blocked = launchReadiness({ economic: { recommendation: "NO_GO" }, legal: { recommendation: "NO_GO" } });
  assert.equal(states(blocked).price, "todo");
  assert.equal(states(blocked).legal, "todo");
  assert.match(blocked.find((i) => i.key === "legal")!.detail, /bloqueado/);
  const review = launchReadiness({ legal: { recommendation: "REVIEW" } });
  assert.match(review.find((i) => i.key === "legal")!.detail, /revisión humana/);
});

test("contentChecklist: solo cuenta como generado lo que trae el borrador", () => {
  const items = contentChecklist(storefront());
  const generated = items.filter((i) => i.generated).map((i) => i.label);
  assert.deepEqual(generated, [
    "Título y propuesta de valor",
    "Descripción del producto",
    "Beneficios y características",
    "Llamada a la acción (CTA)",
  ]);
  assert.equal(items.length, 8);
  assert.ok(contentChecklist(storefront({ data: null })).every((i) => !i.generated));
});
