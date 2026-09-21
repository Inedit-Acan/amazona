import { api, type Product } from "@/lib/api";
import { EMPTY_PRODUCT_MARKETING_DATA, loadProductMarketingData } from "@/lib/product-channels";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
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

  // El mercado pedido manda; si no, el de la última propuesta; si no, EE. UU.
  const market = requestedMarket ?? data.campaigns[0]?.market ?? "us";

  return (
    <div>
      <PageHeader
        title="Marketing y adquisición"
        description="Diseña una propuesta de campaña — audiencias, creatividad (texto + brief de imagen), estimación de rendimiento y recomendación de presupuesto — a partir de datos reales de producto, precio, legal y tienda. Fase 3, Agente 7. Todo el rendimiento es simulado: sin gasto publicitario real ni credenciales de Meta/Google/TikTok Ads."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <MarketingWorkspace
          products={products}
          initialProductId={productId}
          initialData={data}
          initialMarket={market}
        />
      )}
    </div>
  );
}
