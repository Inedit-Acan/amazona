import {
  api,
  type EconomicAnalysis,
  type LegalAnalysis,
  type MarketingCampaign,
  type MarketplaceListing,
  type OperationsRecord,
  type Storefront,
  type SupplierQuote,
} from "@/lib/api";

/** Todo lo persistido de un producto que necesita el panel de Tienda y canales. */
export interface ProductChannelData {
  storefronts: Storefront[];
  listings: MarketplaceListing[];
  legal: LegalAnalysis[];
  economics: EconomicAnalysis[];
  quotes: SupplierQuote[];
}

export const EMPTY_PRODUCT_CHANNEL_DATA: ProductChannelData = {
  storefronts: [],
  listings: [],
  legal: [],
  economics: [],
  quotes: [],
};

/** Módulo compartido (sin "use client") para poder llamarlo tanto desde la página
 * de servidor como desde el cliente al cambiar de producto. */
export async function loadProductChannelData(productId: string): Promise<ProductChannelData> {
  const [storefronts, listings, legal, economics, quotes] = await Promise.all([
    api.listProductStorefronts(productId),
    api.listProductMarketplaceListings(productId),
    api.listProductLegal(productId),
    api.listProductEconomics(productId),
    api.listProductSuppliers(productId),
  ]);
  return { storefronts, listings, legal, economics, quotes };
}

/** Lo de arriba más las propuestas de campaña del producto (panel de Marketing). */
export interface ProductMarketingData extends ProductChannelData {
  campaigns: MarketingCampaign[];
}

export const EMPTY_PRODUCT_MARKETING_DATA: ProductMarketingData = { ...EMPTY_PRODUCT_CHANNEL_DATA, campaigns: [] };

export async function loadProductMarketingData(productId: string): Promise<ProductMarketingData> {
  const [channels, campaigns] = await Promise.all([
    loadProductChannelData(productId),
    api.listProductCampaigns(productId),
  ]);
  return { ...channels, campaigns };
}

/** Lo de Marketing más los informes de operaciones del producto (panel de Operaciones). */
export interface ProductOperationsData extends ProductMarketingData {
  operations: OperationsRecord[];
}

export const EMPTY_PRODUCT_OPERATIONS_DATA: ProductOperationsData = { ...EMPTY_PRODUCT_MARKETING_DATA, operations: [] };

export async function loadProductOperationsData(productId: string): Promise<ProductOperationsData> {
  const [marketing, operations] = await Promise.all([
    loadProductMarketingData(productId),
    api.listProductOperations(productId),
  ]);
  return { ...marketing, operations };
}
