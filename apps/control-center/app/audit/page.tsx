import { api, type Agent, type AuditEntry, type Product } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { AUDIT_DESCRIPTION, AUDIT_TITLE } from "./copy";
import { AuditWorkspace } from "./audit-workspace";

export default async function AuditPage() {
  let entries: AuditEntry[] = [];
  let error: string | null = null;

  try {
    entries = await api.listAudit();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }
  // Productos y agentes solo dan contexto (proyecto y nombre del actor): si fallan,
  // el registro se enseña igual.
  const products: Product[] = await api.listProducts().catch(() => []);
  const agents: Agent[] = await api.listAgents().catch(() => []);

  if (error) {
    return (
      <div>
        <PageHeader title={AUDIT_TITLE} description={AUDIT_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  // El instante se fija en el servidor: los eventos de demostración y los KPIs del
  // día se calculan con él y el cliente hidrata exactamente lo mismo.
  const now = new Date().getTime();

  return <AuditWorkspace entries={entries} products={products} agents={agents} now={now} />;
}
