"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CalendarClock,
  CheckCircle2,
  Clock,
  PackageCheck,
  PackageSearch,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  ShoppingCart,
  Truck,
  type LucideIcon,
} from "lucide-react";
import type { SupplierQuote } from "@/lib/api";
import { DEMO_SALE } from "@/lib/demo/economics";
import {
  DEMO_CHANNELS,
  DEMO_SYNC_SECONDS,
  PERIODS,
  demoKpiDelta,
  type OperatingMode,
} from "@/lib/demo/operations";
import { demoQuotes } from "@/lib/demo/sourcing";
import { demoSku } from "@/lib/demo/storefront";
import { downloadCsv, toCsv } from "@/lib/csv";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import { formatInteger, formatPercent } from "@/lib/format";
import {
  ACTIVE_STATUSES,
  buildOrders,
  carrierPerformance,
  incidentList,
  mapView,
  operationalHealth,
  operationsKpis,
  ordersInPeriod,
  pipelineStages,
  returnsView,
  supplierPerformance,
  type Order,
  type OrderStatus,
  type ProductInput,
  type SupplierInput,
} from "@/lib/operations-view";
import { rankSuppliers } from "@/lib/sourcing-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { ProductOperations } from "./page";
import { OPERATIONS_DESCRIPTION, OPERATIONS_TITLE } from "./copy";
import {
  AutomationsCard,
  CarriersCard,
  HealthCard,
  IncidentsCard,
  LogisticsMapCard,
  OrderTrackingCard,
  ReturnsCard,
  SupplierPerformanceCard,
  formatDay,
  statusTone,
} from "./operations-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: AMAZONA no recibe pedidos reales, así que los pedidos, clientes, canales, transportistas, incidencias, devoluciones, la salud operativa y las automatizaciones son simulados (deterministas por pedido). Real: los productos del catálogo, las cotizaciones de proveedor (origen, plazo y fiabilidad), el precio del análisis económico y, cuando existe, el seguimiento que guardó el agente de operaciones.";

const STATUS_TABS: { key: string; label: string; match: (order: Order) => boolean }[] = [
  { key: "todos", label: "Todos", match: () => true },
  { key: "pendientes", label: "Pendientes", match: (o) => ["confirmed", "supplier", "preparing"].includes(o.status) },
  { key: "transito", label: "En tránsito", match: (o) => o.status === "in_transit" || o.status === "shipped" },
  { key: "retrasados", label: "Retrasados", match: (o) => o.sla !== "ok" && ACTIVE_STATUSES.includes(o.status) },
  { key: "entregados", label: "Entregados", match: (o) => o.status === "delivered" },
  { key: "devueltos", label: "Devueltos", match: (o) => o.status === "returned" },
];

const SLA_TONE: Record<Order["sla"], { tone: LevelTone; icon: LucideIcon; label: string }> = {
  ok: { tone: "ok", icon: CheckCircle2, label: "En SLA" },
  risk: { tone: "warn", icon: Clock, label: "En riesgo" },
  breach: { tone: "bad", icon: AlertTriangle, label: "Excedido" },
};

const RISK_TONE: Record<Order["risk"], LevelTone> = { Bajo: "ok", Medio: "warn", Alto: "bad" };

const INPUT_CLASS = "min-w-0 rounded-md border bg-background px-2.5 py-1.5 text-xs";

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

function quoteToSupplier(quote: SupplierQuote, isDemo: boolean): SupplierInput {
  return {
    id: quote.supplier_id,
    name: quote.data?.name ?? quote.supplier_id,
    region: quote.data?.region ?? "eu",
    leadTimeDays: quote.lead_time_days,
    reliability: quote.reliability_score,
    verified: quote.verified,
    isDemo,
  };
}

function Delta({ value, unit, compare }: { value: number; unit: "pp" | "%" | "días"; compare: string }) {
  if (Math.abs(value) < (unit === "días" ? 0.05 : 0.005)) {
    return <p className="text-xs text-muted-foreground">Sin cambio {compare}</p>;
  }
  const good = unit === "días" ? value <= 0 : value >= 0;
  const Icon = value >= 0 ? ArrowUp : ArrowDown;
  const text =
    unit === "días"
      ? `${Math.abs(value).toLocaleString("es-ES", { maximumFractionDigits: 1 })} días`
      : unit === "pp"
        ? `${Math.abs(value * 100).toLocaleString("es-ES", { maximumFractionDigits: 1 })} pp`
        : formatPercent(Math.abs(value), 0);
  return (
    <p className={cn("flex items-center gap-1 text-xs", good ? "text-primary" : "text-warning")}>
      <Icon className="size-3 shrink-0" />
      {value >= 0 ? "+" : "−"}
      {text} {compare}
    </p>
  );
}

