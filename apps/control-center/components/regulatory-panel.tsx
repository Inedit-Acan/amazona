"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Plus, RefreshCw } from "lucide-react";
import { ApiError, api, type LegalAnalysis, type RegulatoryRequirement } from "@/lib/api";
import {
  EMPTY_EVIDENCE,
  EMPTY_REQUIREMENT,
  complianceLabel,
  evidencePayload,
  evidenceProblems,
  existenceLabel,
  existenceNote,
  isRealAnalysis,
  provenanceLabel,
  requirementPayload,
  requirementProblems,
  requirementsFor,
  sourceDatesLine,
  statusInfo,
  type EvidenceForm,
  type RequirementForm,
} from "@/lib/regulatory-requirements";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const FIELD_CLASS =
  "w-full min-w-0 rounded-md border bg-background/60 px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring";

const TONE_CLASS = {
  ok: "border-emerald-500/40 bg-emerald-500/10",
  warn: "border-warning/40 bg-warning/10",
  bad: "border-destructive/40 bg-destructive/10",
  muted: "border-border bg-muted/40",
} as const;

/** Requisitos regulatorios de la UE (Milestone 41, ADR 0019).
 *
 * Tres cuestiones que esta pantalla **no mezcla**: quién declaró que la norma se
 * aplica (una persona), qué dice la fuente de la norma (EUR-Lex) y si el producto
 * tiene evidencia de cumplimiento. Y un resultado, `PASS`, que solo significa que
 * dentro de lo declarado y comprobado no se ha encontrado un bloqueo. */
