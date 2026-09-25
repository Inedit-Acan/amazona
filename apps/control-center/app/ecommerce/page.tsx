import { api } from "@/lib/api-server";
import { type Product } from "@/lib/api";
import { EMPTY_PRODUCT_CHANNEL_DATA, loadProductChannelData } from "@/lib/product-channels";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { ECOMMERCE_DESCRIPTION, ECOMMERCE_TITLE } from "./copy";
import { EcommerceWorkspace } from "./ecommerce-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function EcommercePage({ searchParams }: PageProps<"/ecommerce">) {
  const params = await searchParams;
  const requestedProductId = first(params.product_id);
  const requestedMarket = first(params.market);

  let products: Product[] = [];
  let data = EMPTY_PRODUCT_CHANNEL_DATA;
  let productId: string | undefined;
  let error: string | null = null;

  try {
    products = await api.listProducts();
    productId = products.find((p) => p.id === requestedProductId)?.id ?? products[0]?.id;
    if (productId) data = await loadProductChannelData(productId);
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  if (error) {
    return (
      <div>
        <PageHeader title={ECOMMERCE_TITLE} description={ECOMMERCE_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  // El mercado pedido manda; si no, el de la última tienda generada; si no, la UE.
  const market = requestedMarket ?? data.storefronts[0]?.market ?? data.listings[0]?.market ?? "eu";
  return <EcommerceWorkspace key={productId} products={products} productId={productId} data={data} initialMarket={market} />;
}
