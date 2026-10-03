import { api } from "@/lib/api-server";
import { type Agent, type AgentExecution, type Approval, type EconomicAnalysis, type LegalAnalysis, type MarketingCampaign, type PipelineReview, type Product, type Storefront, type SupplierQuoteDetail } from "@/lib/api";
import { projectCodeFor } from "@/lib/projects-view";
import { parseRevenueDays, REVENUE_ENTRIES_PAGE_SIZE, revenueWindow } from "@/lib/revenue-query";
import { settle } from "@/lib/revenue-view";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { DASHBOARD_DESCRIPTION, DASHBOARD_TITLE } from "./copy";
import { DashboardWorkspace } from "./dashboard-workspace";

/** Tope de productos de los que se lee el pipeline: no hay endpoint agregado y
 * cada producto cuesta cinco peticiones. */
const PRODUCT_LIMIT = 8;

export interface DashboardProductData {
  product: Product;
  quotes: SupplierQuoteDetail[];
  economics: EconomicAnalysis[];
  legal: LegalAnalysis[];
  storefronts: Storefront[];
  campaigns: MarketingCampaign[];
  /** Código del proyecto de ese producto (pantalla de Proyectos). */
  projectCode: string;
  market: string;
  /** Cuántos análisis tiene: el más avanzado es el que ilustra las decisiones. */
  depth: number;
}

export default async function DashboardPage({ searchParams }: PageProps<"/dashboard">) {
  const params = await searchParams;
  let products: Product[] = [];
  let error: string | null = null;

  try {
    products = await api.listProducts();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

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

  // Todo lo demás es opcional: el Panel resume lo que haya y declara lo que falte.
  const [agents, executions, approvals, reviews] = await Promise.all([
    api.listAgents().catch((): Agent[] => []),
    api.listAgentExecutions().catch((): AgentExecution[] => []),
    api.listApprovals().catch((): Approval[] => []),
    api.listPipelineReviews().catch((): PipelineReview[] => []),
  ]);

  const data: DashboardProductData[] = await Promise.all(
    products.slice(0, PRODUCT_LIMIT).map(async (product, index) => {
      const [quotes, economics, legal, storefronts, campaigns] = await Promise.all([
        api.listProductSuppliers(product.id).catch(() => []),
        api.listProductEconomics(product.id).catch(() => []),
        api.listProductLegal(product.id).catch(() => []),
        api.listProductStorefronts(product.id).catch(() => []),
        api.listProductCampaigns(product.id).catch(() => []),
      ]);
      return {
        product,
        quotes,
        economics,
        legal,
        storefronts,
        campaigns,
        projectCode: projectCodeFor(index),
        market: storefronts[0]?.market ?? legal[0]?.market ?? "eu",
        depth: quotes.length + economics.length + legal.length + storefronts.length + campaigns.length,
      };
    }),
  );

  if (error) {
    return (
      <div>
        <PageHeader title={DASHBOARD_TITLE} description={DASHBOARD_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  // El instante (`now`) se fija en el servidor: las solicitudes de demostración son deterministas a partir de él, así
  // que el cliente hidrata exactamente lo mismo.
  return (
    <DashboardWorkspace
      data={data}
      products={products}
      agents={agents}
      executions={executions}
      approvals={approvals}
      reviews={reviews}
      now={now}
      days={days}
      revenue={{ window: span, summary, series, entries }}
    />
  );
}
