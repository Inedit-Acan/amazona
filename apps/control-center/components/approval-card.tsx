"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, ChevronDown, Loader2 } from "lucide-react";
import { ApiError, api, type Approval, type Decision, type Project } from "@/lib/api";
import { actionLabel, expiryLabel, isActionable, isExpired } from "@/lib/approvals";
import { formatAmount } from "@/lib/format";
import { StatusChip } from "@/components/status-chip";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";

const APPROVER_ACTOR = "owner@amazona.local";

function findEvidence(decision: Decision, source: string) {
  return decision.evidence.find((e) => e.source === source);
}

export function ApprovalCard({
  approval: initialApproval,
  decision,
  project,
}: {
  approval: Approval;
  decision: Decision | null;
  project: Project | null;
}) {
  const router = useRouter();
  const [approval, setApproval] = useState(initialApproval);
  const [showEvidence, setShowEvidence] = useState(false);
  const [pending, setPending] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const financeEvidence = decision ? findEvidence(decision, "finance_validation") : undefined;
  const legalEvidence = decision ? findEvidence(decision, "legal_validation") : undefined;
  const risks = decision
    ? Array.from(
        new Set(
          decision.evidence.flatMap((e) => {
            const raw = e.data?.risks;
            return Array.isArray(raw) ? (raw as string[]) : [];
          }),
        ),
      )
    : [];

  const financeVeto = Boolean(financeEvidence?.data?.finance_veto);
  const legalStatus = (legalEvidence?.data?.legal_status as string | undefined) ?? "UNKNOWN";
  const actionable = isActionable(approval);
  const expired = isExpired(approval);

  async function act(action: "approve" | "reject") {
    setError(null);
    setPending(action);
    try {
      const updated =
        action === "approve"
          ? await api.approveApproval(approval.id, APPROVER_ACTOR)
          : await api.rejectApproval(approval.id, APPROVER_ACTOR);
      setApproval(updated);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Esta aprobación ya no se puede accionar — ya fue resuelta o expiró.");
      } else {
        setError(err instanceof Error ? err.message : "No se pudo actualizar la aprobación.");
      }
    } finally {
      setPending(null);
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-base font-semibold">{actionLabel(approval.action)}</p>
            {project ? (
              <Link
                href={`/projects/${project.id}`}
                className="truncate text-sm text-muted-foreground underline-offset-4 hover:underline"
              >
                {project.name}
              </Link>
            ) : (
              <p className="text-sm text-muted-foreground">Proyecto desconocido</p>
            )}
          </div>
          <StatusChip status={expired ? "EXPIRED" : approval.status} />
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3">
          <div>
            <p className="text-xs text-muted-foreground">Importe (simulado)</p>
            <p className="font-medium">{approval.amount != null ? formatAmount(approval.amount) : "—"}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Confianza</p>
            <p className="font-medium">{decision?.confidence != null ? decision.confidence.toFixed(2) : "—"}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Recomendación del director ejecutivo</p>
            <p className="font-medium">{decision ? decision.status.replace(/_/g, " ") : "—"}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Estado financiero</p>
            <p className="font-medium">{financeVeto ? "Veto (margen negativo)" : "Sin objeciones"}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Estado legal</p>
            <p className="font-medium">{legalStatus.replace(/_/g, " ")}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Riesgo</p>
            <p className="font-medium">{risks.length > 0 ? `${risks.length} señalados` : "Ninguno señalado"}</p>
          </div>
        </div>

        <p className="text-xs text-muted-foreground">{expiryLabel(approval.expires_at)}</p>

        {error ? (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button
            className="flex-1"
            disabled={!actionable || pending !== null}
            onClick={() => act("approve")}
          >
            {pending === "approve" ? <Loader2 className="size-4 animate-spin" /> : null}
            Aprobar
          </Button>
          <Button
            className="flex-1"
            variant="outline"
            disabled={!actionable || pending !== null}
            onClick={() => act("reject")}
          >
            {pending === "reject" ? <Loader2 className="size-4 animate-spin" /> : null}
            Rechazar
          </Button>
          <Button
            variant="ghost"
            className="sm:flex-none"
            onClick={() => setShowEvidence((v) => !v)}
          >
            Más información
            <ChevronDown className={`size-4 transition-transform ${showEvidence ? "rotate-180" : ""}`} />
          </Button>
        </div>

        {showEvidence && decision ? (
          <div>
            <Separator className="mb-3" />
            <p className="mb-2 text-sm font-medium">Evidencia</p>
            <ul className="space-y-2">
              {decision.evidence.map((e, i) => (
                <li key={i} className="rounded-md border bg-muted/30 p-3 text-sm">
                  <p className="font-medium capitalize">{e.source.replace(/_/g, " ")}</p>
                  <p className="text-muted-foreground">{e.summary}</p>
                  {Array.isArray(e.data?.risks) && (e.data!.risks as string[]).length > 0 ? (
                    <p className="mt-1 text-xs text-destructive">
                      Riesgos: {(e.data!.risks as string[]).join(", ")}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
            {decision.rationale ? (
              <p className="mt-2 text-xs text-muted-foreground">{decision.rationale}</p>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
