"use client";

import { useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CalendarClock,
  CheckCircle2,
  Clock,
  Landmark,
  PackageCheck,
  RotateCcw,
  ShoppingCart,
  Wallet,
} from "lucide-react";
import { ApiError, api, type Order } from "@/lib/api";
import { downloadCsv, toCsv } from "@/lib/csv";
import { formatInteger } from "@/lib/format";
import {
  FULFILLMENT_STATUS,
  ORDER_STATUS,
  PARTIAL_FIGURE_NOTE,
  PERIODS,
  TABS,
  appendPage,
  attentionList,
  attentionText,
  countText,
  describe,
  formatAmount,
  formatTotals,
  fulfilmentPipeline,
  fulfilmentTotal,
  loadedFromPage,
  newestFirst,
  orderKpis,
  ordersInPeriod,
  pageErrorText,
  periodCoverage,
  type OrdersLoaded,
} from "@/lib/orders-view";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { KpiCard } from "@/components/kpi-card";
import { LevelChip } from "@/components/level-chip";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OPERATIONS_DESCRIPTION, OPERATIONS_TITLE } from "./copy";
import {
  AbsentCard,
  AttentionCard,
  LoadedBanner,
  NoOrders,
  OrderDetailCard,
  PipelineCard,
  formatDay,
  shortId,
} from "./operations-panels";

/** Guarda el estado de la pantalla en la URL sin recargar el servidor. */
function syncUrl(params: Record<string, string | undefined>) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  }
  window.history.replaceState(null, "", url);
}

/** Cuántas unidades pide un pedido, sumando sus líneas. */
function unitsOf(order: Order): number {
  return order.items.reduce((sum, item) => sum + item.quantity, 0);
}

/** Resumen de los fulfillments de un pedido: «2 · 1 enviado». Vacío si no tiene. */
function fulfilmentSummary(order: Order): string {
  if (order.fulfillments.length === 0) return "—";
  const counts = new Map<string, number>();
  for (const fulfillment of order.fulfillments) counts.set(fulfillment.status, (counts.get(fulfillment.status) ?? 0) + 1);
  return [...counts.entries()].map(([status, count]) => `${count} ${describe(FULFILLMENT_STATUS, status).label.toLowerCase()}`).join(" · ");
}

