import type { ImpactLevel } from "@/lib/economics-model";
import { cn } from "@/lib/utils";

export interface SensitivityBar {
  key: string;
  label: string;
  /** 0–1: longitud relativa de la barra. */
  value: number;
  level: ImpactLevel;
  /** Texto del tooltip nativo (p. ej. «−35 % de beneficio»). */
  detail?: string;
}

const LEVEL_STYLE: Record<ImpactLevel, { bar: string; text: string }> = {
  Alto: { bar: "bg-destructive", text: "text-destructive" },
  Medio: { bar: "bg-[#f8925c]", text: "text-[#f8925c]" },
  Bajo: { bar: "bg-warning", text: "text-warning" },
};

/** Barras de impacto con nivel (análisis de sensibilidad del mockup de
 * Economía): etiqueta, barra coloreada por nivel y el nivel a la derecha. */
export function SensitivityBars({ items, ariaLabel }: { items: SensitivityBar[]; ariaLabel: string }) {
  return (
    <ul className="space-y-3" aria-label={ariaLabel}>
      {items.map((item) => (
        <li key={item.key} className="grid grid-cols-[minmax(0,9rem)_1fr_3.25rem] items-center gap-3 text-xs" title={item.detail}>
          <span className="truncate">{item.label}</span>
          <span className="h-2 rounded-full bg-muted">
            <span
              className={cn("block h-full rounded-full", LEVEL_STYLE[item.level].bar)}
              style={{ width: `${Math.max(4, Math.min(1, item.value) * 100)}%` }}
            />
          </span>
          <span className={cn("font-medium", LEVEL_STYLE[item.level].text)}>{item.level}</span>
        </li>
      ))}
    </ul>
  );
}
