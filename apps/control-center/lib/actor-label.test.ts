import assert from "node:assert/strict";
import { test } from "node:test";
import { LOCAL_ACTOR, actorLabel } from "./actor-label.ts";

test("el actor local sin autenticar no es una identidad: se dice «sin autenticar»", () => {
  assert.equal(actorLabel(LOCAL_ACTOR), "Operador local (sin autenticar)");
  assert.equal(actorLabel(LOCAL_ACTOR, "declared"), "Operador local (sin autenticar)");
});

test("un nombre declarado no se enseña como identidad ni se llama verificado", () => {
  assert.equal(actorLabel("someone-declared", "declared"), "Actor sin autenticar");
  assert.equal(actorLabel("owner@amazona.local", "declared"), "Actor sin autenticar");
});

test("solo `token` (verificado por el backend) es «persona autenticada», y nunca con su correo", () => {
  assert.equal(actorLabel("ana@example.com", "token"), "Persona autenticada");
  assert.doesNotMatch(actorLabel("ana@example.com", "token"), /@|ana/);
});

test("sin fuente: un correo se oculta y el resto se enseña tal cual", () => {
  assert.equal(actorLabel("owner@amazona.local"), "Persona (correo no mostrado)");
  assert.equal(actorLabel("agent-product-1"), "agent-product-1");
});

test("ausente o vacío: se dice, nunca se inventa un nombre", () => {
  for (const value of [null, undefined, "", "   "]) assert.equal(actorLabel(value), "Sin actor registrado");
});

test("ninguna etiqueta llama a nadie propietario, owner ni usuario autenticado, ni contiene un correo", () => {
  for (const [actor, source] of [[LOCAL_ACTOR, "declared"], ["x@y.z", "declared"], ["x@y.z", "token"], ["x@y.z", null], ["a", "cli"], ["", null]] as const) {
    const label = actorLabel(actor, source);
    assert.doesNotMatch(label, /propietario|owner|usuario autenticado|@/i, label);
  }
});