export function OperationsWorkspace({
  data,
  today,
  initialPeriod,
  initialTab,
  initialOrderId,
}: {
  data: ProductOperations[];
  today: string;
  initialPeriod?: string;
  initialTab?: string;
  initialOrderId?: string;
}) {
  const [period, setPeriod] = useState(() => (PERIODS.some((p) => p.value === initialPeriod) ? initialPeriod! : "7d"));
  const [tab, setTab] = useState(() => (STATUS_TABS.some((t) => t.key === initialTab) ? initialTab! : "todos"));
  const [orderId, setOrderId] = useState<string | null>(initialOrderId ?? null);
  const [channel, setChannel] = useState("all");
  const [supplierFilter, setSupplierFilter] = useState("all");
  const [mode, setMode] = useState<OperatingMode>("semi");

  // Productos reales con su proveedor (cotización real si existe; si no, la misma
  // de demostración que recomienda Proveedores) y su precio de Economía.
  const products = useMemo<ProductInput[]>(
    () =>
      data.map(({ product, quotes, economics }) => {
        const real = quotes.length > 0;
        const ranked = rankSuppliers(real ? dedupeQuotesBySupplier(quotes) : demoQuotes(product.id));
        return {
          id: product.id,
          name: product.name,
          sku: demoSku(product.category, product.id),
          price: economics[0]?.sale_price ?? DEMO_SALE.salePrice,
          suppliers: ranked.slice(0, 3).map((r) => quoteToSupplier(r.quote, !real)),
        };
      }),
    [data],
  );

  const allOrders = useMemo(() => buildOrders(products, today), [products, today]);
  const days = PERIODS.find((p) => p.value === period)!.days;
  const compareLabel = days === 1 ? "vs. ayer" : `vs. ${days} d ant.`;
  const periodOrders = useMemo(() => ordersInPeriod(allOrders, today, days), [allOrders, today, days]);

  const suppliers = useMemo(() => {
    const map = new Map<string, SupplierInput>();
    for (const product of products) for (const supplier of product.suppliers) map.set(supplier.id, supplier);
    return [...map.values()];
  }, [products]);

  const kpis = operationsKpis(periodOrders, today, days);
  const stages = pipelineStages(periodOrders);
  const incidents = incidentList(periodOrders);
  const supplierRows = supplierPerformance(periodOrders, suppliers);
  const carrierRows = carrierPerformance(periodOrders);
  const returns = returnsView(periodOrders);
  const health = operationalHealth(kpis, supplierRows, carrierRows);
  const map = mapView(periodOrders);
  // Lo único que el agente de operaciones aporta al Control Tower: su política de
  // devoluciones y su ticket de soporte de ejemplo.
  const agentRecord = data.flatMap((d) => d.operations)[0];

  const tabRows = useMemo(() => {
    const matcher = STATUS_TABS.find((t) => t.key === tab)!.match;
    return periodOrders.filter(
      (o) => matcher(o) && (channel === "all" || o.channel === channel) && (supplierFilter === "all" || o.supplierId === supplierFilter),
    );
  }, [periodOrders, tab, channel, supplierFilter]);

  const selected = periodOrders.find((o) => o.id === orderId) ?? tabRows[0] ?? periodOrders[0];
  const selectedRecord = selected
    ? data.find((d) => d.product.id === selected.productId)?.operations.find((r) => r.market === selected.market)
    : undefined;

  if (data.length === 0) {
    return (
      <div>
        <PageHeader title={OPERATIONS_TITLE} description={OPERATIONS_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState
              icon={PackageSearch}
              title="Aún no hay productos que operar"
              description="El centro de operaciones parte del catálogo: sin productos no hay pedidos que seguir."
            />
          </CardContent>
        </Card>
      </div>
    );
  }

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
      ["Pedido", "Fecha", "Canal", "Producto", "Cliente", "Proveedor", "Estado", "Entrega estimada", "SLA", "Riesgo", "Importe"],
      tabRows.map((o) => [
        o.id,
        formatDay(o.createdAt),
        o.channel,
        o.productName,
        o.customer,
        o.supplierName,
        statusText(o.status),
        formatDay(o.estimatedAt),
        SLA_TONE[o.sla].label,
        o.risk,
        o.amount,
      ]),
    );
    downloadCsv(`operaciones-${period}.csv`, csv);
  }

  const columns: DataTableColumn<Order>[] = [
    { key: "id", header: "Pedido", cell: (o) => <span className="font-medium whitespace-nowrap">#{o.id}</span>, sortValue: (o) => o.id, exportValue: (o) => o.id },
    { key: "date", header: "Fecha", cell: (o) => <span className="whitespace-nowrap">{formatDay(o.createdAt)}</span>, sortValue: (o) => o.createdAt, exportValue: (o) => formatDay(o.createdAt) },
    { key: "channel", header: "Canal", cell: (o) => o.channel, sortValue: (o) => o.channel, exportValue: (o) => o.channel },
    { key: "product", header: "Producto", cell: (o) => <span className="block max-w-44 whitespace-normal leading-tight">{o.productName}</span>, sortValue: (o) => o.productName, exportValue: (o) => o.productName },
    { key: "customer", header: "Cliente", cell: (o) => o.customer, sortValue: (o) => o.customer, exportValue: (o) => o.customer },
    { key: "supplier", header: "Proveedor", cell: (o) => <span className="block max-w-40 whitespace-normal leading-tight">{o.supplierName}</span>, sortValue: (o) => o.supplierName, exportValue: (o) => o.supplierName },
    {
      key: "status",
      header: "Estado",
      cell: (o) => <LevelChip tone={statusTone(o.status)}>{statusText(o.status)}</LevelChip>,
      sortValue: (o) => statusText(o.status),
      exportValue: (o) => statusText(o.status),
    },
    { key: "eta", header: "Entrega est.", cell: (o) => <span className="whitespace-nowrap">{formatDay(o.estimatedAt)}</span>, sortValue: (o) => o.estimatedAt, exportValue: (o) => formatDay(o.estimatedAt) },
    {
      key: "sla",
      header: "SLA",
      cell: (o) => {
        const sla = SLA_TONE[o.sla];
        return <sla.icon className={cn("size-4", o.sla === "ok" ? "text-primary" : o.sla === "risk" ? "text-warning" : "text-destructive")} aria-label={sla.label} />;
      },
      sortValue: (o) => o.sla,
      exportValue: (o) => SLA_TONE[o.sla].label,
    },
    { key: "risk", header: "Riesgo", cell: (o) => <LevelChip tone={RISK_TONE[o.risk]}>{o.risk}</LevelChip>, sortValue: (o) => o.risk, exportValue: (o) => o.risk },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title={OPERATIONS_TITLE}
        description={OPERATIONS_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <RefreshCw className="size-3.5" /> Última sincronización: hace {DEMO_SYNC_SECONDS} s
            </p>
            <label className="flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
              <CalendarClock className="size-4 shrink-0 text-primary" />
              <span className="sr-only">Periodo</span>
              <select value={period} onChange={(e) => changePeriod(e.target.value)} className="bg-transparent text-sm font-medium text-primary outline-none">
                {PERIODS.map((p) => (
                  <option key={p.value} value={p.value} className="bg-popover text-foreground">
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <Button variant="outline" onClick={exportOrders}>
              Exportar informe
            </Button>
          </>
        }
      />

      {/* KPIs */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8" aria-label="Indicadores de operaciones">
        <KpiCard
          label="Pedidos activos"
          leading={<ShoppingCart className="size-8 shrink-0 text-primary" />}
          value={formatInteger(kpis.active)}
          footer={<Delta value={demoKpiDelta("active", 0.15)} unit="%" compare={compareLabel} />}
        />
        <KpiCard
          label="En tránsito"
          leading={<Truck className="size-8 shrink-0 text-primary" />}
          value={formatInteger(kpis.inTransit)}
          footer={<Delta value={demoKpiDelta("transit", 0.15)} unit="%" compare={compareLabel} />}
        />
        <KpiCard
          label="Entregados hoy"
          leading={<PackageCheck className="size-8 shrink-0 text-primary" />}
          value={formatInteger(kpis.deliveredToday)}
          footer={<Delta value={demoKpiDelta("delivered", 0.25)} unit="%" compare={compareLabel} />}
        />
        <KpiCard
          label="A tiempo"
          leading={<Clock className="size-8 shrink-0 text-primary" />}
          value={formatPercent(kpis.onTimeRate)}
          accent={kpis.onTimeRate >= 0.9}
          footer={<Delta value={demoKpiDelta("ontime", 0.03)} unit="pp" compare={compareLabel} />}
        />
        <KpiCard
          label="Incidencias"
          leading={<AlertTriangle className={cn("size-8 shrink-0", kpis.incidents > 0 ? "text-destructive" : "text-primary")} />}
          value={formatInteger(kpis.incidents)}
          tone={kpis.incidents > 0 ? "danger" : "default"}
          footer={<Delta value={demoKpiDelta("incidents", 0.3)} unit="%" compare={compareLabel} />}
        />
        <KpiCard
          label="Devoluciones"
          leading={<RotateCcw className="size-8 shrink-0 text-primary" />}
          value={formatPercent(kpis.returnRate)}
          footer={<Delta value={demoKpiDelta("returns", 0.02)} unit="pp" compare={compareLabel} />}
        />
        <KpiCard
          label="Entrega media"
          leading={<CalendarClock className="size-8 shrink-0 text-primary" />}
          value={`${kpis.avgDeliveryDays.toLocaleString("es-ES", { maximumFractionDigits: 1 })} días`}
          footer={<Delta value={demoKpiDelta("leadtime", 1.5)} unit="días" compare={compareLabel} />}
        />
        <KpiCard
          label="SLA proveedor"
          leading={<ShieldCheck className="size-8 shrink-0 text-primary" />}
          value={formatPercent(kpis.supplierSla)}
          footer={<Delta value={demoKpiDelta("sla", 0.03)} unit="pp" compare={compareLabel} />}
        />
      </section>

      {/* Pipeline · Incidencias · Mapa */}
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1.05fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Pipeline de pedidos</CardTitle>
            <CardDescription>Estado actual de los pedidos abiertos y entregas del periodo.</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="grid grid-cols-3 gap-2">
              {stages.map((stage) => (
                <li key={stage.key} className="min-w-0 rounded-xl border bg-background/40 p-2.5 text-center">
                  <p className="text-[11px] leading-tight text-muted-foreground">{stage.label}</p>
                  <p className="mt-1 text-xl font-semibold">{formatInteger(stage.count)}</p>
                  <p className="text-[11px] text-primary">{formatPercent(periodOrders.length ? stage.count / periodOrders.length : 0, 0)}</p>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>

        <IncidentsCard incidents={incidents} selectedId={selected?.id ?? null} onSelect={selectOrder} ticket={agentRecord?.data?.support_ticket_example} />
        <LogisticsMapCard nodes={map.nodes} routes={map.routes} />
      </section>

      {/* Pedidos recientes · Seguimiento */}
      <section className="grid gap-4 min-[106.25rem]:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Pedidos recientes</CardTitle>
            <CardAction>
              <DataProvenanceBadge status="demo" compact tooltip="Pedidos, clientes y canales de demostración sobre productos y proveedores reales." />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            <Tabs value={tab} onValueChange={changeTab}>
              <TabsList className="flex w-full flex-wrap justify-start group-data-horizontal/tabs:h-auto">
                {STATUS_TABS.map((item) => (
                  <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                    {item.label} ({periodOrders.filter(item.match).length})
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>

            <div className="flex flex-wrap gap-2">
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                Canal
                <select value={channel} onChange={(e) => setChannel(e.target.value)} className={INPUT_CLASS}>
                  <option value="all">Todos</option>
                  {DEMO_CHANNELS.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                Proveedor
                <select value={supplierFilter} onChange={(e) => setSupplierFilter(e.target.value)} className={INPUT_CLASS}>
                  <option value="all">Todos</option>
                  {suppliers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <DataTable
              columns={columns}
              rows={tabRows}
              getRowId={(o) => o.id}
              selectedId={selected?.id ?? null}
              onSelect={(o) => selectOrder(o.id)}
              getSearchText={(o) => `${o.id} ${o.productName} ${o.customer} ${o.supplierName} ${o.channel}`}
              searchPlaceholder="Buscar pedido, producto, cliente…"
              emptyMessage="Sin pedidos con estos filtros."
            />
          </CardContent>
        </Card>

        <OrderTrackingCard order={selected} record={selectedRecord} />
      </section>

      {/* Proveedores · Devoluciones · Transportistas · Salud */}
      <section className="grid gap-4 md:grid-cols-2 min-[112.5rem]:grid-cols-4">
        <SupplierPerformanceCard rows={supplierRows} />
        <ReturnsCard view={returns} policy={agentRecord?.data?.return_policy} />
        <CarriersCard rows={carrierRows} />
        <HealthCard health={health} />
      </section>

      <AutomationsCard mode={mode} onModeChange={setMode} />
    </div>
  );
}

function statusText(status: OrderStatus): string {
  return {
    confirmed: "Confirmado",
    supplier: "Proveedor",
    preparing: "Preparación",
    shipped: "Despachado",
    in_transit: "En tránsito",
    delivered: "Entregado",
    returned: "Devuelto",
  }[status];
}
