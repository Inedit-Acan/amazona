import { api } from "@/lib/api-server";
import { readDashboard } from "@/lib/dashboard-reads";
import { parseRevenueDays, REVENUE_ENTRIES_PAGE_SIZE, revenueWindow } from "@/lib/revenue-query";
import { settle } from "@/lib/revenue-view";
import { DashboardWorkspace } from "./dashboard-workspace";

export default async function DashboardPage({ searchParams }: PageProps<"/dashboard">) {
  const params = await searchParams;

  // Los ingresos salen del registro de ingresos verificados (ADR 0030) y son tres lecturas de solo lectura. Cada una
  // devuelve su dato o su error: un fallo se enseña como fallo y NUNCA se sustituye por datos de demostración.
  const now = new Date().getTime();
  const days = parseRevenueDays(params.dias);
  const span = revenueWindow(now, days);
  const [summary, series, entries] = await Promise.all([
    settle(() => api.revenueSummary(span)),
    settle(() => api.revenueSeries(span, "day")),
    settle(() => api.revenueEntries({ window: span, limit: REVENUE_ENTRIES_PAGE_SIZE })),
  ]);

  // Todo lo demás son lecturas que pueden fallar una a una (M46, Commit 6): cada una llega con su estado
  // (`loaded` / `empty` / `unread` / `error`) y NINGUNA convierte su error en una lista vacía. Ver `lib/dashboard-reads.ts`.
  const reads = await readDashboard(api);

  // El instante (`now`) se fija en el servidor: las solicitudes de demostración son deterministas a partir de él, así
  // que el cliente hidrata exactamente lo mismo.
  return <DashboardWorkspace reads={reads} now={now} days={days} revenue={{ window: span, summary, series, entries }} />;
}
