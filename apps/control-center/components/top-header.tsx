"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Bell, CircleCheck, CircleX, LoaderCircle, Search, TriangleAlert, type LucideIcon } from "lucide-react";
import { NAV_ITEMS } from "@/components/nav-items";
import { SessionBadge } from "@/components/session-badge";
import { api } from "@/lib/api";
import {
  checkBackend,
  HEALTH_SCOPE_NOTE,
  healthLabel,
  HealthMonitor,
  INITIAL_HEALTH,
  type BackendHealthState,
  type HealthVerdict,
} from "@/lib/backend-health";
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

/** La salud del backend (M47). Una sola petición activa; se comprueba al montar, al volver a la pestaña, al recuperar el
 * foco y cada 60 s SOLO mientras la pestaña es visible (`lib/backend-health.ts`). El estado inicial es «comprobando»,
 * nunca «operativo». */
function useBackendHealth(): BackendHealthState {
  const [state, setState] = useState<BackendHealthState>(INITIAL_HEALTH);
  useEffect(() => {
    const monitor = new HealthMonitor({
      check: () => checkBackend((signal) => api.getReadiness(signal)),
      now: () => Date.now(),
      onChange: setState,
    });
    const onVisibility = () => monitor.setVisible(document.visibilityState === "visible");
    const onFocus = () => monitor.focus();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onFocus);
    monitor.start(document.visibilityState === "visible");
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
      monitor.dispose();
    };
  }, []);
  return state;
}

/** Icono, color y punto de cada veredicto. El color nunca va solo: lleva icono y texto (visible desde `lg`, y para
 * lectores de pantalla siempre). */
const VERDICT_STYLE: Record<HealthVerdict, { icon: LucideIcon; text: string; dot: string }> = {
  ready: { icon: CircleCheck, text: "text-success", dot: "bg-success shadow-[0_0_6px_var(--success)]" },
  degraded: { icon: TriangleAlert, text: "text-warning", dot: "bg-warning" },
  unavailable: { icon: CircleX, text: "text-destructive", dot: "bg-destructive" },
};

function BackendStatus() {
  const state = useBackendHealth();
  const label = healthLabel(state);
  const refreshing = state.kind === "known" && state.refreshing;
  const style = state.kind === "known" ? VERDICT_STYLE[state.verdict] : null;
  const Icon = state.kind === "checking" ? LoaderCircle : refreshing ? LoaderCircle : style!.icon;
  const checkedAt =
    state.kind === "known"
      ? `Última comprobación: ${new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(state.checkedAt)}${refreshing ? " (actualizando…)" : ""}. `
      : "Todavía sin comprobar. ";
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy={state.kind === "checking" || refreshing}
      title={`${checkedAt}${HEALTH_SCOPE_NOTE}`}
      className="flex items-center gap-1.5"
    >
      <Icon
        aria-hidden
        className={cn("size-3.5 shrink-0", style ? style.text : "text-muted-foreground", (state.kind === "checking" || refreshing) && "animate-spin")}
      />
      <span className={cn("size-2 rounded-full", style ? style.dot : "bg-muted-foreground/50")} aria-hidden />
      <span className={cn("font-medium sr-only lg:not-sr-only", style ? "text-foreground" : "text-muted-foreground")}>{label}</span>
    </div>
  );
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
        <BackendStatus />

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
