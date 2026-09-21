"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowRight, Landmark, Loader2, Megaphone, PackageCheck, PackageSearch, Truck } from "lucide-react";
import { ApiError, api, type Product } from "@/lib/api";
import { formatAmount } from "@/lib/format";
import { legalGate } from "@/lib/legal";
import { platformLabel } from "@/lib/marketing";
import { MARKET_LABELS, latestForMarket, marketLabel } from "@/lib/markets";
import {
  EMPTY_PRODUCT_OPERATIONS_DATA,
  loadProductOperationsData,
  type ProductOperationsData,
} from "@/lib/product-channels";
import { regionLabel } from "@/lib/regions";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { NextStepBar } from "@/components/next-step-bar";
import { ProductHeader } from "@/components/product-header";
import { StatusChip } from "@/components/status-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { OperationsPanels } from "./operations-panels";

const INPUT_CLASS = "w-full rounded-md border bg-background px-3 py-2 text-sm";

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}

function ContextItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1 rounded-lg border bg-background/50 p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{children}</dd>
    </div>
  );
}

export function OperationsWorkspace({
  products,
  initialProductId,
  initialData,
  initialMarket,
}: {
  products: Product[];
  initialProductId?: string;
  initialData: ProductOperationsData;
  initialMarket: string;
}) {
  const router = useRouter();

  const [productId, setProductId] = useState(initialProductId ?? "");
  const [data, setData] = useState(initialData);
  const [market, setMarket] = useState(initialMarket);
  const [changingProduct, setChangingProduct] = useState(false);
  const [loadingProduct, setLoadingProduct] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestProductRequest = useRef(initialProductId ?? "");

  const product = products.find((p) => p.id === productId);
  const record = latestForMarket(data.operations, market);
  const economic = data.economics[0];
  const economicQuote = economic ? data.quotes.find((q) => q.id === economic.supplier_quote_id) : undefined;
  const campaign = data.campaigns.find((c) => c.market === market);
  const legal = latestForMarket(data.legal, market);
  const gate = legal ? legalGate(legal.recommendation) : undefined;

  async function changeProduct(id: string) {
    latestProductRequest.current = id;
    setProductId(id);
    setChangingProduct(false);
    setError(null);
    setLoadingProduct(true);
    try {
      const next = await loadProductOperationsData(id);
      if (latestProductRequest.current !== id) return;
      setData(next);
      setMarket(next.operations[0]?.market ?? market);
    } catch (err) {
      if (latestProductRequest.current !== id) return;
      setData(EMPTY_PRODUCT_OPERATIONS_DATA);
      setError(err instanceof ApiError ? err.detail : "No se pudo cargar el estado operativo del producto.");
    } finally {
      if (latestProductRequest.current === id) setLoadingProduct(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!product) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createOperationsRun({ product_id: product.id, market });
      setData((current) => ({ ...current, operations: [result, ...current.operations] }));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "La simulación de operaciones falló.");
    } finally {
      setSubmitting(false);
    }
  }

  if (products.length === 0 || !product) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            icon={PackageSearch}
            title="Aún no hay productos que operar"
            description="La simulación operativa parte de un producto investigado, con sus análisis económico y legal."
            action={
              <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/research" />}>
                Ir a Investigación
              </Button>
            }
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit}>
        <Card>
          <CardHeader>
            <CardTitle>Producto y contexto</CardTitle>
            <CardAction>
              <Button type="button" variant="ghost" size="xs" onClick={() => setChangingProduct((v) => !v)}>
                Cambiar producto
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-12">
              {changingProduct ? (
                <div className="md:col-span-2 xl:col-span-8">
                  <Field label="Producto" htmlFor="operations-product">
                    <select
                      id="operations-product"
                      value={productId}
                      onChange={(e) => void changeProduct(e.target.value)}
                      className={INPUT_CLASS}
                    >
                      {products.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} · {p.category}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
              ) : null}
              <div className="md:col-span-2 xl:col-span-5">
                <ProductHeader product={product} />
              </div>
              <div className="xl:col-span-3">
                <Field label="Mercado" htmlFor="operations-market">
                  <select
                    id="operations-market"
                    value={market}
                    onChange={(e) => setMarket(e.target.value)}
                    className={INPUT_CLASS}
                  >
                    {Object.entries(MARKET_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <div className="flex items-end xl:col-span-4">
                <Button type="submit" size="lg" className="w-full" disabled={submitting || loadingProduct}>
                  {submitting ? <Loader2 className="animate-spin" /> : <PackageCheck />}
                  {submitting ? "Simulando…" : record ? "Regenerar simulación" : "Generar simulación operativa"}
                </Button>
              </div>
            </div>

            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <ContextItem label="Precio del análisis económico">
                {loadingProduct ? (
                  <Loader2 className="size-4 animate-spin text-muted-foreground" />
                ) : economic ? (
                  formatAmount(economic.sale_price)
                ) : (
                  <Link href={`/economics?product_id=${product.id}`} className="text-xs font-normal text-primary underline">
                    Sin análisis económico
                  </Link>
                )}
              </ContextItem>
              <ContextItem label="Proveedor">
                {loadingProduct ? (
                  <Loader2 className="size-4 animate-spin text-muted-foreground" />
                ) : economicQuote ? (
                  <>
                    <span className="block truncate">{economicQuote.data?.name ?? economicQuote.supplier_id}</span>
                    <span className="block text-xs font-normal text-muted-foreground">
                      {regionLabel(economicQuote.data?.region)} · {economicQuote.lead_time_days} días
                    </span>
                  </>
                ) : (
                  <span className="text-xs font-normal text-muted-foreground">Sin cotización analizada</span>
                )}
              </ContextItem>
              <ContextItem label="Legal Gate">
                {loadingProduct ? (
                  <Loader2 className="size-4 animate-spin text-muted-foreground" />
                ) : gate ? (
                  gate.title
                ) : (
                  <Link href={`/legal?product_id=${product.id}`} className="text-xs font-normal text-primary underline">
                    Sin análisis legal en este mercado
                  </Link>
                )}
              </ContextItem>
              <ContextItem label="Campaña">
                {loadingProduct ? (
                  <Loader2 className="size-4 animate-spin text-muted-foreground" />
                ) : campaign ? (
                  <span className="flex flex-wrap items-center gap-1.5">
                    <StatusChip status={campaign.campaign_status} />
                    <span className="text-xs font-normal text-muted-foreground">{platformLabel(campaign.platform)}</span>
                  </span>
                ) : (
                  <Link
                    href={`/marketing?${new URLSearchParams({ product_id: product.id, market }).toString()}`}
                    className="text-xs font-normal text-primary underline"
                  >
                    Sin campaña en {marketLabel(market)}
                  </Link>
                )}
              </ContextItem>
              <ContextItem label="Pedidos reales">
                <DataProvenanceBadge status="pending" tooltip="AMAZONA aún no recibe ni gestiona pedidos reales." />
              </ContextItem>
            </dl>
            <p className="text-[11px] text-muted-foreground">
              Cada simulación es un pedido de muestra de {marketLabel(market)} con datos reales del producto (plazo del
              proveedor, precio, Legal Gate): no hay pedidos, clientes ni transportistas reales.
            </p>
          </CardContent>
        </Card>
      </form>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo completar la operación</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {record ? (
        <OperationsPanels record={record} economic={economic} quote={economicQuote} />
      ) : (
        <Card>
          <CardContent>
            <EmptyState
              icon={Truck}
              title={`Sin simulación operativa de este producto en ${marketLabel(market)}`}
              description="Pulsa «Generar simulación operativa» para ver aquí el seguimiento de un pedido de muestra, la política de devoluciones y el triaje de soporte."
            />
          </CardContent>
        </Card>
      )}

      <NextStepBar
        steps={[
          { label: "Campaña propuesta", icon: Megaphone, state: campaign ? "done" : "todo" },
          { label: "Simulación operativa", icon: Truck, state: record ? "done" : "current" },
          { label: "Finanzas y control", icon: Landmark, state: record ? "current" : "todo" },
        ]}
        action={
          <Button type="button" disabled={!record} onClick={() => router.push("/cfo")}>
            Ir a Finanzas y control
            <ArrowRight />
          </Button>
        }
      />
    </div>
  );
}
