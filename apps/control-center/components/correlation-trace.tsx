import type { AuditEntry } from "@/lib/api";
import { parseUtc } from "@/lib/dates";

/** Visualizes every audit entry sharing one correlation ID as a
 * chronological chain (parte2.md §8.7 "Correlation Trace") — whatever
 * steps actually happened for that run, in the order the backend
 * recorded them (`GET /api/audit` is ordered by created_at ascending),
 * not a hardcoded "Solicitud -> Economía -> Legal -> ..." sequence: the
 * real chain differs between the CEOOrchestrator flow and the Fase 3
 * pipeline. */
export function CorrelationTrace({ entries }: { entries: AuditEntry[] }) {
  if (entries.length === 0) return null;

  return (
    <ol className="space-y-0">
      {entries.map((entry, index) => (
        <li key={entry.id} className="relative flex gap-3 pb-6 last:pb-0">
          {index < entries.length - 1 ? (
            <span className="absolute top-3 left-[5px] h-full w-px bg-border" aria-hidden />
          ) : null}
          <span className="relative z-10 mt-1.5 size-[11px] shrink-0 rounded-full bg-primary shadow-[0_0_8px_-1px_var(--emerald)]" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <p className="text-sm font-medium">{entry.action}</p>
              <p className="text-xs text-muted-foreground">{new Date(parseUtc(entry.created_at)).toLocaleString("es-ES")}</p>
            </div>
            <p className="text-xs text-muted-foreground">
              {entry.actor} · {entry.resource}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
