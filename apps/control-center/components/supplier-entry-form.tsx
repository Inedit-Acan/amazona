"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Plus } from "lucide-react";
import { ApiError, api, type SupplyCapability } from "@/lib/api";
import { CAPABILITY_LABEL } from "@/lib/sourcing-view";
import {
  EMPTY_ENTRY,
  capabilityPayloads,
  problems,
  quotePayload,
  supplierPayload,
  type SupplierEntryForm,
} from "@/lib/supplier-entry";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const FIELD_CLASS =
  "w-full min-w-0 rounded-md border bg-background/60 px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring";

/** Los campos de texto y número, en el orden en que se rellenan al colgar el
 * teléfono con un proveedor. */
const FIELDS: { key: keyof SupplierEntryForm; label: string; placeholder?: string; type?: string }[] = [
  { key: "name", label: "Nombre *", placeholder: "Fábrica Real S.L." },
  { key: "country", label: "País", placeholder: "ES" },
  { key: "city", label: "Ciudad", placeholder: "Valencia" },
  { key: "website", label: "Web", placeholder: "https://…" },
  { key: "unitPrice", label: "Precio por unidad", placeholder: "6,40" },
  { key: "currency", label: "Moneda", placeholder: "EUR" },
  { key: "moq", label: "MOQ", placeholder: "25" },
  { key: "leadTimeDays", label: "Preparación (días)", placeholder: "7" },
  { key: "transitDays", label: "Transporte (días)", placeholder: "3" },
  { key: "incoterm", label: "Incoterm", placeholder: "DDP" },
  { key: "logisticsCostPerUnit", label: "Coste logístico / unidad", placeholder: "0,42" },
  { key: "paymentTerms", label: "Condiciones de pago", placeholder: "50 % anticipo, 50 % a 30 días" },
  { key: "destinationMarket", label: "Mercado de destino", placeholder: "eu" },
  { key: "validUntil", label: "Válida hasta", type: "date" },
];

/** Alta manual de un proveedor real y su cotización (Milestone 39, ADR 0017).
 *
 * Es la razón de ser del milestone: un precio negociado no lo publica ninguna
 * API, lo trae una persona de una conversación. Y por eso el formulario está
 * hecho al revés de lo normal: **casi nada es obligatorio**, y lo que se deja
 * en blanco viaja como no declarado en vez de como cero. Las capacidades del
 * §16 son de tres estados —sí, no, sin contestar— porque una casilla que manda
 * «no» por omisión inventa siete respuestas por proveedor. */
export function SupplierEntryForm({ productId }: { productId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<SupplierEntryForm>(EMPTY_ENTRY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const found = problems(form);

  function set<K extends keyof SupplierEntryForm>(key: K, value: SupplierEntryForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function cycle(capability: SupplyCapability) {
    setForm((current) => {
      const now = current.capabilities[capability];
      // Sin contestar → sí → no → sin contestar. El tercer estado existe porque
      // «no lo ha dicho» no es «no».
      const next = now === undefined ? true : now ? false : undefined;
      const capabilities = { ...current.capabilities };
      if (next === undefined) delete capabilities[capability];
      else capabilities[capability] = next;
      return { ...current, capabilities };
    });
  }

  async function save() {
    if (found.length > 0) return;
    setSaving(true);
    setError(null);
    try {
      const supplier = await api.createSupplier(supplierPayload(form));
      await api.createSupplierQuote(supplier.id, quotePayload(form, productId));
      for (const capability of capabilityPayloads(form)) {
        await api.declareSupplierCapability(supplier.id, capability);
      }
      setForm(EMPTY_ENTRY);
      setOpen(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "No se pudo guardar el proveedor.");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Plus className="size-3.5" />
        Añadir proveedor real
      </Button>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Añadir un proveedor real</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          Solo el nombre es obligatorio. Lo que dejes en blanco se guarda como{" "}
          <strong>no declarado</strong>, no como cero.
        </p>

        <div className="grid gap-2 sm:grid-cols-2">
          {FIELDS.map(({ key, label, placeholder, type }) => (
            <label key={key} className="space-y-1">
              <span className="text-[11px] text-muted-foreground">{label}</span>
              <input
                className={FIELD_CLASS}
                type={type ?? "text"}
                placeholder={placeholder}
                value={form[key] as string}
                onChange={(e) => set(key, e.target.value as SupplierEntryForm[typeof key])}
              />
            </label>
          ))}
          <label className="space-y-1">
            <span className="text-[11px] text-muted-foreground">Quién sostiene estos datos</span>
            <select
              className={FIELD_CLASS}
              value={form.verification}
              onChange={(e) => set("verification", e.target.value as SupplierEntryForm["verification"])}
            >
              <option value="supplier_claim">Lo dice el proveedor</option>
              <option value="third_party_verified">Verificado por un tercero</option>
            </select>
          </label>
          {form.verification === "third_party_verified" && (
            <label className="space-y-1">
              <span className="text-[11px] text-muted-foreground">Quién verificó *</span>
              <input
                className={FIELD_CLASS}
                placeholder="Bureau Veritas"
                value={form.verifiedBy}
                onChange={(e) => set("verifiedBy", e.target.value)}
              />
            </label>
          )}
        </div>

        <div className="space-y-1.5">
          <p className="text-[11px] text-muted-foreground">
            Capacidades (plan §16). Pulsa para alternar: sin contestar → sí → no.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {(Object.keys(CAPABILITY_LABEL) as SupplyCapability[]).map((capability) => {
              const state = form.capabilities[capability];
              return (
                <button
                  key={capability}
                  type="button"
                  onClick={() => cycle(capability)}
                  className={
                    state === true
                      ? "rounded-full border border-primary/30 bg-primary/15 px-2.5 py-1 text-xs text-primary"
                      : state === false
                        ? "rounded-full border border-warning/30 bg-warning/15 px-2.5 py-1 text-xs text-warning"
                        : "rounded-full border px-2.5 py-1 text-xs text-muted-foreground"
                  }
                >
                  {CAPABILITY_LABEL[capability]}
                  {state === undefined ? " · sin contestar" : state ? " · sí" : " · no"}
                </button>
              );
            })}
          </div>
        </div>

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
            Guardar proveedor
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={saving}>
            Cancelar
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
