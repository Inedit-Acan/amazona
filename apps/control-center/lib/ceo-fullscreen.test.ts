import assert from "node:assert/strict";
import { test } from "node:test";
import {
  FULLSCREEN_UNSUPPORTED_TEXT,
  FULLSCREEN_WAITING_TEXT,
  fullscreenBlocker,
  fullscreenSupported,
} from "./ceo-fullscreen.ts";

// «Vista completa» (M47, Commit 2): una sola funcionalidad —la pantalla completa del grafo— y, sin Fullscreen API, ningún
// simulacro: el control se deshabilita y lo explica.

test("la Fullscreen API solo cuenta si el documento dice que está habilitada", () => {
  assert.equal(fullscreenSupported({ fullscreenEnabled: true }), true);
  assert.equal(fullscreenSupported({ fullscreenEnabled: false }), false);
  assert.equal(fullscreenSupported({}), false, "sin la propiedad (p. ej. iOS) no se supone soporte");
  assert.equal(fullscreenSupported(undefined), false);
  assert.equal(fullscreenSupported(null), false);
});

test("sin soporte el control queda no disponible y dice «Vista completa no disponible en este navegador»", () => {
  const reason = fullscreenBlocker({ supported: false, graphDrawn: true });
  assert.equal(reason, FULLSCREEN_UNSUPPORTED_TEXT);
  assert.match(reason!, /Vista completa no disponible en este navegador/);
});

test("con soporte pero sin grafo dibujado (registro sin leer o fallido) también se explica; no se abre nada", () => {
  assert.equal(fullscreenBlocker({ supported: true, graphDrawn: false }), FULLSCREEN_WAITING_TEXT);
});

test("con soporte y grafo dibujado el control puede usarse", () => {
  assert.equal(fullscreenBlocker({ supported: true, graphDrawn: true }), null);
});

test("la falta de soporte prevalece sobre la espera (es el motivo que no se resuelve esperando)", () => {
  assert.equal(fullscreenBlocker({ supported: false, graphDrawn: false }), FULLSCREEN_UNSUPPORTED_TEXT);
});
