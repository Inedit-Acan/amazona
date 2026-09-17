import { Fragment } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export type ServiceMapStatus = "active" | "error" | "idle";

export interface ServiceMapNode {
  id: string;
  label: string;
  status: ServiceMapStatus;
  /** Why it's idle/not colored — shown as a tooltip-less caption, never silently omitted. */
  note?: string;
}

const STATUS_DOT: Record<ServiceMapStatus, string> = {
  active: "bg-emerald-500",
  error: "bg-red-500",
  idle: "bg-muted-foreground/40",
};

/** 2.5D service topology (parte2.md §9.8) — every node the spec
 * describes is shown for context, but only the ones this backend
 * actually reports health for (database, Supabase configuration, and
 * API reachability itself) are colored active/error. The rest stay
 * idle with a `note` explaining there's no real signal for them yet —
 * never guessed. */
export function ServiceMap({ nodes }: { nodes: ServiceMapNode[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {nodes.map((node, i) => (
        <Fragment key={node.id}>
          <div
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium",
              node.status === "idle" ? "text-muted-foreground" : "text-foreground",
            )}
            title={node.note}
          >
            <span className={cn("size-1.5 rounded-full", STATUS_DOT[node.status])} />
            {node.label}
          </div>
          {i < nodes.length - 1 ? <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" /> : null}
        </Fragment>
      ))}
    </div>
  );
}
