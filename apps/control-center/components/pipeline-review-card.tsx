"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type PipelineReview } from "@/lib/api";
import { StatusChip } from "@/components/status-chip";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";

const APPROVER_ACTOR = "owner@amazona.local";

export function PipelineReviewCard({ review: initialReview }: { review: PipelineReview }) {
  const router = useRouter();
  const [review, setReview] = useState(initialReview);
  const [pending, setPending] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const actionable = review.status === "PENDING";

  async function act(action: "approve" | "reject") {
    setError(null);
    setPending(action);
    try {
      const updated =
        action === "approve"
          ? await api.approvePipelineReview(review.id, APPROVER_ACTOR)
          : await api.rejectPipelineReview(review.id, APPROVER_ACTOR);
      setReview(updated);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Esta revisión de pipeline ya no se puede accionar — ya fue resuelta.");
      } else {
        setError(err instanceof Error ? err.message : "No se pudo actualizar la revisión de pipeline.");
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
            <p className="truncate text-base font-semibold">Revisión de pipeline</p>
            <p className="truncate text-sm text-muted-foreground">
              Ejecución {review.pipeline_run_id.slice(0, 8)}
            </p>
          </div>
          <StatusChip status={review.status} />
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div>
          <p className="text-xs text-muted-foreground">Motivos señalados para revisión</p>
          <ul className="mt-1 list-inside list-disc text-sm">
            {review.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>

        {error ? (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button className="flex-1" disabled={!actionable || pending !== null} onClick={() => act("approve")}>
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
        </div>
      </CardContent>
    </Card>
  );
}