export function RegulatoryPanel({
  requirements,
  analysis,
  productId,
  productCategory,
}: {
  requirements: RegulatoryRequirement[];
  analysis: LegalAnalysis | undefined;
  productId: string;
  productCategory: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<RequirementForm>({ ...EMPTY_REQUIREMENT, productScope: productCategory });
  const [evidenceFor, setEvidenceFor] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceForm>(EMPTY_EVIDENCE);

  const mine = requirementsFor(requirements, productCategory);
  const others = requirements.length - mine.length;
  const problems = requirementProblems(form);
  const real = isRealAnalysis(analysis) ? analysis : null;
  const results = new Map((real?.data.requirements ?? []).map((r) => [r.requirement_id, r]));

  async function act(key: string, work: () => Promise<unknown>, failure: string) {
    setBusy(key);
    setError(null);
    try {
      await work();
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : failure);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card id="regulatory" className="scroll-mt-4">
      <CardHeader>
        <CardTitle>Requisitos regulatorios de la UE</CardTitle>
        <CardDescription>
          Los declara una persona; la fuente (EUR-Lex) solo comprueba que la norma existe y su vigencia. No decide a
          qué productos se aplica.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-[13px]">
        {real ? (
          <div className={cn("space-y-1.5 rounded-lg border p-3", TONE_CLASS[statusInfo(real.data.legal_status).tone])}>
            <p className="text-sm font-semibold">{statusInfo(real.data.legal_status).title}</p>
            <p>{statusInfo(real.data.legal_status).detail}</p>
            {real.data.reasons && real.data.reasons.length > 0 && real.data.legal_status !== "PASS" ? (
              <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
                {real.data.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
            {real.data.certification_flag_ignored ? (
              <p className="text-xs text-warning">
                La casilla «ya se cuenta con las certificaciones» no se usa aquí: un booleano no es evidencia de un
                requisito. Aporta la evidencia en cada requisito.
              </p>
            ) : null}
            {real.data.disclaimer ? <p className="text-xs text-muted-foreground">{real.data.disclaimer}</p> : null}
          </div>
        ) : analysis ? (
          <Alert>
            <AlertTitle>Este análisis es simulado</AlertTitle>
            <AlertDescription>
              Se hizo sobre un dataset de demostración. Con el proveedor regulatorio en «real» el análisis evalúa los
              requisitos declarados de abajo.
            </AlertDescription>
          </Alert>
        ) : null}

        {mine.length === 0 ? (
          <p className="text-muted-foreground">
            Nadie ha declarado requisitos para «{productCategory}» en la UE. Eso no significa que no los haya: significa
            que nadie ha dicho cuáles se aplican.
            {others > 0 ? ` (Hay ${others} declarados para otros alcances.)` : ""}
          </p>
        ) : (
          <ul className="space-y-3">
            {mine.map((r) => {
              const result = results.get(r.id);
              const note = existenceNote(r.existence);
              return (
                <li key={r.id} className="space-y-2 rounded-lg border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">
                      {r.regulation} <span className="font-mono text-xs text-muted-foreground">{r.celex}</span>
                    </span>
                    <Badge variant="outline">{r.kind === "restriction" ? "Restricción" : "Obligación"}</Badge>
                  </div>
                  <p className="text-muted-foreground">{r.requirement}</p>

                  <dl className="grid gap-1.5 sm:grid-cols-3">
                    <div className="rounded-md bg-muted/40 p-2">
                      <dt className="text-[11px] uppercase text-muted-foreground">1 · Aplicabilidad</dt>
                      <dd>{provenanceLabel(r.applicability_provenance)}</dd>
                      <dd className="text-xs text-muted-foreground">por {r.declared_by}</dd>
                    </div>
                    <div className="rounded-md bg-muted/40 p-2">
                      <dt className="text-[11px] uppercase text-muted-foreground">2 · Existencia y vigencia</dt>
                      <dd>{existenceLabel(r.existence)}</dd>
                      {r.anchor ? (
                        <dd className="text-xs text-muted-foreground">
                          comprobada el {r.anchor.verified_at.slice(0, 10)} · volver a comprobar tras el{" "}
                          {r.anchor.recheck_after.slice(0, 10)}
                        </dd>
                      ) : null}
                    </div>
                    <div className="rounded-md bg-muted/40 p-2">
                      <dt className="text-[11px] uppercase text-muted-foreground">3 · Evidencia de cumplimiento</dt>
                      <dd>{result ? complianceLabel(result.compliance.state) : "Sin evaluar todavía"}</dd>
                    </div>
                  </dl>

                  {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
                  {r.anchor ? (
                    <p className="text-xs text-muted-foreground">
                      {sourceDatesLine(r.anchor.source_effective_from, r.anchor.source_effective_to)}
                      {r.anchor.eli ? (
                        <>
                          {" · "}
                          <a className="underline" href={r.anchor.eli} target="_blank" rel="noreferrer">
                            ELI
                          </a>
                        </>
                      ) : null}
                    </p>
                  ) : null}
                  {r.anchor?.act_type === "directive" && !r.transposition_reference ? (
                    <p className="text-xs text-warning">
                      Es una directiva y no hay transposición nacional declarada: mientras falte, no se puede concluir
                      PASS.
                    </p>
                  ) : null}
                  {result && result.reasons.length > 0 ? (
                    <ul className="list-disc space-y-0.5 pl-4 text-xs text-warning">
                      {result.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  ) : null}

                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy !== null}
                      onClick={() =>
                        void act(`verify:${r.id}`, () => api.verifyRegulatoryRequirement(r.id), "No se pudo comprobar la norma.")
                      }
                    >
                      {busy === `verify:${r.id}` ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                      Comprobar en EUR-Lex
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEvidenceFor(evidenceFor === r.id ? null : r.id)}>
                      Aportar evidencia
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy !== null}
                      onClick={() =>
                        void act(`withdraw:${r.id}`, () => api.withdrawRegulatoryRequirement(r.id), "No se pudo retirar.")
                      }
                    >
                      Retirar
                    </Button>
                  </div>

                  {evidenceFor === r.id ? (
                    <div className="grid gap-2 rounded-md border p-2 sm:grid-cols-2">
                      <label className="space-y-1">
                        <span className="text-[11px] text-muted-foreground">Referencia (nº de certificado…)</span>
                        <input
                          className={FIELD_CLASS}
                          value={evidence.reference}
                          onChange={(e) => setEvidence({ ...evidence, reference: e.target.value })}
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-[11px] text-muted-foreground">Vigente hasta</span>
                        <input
                          className={FIELD_CLASS}
                          type="date"
                          value={evidence.validUntil}
                          onChange={(e) => setEvidence({ ...evidence, validUntil: e.target.value })}
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-[11px] text-muted-foreground">Quién la sostiene</span>
                        <select
                          className={FIELD_CLASS}
                          value={evidence.provenance}
                          onChange={(e) =>
                            setEvidence({ ...evidence, provenance: e.target.value as EvidenceForm["provenance"] })
                          }
                        >
                          <option value="declared">La declaro yo</option>
                          <option value="third_party_verified">La emitió un tercero</option>
                        </select>
                      </label>
                      {evidence.provenance === "third_party_verified" ? (
                        <label className="space-y-1">
                          <span className="text-[11px] text-muted-foreground">Quién la emitió</span>
                          <input
                            className={FIELD_CLASS}
                            value={evidence.issuer}
                            onChange={(e) => setEvidence({ ...evidence, issuer: e.target.value })}
                          />
                        </label>
                      ) : null}
                      {evidenceProblems(evidence).map((message) => (
                        <p key={message} className="text-xs text-warning sm:col-span-2">
                          {message}
                        </p>
                      ))}
                      <div className="sm:col-span-2">
                        <Button
                          size="sm"
                          disabled={busy !== null || evidenceProblems(evidence).length > 0}
                          onClick={() =>
                            void act(
                              `evidence:${r.id}`,
                              async () => {
                                await api.declareComplianceEvidence(productId, evidencePayload(r.id, evidence));
                                setEvidence(EMPTY_EVIDENCE);
                                setEvidenceFor(null);
                              },
                              "No se pudo guardar la evidencia.",
                            )
                          }
                        >
                          Guardar evidencia
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}

        {error ? (
          <Alert variant="destructive">
            <AlertTitle>No se pudo completar</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {!open ? (
          <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
            <Plus className="size-3.5" />
            Declarar un requisito
          </Button>
        ) : (
          <div className="space-y-2 rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">
              Estás declarando que esta norma se aplica al alcance indicado. Es un juicio tuyo: la fuente no lo confirma.
              Solo Derecho de la UE.
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Alcance de producto (categoría)</span>
                <input
                  className={FIELD_CLASS}
                  value={form.productScope}
                  onChange={(e) => setForm({ ...form, productScope: e.target.value })}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">CELEX de la norma</span>
                <input
                  className={FIELD_CLASS}
                  placeholder="32023R0988"
                  value={form.celex}
                  onChange={(e) => setForm({ ...form, celex: e.target.value })}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Nombre de la norma</span>
                <input
                  className={FIELD_CLASS}
                  value={form.regulation}
                  onChange={(e) => setForm({ ...form, regulation: e.target.value })}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Artículo o referencia (opcional)</span>
                <input
                  className={FIELD_CLASS}
                  value={form.reference}
                  onChange={(e) => setForm({ ...form, reference: e.target.value })}
                />
              </label>
              <label className="space-y-1 sm:col-span-2">
                <span className="text-[11px] text-muted-foreground">Requisito</span>
                <textarea
                  className={FIELD_CLASS}
                  rows={2}
                  value={form.requirement}
                  onChange={(e) => setForm({ ...form, requirement: e.target.value })}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Tipo</span>
                <select
                  className={FIELD_CLASS}
                  value={form.kind}
                  onChange={(e) => setForm({ ...form, kind: e.target.value as RequirementForm["kind"] })}
                >
                  <option value="obligation">Obligación: hay que demostrar el cumplimiento</option>
                  <option value="restriction">Restricción: no se puede comercializar sin evidencia</option>
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Transposición nacional (si es directiva)</span>
                <input
                  className={FIELD_CLASS}
                  placeholder="Real Decreto 187/2016"
                  value={form.transposition}
                  onChange={(e) => setForm({ ...form, transposition: e.target.value })}
                />
              </label>
            </div>
            {problems.length > 0 ? (
              <ul className="space-y-0.5 text-xs text-warning">
                {problems.map((problem) => (
                  <li key={problem.field}>{problem.message}</li>
                ))}
              </ul>
            ) : null}
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={busy !== null || problems.length > 0}
                onClick={() =>
                  void act(
                    "declare",
                    async () => {
                      await api.declareRegulatoryRequirement(requirementPayload(form));
                      setForm({ ...EMPTY_REQUIREMENT, productScope: productCategory });
                      setOpen(false);
                    },
                    "No se pudo declarar el requisito.",
                  )
                }
              >
                {busy === "declare" ? <Loader2 className="size-3.5 animate-spin" /> : null}
                Declarar
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={busy !== null}>
                Cancelar
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
