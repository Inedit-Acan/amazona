import { api, type Product } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { SourcingWorkspace } from "./sourcing-workspace";

export default async function SourcingPage({ searchParams }: PageProps<"/sourcing">) {
  const { product_id } = await searchParams;
  const initialProductId = Array.isArray(product_id) ? product_id[0] : product_id;

  let products: Product[] = [];
  let error: string | null = null;

  try {
    products = await api.listProducts();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  return (
    <div>
      <PageHeader
        title="Proveedores y abastecimiento"
        description="Encuentra, compara y valida proveedores para tu producto. Analiza costes, logística, fiabilidad y compatibilidad con Amazona. Fase 3, Agente 2 — datos de proveedor y logística simulados por fixtures, sin fuentes reales todavía."
      />

      {error ? <ApiErrorAlert message={error} /> : <SourcingWorkspace products={products} initialProductId={initialProductId} />}
    </div>
  );
}
