import { Fragment, type ComponentType } from "react";
import { cn } from "@/lib/utils";

export type ServiceMapStatus = "active" | "error" | "idle" | "demo";

export interface ServiceMapNode {
  id: string;
  label: string;
  status: ServiceMapStatus;
  icon?: ComponentType<{ className?: string }>;
  /** Columna inicial (1–12) y ancho en columnas dentro del nivel. */
  col: number;
  span: number;
  /** Por qué está en gris o en rojo; se enseña al pasar el cursor. */
  note?: string;
}

export interface ServiceMapTier {
  nodes: ServiceMapNode[];
  /** Nodo del que cuelga el tramo hacia el nivel siguiente (por defecto, el primero). */
  hubId?: string;
}

const COLUMNS = 12;
/** Alto (px) del hueco entre niveles, donde se dibujan los conectores. */
const GAP = 26;

const NODE_STYLE: Record<ServiceMapStatus, string> = {
  active: "border-primary/40 bg-primary/5 text-foreground",
  error: "border-destructive/50 bg-destructive/10 text-destructive",
  idle: "border-border bg-muted/30 text-muted-foreground",
  demo: "border-dashed border-primary/30 bg-primary/5 text-muted-foreground",
};

const ICON_STYLE: Record<ServiceMapStatus, string> = {
  active: "text-primary",
  error: "text-destructive",
  idle: "text-muted-foreground",
  demo: "text-primary/60",
};

function centerOf(node: ServiceMapNode): number {
  return ((node.col - 1 + node.span / 2) / COLUMNS) * 100;
}

function hubOf(tier: ServiceMapTier): ServiceMapNode {
  return tier.nodes.find((node) => node.id === tier.hubId) ?? tier.nodes[0];
}

/** Tramo entre dos niveles: baja del nodo (o de los nodos) de arriba, cruza por un
 * bus horizontal y sube/baja a cada nodo de abajo. Se dibuja con divs posicionados
 * en porcentaje —no con SVG— para que las líneas sigan siendo de un píxel a
 * cualquier ancho y no dependan de redondeos que romperían la hidratación. */
function Connector({ from, to }: { from: number[]; to: number[] }) {
  const all = [...from, ...to];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const needsBus = max - min > 0.01;
  return (
    <div className="relative" style={{ height: GAP }} aria-hidden>
      {from.map((x) => (
        <span key={`from-${x}`} className="absolute top-0 w-px -translate-x-1/2 bg-border" style={{ left: `${x}%`, height: GAP / 2 }} />
      ))}
      {needsBus ? (
        <span className="absolute h-px bg-border" style={{ left: `${min}%`, width: `${max - min}%`, top: GAP / 2 }} />
      ) : null}
      {to.map((x) => (
        <Fragment key={`to-${x}`}>
          <span className="absolute w-px -translate-x-1/2 bg-border" style={{ left: `${x}%`, top: GAP / 2, height: GAP / 2 - 3 }} />
          <span
            className="absolute size-0 -translate-x-1/2 border-x-[3px] border-t-[4px] border-x-transparent border-t-border"
            style={{ left: `${x}%`, top: GAP - 4 }}
          />
        </Fragment>
      ))}
    </div>
  );
}

/** Topología de servicios por niveles (spec parte2 §9.8). Cada nodo dice si
 * responde (verde), si falla (rojo), si su estado es de demostración (verde con
 * el borde a trazos) o si no hay telemetría suya (gris): el mapa nunca presenta
 * como medido un servicio que no lo está, y `note` explica el motivo. */
export function ServiceMap({ tiers }: { tiers: ServiceMapTier[] }) {
  return (
    <div className="min-w-0">
      {tiers.map((tier, index) => {
        const next = tiers[index + 1];
        const from = next && next.nodes.length === 1 && tier.nodes.length > 1 ? tier.nodes : [hubOf(tier)];
        return (
          <Fragment key={tier.nodes.map((node) => node.id).join("-")}>
            <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${COLUMNS}, minmax(0, 1fr))` }}>
              {tier.nodes.map((node) => {
                const Icon = node.icon;
                return (
                  <div
                    key={node.id}
                    style={{ gridColumn: `${node.col} / span ${node.span}` }}
                    className={cn(
                      "flex min-w-0 items-center justify-center gap-1.5 rounded-lg border px-1.5 py-2 text-center text-[10px] leading-tight font-medium sm:text-[11px]",
                      NODE_STYLE[node.status],
                    )}
                    title={node.note}
                  >
                    {Icon ? <Icon className={cn("size-3.5 shrink-0", ICON_STYLE[node.status])} /> : null}
                    <span className="min-w-0 break-words">{node.label}</span>
                  </div>
                );
              })}
            </div>
            {next ? <Connector from={from.map(centerOf)} to={next.nodes.map(centerOf)} /> : null}
          </Fragment>
        );
      })}
    </div>
  );
}
