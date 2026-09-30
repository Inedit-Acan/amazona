"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Plus } from "lucide-react";
import { ApiError, api, type ExchangeRate } from "@/lib/api";
import {
  EMPTY_RATE,
  pairSentence,
  problems,
  ratePayload,
  type ExchangeRateForm as RateForm,
} from "@/lib/exchange-rate-entry";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ingestedOn, splitRates } from "@/lib/fx-source";

const FIELD_CLASS =
  "w-full min-w-0 rounded-md border bg-background/60 px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring";

/** Alta manual de un tipo de cambio (Milestone 40, ADR 0018).
 *
 * Es la única fuente de tipos de cambio que cuesta cero euros: una persona
 * escribe el cambio que le aplicó el banco, con su fecha. Sin esto —o sin una
 * tasa de demostración en un entorno que las admita— un coste en otra moneda
 * deja el análisis **no evaluable**, y nunca se supone 1:1.
 *
 * Lo que este formulario protege sobre todo es la dirección del par, que se lee
 * en palabras debajo de los campos. */
export function ExchangeRateForm({ rates }: { rates: ExchangeRate[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<RateForm>(EMPTY_RATE);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Nunca `Date.now()` dentro del render.
  const today = new Date().toISOString().slice(0, 10);
  const found = problems(form, today);
  const { declared, ecb } = splitRates(rates);

  function set<K extends keyof RateForm>(key: K, value: RateForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    if (found.length > 0) return;
    setSaving(true);
    setError(null);
    try {
      await api.declareExchangeRate(ratePayload(form));
      setForm(EMPTY_RATE);
      setOpen(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "No se pudo guardar el tipo de cambio.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Tipos de cambio declarados</CardTitle>
        <CardDescription>
          Sin tasa, un coste en otra moneda deja el análisis sin evaluar. Nunca se supone 1:1.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-[13px]">
        {declared.length === 0 ? (
          <p className="text-muted-foreground">
            Ninguna declarada todavía.
          </p>
        ) : (
          <ul className="space-y-1">
            {declared.slice(0, 5).map((rate) => (
              <li key={rate.id} className="flex justify-between gap-3 border-b py-1 last:border-b-0">
                <span>
                  1 {rate.base_currency} = {rate.rate} {rate.quote_currency}
                  <span className="block text-[11px] text-muted-foreground">
                    vigente el {rate.effective_date} · {rate.source}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}

        {ecb && (
          <div className="rounded-lg border bg-background/40 px-3 py-2">
            <p className="font-medium">Referencia BCE</p>
            <p className="text-muted-foreground">
              {ecb.count} tasas guardadas · la más reciente vigente el {ecb.latestEffectiveDate}
              {ingestedOn(ecb.latestIngestedAt) ? ` · ingerida el ${ingestedOn(ecb.latestIngestedAt)}` : ""}
            </p>
            <p className="text-[11px] text-muted-foreground">
              {ecb.notice.warning} {ecb.notice.attribution}
            </p>
          </div>
        )}

        {!open ? (
          <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
            <Plus className="size-3.5" />
            Declarar un tipo de cambio
          </Button>
        ) : (
          <div className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Moneda de origen</span>
                <input
                  className={FIELD_CLASS}
                  value={form.baseCurrency}
                  onChange={(e) => set("baseCurrency", e.target.value)}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Moneda de destino</span>
                <input
                  className={FIELD_CLASS}
                  value={form.quoteCurrency}
                  onChange={(e) => set("quoteCurrency", e.target.value)}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Tasa</span>
                <input
                  className={FIELD_CLASS}
                  placeholder="0,92"
                  value={form.rate}
                  onChange={(e) => set("rate", e.target.value)}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Vigente el</span>
                <input
                  className={FIELD_CLASS}
                  type="date"
                  max={today}
                  value={form.effectiveDate}
                  onChange={(e) => set("effectiveDate", e.target.value)}
                />
              </label>
              <label className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Quién la sostiene</span>
                <select
                  className={FIELD_CLASS}
                  value={form.provenance}
                  onChange={(e) => set("provenance", e.target.value as RateForm["provenance"])}
                >
                  <option value="declared">La declaro yo</option>
                  <option value="third_party_verified">La emite un tercero</option>
                </select>
              </label>
              {form.provenance === "third_party_verified" && (
                <label className="space-y-1">
                  <span className="text-[11px] text-muted-foreground">Quién la emite</span>
                  <input
                    className={FIELD_CLASS}
                    value={form.declaredBy}
                    onChange={(e) => set("declaredBy", e.target.value)}
                  />
                </label>
              )}
            </div>

            <p className="rounded-md border bg-background/40 px-2.5 py-1.5 font-medium">
              {pairSentence(form)}
            </p>

            {found.length > 0 && (
              <ul className="space-y-0.5 text-xs text-warning">
                {found.map((problem) => (
                  <li key={problem.field}>{problem.message}</li>
                ))}
              </ul>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertTitle>No se guardó</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="flex gap-2">
              <Button size="sm" onClick={save} disabled={saving || found.length > 0}>
                {saving && <Loader2 className="size-3.5 animate-spin" />}
                Guardar
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={saving}>
                Cancelar
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
