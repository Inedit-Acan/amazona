import { api, type Product } from "@/lib/api";
import { EMPTY_PRODUCT_CHANNEL_DATA, loadProductChannelData } from "@/lib/product-channels";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
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

  // El mercado pedido manda; si no, el de lo último generado; si no, EE. UU.
  const market = requestedMarket ?? data.storefronts[0]?.market ?? data.listings[0]?.market ?? "us";
  // Con un listado de Amazon pero sin tienda en ese mercado, se abre directamente Amazon.
  const hasStorefront = data.storefronts.some((s) => s.market === market);
  const hasListing = data.listings.some((l) => l.market === market);
  const channel = !hasStorefront && hasListing ? "amazon" : "own-store";

  return (
    <div>
      <PageHeader
        title="Tienda y canales de venta"
        description="Genera y gestiona la oferta comercial por canal — tienda propia y marketplaces — para un mismo producto, precio, proveedor y Legal Gate. Fase 3, Agentes 5-6. Son borradores simulados: todavía no hay tienda, dominio ni procesamiento de pagos reales."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <EcommerceWorkspace
          products={products}
          initialProductId={productId}
          initialData={data}
          initialMarket={market}
          initialChannel={channel}
        />
      )}
    </div>
  );
}
