import { api } from "@/lib/api-server";
import { type OrderPage } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { OPERATIONS_DESCRIPTION, OPERATIONS_TITLE } from "./copy";
import { OperationsWorkspace } from "./operations-workspace";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** Cuántos pedidos pide cada página (`GET /api/orders?limit=`): ~0,5 s de backend con 100 (ver ADR 0028, E8). El backend
 * dice si hay más (`has_more`) y la pantalla lo cuenta; «Cargar más» pide la siguiente con `next_cursor`. */
const PAGE_SIZE = 100;

export default async function OperationsPage({ searchParams }: PageProps<"/operations">) {
  const params = await searchParams;

  // Lo que se enseña son los pedidos que existen: ni uno generado. Si no hay, la pantalla lo dice. Y si hay más de los
  // que caben en la primera página, también: nunca se toma una página por el total.
  let firstPage: OrderPage | null = null;
  let error: string | null = null;
  try {
    firstPage = await api.listOrders({ limit: PAGE_SIZE });
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  if (error || firstPage === null) {
    return (
      <div>
        <PageHeader title={OPERATIONS_TITLE} description={OPERATIONS_DESCRIPTION} />
        <ApiErrorAlert message={error ?? "Error desconocido"} />
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
      initialOrders={firstPage.items}
      initialHasMore={firstPage.has_more}
      initialNextCursor={firstPage.next_cursor}
      pageSize={PAGE_SIZE}
      names={names}
      today={today}
      initialPeriod={first(params.periodo)}
      initialTab={first(params.estado)}
      initialOrderId={first(params.pedido)}
    />
  );
}
