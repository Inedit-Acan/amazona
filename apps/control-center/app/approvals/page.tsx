import { api } from "@/lib/api-server";
import { type Agent, type Approval, type EconomicAnalysis, type LegalAnalysis, type MarketingCampaign, type PipelineReview, type Product, type Storefront, type SupplierQuote } from "@/lib/api";
import { projectCodeFor } from "@/lib/projects-view";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { APPROVALS_DESCRIPTION, APPROVALS_TITLE } from "./copy";
import { ApprovalsWorkspace } from "./approvals-workspace";

/** Tope de productos de los que se lee el contexto de las solicitudes. */
const PRODUCT_LIMIT = 6;

export interface ApprovalContextData {
  product: Product;
  quotes: SupplierQuote[];
  economics: EconomicAnalysis[];
  legal: LegalAnalysis[];
  storefronts: Storefront[];
  campaigns: MarketingCampaign[];
  projectCode: string;
  market: string;
  /** Cuántos análisis tiene: el más avanzado es el que ilustra la bandeja. */
  depth: number;
}

export default async function ApprovalsPage() {
  let approvals: Approval[] = [];
  let error: string | null = null;
  try {
    approvals = await api.listApprovals();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  const reviews: PipelineReview[] = await api.listPipelineReviews().catch(() => []);
  const agents: Agent[] = await api.listAgents().catch(() => []);
  const products: Product[] = await api.listProducts().catch(() => []);

  const context: ApprovalContextData[] = await Promise.all(
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
        <PageHeader title={APPROVALS_TITLE} description={APPROVALS_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  const now = new Date().getTime();

  return <ApprovalsWorkspace approvals={approvals} reviews={reviews} agents={agents} context={context} now={now} />;
}
