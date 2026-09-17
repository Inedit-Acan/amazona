"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type PipelineKillSwitchState } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function KillSwitchControl() {
  const [state, setState] = useState<PipelineKillSwitchState | null>(null);
  const [reason, setReason] = useState("");
  const [actor, setActor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getPipelineKillSwitch()
      .then(setState)
      .catch(() => undefined);
  }, []);

  async function handleToggle() {
    if (!state) return;
    setError(null);
    setBusy(true);
    try {
      const next = await api.setPipelineKillSwitch({
        enabled: !state.enabled,
        reason: state.enabled ? reason || "no reason given" : undefined,
        actor: actor || "unknown",
      });
      setState(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update the kill switch.");
    } finally {
      setBusy(false);
    }
  }

  if (!state) return null;

  return (
    <Card className="max-w-2xl">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Pipeline kill switch</CardTitle>
        <span
          className={`text-sm font-semibold ${state.enabled ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}`}
        >
          {state.enabled ? "ENABLED" : "DISABLED"}
        </span>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          When disabled, no new pipeline run can start (Milestone 14, ADR 0006) — every attempt is
          rejected until an operator re-enables it.
        </p>
        {!state.enabled && state.reason ? (
          <p className="text-sm text-muted-foreground">Reason: {state.reason}</p>
        ) : null}
        <div className="grid gap-2 sm:grid-cols-2">
          <input
            placeholder="your actor id"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
          />
          {state.enabled ? (
            <input
              placeholder="reason for disabling"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            />
          ) : null}
        </div>
        {error ? (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertTitle>Kill switch update failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        <Button variant={state.enabled ? "destructive" : "default"} disabled={busy} onClick={handleToggle}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : null}
          {state.enabled ? "Disable pipeline" : "Re-enable pipeline"}
        </Button>
      </CardContent>
    </Card>
  );
}
