"use client";

import { useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { periodLabel } from "@/lib/revenue-view";
import { REVENUE_PERIODS } from "@/lib/revenue-query";

/** Periodo de las pantallas que leen el registro de ingresos (Panel y Finanzas).
 *
 * Es **navegación, no estado**: cambia `?dias=` y deja que el servidor vuelva a leer. Así la lectura se hace donde se
 * hace siempre —en el servidor, con el token de la petición— y nada de esto escribe en el backend. */
export function PeriodSelect({ days, label = "Periodo de los ingresos" }: { days: number; label?: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
      <span className="sr-only">{label}</span>
      <select
        value={days}
        aria-label={label}
        onChange={(event) => {
          const next = Number(event.target.value);
          startTransition(() => router.replace(`${pathname}?dias=${next}`, { scroll: false }));
        }}
        className="rounded-md border bg-background px-2 py-1 text-xs text-foreground"
      >
        {REVENUE_PERIODS.map((value) => (
          <option key={value} value={value}>
            {periodLabel(value)}
          </option>
        ))}
      </select>
    </label>
  );
}
