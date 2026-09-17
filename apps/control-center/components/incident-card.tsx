"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type Incident } from "@/lib/api";
import { StatusChip } from "@/components/status-chip";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

const SEVERITY_STYLES: Record<Incident["severity"], string> = {
  LOW: "bg-muted text-muted-foreground border-border",
  MEDIUM: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30",
  HIGH: "bg-orange-500/15 text-orange-600 dark:text-orange-400 border-orange-500/30",
  CRITICAL: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
};

const OPERATOR_ACTOR = "owner@amazona.local";

export function IncidentCard({ incident: initialIncident }: { incident: Incident }) {
  const router = useRouter();
  const [incident, setIncident] = useState(initialIncident);
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function resolve() {
    setError(null);
    setResolving(true);
    try {
      const updated = await api.resolveIncident(incident.id, OPERATOR_ACTOR);
      setIncident(updated);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("This incident was already resolved.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to resolve incident.");
      }
    } finally {
      setResolving(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{incident.title}</p>
            <p className="text-xs text-muted-foreground">{new Date(incident.created_at).toLocaleString()}</p>
          </div>
          <div className="flex items-center gap-1.5">
            <Badge variant="outline" className={cn("font-medium", SEVERITY_STYLES[incident.severity])}>
              {incident.severity}
            </Badge>
            <StatusChip status={incident.status} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {incident.description ? <p className="text-sm text-muted-foreground">{incident.description}</p> : null}

        {incident.status === "RESOLVED" && incident.resolved_at ? (
          <p className="text-xs text-muted-foreground">Resuelto: {new Date(incident.resolved_at).toLocaleString()}</p>
        ) : null}

        {error ? (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {incident.status === "OPEN" ? (
          <Button size="sm" variant="outline" disabled={resolving} onClick={resolve}>
            {resolving ? <Loader2 className="size-4 animate-spin" /> : null}
            Marcar como resuelto
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
