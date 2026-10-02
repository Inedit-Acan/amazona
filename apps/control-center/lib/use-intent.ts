/** El conservador de claves de intención, ligado a un componente (Milestone 44, ADR 0028 §9).
 *
 * Cada formulario llama a `useIntent("su-ámbito")` y obtiene **su** conservador: dos formularios no comparten
 * intención, ni siquiera si piden lo mismo. El conservador se crea una sola vez por componente (inicializador perezoso
 * de `useState`), así que un rerender no lo cambia ni genera claves: una clave nace únicamente dentro de `run`, cuando la
 * persona actúa. Las intenciones ambiguas (timeout, red, resultado desconocido) sobreviven a una navegación en
 * `sessionStorage`, que acaba con la pestaña; nunca en `localStorage`.
 *
 *     const intent = useIntent("fulfillment");
 *     await intent.run(
 *       { operation: OPERATIONS.fulfillmentPurchase, target: fulfillment.id, params: {} },
 *       (key) => api.purchaseFulfillment(fulfillment.id, key),
 *     );
 *
 * `intent.phase` sirve para deshabilitar el botón mientras algo está en vuelo y para avisar de un resultado desconocido
 * (`"unknown"`): ahí la interfaz no ofrece «reintentar con otra clave»; ofrece `intent.discard` solo después de que una
 * persona haya comprobado qué pasó. */

import { useState, useSyncExternalStore } from "react";
import { createIntentKeeper, type IntentKeeper, type IntentPhase, type IntentStorage } from "./intent-key.ts";

/** `sessionStorage` si existe y deja usarse (el modo privado de algunos navegadores lo bloquea); si no, solo memoria. */
function tabStorage(): IntentStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export interface UseIntent {
  run: IntentKeeper["run"];
  discard: IntentKeeper["discard"];
  phaseOf: IntentKeeper["phaseOf"];
  phase: IntentPhase;
}

export function useIntent(scope: string): UseIntent {
  const [keeper] = useState(() => createIntentKeeper({ scope, storage: tabStorage() }));
  const phase = useSyncExternalStore(keeper.subscribe, keeper.phase, (): IntentPhase => "idle");
  return { run: keeper.run, discard: keeper.discard, phaseOf: keeper.phaseOf, phase };
}
