import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ACTION_LABELS,
  CHAT_MAX_CHARS,
  canSend,
  classifyChatError,
  conversationLines,
  costLabel,
  isOpen,
  sourcesLabel,
  toolsRead,
  type CeoMessage,
} from "./ceo-chat.ts";

const message = (role: CeoMessage["role"], structured: CeoMessage["structured"] = null): CeoMessage => ({
  id: `m-${role}`,
  seq: 1,
  role,
  content: role,
  structured,
  provider: null,
  model: null,
  input_tokens: null,
  output_tokens: null,
  estimated_cost_usd: null,
  external_cost_category: null,
  created_at: null,
});

test("solo se envía un mensaje con texto, dentro del máximo y sin otro en curso", () => {
  assert.equal(canSend("hola", false), true);
  assert.equal(canSend("   ", false), false);
  assert.equal(canSend("", false), false);
  assert.equal(canSend("hola", true), false);
  assert.equal(canSend("x".repeat(CHAT_MAX_CHARS), false), true);
  assert.equal(canSend("x".repeat(CHAT_MAX_CHARS + 1), false), false);
});

test("un 503 es «el CEO no está disponible», con la conversación a salvo y sin enseñar el cuerpo crudo", () => {
  const body = JSON.stringify({ detail: { code: "model_unavailable", message: "El CEO no está disponible ahora.", conversation_id: "c-1" } });

  const failure = classifyChatError(503, body);

  assert.deepEqual(failure, { kind: "unavailable", message: "El CEO no está disponible ahora.", conversationId: "c-1" });
  const garbled = classifyChatError(503, "<html>boom</html>");
  assert.equal(garbled.kind, "unavailable");
  assert.doesNotMatch(JSON.stringify(garbled), /boom|html/);
});

test("401 y 403 son de identidad y los demás fallos tienen un texto fijo", () => {
  assert.equal(classifyChatError(401, "").kind, "unauthenticated");
  assert.equal(classifyChatError(403, "").kind, "forbidden");
  for (const status of [404, 409, 422, 428, 500]) {
    const failure = classifyChatError(status, "password=hunter2 stack trace");
    assert.equal(failure.kind, "error");
    assert.doesNotMatch(JSON.stringify(failure), /hunter2|stack/);
  }
});

test("el coste no estimado se dice, no se convierte en cero", () => {
  assert.match(costLabel({ estimated_cost_usd: null, input_tokens: 10, output_tokens: 2 }), /Coste no estimado/);
  assert.doesNotMatch(costLabel({ estimated_cost_usd: null, input_tokens: 10, output_tokens: 2 }), /0\.0000/);
  assert.match(costLabel({ estimated_cost_usd: 0.0123, input_tokens: 1000, output_tokens: 100 }), /0\.0123 USD · 1000 entrada · 100 salida/);
});

test("solo una propuesta pendiente se puede confirmar o rechazar", () => {
  assert.equal(isOpen({ status: "PROPOSED" }), true);
  for (const status of ["EXECUTING", "EXECUTED", "FAILED", "REJECTED"] as const) assert.equal(isOpen({ status }), false, status);
});

test("la conversación visible no lleva herramientas ni mensajes internos; las herramientas son fuentes", () => {
  const all = [
    message("user"),
    message("tool", { tool: "get_budget_status" }),
    message("tool", { tool: "propose_retry_task" }),
    message("tool", { tool: "get_budget_status" }),
    message("assistant"),
  ];

  assert.deepEqual(conversationLines(all).map((m) => m.role), ["user", "assistant"]);
  assert.deepEqual(toolsRead(all), ["get_budget_status"]);
  assert.equal(sourcesLabel([]), null);
  assert.equal(sourcesLabel(["Presupuesto", "Última misión"]), "Fuentes: Presupuesto · Última misión");
});

test("cada acción que el backend puede proponer tiene su etiqueta", () => {
  assert.deepEqual(Object.keys(ACTION_LABELS).sort(), [
    "approve_approval",
    "create_mission",
    "reassign_task",
    "reject_approval",
    "resume_mission",
    "retry_task",
  ]);
});

test("las fuentes de cada respuesta salen de las lecturas hechas desde la pregunta que la provocó", async () => {
  const { sourcesByAnswer } = await import("./ceo-chat.ts");
  const at = (m: CeoMessage, seq: number, id: string): CeoMessage => ({ ...m, seq, id });
  const messages = [
    at(message("user"), 1, "u1"),
    at(message("tool", { tool: "get_budget_status" }), 2, "t1"),
    at(message("assistant"), 3, "a1"),
    at(message("user"), 4, "u2"),
    at(message("assistant"), 5, "a2"),
  ];

  assert.deepEqual(sourcesByAnswer(messages), { a1: ["Presupuesto"], a2: [] });
});