export function OperationsWorkspace({
  initialOrders,
  initialHasMore,
  initialNextCursor,
  pageSize,
  names,
  today,
  initialPeriod,
  initialTab,
  initialOrderId,
}: {
  /** La primera página de `GET /api/orders`: los pedidos más recientes, no necesariamente todos. */
  initialOrders: Order[];
  /** El backend dice que existen pedidos más antiguos que el último de `initialOrders`. */
  initialHasMore: boolean;
  /** De dónde sigue la siguiente página (se devuelve tal cual al backend). */
  initialNextCursor: string | null;
  /** Cuántos pedidos pide cada página. */
  pageSize: number;
  /** Nombre real de cada producto, por id. Si no se conoce, la pantalla enseña el id. */
  names: [string, string][];
  today: string;
  initialPeriod?: string;
  initialTab?: string;
  initialOrderId?: string;
}) {
  const [period, setPeriod] = useState(() => (PERIODS.some((p) => p.value === initialPeriod) ? initialPeriod! : "all"));
  const [tab, setTab] = useState(() => (TABS.some((t) => t.key === initialTab) ? initialTab! : "todos"));
  const [orderId, setOrderId] = useState<string | null>(initialOrderId ?? null);
  // Lo cargado hasta ahora y si el backend dice que hay más. Esta pantalla nunca da una página por el total.
  const [loaded, setLoaded] = useState<OrdersLoaded>(() =>
    loadedFromPage({ items: initialOrders, has_more: initialHasMore, next_cursor: initialNextCursor }),
  );
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const orders = loaded.orders;

  async function loadMore() {
    if (inFlight.current || !loaded.hasMore || loaded.nextCursor === null) return;
    inFlight.current = true;
    setLoading(true);
    setLoadError(null);
    try {
      const page = await api.listOrders({ limit: pageSize, cursor: loaded.nextCursor });
      setLoaded((current) => appendPage(current, page));
    } catch (err) {
      setLoadError(
        err instanceof ApiError
          ? pageErrorText(err.status, err.detail)
          : pageErrorText(undefined, err instanceof Error ? err.message : "error desconocido"),
      );
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  const nameById = useMemo(() => new Map(names), [names]);
  const days = PERIODS.find((p) => p.value === period)!.days;
  const periodOrders = useMemo(() => newestFirst(ordersInPeriod(orders, today, days)), [orders, today, days]);
  const coverage = useMemo(() => periodCoverage(loaded, today, days), [loaded, today, days]);
  const partial = coverage === "partial";
  const kpis = useMemo(() => orderKpis(periodOrders), [periodOrders]);
  const stages = useMemo(() => fulfilmentPipeline(periodOrders), [periodOrders]);
  const attention = useMemo(() => attentionList(periodOrders), [periodOrders]);
  const tabRows = useMemo(() => periodOrders.filter(TABS.find((t) => t.key === tab)!.match), [periodOrders, tab]);
  const selected = periodOrders.find((o) => o.id === orderId) ?? tabRows[0] ?? periodOrders[0];

  function changePeriod(value: string) {
    setPeriod(value);
    syncUrl({ periodo: value });
  }

  function changeTab(value: string) {
    setTab(value);
    syncUrl({ estado: value });
  }

  function selectOrder(id: string) {
    setOrderId(id);
    syncUrl({ pedido: id });
  }

  function exportOrders() {
    const csv = toCsv(
      ["Pedido", "Creado", "Estado", "Mercado", "Unidades", "Importe", "Cobrado", "Fulfillments", "Atención"],
      tabRows.map((o) => [
        o.id,
        o.created_at,
        describe(ORDER_STATUS, o.status).label,
        o.market,
        unitsOf(o),
        formatAmount(o.amount_due),
        formatTotals(orderKpis([o]).captured) ?? "",
        fulfilmentSummary(o),
        o.attention_reasons.map(attentionText).join("; "),
      ]),
    );
    downloadCsv(`operaciones-${period}-${tab}${partial ? "-parcial" : ""}.csv`, csv);
  }

  const columns: DataTableColumn<Order>[] = [
    {
      key: "id",
      header: "Pedido",
      cell: (o) => (
        <span className="font-medium whitespace-nowrap" title={o.id}>
          #{shortId(o.id)}
        </span>
      ),
      sortValue: (o) => o.id,
      exportValue: (o) => o.id,
    },
    {
      key: "date",
      header: "Creado",
      cell: (o) => <span className="whitespace-nowrap">{formatDay(o.created_at)}</span>,
      sortValue: (o) => Date.parse(o.created_at),
      exportValue: (o) => o.created_at,
    },
    {
      key: "status",
      header: "Estado",
      cell: (o) => {
        const status = describe(ORDER_STATUS, o.status);
        return <LevelChip tone={status.tone}>{status.label}</LevelChip>;
      },
      sortValue: (o) => describe(ORDER_STATUS, o.status).label,
      exportValue: (o) => describe(ORDER_STATUS, o.status).label,
    },
    { key: "market", header: "Mercado", cell: (o) => o.market, sortValue: (o) => o.market, exportValue: (o) => o.market },
    {
      key: "units",
      header: "Unidades",
      cell: (o) => formatInteger(unitsOf(o)),
      sortValue: (o) => unitsOf(o),
      exportValue: (o) => unitsOf(o),
      align: "right",
    },
    {
      key: "amount",
      header: "Importe",
      cell: (o) => <span className="whitespace-nowrap">{formatAmount(o.amount_due)}</span>,
      sortValue: (o) => Number(o.amount_due.amount),
      exportValue: (o) => formatAmount(o.amount_due),
      align: "right",
    },
    {
      key: "fulfilment",
      header: "Fulfillment",
      cell: (o) => <span className="block max-w-48 whitespace-normal leading-tight">{fulfilmentSummary(o)}</span>,
      sortValue: (o) => o.fulfillments.length,
      exportValue: (o) => fulfilmentSummary(o),
    },
    {
      key: "attention",
      header: "Atención",
      cell: (o) =>
        o.attention_required ? (
          <AlertTriangle className="size-4 text-destructive" aria-label={`Requiere atención: ${o.attention_reasons.map(attentionText).join("; ")}`} />
        ) : (
          <CheckCircle2 className="size-4 text-primary" aria-label="Sin avisos" />
        ),
      sortValue: (o) => o.attention_reasons.length,
      exportValue: (o) => o.attention_reasons.map(attentionText).join("; "),
    },
  ];

  const header = (
    <PageHeader
      title={OPERATIONS_TITLE}
      description={OPERATIONS_DESCRIPTION}
      actions={
        <>
          <LevelChip tone="neutral">Datos reales · eventos simulados</LevelChip>
          <label className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
            <CalendarClock className="size-4 shrink-0 text-primary" />
            <span className="sr-only">Periodo</span>
            <select value={period} onChange={(e) => changePeriod(e.target.value)} className="bg-transparent text-sm font-medium text-primary outline-none">
              {PERIODS.map((p) => (
                <option key={p.value} value={p.value} className="bg-popover text-foreground">
                  {p.value === "all" && loaded.hasMore ? "Todo lo cargado" : p.label}
                </option>
              ))}
            </select>
          </label>
          <Button variant="outline" onClick={exportOrders} disabled={tabRows.length === 0}>
            Exportar informe
          </Button>
        </>
      }
    />
  );

  if (periodOrders.length === 0) {
    return (
      <div className="space-y-5">
        {header}
        <NoOrders loaded={orders.length} hasMore={loaded.hasMore} onLoadMore={loadMore} loading={loading} />
        {loadError ? (
          <LoadedBanner loaded={orders.length} hasMore={loaded.hasMore} loading={loading} error={loadError} onLoadMore={loadMore} />
        ) : null}
        <AbsentCard />
      </div>
    );
  }

  const captured = formatTotals(kpis.captured);
  const refunded = formatTotals(kpis.refunded);
  const inProgress = formatTotals(kpis.refundInProgress);

  // Un contador es un total solo si lo cargado cubre el periodo; si no, es un mínimo («12+»), y se dice.
  const count = (n: number) => countText(formatInteger(n), coverage);
  const partialCaption = partial ? "Mínimo: hay pedidos sin cargar" : undefined;

  return (
    <div className="space-y-5">
      {header}

      <LoadedBanner loaded={orders.length} hasMore={loaded.hasMore} loading={loading} error={loadError} onLoadMore={loadMore} />

      <section className="grid gap-4 grid-cols-2 md:grid-cols-3 xl:grid-cols-6" aria-label="Pedidos por estado">
        <KpiCard label="Pedidos" leading={<ShoppingCart className="size-8 shrink-0 text-primary" />} value={count(kpis.total)} caption={partialCaption} />
        <KpiCard label="Pendientes de cobro" leading={<Clock className="size-8 shrink-0 text-primary" />} value={count(kpis.awaitingPayment)} caption={partialCaption} />
        <KpiCard label="Pagados" leading={<PackageCheck className="size-8 shrink-0 text-primary" />} value={count(kpis.paid)} caption={partialCaption} />
        <KpiCard label="Completados" leading={<CheckCircle2 className="size-8 shrink-0 text-primary" />} value={count(kpis.completed)} caption={partialCaption} />
        <KpiCard label="Cancelados" leading={<Ban className="size-8 shrink-0 text-primary" />} value={count(kpis.cancelled)} caption={partialCaption} />
        <KpiCard
          label="Requieren atención"
          leading={<AlertTriangle className={kpis.attention > 0 ? "size-8 shrink-0 text-destructive" : "size-8 shrink-0 text-primary"} />}
          value={count(kpis.attention)}
          caption={partialCaption}
          tone={kpis.attention > 0 ? "danger" : "default"}
        />
      </section>

      <section className="grid gap-4 sm:grid-cols-2" aria-label="Dinero">
        <KpiCard
          label="Cobrado"
          leading={<Wallet className="size-8 shrink-0 text-primary" />}
          value={captured ?? "—"}
          caption={
            partial
              ? `${PARTIAL_FIGURE_NOTE}${captured ? "" : ": sin cobros entre ellos"}`
              : captured
                ? "Dinero realmente cobrado, por evidencia verificada"
                : "Sin cobros"
          }
        />
        <KpiCard
          label="Reembolsado"
          leading={<RotateCcw className="size-8 shrink-0 text-primary" />}
          value={refunded ?? "—"}
          caption={
            partial
              ? `${PARTIAL_FIGURE_NOTE}${inProgress ? `. Pedido y sin confirmar: ${inProgress}` : ""}`
              : inProgress
                ? `Pedido y sin confirmar: ${inProgress}`
                : refunded
                  ? "Confirmado por un hecho verificado del proveedor"
                  : "Sin reembolsos"
          }
        />
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <PipelineCard stages={stages} total={fulfilmentTotal(periodOrders)} partial={partial} />
        <AttentionCard orders={attention} selectedId={selected?.id ?? null} onSelect={selectOrder} partial={partial} />
      </section>

      <section className="grid gap-4 min-[106.25rem]:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Landmark className="size-4 text-muted-foreground" /> Pedidos
            </CardTitle>
            <CardDescription>
              {loaded.hasMore
                ? "Los pedidos cargados, del más reciente al más antiguo. La búsqueda, el orden y los contadores actúan solo sobre ellos; hay más sin cargar."
                : "Los pedidos que existen en la base de datos, del más reciente al más antiguo."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Tabs value={tab} onValueChange={changeTab}>
              <TabsList className="flex w-full flex-wrap justify-start group-data-horizontal/tabs:h-auto">
                {TABS.map((item) => (
                  <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                    {item.label} ({count(periodOrders.filter(item.match).length)})
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>

            <DataTable
              columns={columns}
              rows={tabRows}
              getRowId={(o) => o.id}
              selectedId={selected?.id ?? null}
              onSelect={(o) => selectOrder(o.id)}
              getSearchText={(o) => `${o.id} ${o.market} ${o.customer_ref} ${describe(ORDER_STATUS, o.status).label}`}
              searchPlaceholder="Buscar pedido, mercado, estado…"
              emptyMessage="Ningún pedido con este filtro."
            />
          </CardContent>
        </Card>

        <OrderDetailCard order={selected} names={nameById} />
      </section>

      <AbsentCard />
    </div>
  );
}
