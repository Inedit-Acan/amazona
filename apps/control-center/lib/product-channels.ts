import {
  api,
  type EconomicAnalysis,
  type LegalAnalysis,
  type MarketplaceListing,
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
