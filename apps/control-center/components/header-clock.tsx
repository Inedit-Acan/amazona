"use client";

import { useSyncExternalStore } from "react";

/** Minuto actual; en el servidor null, para no desajustar la hidratación. */
function useMinute(): number | null {
  return useSyncExternalStore(
    (onChange) => {
      const id = window.setInterval(onChange, 15_000);
      return () => window.clearInterval(id);
    },
    () => Math.floor(Date.now() / 60_000),
    () => null,
  );
}

/** Fecha y hora de la cabecera de los paneles («22 sept 2026 / 10:32»). */
export function HeaderClock() {
  const minute = useMinute();
  const now = minute === null ? null : new Date(minute * 60_000);
  return (
    <div className="text-sm leading-tight">
      <p className="text-muted-foreground">
        {now ? now.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" }) : "—"}
      </p>
      <p className="font-medium tabular-nums">
        {now ? now.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }) : ""}
      </p>
    </div>
  );
}
