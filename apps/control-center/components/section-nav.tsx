import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface SectionNavItem {
  label: string;
  /** Ancla de la misma página (`#id`). Sin `href` el elemento se muestra deshabilitado. */
  href?: string;
  icon?: LucideIcon;
  /** Por qué está deshabilitado (tooltip nativo). */
  pendingReason?: string;
  /** Sección seleccionada (resaltada como la pestaña activa del mockup). */
  active?: boolean;
  onClick?: () => void;
}

/** Pestañas-ancla de un panel largo (las «tabs» de los mockups): las secciones
 * con datos reales saltan a su tarjeta; las que dependen de backend que aún no
 * existe salen deshabilitadas con el motivo, en lugar de abrir una pestaña vacía. */
export function SectionNav({ label, items }: { label: string; items: SectionNavItem[] }) {
  return (
    <nav aria-label={label} className="flex flex-wrap gap-2">
      {items.map((item) => {
        const Icon = item.icon;
        return item.href ? (
          <Button
            key={item.label}
            size="sm"
            variant="outline"
            nativeButton={false}
            render={<a href={item.href} onClick={item.onClick} aria-current={item.active ? "true" : undefined} />}
            className={cn(item.active && "border-primary/70 bg-panel-hover text-foreground")}
          >
            {Icon ? <Icon /> : null}
            {item.label}
          </Button>
        ) : (
          <Button key={item.label} size="sm" variant="outline" disabled title={item.pendingReason ?? "Pendiente"}>
            {Icon ? <Icon /> : null}
            {item.label}
          </Button>
        );
      })}
    </nav>
  );
}
