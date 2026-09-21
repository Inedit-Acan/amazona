import { api, type Product } from "@/lib/api";
import { EMPTY_PRODUCT_OPERATIONS_DATA, loadProductOperationsData } from "@/lib/product-channels";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { OperationsWorkspace } from "./operations-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function OperationsPage({ searchParams }: PageProps<"/operations">) {
  const params = await searchParams;
  const requestedProductId = first(params.product_id);
  const requestedMarket = first(params.market);

  let products: Product[] = [];
  let data = EMPTY_PRODUCT_OPERATIONS_DATA;
  let productId: string | undefined;
  let error: string | null = null;

  try {
    products = await api.listProducts();
    productId = products.find((p) => p.id === requestedProductId)?.id ?? products[0]?.id;
    if (productId) data = await loadProductOperationsData(productId);
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  // El mercado pedido manda; si no, el del último informe; si no, EE. UU.
  const market = requestedMarket ?? data.operations[0]?.market ?? "us";

  return (
    <div>
      <PageHeader
        title="Operaciones"
        description="Simula un pedido de muestra con seguimiento, la coordinación con el proveedor, la política de devoluciones y el triaje de soporte (IA vs persona) a partir de datos reales de producto, abastecimiento, precio y legal. Fase 3, Agente 8. Todavía no es el Control Tower de la spec: no hay pedidos, clientes, transportistas ni ticketing reales."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <OperationsWorkspace
          products={products}
          initialProductId={productId}
          initialData={data}
          initialMarket={market}
        />
      )}
    </div>
  );
}
