"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Bell, Search } from "lucide-react";
import { NAV_ITEMS } from "@/components/nav-items";
import { SessionBadge } from "@/components/session-badge";
import { cn } from "@/lib/utils";

/** Live clock — actualiza cada minuto, suficiente para la cabecera
 * (docs/design/AMAZONA_sistema_de_diseno_visual.md §4, "barra superior
 * con ... fecha/hora"). No usa datos simulados: es la hora real del
 * navegador del usuario. */
function useNow() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    // La primera lectura va en un temporizador, no en el cuerpo del efecto:
    // `react-hooks/set-state-in-effect` prohíbe lo segundo. El servidor sigue
    // renderizando null, que es lo que evita el desajuste de hidratación.
    const first = setTimeout(() => setNow(new Date()), 0);
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);
  return now;
}

const DATE_FORMATTER = new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", year: "numeric" });
const TIME_FORMATTER = new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit" });

/** Barra superior compartida por todos los paneles (shell común, §4 del
 * sistema de diseño): búsqueda global, estado del sistema, notificaciones,
 * fecha/hora y la sesión del usuario. Solo escritorio — en móvil el shell
 * ya muestra su propia cabecera compacta. */
export function TopHeader({ className }: { className?: string }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const now = useNow();

  const dateLabel = useMemo(() => (now ? DATE_FORMATTER.format(now) : ""), [now]);
  const timeLabel = useMemo(() => (now ? TIME_FORMATTER.format(now) : ""), [now]);

  function handleSearchSubmit(event: React.FormEvent) {
    event.preventDefault();
    const normalized = query.trim().toLowerCase();
    if (!normalized) return;
    const match = NAV_ITEMS.find((item) => item.label.toLowerCase().includes(normalized));
    if (match) {
      router.push(match.href);
      setQuery("");
    }
  }

  return (
    <header className={cn("items-center justify-between gap-4 border-b bg-card px-6 py-3", className)}>
      <form onSubmit={handleSearchSubmit} className="min-w-0 max-w-sm flex-1">
        <label className="relative block">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar en Amazona…"
            className="w-full rounded-md border bg-background py-1.5 pr-3 pl-9 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </label>
      </form>

      <div className="flex shrink-0 items-center gap-4 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-success shadow-[0_0_6px_var(--success)]" />
          <span className="hidden font-medium text-foreground lg:inline">Sistema operativo</span>
        </div>

        <button
          type="button"
          aria-label="Notificaciones"
          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-panel-hover hover:text-foreground"
        >
          <Bell className="size-4" />
        </button>

        {now ? (
          <span className="hidden whitespace-nowrap sm:inline">
            {dateLabel} · {timeLabel}
          </span>
        ) : null}

        <SessionBadge />
      </div>
    </header>
  );
}
