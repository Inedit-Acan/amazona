// Prueba integrada de las claves de intención: el módulo REAL (`lib/intent-key.ts`) hablando por HTTP con el backend REAL.
//
// No es un test de `npm test` (necesita un backend vivo): lo lanza `backend/tests/integration/test_frontend_intent_key_flow.py`,
// que arranca el backend sobre una base PostgreSQL efímera, ejecuta este script y cuenta **en la base de datos** cuántos
// pedidos hay. Aquí solo se provocan las situaciones y se informa de cuántas peticiones salieron de verdad.
//
//   AMAZONA_API_URL=http://127.0.0.1:8765 PRODUCT_ID=<id> node scripts/intent-e2e.ts
//
// Los fallos se simulan **después** de que la petición real llegue al servidor (la respuesta se «pierde»): es la situación
// que importa, porque la petición salió y el cliente no lo sabe. Sin dependencias; requiere Node con soporte de TypeScript.

import { createIntentKeeper, type IntentSpec } from "../lib/intent-key.ts";
import { newIdempotencyKey } from "../lib/idempotency.ts";

const API = (process.env.AMAZONA_API_URL ?? "").replace(/\/$/, "");
const PRODUCT_ID = process.env.PRODUCT_ID ?? "";
if (!API || !PRODUCT_ID) {
  console.error("AMAZONA_API_URL and PRODUCT_ID are required");
  process.exit(2);
}

class HttpError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

let requestsSent = 0;
type Loss = "none" | "timeout" | "network" | "gateway";

/** `POST /api/orders` como lo hace `lib/api.ts`: la clave la pone quien llama y el error lleva estado y cuerpo. */
async function createOrder(customerRef: string, quantity: number, key: string, loss: Loss = "none") {
  requestsSent += 1;
  const response = await fetch(`${API}/api/orders`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify({
      customer_ref: customerRef,
      market: "eu",
      lines: [
        { product_id: PRODUCT_ID, quantity, unit_price: { amount: "25.00", currency: "EUR" } },
      ],
    }),
  });
  const text = await response.text(); // el servidor ya hizo su trabajo
  if (loss === "timeout") throw new DOMException("The operation timed out", "TimeoutError");
  if (loss === "network") throw new TypeError("fetch failed");
  if (loss === "gateway") throw new HttpError("<html>502 Bad Gateway</html>", 502);
  if (!response.ok) throw new HttpError(text, response.status);
  return JSON.parse(text) as { id: string };
}

const spec = (customerRef: string, quantity = 2): IntentSpec => ({
  operation: "order.create",
  target: customerRef,
  params: { customer_ref: customerRef, quantity },
});

async function attempt<T>(promise: Promise<T>): Promise<T | "failed"> {
  try {
    return await promise;
  } catch {
    return "failed";
  }
}

const report: Record<string, unknown> = {};

// 1. Veinte clics idénticos a la vez: una petición.
{
  const keeper = createIntentKeeper();
  const before = requestsSent;
  const clicks = Array.from({ length: 20 }, () =>
    keeper.run(spec("sim_e2e_burst"), (key) => createOrder("sim_e2e_burst", 2, key)),
  );
  const results = await Promise.all(clicks);
  report.burst = { requests: requestsSent - before, distinctOrders: new Set(results.map((r) => r.id)).size };
}

// 2-4. La petición sale, el servidor la procesa y el cliente no recibe respuesta (timeout / red / 502): se reintenta
//      con la misma intención y debe seguir habiendo un solo pedido.
for (const loss of ["timeout", "network", "gateway"] as const) {
  const customer = `sim_e2e_${loss}`;
  const keeper = createIntentKeeper();
  const before = requestsSent;
  const first = await attempt(keeper.run(spec(customer), (key) => createOrder(customer, 2, key, loss)));
  const keyAfterLoss = keeper.keyOf(spec(customer));
  const second = await keeper.run(spec(customer), (key) => createOrder(customer, 2, key));
  report[loss] = {
    firstFailed: first === "failed",
    sameKeyKept: keyAfterLoss !== null,
    requests: requestsSent - before,
    answeredWithOriginal: typeof second === "object",
  };
}

// 5. Dos formularios independientes con los mismos datos: dos intenciones, dos pedidos (no comparten clave).
{
  const one = createIntentKeeper({ scope: "form-a" });
  const two = createIntentKeeper({ scope: "form-b" });
  const customer = "sim_e2e_twoforms";
  const [a, b] = await Promise.all([
    one.run(spec(customer), (key) => createOrder(customer, 2, key)),
    two.run(spec(customer), (key) => createOrder(customer, 2, key)),
  ]);
  report.twoForms = { distinctOrders: new Set([a.id, b.id]).size };
}

// 6. Parámetros que cambian: otra intención, otro pedido.
{
  const keeper = createIntentKeeper();
  const customer = "sim_e2e_changed";
  await attempt(keeper.run(spec(customer, 2), (key) => createOrder(customer, 2, key, "timeout")));
  const first = await keeper.run(spec(customer, 2), (key) => createOrder(customer, 2, key));
  const changed = await keeper.run(spec(customer, 3), (key) => createOrder(customer, 3, key));
  report.changed = { distinctOrders: new Set([first.id, changed.id]).size };
}

// 7. Tras un éxito, una nueva acción deliberada es otro pedido.
{
  const keeper = createIntentKeeper();
  const customer = "sim_e2e_again";
  const first = await keeper.run(spec(customer), (key) => createOrder(customer, 2, key));
  const again = await keeper.run(spec(customer), (key) => createOrder(customer, 2, key));
  report.again = { distinctOrders: new Set([first.id, again.id]).size };
}

// 8. Contraste: sin conservar la clave (una nueva por clic, como hace `request` sin ayuda) cada reintento es otro pedido.
{
  const customer = "sim_e2e_nokeeper";
  const before = requestsSent;
  await attempt(createOrder(customer, 2, newIdempotencyKey(), "timeout"));
  await createOrder(customer, 2, newIdempotencyKey());
  report.withoutKeeper = { requests: requestsSent - before };
}

console.log(JSON.stringify(report));
