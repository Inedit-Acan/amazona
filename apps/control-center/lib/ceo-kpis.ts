import type { RevenueSummary } from "./api.ts";
import { unavailableState, type UnavailableState } from "./ceo-blocks.ts";
import { revenueFigures, type FigureSecondary, type FigureLine } from "./revenue-figures.ts";
import type { RevenueWindow } from "./revenue-query.ts";
import { periodLabel, settle, type Settled } from "./revenue-view.ts";

// Los KPI del Director ejecutivo (M47, Commit 3A).
//
// INGRESOS. La semántica (origen × moneda, de `verified[]`, sin sumas ni conversiones, lo de revisión y pendiente aparte, vacío ≠ error) NO vive
// aquí: desde el Commit 3A.1 está en `lib/revenue-figures.ts`, el núcleo único que comparten `/ceo`, `/dashboard` y `/cfo`. Este módulo solo
// añade lo propio de `/ceo`: el periodo en texto, la lectura de UNA ventana y los tres KPI que hoy no tienen fuente. Reexporta los nombres que
// ya usaban los componentes de `/ceo`, para que ninguno cambie.

export {
  hasSecondary,
  linesCountText,
  OUTSIDE_FIGURE_TEXT,
  secondarySummary,
  type FigureLine as IngresosLine,
  type FigureSecondary as IngresosSecondary,
  type PendingFigure as PendingLine,
  type ReviewFigure as UnderReviewLine,
} from "./revenue-figures.ts";

/** Qué demuestra y qué no la tarjeta de Ingresos. */
export const INGRESOS_NOT_SETTLED_NOTE = "Un hecho verificado no es dinero liquidado.";
/** Solo se dice cuando hay más de una línea: con una sola no hay nada que sumar. */
export const INGRESOS_NO_SUM_NOTE = "Orígenes y monedas no se suman ni se convierten.";

export type IngresosView =
  | { kind: "error"; message: string }
  | { kind: "empty"; periodText: string; secondary: FigureSecondary }
  | { kind: "loaded"; periodText: string; lines: FigureLine[]; secondary: FigureSecondary };

/** Altura de la tarjeta de Ingresos (M47, 3A): el máximo que se acepta en desktop en estado normal, y el alto del área de líneas con
 * scroll (en `rem`; `components/ceo/revenue-kpi.tsx` lleva la clase literal `max-h-[6rem]` y una prueba la ata a este número). Con
 * más líneas de las que caben, las líneas hacen scroll y el desglose completo está en «Ver desglose»: nada se oculta. */
export const INGRESOS_CARD_MAX_PX = 300;
export const INGRESOS_LINES_MAX_REM = 6;

export function ingresosView(settled: Settled<RevenueSummary>, days: number): IngresosView {
  if (!settled.ok) return { kind: "error", message: settled.message };
  const figures = revenueFigures(settled.data);
  if (figures.kind === "error") return figures;
  const periodText = `${periodLabel(days)} (UTC)`;
  return figures.kind === "empty"
    ? { kind: "empty", periodText, secondary: figures.secondary }
    : { kind: "loaded", periodText, lines: figures.lines, secondary: figures.secondary };
}

/** Lo que Ingresos necesita del cliente de la API. `api` lo cumple; las pruebas pasan dobles. */
export interface IngresosSource {
  revenueSummary(window?: RevenueWindow): Promise<RevenueSummary>;
}

/** UNA lectura (`GET /api/revenue/summary?from=&to=`) de la ventana elegida. Un fallo es `error`; nunca datos de otra ventana ni vacío. */
export async function readIngresos(source: IngresosSource, window: RevenueWindow, days: number): Promise<IngresosView> {
  return ingresosView(await settle(() => source.revenueSummary(window)), days);
}

// --- Los otros tres KPI: hoy no hay fuente ---------------------------------------------------------------------------------

export interface UnavailableKpi {
  key: "beneficio" | "margen" | "cash";
  label: string;
  state: UnavailableState;
  /** La frase corta que sale en la tarjeta; el motivo completo es `state.reason`. */
  caption: string;
  /** Un enlace solo donde tiene sentido, sin sugerir que la cifra ya exista. */
  link?: { href: string; label: string };
}

export const UNAVAILABLE_KPIS: UnavailableKpi[] = [
  {
    key: "beneficio",
    label: "Beneficio",
    state: unavailableState("Falta una fuente de costes completa: el backend no registra coste de ventas, envíos, comisiones ni impuestos."),
    caption: "Falta una fuente de costes completa.",
    link: { href: "/cfo", label: "Ver en Finanzas el margen de contribución declarado (no es el beneficio)" },
  },
  {
    key: "margen",
    label: "Margen neto",
    state: unavailableState("Depende del beneficio, que hoy no puede calcularse."),
    caption: "Depende del beneficio.",
  },
  {
    key: "cash",
    label: "Cash disponible",
    state: unavailableState("No hay fuente de caja: el backend no tiene cuentas ni conciliación."),
    caption: "No hay fuente de caja.",
  },
];
