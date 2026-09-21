import type { LucideIcon } from "lucide-react";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface PendingFeature {
  icon: LucideIcon;
  title: string;
  description: string;
}

/** Tarjeta «esto está en el mockup y el backend aún no lo da»: lista lo que
 * falta con borde discontinuo y un único badge «Pendiente», en vez de dibujar
 * cifras inventadas. `note` explica qué haría falta en el backend. */
export function PendingFeatures({
  id,
  title,
  tooltip,
  items,
  note,
  columns = 2,
  className,
}: {
  id?: string;
  title: string;
  tooltip: string;
  items: PendingFeature[];
  note?: string;
  columns?: 2 | 4;
  className?: string;
}) {
  return (
    <Card id={id} className={cn("scroll-mt-4", className)}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="pending" tooltip={tooltip} />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className={cn("grid gap-3 sm:grid-cols-2", columns === 4 && "xl:grid-cols-4")}>
          {items.map((item) => (
            <li key={item.title} className="flex gap-3 rounded-lg border border-dashed p-3">
              <item.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">{item.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{item.description}</p>
              </div>
            </li>
          ))}
        </ul>
        {note ? <p className="mt-3 text-[11px] text-muted-foreground">{note}</p> : null}
      </CardContent>
    </Card>
  );
}
