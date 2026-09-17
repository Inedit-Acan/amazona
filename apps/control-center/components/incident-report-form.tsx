"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type IncidentSeverity } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const OPERATOR_ACTOR = "owner@amazona.local";

/** v1: manual reporting only — a human reports and resolves. See
 * docs/design/AMAZONA_handoff_backend_paneles_pendientes.md §4 for why
 * this deliberately does not auto-create incidents from system
 * signals. */
export function IncidentReportForm() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<IncidentSeverity>("MEDIUM");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.createIncident({
        title,
        description: description || undefined,
        severity,
        actor: OPERATOR_ACTOR,
      });
      setTitle("");
      setDescription("");
      setSeverity("MEDIUM");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to report incident.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="space-y-3" onSubmit={handleSubmit}>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1.5 sm:col-span-2">
          <label htmlFor="incidentTitle" className="text-sm font-medium">
            Título
          </label>
          <input
            id="incidentTitle"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="incidentSeverity" className="text-sm font-medium">
            Severidad
          </label>
          <select
            id="incidentSeverity"
            value={severity}
            onChange={(e) => setSeverity(e.target.value as IncidentSeverity)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
          >
            <option value="LOW">LOW</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="HIGH">HIGH</option>
            <option value="CRITICAL">CRITICAL</option>
          </select>
        </div>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="incidentDescription" className="text-sm font-medium">
          Descripción (opcional)
        </label>
        <textarea
          id="incidentDescription"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo reportar el incidente</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <Button type="submit" size="sm" disabled={submitting || !title}>
        {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
        Reportar incidente
      </Button>
    </form>
  );
}
