// El layout del Director ejecutivo (M47, Commit 2): los umbrales, con nombre, en UN sitio.
//
// Tailwind necesita las clases escritas literalmente, así que los componentes llevan `min-[1440px]:`; `lib/ceo-layout.test.ts`
// lee los componentes y exige que ese número sea `CEO_PANEL_MIN_PX` y que no haya otro umbral de panel. Mover el panel a otro
// ancho es cambiar este valor y esas clases a la vez, y la prueba avisa si solo se cambia una de las dos.

/** Desde este ancho, la columna del CEO IA es persistente (como el mockup aprobado); por debajo pasa a un drawer. */
export const CEO_PANEL_MIN_PX = 1440;

/** Ancho de la columna del CEO IA, en rem (≈ la columna derecha del mockup, 325 px de 1536). */
export const CEO_PANEL_REM = 20;

/** Desde este ancho (`xl`), Decisiones / Oportunidades / Riesgos son tres tarjetas; por debajo, pestañas. */
export const CEO_TRIPTYCH_MIN_PX = 1280;

/** Por debajo de este ancho el grafo se abre en 2D (no hay sitio para orbitar con un dedo y el HUD). */
export const CEO_NARROW_MAX_PX = 767;

/** Las consultas de medios que usan los componentes, derivadas de los umbrales. */
export const CEO_PANEL_QUERY = `(min-width: ${CEO_PANEL_MIN_PX}px)`;
export const CEO_NARROW_QUERY = `(max-width: ${CEO_NARROW_MAX_PX}px)`;
