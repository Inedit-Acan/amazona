"use client";

import { AlertTriangle, CheckCircle2, Info, Loader2, PackageSearch } from "lucide-react";
import type { Order, OrderFulfillment, OrderItem, OrderPayment, OrderRefund } from "@/lib/api";
import {
  ABSENT,
  FULFILLMENT_STATUS,
  ORDER_STATUS,
  PAYMENT_STATUS,
  REFUND_STATUS,
  attentionText,
  describe,
  formatAmount,
  loadedSummary,
  orderEvents,
  PARTIAL_FIGURE_NOTE,
  type PipelineStage,
  type Tone,
} from "@/lib/orders-view";
import { formatInteger } from "@/lib/format";
import { EmptyState } from "@/components/empty-state";
import { LevelChip } from "@/components/level-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Fecha y hora en UTC: el servidor y el navegador escriben exactamente lo mismo, así que no hay desajuste al hidratar. */
export function formatMoment(iso: string): string {
  const text = new Date(iso).toLocaleString("es-ES", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
  return `${text} UTC`;
}

export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** Un identificador largo se acorta para leerlo; el completo sigue en el `title`. */
export function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

export function StatusChip({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <LevelChip tone={tone}>{children}</LevelChip>;
}

// --- Lo cargado frente a lo que existe ---------------------------------------------------------------------------

/** Dice qué se está viendo: cuántos pedidos están cargados y si hay más. Nunca «X de Y»: el total no se conoce.
 * Con más pedidos sin cargar, además lo avisa y ofrece cargar la siguiente página; si cargarla falla, lo dice con la
 * causa y no pierde lo ya cargado. */
export function LoadedBanner({
  loaded,
  hasMore,
  loading,
  error,
  onLoadMore,
}: {
  loaded: number;
  hasMore: boolean;
  loading: boolean;
  error: string | null;
  onLoadMore: () => void;
}) {
  return (
    <section aria-label="Pedidos cargados" className="space-y-2">
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm",
          hasMore ? "border-amber-500/40 bg-amber-500/5" : "bg-card text-muted-foreground",
        )}
      >
        <div>
          <p className="font-medium" data-testid="loaded-summary">
            {loadedSummary(loaded, hasMore)}
          </p>
          {hasMore ? (
            <p className="text-xs text-muted-foreground">
              Los pedidos van del más reciente al más antiguo. Las cifras de esta pantalla cubren solo los cargados
              mientras haya más sin cargar; los contadores con «+» son un mínimo, no un total.
            </p>
          ) : null}
        </div>
        {hasMore ? (
          <Button variant="outline" onClick={onLoadMore} disabled={loading}>
            {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
            {loading ? "Cargando…" : "Cargar más pedidos"}
          </Button>
        ) : null}
      </div>
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>No se pudo cargar la siguiente página</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}

// --- Pipeline de fulfillment --------------------------------------------------------------------------------------

export function PipelineCard({ stages, total, partial }: { stages: PipelineStage[]; total: number; partial: boolean }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Fulfillment</CardTitle>
        <CardDescription>
          {total === 0
            ? partial
              ? "Ningún pedido cargado tiene un fulfillment; hay más pedidos sin cargar."
              : "Ningún pedido tiene todavía un fulfillment."
            : `${formatInteger(total)}${partial ? "+" : ""} ${total === 1 && !partial ? "fulfillment" : "fulfillments"} en los pedidos de este periodo.`}
          {partial && total > 0 ? ` ${PARTIAL_FIGURE_NOTE}.` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {stages.map((stage) => {
            const tone = describe(FULFILLMENT_STATUS, stage.status).tone;
            return (
              <li
                key={stage.status}
                className={cn(
                  "min-w-0 rounded-xl border bg-background/40 p-2.5 text-center",
                  stage.count > 0 && tone === "bad" && "border-destructive/40",
                  stage.count === 0 && "opacity-60",
                )}
              >
                <p className="text-[11px] leading-tight text-muted-foreground">{stage.label}</p>
                <p className="mt-1 text-xl font-semibold">{formatInteger(stage.count)}</p>
              </li>
            );
          })}
        </ol>
        <p className="mt-3 text-[11px] text-muted-foreground">
          Cada compra y cada envío los ordena una persona; «pudo salir» significa que la petición pudo llegar al
          proveedor y todavía no se sabe el resultado.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Pedidos que piden una mirada ---------------------------------------------------------------------------------

export function AttentionCard({
  orders,
  selectedId,
  onSelect,
  partial,
}: {
  orders: Order[];
  selectedId: string | null;
  onSelect: (orderId: string) => void;
  /** Hay pedidos sin cargar: la lista es un mínimo, y «ninguno» solo se puede afirmar de los cargados. */
  partial: boolean;
}) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Requieren atención
          <LevelChip tone={orders.length > 0 ? "bad" : "ok"}>{partial ? `${orders.length}+` : orders.length}</LevelChip>
        </CardTitle>
        <CardDescription>
          Se calcula al leer, a partir del estado de cobros, reembolsos y fulfillments. El sistema avisa; no arregla nada
          por su cuenta.{partial ? ` ${PARTIAL_FIGURE_NOTE}.` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {orders.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <CheckCircle2 className="size-4 shrink-0 text-primary" />{" "}
            {partial ? "Ningún pedido cargado requiere atención; hay más sin cargar." : "Ningún pedido requiere atención."}
          </p>
        ) : (
          <ul className="space-y-2">
            {orders.slice(0, 6).map((order) => (
              <li key={order.id}>
                <button
                  type="button"
                  onClick={() => onSelect(order.id)}
                  aria-pressed={selectedId === order.id}
                  className={cn(
                    "w-full rounded-lg border p-2 text-left transition",
                    selectedId === order.id ? "border-primary/60 bg-primary/5" : "hover:border-primary/40",
                  )}
                >
                  <span className="block text-[13px] font-medium" title={order.id}>
                    Pedido #{shortId(order.id)}
                  </span>
                  <ul className="mt-1 space-y-0.5">
                    {order.attention_reasons.map((reason) => (
                      <li key={reason} className="flex gap-1.5 text-xs text-muted-foreground">
                        <AlertTriangle className="mt-0.5 size-3 shrink-0 text-destructive" />
                        {attentionText(reason)}
                      </li>
                    ))}
                  </ul>
                </button>
              </li>
            ))}
          </ul>
        )}
        {orders.length > 6 ? (
          <p className="mt-2 text-[11px] text-muted-foreground">Hay {orders.length - 6} más: usa la pestaña «Requieren atención».</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

// --- Detalle de un pedido -----------------------------------------------------------------------------------------

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b py-1 last:border-b-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right font-medium break-words">{children}</dd>
    </div>
  );
}

function Lines({ items, names }: { items: OrderItem[]; names: Map<string, string> }) {
  return (
    <ul className="space-y-1.5 text-xs">
      {items.map((item) => (
        <li key={item.id} className="rounded-lg border bg-background/40 p-2">
          <p className="text-[13px] font-medium">
            Línea {item.line_number} · {names.get(item.product_id) ?? `producto ${shortId(item.product_id)}`}
          </p>
          <p className="text-muted-foreground">
            {item.quantity} × {formatAmount(item.unit_price)} = {formatAmount(item.line_total)} · asignadas a un
            fulfillment: {item.allocated_quantity}/{item.quantity}
          </p>
          <p className="text-muted-foreground">
            {item.unit_cost
              ? `Coste de proveedor declarado: ${formatAmount(item.unit_cost)} por unidad${item.cost_provenance ? ` (${item.cost_provenance})` : ""}`
              : "Coste de proveedor: desconocido (no se trata como cero)"}
          </p>
        </li>
      ))}
    </ul>
  );
}

function Payments({ payments }: { payments: OrderPayment[] }) {
  if (payments.length === 0) return <p className="text-xs text-muted-foreground">Ningún intento de cobro todavía.</p>;
  return (
    <ul className="space-y-1.5 text-xs">
      {payments.map((payment) => {
        const status = describe(PAYMENT_STATUS, payment.status);
        return (
          <li key={payment.id} className="rounded-lg border bg-background/40 p-2">
            <p className="flex flex-wrap items-center gap-2 text-[13px] font-medium">
              Intento {payment.attempt_number}
              <StatusChip tone={status.tone}>{status.label}</StatusChip>
            </p>
            <p className="text-muted-foreground">
              Pedido: {formatAmount(payment.amount)} · cobrado: {formatAmount(payment.captured_amount)}
              {" · "}
              reservado para devolver: {formatAmount(payment.refund_committed_amount)} · devuelto (confirmado):{" "}
              {formatAmount(payment.refunded_amount)}
            </p>
            {payment.duplicate_of_payment_id ? (
              <p className="text-destructive">Segundo cobro confirmado del mismo pedido: el dinero se movió y queda registrado.</p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function Refunds({ refunds }: { refunds: OrderRefund[] }) {
  if (refunds.length === 0) return <p className="text-xs text-muted-foreground">Ningún reembolso.</p>;
  return (
    <ul className="space-y-1.5 text-xs">
      {refunds.map((refund) => {
        const status = describe(REFUND_STATUS, refund.status);
        return (
          <li key={refund.id} className="rounded-lg border bg-background/40 p-2">
            <p className="flex flex-wrap items-center gap-2 text-[13px] font-medium">
              {formatAmount(refund.amount)}
              <StatusChip tone={status.tone}>{status.label}</StatusChip>
            </p>
            <p className="text-muted-foreground">
              Motivo: {refund.reason} · pedido el {formatMoment(refund.requested_at)}
              {refund.status === "SENDING" ? " · el dinero solo se da por devuelto con un hecho verificado del proveedor" : ""}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function Fulfillments({ fulfillments }: { fulfillments: OrderFulfillment[] }) {
  if (fulfillments.length === 0) return <p className="text-xs text-muted-foreground">Ningún fulfillment todavía.</p>;
  return (
    <ul className="space-y-1.5 text-xs">
      {fulfillments.map((fulfillment, index) => {
        const status = describe(FULFILLMENT_STATUS, fulfillment.status);
        const units = fulfillment.items.reduce((sum, item) => sum + item.quantity, 0);
        return (
          <li key={fulfillment.id} className="rounded-lg border bg-background/40 p-2">
            <p className="flex flex-wrap items-center gap-2 text-[13px] font-medium">
              Fulfillment {index + 1} · {units} {units === 1 ? "unidad" : "unidades"}
              <StatusChip tone={status.tone}>{status.label}</StatusChip>
            </p>
            <p className="text-muted-foreground">
              Líneas: {fulfillment.items.map((item) => `${item.line_number} (×${item.quantity})`).join(", ")}
              {fulfillment.purchase_reference ? ` · compra ${fulfillment.purchase_reference}` : ""}
              {fulfillment.tracking_reference ? ` · envío ${fulfillment.tracking_reference}` : ""}
            </p>
            {fulfillment.status === "UNKNOWN_OUTCOME" ? (
              <p className="text-destructive">
                No se sabe si {fulfillment.unknown_phase === "ship" ? "el envío" : "la compra"} salió. No se reintenta ni se
                cancela hasta reconciliarlo o resolverlo.
              </p>
            ) : null}
            {fulfillment.failed_attempts > 0 ? (
              <p className="text-warning">
                {fulfillment.failed_attempts} {fulfillment.failed_attempts === 1 ? "intento fallido" : "intentos fallidos"}
                {fulfillment.last_failure_code ? ` (${fulfillment.last_failure_code})` : ""}
              </p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function OrderDetailCard({ order, names }: { order: Order | undefined; names: Map<string, string> }) {
  if (!order) {
    return (
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>Detalle del pedido</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Elige un pedido en la tabla o en «Requieren atención».</p>
        </CardContent>
      </Card>
    );
  }
  const status = describe(ORDER_STATUS, order.status);
  const events = orderEvents(order);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <span title={order.id}>Pedido #{shortId(order.id)}</span>
          <StatusChip tone={status.tone}>{status.label}</StatusChip>
          <StatusChip tone="neutral">{order.is_simulated ? "Simulado" : "Real"}</StatusChip>
        </CardTitle>
        <CardDescription>
          {order.is_simulated
            ? "Pedido de una simulación: sin pasarela, proveedor ni transportista reales."
            : "Pedido fuera de simulación."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {order.attention_required ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-2 text-xs">
            <p className="flex items-center gap-1.5 font-medium text-destructive">
              <AlertTriangle className="size-3.5" /> Requiere atención
            </p>
            <ul className="mt-1 space-y-0.5 text-muted-foreground">
              {order.attention_reasons.map((reason) => (
                <li key={reason}>{attentionText(reason)}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <dl className="text-xs">
          <Row label="Importe del pedido">{formatAmount(order.amount_due)}</Row>
          <Row label="Mercado">{order.market}</Row>
          <Row label="Referencia de cliente (opaca)">{order.customer_ref}</Row>
          <Row label="Creado">{formatMoment(order.created_at)}</Row>
          {order.paid_at ? <Row label="Pagado">{formatMoment(order.paid_at)}</Row> : null}
        </dl>

        <section className="space-y-1.5">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase">Líneas</h3>
          <Lines items={order.items} names={names} />
        </section>
        <section className="space-y-1.5">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase">Cobros</h3>
          <Payments payments={order.payments} />
        </section>
        <section className="space-y-1.5">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase">Reembolsos</h3>
          <Refunds refunds={order.refunds} />
        </section>
        <section className="space-y-1.5">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase">Fulfillments</h3>
          <Fulfillments fulfillments={order.fulfillments} />
        </section>
        <section className="space-y-1.5">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase">Historia</h3>
          <ol className="space-y-1 border-l pl-3 text-xs">
            {events.map((event, index) => (
              <li key={`${event.at}-${index}`}>
                <span className="font-medium">{event.label}</span>
                {event.detail ? <span className="text-muted-foreground"> · {event.detail}</span> : null}
                <span className="block text-[11px] text-muted-foreground">{formatMoment(event.at)}</span>
              </li>
            ))}
          </ol>
        </section>
      </CardContent>
    </Card>
  );
}

// --- Lo que todavía no existe -------------------------------------------------------------------------------------

export function AbsentCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Info className="size-4 text-muted-foreground" /> Lo que esta pantalla todavía no puede mostrar
        </CardTitle>
        <CardDescription>
          El centro de control anterior enseñaba estas cosas con datos inventados. Ahora se dice que no existen, en lugar
          de rellenarlas.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {ABSENT.map((item) => (
            <li key={item.key} className="rounded-lg border border-dashed p-3 text-xs">
              <p className="text-[13px] font-medium">{item.title}</p>
              <p className="mt-1 text-muted-foreground">{item.why}</p>
              <p className="mt-2 font-medium text-muted-foreground">Sin datos</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/** Ningún pedido en el periodo elegido. Tres casos que no se confunden: no existe ninguno (se afirma solo si todo está
 * cargado), hay pedidos pero fuera del periodo, o el periodo está vacío **entre los cargados** y hay más sin cargar. */
export function NoOrders({
  loaded,
  hasMore,
  onLoadMore,
  loading,
}: {
  loaded: number;
  hasMore: boolean;
  onLoadMore: () => void;
  loading: boolean;
}) {
  const title =
    loaded > 0 ? "Ningún pedido cargado en este periodo" : hasMore ? "Ningún pedido cargado" : "Todavía no hay pedidos";
  const description =
    loaded > 0
      ? `Hay ${formatInteger(loaded)} ${loaded === 1 ? "pedido cargado" : "pedidos cargados"} fuera de este periodo: elige «${hasMore ? "Todo lo cargado" : "Todo el historial"}».${hasMore ? " Hay más pedidos sin cargar." : ""}`
      : hasMore
        ? "Hay pedidos sin cargar."
        : "Un pedido existe cuando se crea desde la API. Esta pantalla solo muestra lo que existe: no genera pedidos de ejemplo.";
  return (
    <Card>
      <CardContent>
        <EmptyState icon={PackageSearch} title={title} description={description} />
        {hasMore ? (
          <div className="flex justify-center pb-2">
            <Button variant="outline" onClick={onLoadMore} disabled={loading}>
              {loading ? "Cargando…" : "Cargar más pedidos"}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
