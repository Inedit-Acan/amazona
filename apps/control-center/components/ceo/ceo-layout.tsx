import type { ReactNode } from "react";

/** La rejilla del Director ejecutivo (M47, Commit 2), como el mockup aprobado: a partir de 1440 px dos zonas —el cuerpo a la
 * izquierda y la columna del CEO IA a la derecha (20 rem, pegajosa)—; por debajo, una sola columna y el panel pasa a un drawer.
 *
 * El umbral (1440) vive en `lib/ceo-layout.ts` (`CEO_PANEL_MIN_PX`); las clases `min-[1440px]:` de aquí deben coincidir con él
 * (lo comprueba `lib/ceo-layout.test.ts`). La cabecera va por encima de la rejilla, de modo que la columna del CEO IA empieza a
 * la altura de la fila de KPI, como en el mockup. */
export function CeoLayout({ children, panel }: { children: ReactNode; panel: ReactNode }) {
  return (
    <div className="min-[1440px]:grid min-[1440px]:grid-cols-[minmax(0,1fr)_20rem] min-[1440px]:items-start min-[1440px]:gap-4">
      <div className="min-w-0 space-y-4">{children}</div>
      <aside aria-label="CEO IA" className="hidden min-[1440px]:sticky min-[1440px]:top-4 min-[1440px]:block min-[1440px]:h-[calc(100dvh-7rem)] min-[1440px]:min-h-[34rem]">
        {panel}
      </aside>
    </div>
  );
}
