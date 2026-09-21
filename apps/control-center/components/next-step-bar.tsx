import { Fragment, type ReactNode } from "react";
import { Check, ChevronRight, type LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface NextStep {
  label: string;
  icon: LucideIcon;
  /** done = ya cumplido, current = el que toca ahora, todo = pendiente en el flujo. */
  state: "done" | "current" | "todo";
}

/** Barra "Siguiente paso en el flujo" que cierra los paneles del pipeline
 * (mockups de Proveedores, Economía, Legal…). Solo describe el flujo y ofrece
 * la acción real siguiente en `action` — no calcula ni simula el estado de los
 * pasos: quien la usa decide cuáles están done/current/todo con datos reales. */
export function NextStepBar({
  title = "Siguiente paso en el flujo",
  steps,
  action,
}: {
  title?: string;
  steps: NextStep[];
  action?: ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 space-y-3">
          <p className="text-sm font-semibold">{title}</p>
          <ol className="flex flex-wrap items-center gap-x-2 gap-y-2">
            {steps.map((step, index) => {
              const Icon = step.icon;
              return (
                <Fragment key={step.label}>
                  <li className="flex items-center gap-2">
                    <span
                      className={cn(
                        "flex size-7 shrink-0 items-center justify-center rounded-full border",
                        step.state === "done" && "border-primary bg-primary text-primary-foreground",
                        step.state === "current" &&
                          "border-primary text-primary shadow-[0_0_10px_-2px_var(--emerald)]",
                        step.state === "todo" && "border-border text-muted-foreground",
                      )}
                    >
                      {step.state === "done" ? <Check className="size-3.5" /> : <Icon className="size-3.5" />}
                    </span>
                    <span
                      className={cn(
                        "text-xs",
                        step.state === "todo" ? "text-muted-foreground" : "font-medium text-foreground",
                      )}
                    >
                      {step.label}
                    </span>
                  </li>
                  {index < steps.length - 1 ? (
                    <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  ) : null}
                </Fragment>
              );
            })}
          </ol>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </CardContent>
    </Card>
  );
}
