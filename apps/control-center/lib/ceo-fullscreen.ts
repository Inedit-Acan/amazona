// «Vista completa» del Director ejecutivo (M47, Commit 2): una sola funcionalidad —la pantalla completa del grafo de agentes
// que ya existía— detrás de dos controles (la cabecera y la tarjeta del Decision Engine). No hay ruta nueva.

export const FULLSCREEN_LABEL = "Vista completa";
export const FULLSCREEN_CARD_LABEL = "Abrir vista completa";

/** Lo que dicen los controles cuando no pueden abrir la vista completa. No se simula una pantalla completa. */
export const FULLSCREEN_UNSUPPORTED_TEXT = "Vista completa no disponible en este navegador";
export const FULLSCREEN_WAITING_TEXT = "Vista completa disponible cuando se haya leído el registro de agentes";

/** Lo único que se necesita del documento: se puede probar con un objeto cualquiera. */
export interface FullscreenDocument {
  fullscreenEnabled?: boolean;
}

/** ¿El navegador permite la Fullscreen API? Sin documento (servidor) o con `fullscreenEnabled` falso/ausente, no. */
export function fullscreenSupported(doc: FullscreenDocument | null | undefined): boolean {
  return doc?.fullscreenEnabled === true;
}

/** Por qué un control de vista completa está deshabilitado; `null` si puede usarse. */
export function fullscreenBlocker(input: { supported: boolean; graphDrawn: boolean }): string | null {
  if (!input.supported) return FULLSCREEN_UNSUPPORTED_TEXT;
  if (!input.graphDrawn) return FULLSCREEN_WAITING_TEXT;
  return null;
}
