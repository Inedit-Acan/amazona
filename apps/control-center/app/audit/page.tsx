import { api, type AuditEntry } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default async function AuditPage({ searchParams }: PageProps<"/audit">) {
  const { correlation_id } = await searchParams;
  const correlationId = Array.isArray(correlation_id) ? correlation_id[0] : correlation_id;

  let entries: AuditEntry[] = [];
  let error: string | null = null;

  try {
    entries = await api.listAudit(correlationId);
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div>
      <PageHeader
        title="Audit trail"
        description={
          correlationId
            ? `Showing every action recorded under correlation ID ${correlationId}.`
            : "Every material action, traceable by correlation ID."
        }
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : entries.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No audit entries {correlationId ? "for this correlation ID" : "yet"}.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>Correlation ID</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {new Date(entry.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{entry.actor}</TableCell>
                    <TableCell className="text-sm font-medium">{entry.action}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{entry.resource}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {entry.correlation_id}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
