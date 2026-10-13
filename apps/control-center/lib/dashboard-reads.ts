import type {
  Agent,
  AgentExecution,
  Approval,
  EconomicAnalysis,
  LegalAnalysis,
  MarketingCampaign,
  PipelineReview,
  Product,
  Storefront,
  SupplierQuoteDetail,
} from "./api.ts";
import { projectCodeFor } from "./projects-view.ts";
import { listOf, readList, unreadState, type ReadState } from "./read-state.ts";

// Las lecturas del Panel (M46, Commit 6). Eran nueve `.catch(() => [])` repartidos por `app/dashboard/page.tsx`: cada
// error se volvía una lista vacía y de ahí salían cifras, fases y ejecuciones que no eran reales. Aquí cada lectura
// devuelve un `ReadState` y NINGUNA traga su error. Es una función pura sobre una `DashboardSource` inyectable, para
// poder probar —con dobles que fallan de todas las formas— que ningún fallo se convierte en un dato.

/** Tope de productos de los que se lee el pipeline: no hay endpoint agregado y cada producto cuesta cinco peticiones.
 * Los productos que pasan del tope NO se leen: son `unread`, no «sin análisis». */
export const PRODUCT_LIMIT = 8;

/** Lo que el Panel necesita del cliente de la API. `api` lo cumple; las pruebas pasan dobles. */
export interface DashboardSource {
  listProducts(): Promise<Product[]>;
  listAgents(): Promise<Agent[]>;
  listAgentExecutions(): Promise<AgentExecution[]>;
  listApprovals(): Promise<Approval[]>;
  listPipelineReviews(): Promise<PipelineReview[]>;
  listProductSuppliers(productId: string): Promise<SupplierQuoteDetail[]>;
  listProductEconomics(productId: string): Promise<EconomicAnalysis[]>;
  listProductLegal(productId: string): Promise<LegalAnalysis[]>;
  listProductStorefronts(productId: string): Promise<Storefront[]>;
  listProductCampaigns(productId: string): Promise<MarketingCampaign[]>;
}

/** Un producto del catálogo y las cinco lecturas de su pipeline, cada una con su estado. */
export interface CatalogEntry {
  product: Product;
  /** Código del proyecto de ese producto (pantalla de Proyectos). */
  projectCode: string;
  quotes: ReadState<SupplierQuoteDetail[]>;
  economics: ReadState<EconomicAnalysis[]>;
  legal: ReadState<LegalAnalysis[]>;
  storefronts: ReadState<Storefront[]>;
  campaigns: ReadState<MarketingCampaign[]>;
}

export interface DashboardReads {
  products: ReadState<Product[]>;
  agents: ReadState<Agent[]>;
  executions: ReadState<AgentExecution[]>;
  approvals: ReadState<Approval[]>;
  reviews: ReadState<PipelineReview[]>;
  /** Los productos de los que se leyó el pipeline (hasta `PRODUCT_LIMIT`). */
  catalog: CatalogEntry[];
  /** Los productos que NO se leyeron por pasar del tope: `unread`. */
  unreadProductIds: string[];
}

export async function readDashboard(source: DashboardSource): Promise<DashboardReads> {
  const [products, agents, executions, approvals, reviews] = await Promise.all([
    readList(() => source.listProducts(), "el catálogo de productos"),
    readList(() => source.listAgents(), "los agentes"),
    readList(() => source.listAgentExecutions(), "el log de ejecuciones"),
    readList(() => source.listApprovals(), "las aprobaciones"),
    readList(() => source.listPipelineReviews(), "las revisiones de pipeline"),
  ]);

  const all = listOf(products) ?? [];
  const read = all.slice(0, PRODUCT_LIMIT);
  const catalog = await Promise.all(
    read.map(async (product, index): Promise<CatalogEntry> => {
      const [quotes, economics, legal, storefronts, campaigns] = await Promise.all([
        readList(() => source.listProductSuppliers(product.id), "los proveedores del producto"),
        readList(() => source.listProductEconomics(product.id), "los análisis económicos del producto"),
        readList(() => source.listProductLegal(product.id), "los análisis legales del producto"),
        readList(() => source.listProductStorefronts(product.id), "las tiendas del producto"),
        readList(() => source.listProductCampaigns(product.id), "las campañas del producto"),
      ]);
      return { product, projectCode: projectCodeFor(index), quotes, economics, legal, storefronts, campaigns };
    }),
  );

  return {
    products,
    agents,
    executions,
    approvals,
    reviews,
    catalog,
    unreadProductIds: all.slice(PRODUCT_LIMIT).map((product) => product.id),
  };
}

/** El estado `unread` de un producto que no entró en la lectura del pipeline. */
export const OUT_OF_READ_LIMIT = unreadState(`solo se lee el pipeline de los ${PRODUCT_LIMIT} primeros productos`);
