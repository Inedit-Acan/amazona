import type { Agent, Approval, EconomicAnalysis, LegalAnalysis, MarketingCampaign, PipelineReview, Product, Storefront, SupplierQuoteDetail } from "./api.ts";
import { approvalsContract, reviewsContract } from "./ceo-block-contracts.ts";
import { projectCodeFor } from "./projects-view.ts";
import { listOf, readList, type ReadState } from "./read-state.ts";

// LAS LECTURAS de /approvals (M47, Commit 6b). Antes eran OCHO `.catch(() => [])`: si fallaban las revisiones de pipeline, el registro de
// agentes, el catálogo o cualquier análisis de un producto, la pantalla lo enseñaba como «no hay nada». Ahora cada lectura es un
// `ReadState`: las aprobaciones y las revisiones (lo REAL) llevan además su contrato de fila, y el contexto que solo sirve para ilustrar
// la demostración (agentes, catálogo y análisis de los productos) anota qué no pudo leer en vez de callarlo.

/** Tope de productos de los que se lee el contexto de la demostración. */
export const PRODUCT_LIMIT = 6;

export interface ApprovalContextData {
  product: Product;
  quotes: SupplierQuoteDetail[];
  economics: EconomicAnalysis[];
  legal: LegalAnalysis[];
  storefronts: Storefront[];
  campaigns: MarketingCampaign[];
  projectCode: string;
  market: string;
  /** Cuántos análisis tiene: el más avanzado es el que ilustra la demostración. */
  depth: number;
}

export interface ApprovalsSource {
  listApprovals(): Promise<Approval[]>;
  listPipelineReviews(): Promise<PipelineReview[]>;
  listAgents(): Promise<Agent[]>;
  listProducts(): Promise<Product[]>;
  listProductSuppliers(productId: string): Promise<SupplierQuoteDetail[]>;
  listProductEconomics(productId: string): Promise<EconomicAnalysis[]>;
  listProductLegal(productId: string): Promise<LegalAnalysis[]>;
  listProductStorefronts(productId: string): Promise<Storefront[]>;
  listProductCampaigns(productId: string): Promise<MarketingCampaign[]>;
}

export interface ApprovalsPageReads {
  /** Lo REAL de la bandeja: cada fuente con su estado de lectura. */
  approvals: ReadState<Approval[]>;
  reviews: ReadState<PipelineReview[]>;
  /** Solo ilustran la demostración. */
  agents: ReadState<Agent[]>;
  products: ReadState<Product[]>;
  contexts: ApprovalContextData[];
  /** Qué parte del contexto de la demostración no se pudo leer («los análisis legales de «X»»). Vacío = todo leído. */
  contextFailures: string[];
}

export async function readApprovalsPage(source: ApprovalsSource): Promise<ApprovalsPageReads> {
  const [approvals, reviews, agents, products] = await Promise.all([
    readList(() => source.listApprovals(), "las aprobaciones"),
    readList(() => source.listPipelineReviews(), "las revisiones de pipeline"),
    readList(() => source.listAgents(), "el registro de agentes"),
    readList(() => source.listProducts(), "el catálogo de productos"),
  ]);

  const contextFailures: string[] = [];
  if (agents.kind === "error") contextFailures.push("el registro de agentes");
  if (products.kind === "error") contextFailures.push("el catálogo de productos");

  const contexts = await Promise.all(
    (listOf(products) ?? []).slice(0, PRODUCT_LIMIT).map(async (product, index) => {
      const [quotes, economics, legal, storefronts, campaigns] = await Promise.all([
        readList(() => source.listProductSuppliers(product.id), "las cotizaciones"),
        readList(() => source.listProductEconomics(product.id), "los análisis económicos"),
        readList(() => source.listProductLegal(product.id), "los análisis legales"),
        readList(() => source.listProductStorefronts(product.id), "las tiendas"),
        readList(() => source.listProductCampaigns(product.id), "las campañas"),
      ]);
      const failures = [
        quotes.kind === "error" ? "las cotizaciones de proveedores" : null,
        economics.kind === "error" ? "los análisis económicos" : null,
        legal.kind === "error" ? "los análisis legales" : null,
        storefronts.kind === "error" ? "las tiendas" : null,
        campaigns.kind === "error" ? "las campañas" : null,
      ].flatMap((label) => (label === null ? [] : [`${label} de «${product.name}»`]));
      const data = {
        product,
        quotes: listOf(quotes) ?? [],
        economics: listOf(economics) ?? [],
        legal: listOf(legal) ?? [],
        storefronts: listOf(storefronts) ?? [],
        campaigns: listOf(campaigns) ?? [],
      };
      return {
        failures,
        context: {
          ...data,
          projectCode: projectCodeFor(index),
          market: data.storefronts[0]?.market ?? data.legal[0]?.market ?? "eu",
          depth: data.quotes.length + data.economics.length + data.legal.length + data.storefronts.length + data.campaigns.length,
        } satisfies ApprovalContextData,
      };
    }),
  );
  for (const entry of contexts) contextFailures.push(...entry.failures);

  return {
    approvals: approvalsContract(approvals),
    reviews: reviewsContract(reviews),
    agents,
    products,
    contexts: contexts.map((entry) => entry.context),
    contextFailures,
  };
}
