import { api, type EconomicAnalysis, type OperationsRecord, type Product, type SupplierQuote } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { OPERATIONS_DESCRIPTION, OPERATIONS_TITLE } from "./copy";
import { OperationsWorkspace } from "./operations-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export interface ProductOperations {
  product: Product;
  quotes: SupplierQuote[];
  economics: EconomicAnalysis[];
  operations: OperationsRecord[];
}

export default async function OperationsPage({ searchParams }: PageProps<"/operations">) {
  const params = await searchParams;

  let products: Product[] = [];
  let error: string | null = null;
  try {
    products = await api.listProducts();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  // El Control Tower es global: hace falta el catálogo entero, no un producto.
  // Cada endpoint falla por su cuenta: sin cotizaciones o sin análisis la
  // pantalla sigue en pie con lo que haya.
  const data: ProductOperations[] = await Promise.all(
    products.map(async (product) => ({
      product,
      quotes: await api.listProductSuppliers(product.id).catch(() => []),
      economics: await api.listProductEconomics(product.id).catch(() => []),
      operations: await api.listProductOperations(product.id).catch(() => []),
    })),
  );

  if (error) {
    return (
      <div>
        <PageHeader title={OPERATIONS_TITLE} description={OPERATIONS_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  // El día se fija en el servidor: los pedidos de demostración son deterministas
  // a partir de él y así el cliente hidrata exactamente lo mismo.
  const today = new Date().toISOString().slice(0, 10);

  return (
    <OperationsWorkspace
      data={data}
      today={today}
      initialPeriod={first(params.periodo)}
      initialTab={first(params.estado)}
      initialOrderId={first(params.pedido)}
    />
  );
}
