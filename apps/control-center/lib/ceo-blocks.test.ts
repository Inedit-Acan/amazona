import assert from "node:assert/strict";
import { test } from "node:test";
import { blockNotice, NOT_CONNECTED_YET, unavailableState, type BlockState } from "./ceo-blocks.ts";
import { READ_ERROR_TEXT, READ_UNAVAILABLE_VALUE, READ_UNREAD_TEXT } from "./read-state.ts";

// Los estados de un bloque del Director ejecutivo (M47, Commit 2): `unread` y `unavailable` no se mezclan, y ninguno es un cero.

test("sin leer ≠ no disponible ≠ vacío ≠ error: cuatro avisos distintos", () => {
  const states: BlockState<unknown>[] = [NOT_CONNECTED_YET, unavailableState("sin fuente"), { kind: "empty" }, { kind: "error", message: "No se pudo cargar x." }];
  const notices = states.map((state) => blockNotice(state)!);
  assert.deepEqual(notices.map((notice) => notice.kind), ["unread", "unavailable", "empty", "error"]);
  assert.equal(new Set(notices.map((notice) => notice.label)).size, 4, "dos estados distintos no pueden decir lo mismo");
  assert.equal(notices[0].label, READ_UNREAD_TEXT);
  assert.equal(notices[1].label, READ_UNAVAILABLE_VALUE);
  assert.equal(notices[3].label, READ_ERROR_TEXT);
});

test("un bloque sin leer NO se convierte en vacío: no dice «Sin elementos», «Sin datos» ni 0", () => {
  const notice = blockNotice(NOT_CONNECTED_YET)!;
  assert.equal(notice.kind, "unread");
  assert.doesNotMatch(`${notice.label} ${notice.detail}`, /sin elementos|sin datos|^0\b|\b0 \/ 0\b|\b0 %/i);
});

test("un error NO se convierte en dato: ni demostración, ni cero, ni vacío", () => {
  const notice = blockNotice({ kind: "error", message: "No se pudo cargar los agentes." })!;
  assert.equal(notice.kind, "error");
  assert.doesNotMatch(`${notice.label} ${notice.detail}`, /demo|sin elementos|sin datos|^0\b/i);
});

test("un bloque con lectura válida no tiene aviso: enseña su contenido", () => {
  assert.equal(blockNotice({ kind: "loaded", data: [1] }), null);
});

test("«no disponible» lleva el motivo, que no es una promesa de datos", () => {
  const notice = blockNotice(unavailableState("El backend no tiene una entidad de hitos."))!;
  assert.equal(notice.label, "No disponible");
  assert.match(notice.detail, /hitos/);
});
