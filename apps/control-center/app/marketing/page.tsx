import { api } from "@/lib/api-server";
import { type Product } from "@/lib/api";
import { EMPTY_PRODUCT_MARKETING_DATA, loadProductMarketingData } from "@/lib/product-channels";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { MARKETING_DESCRIPTION, MARKETING_TITLE } from "./copy";
import { MarketingWorkspace } from "./marketing-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function MarketingPage({ searchParams }: PageProps<"/marketing">) {
  const params = await searchParams;
  const requestedProductId = first(params.product_id);
  const requestedMarket = first(params.market);

  let products: Product[] = [];
  let data = EMPTY_PRODUCT_MARKETING_DATA;
  let productId: string | undefined;
  let error: string | null = null;

  try {
    products = await api.listProducts();
    productId = products.find((p) => p.id === requestedProductId)?.id ?? products[0]?.id;
    if (productId) data = await loadProductMarketingData(productId);
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  if (error) {
    return (
      <div>
        <PageHeader title={MARKETING_TITLE} description={MARKETING_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  // El mercado pedido manda; si no, el de la última propuesta de campaña; si no, la UE.
  const market = requestedMarket ?? data.campaigns[0]?.market ?? "eu";
  return <MarketingWorkspace key={productId} products={products} productId={productId} data={data} initialMarket={market} />;
}
