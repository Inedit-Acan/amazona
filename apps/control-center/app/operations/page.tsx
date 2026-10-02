import { api } from "@/lib/api-server";
import { type Order } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { OPERATIONS_DESCRIPTION, OPERATIONS_TITLE } from "./copy";
import { OperationsWorkspace } from "./operations-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** El máximo que el backend devuelve de una vez (`GET /api/orders?limit=`). */
const ORDERS_LIMIT = 500;

export default async function OperationsPage({ searchParams }: PageProps<"/operations">) {
  const params = await searchParams;

  // Lo que se enseña son los pedidos que existen: ni uno generado. Si no hay, la pantalla lo dice.
  let orders: Order[] = [];
  let error: string | null = null;
  try {
    orders = await api.listOrders({ limit: ORDERS_LIMIT });
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  if (error) {
    return (
      <div>
        <PageHeader title={OPERATIONS_TITLE} description={OPERATIONS_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  // Los nombres de producto son un adorno de lectura: sin ellos la pantalla enseña el identificador.
  const products = await api.listProducts().catch(() => []);
  const names: [string, string][] = products.map((product) => [product.id, product.name]);

  // El día se fija en el servidor: el periodo se calcula a partir de él y el cliente hidrata exactamente lo mismo.
  const today = new Date().toISOString().slice(0, 10);

  return (
    <OperationsWorkspace
      orders={orders}
      names={names}
      today={today}
      initialPeriod={first(params.periodo)}
      initialTab={first(params.estado)}
      initialOrderId={first(params.pedido)}
    />
  );
}
