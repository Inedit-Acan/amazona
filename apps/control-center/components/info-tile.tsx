import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/** Recuadro de un dato de contexto (proveedor, mercado, modelo logístico…) de la
 * franja de producto de los paneles del pipeline. */
export function InfoTile({ label, icon: Icon, children }: { label: string; icon?: LucideIcon; children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border bg-background/40 p-3">
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {Icon ? <Icon className="size-3.5 shrink-0" /> : null}
        {label}
      </p>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}
