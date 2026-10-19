import type { BudgetFigures, BudgetRead } from "./api.ts";
import { formatUtcDateTime } from "./ceo-block-view.ts";
import { parseUtc } from "./dates.ts";
import { add, isNegative, isZero, parseDecimal, subtract, type Decimal } from "./decimal.ts";
import { READ_UNAVAILABLE_VALUE, readOne, type ReadState } from "./read-state.ts";
import { formatMoney } from "./revenue-format.ts";

// El presupuesto operativo en pantalla (M47). UNA lectura (`GET /api/budget`) y UNA vista, que comparten `/ceo` y `/cfo`: ninguna de
// las dos pantallas lee el presupuesto por su cuenta ni calcula una segunda versión.
//
// Qué es: el techo de gasto INTERNO que el propietario autorizó y lo que el libro ha movido contra él. No es caja, ni ingresos, ni
// beneficio, ni dinero que haya salido de ninguna cuenta; la nota de alcance lo dice en cada tarjeta.
//
// La cuenta, que es la del motor (`BudgetState.available` y la sentencia que reserva):
//
//   usado      = reservado + comprometido
//   disponible = techo − usado
//   % usado    = usado / techo
//
// Lo GASTADO se enseña aparte y NO entra en la cuenta: un `COMMIT` ya lo suma a lo comprometido, y restarlo otra vez contaría el gasto dos
// veces (el agente CFO suma `reserved + committed + spent` en su informe; esa cuenta no es esta, ver el handoff).
//
// Los cuatro estados de una lectura (`lib/read-state.ts`) no se mezclan:
//   · empty   «No hay presupuesto autorizado»: el backend contestó y no hay ninguno. Es un hecho, no un error y no un cero.
//   · error   «No disponible»: la lectura falló o la respuesta no cumple el contrato (sin techo, importes que no son decimales, un disponible
//             que no cuadra). Nunca un 0, nunca «Agotado».
//   · unread  «Sin leer»: no se intentó.
//   · loaded  hay presupuesto: techo, reservado, comprometido, gastado y disponible, con su estado.
// «Agotado» solo existe en `loaded`, con techo > 0 y disponible = 0. Una contabilidad que no cuadra (lo usado supera el techo) es
// «Inconsistente», se enseña tal cual y no lleva porcentaje ni barra: un porcentaje sobre un saldo roto sería una cifra falsa.
//
// Aritmética con dinero: `lib/decimal.ts` (bigint), sin `float`. El único número que sale es el porcentaje, que no es dinero y se calcula
// con enteros (por mil, redondeando hacia abajo: un casi agotado nunca se enseña como 100 %).

export const BUDGET_TITLE = "Presupuesto operativo";
export const BUDGET_EMPTY_LABEL = "No hay presupuesto autorizado";
export const BUDGET_EMPTY_DETAIL = "El propietario no ha autorizado ningún presupuesto operativo.";
export const BUDGET_EXHAUSTED_LABEL = "Agotado";
export const BUDGET_CURRENCY_UNAVAILABLE = "Moneda no disponible";
export const BUDGET_SOURCE_NOTE = "Presupuesto autorizado y su saldo, leídos del libro del backend (budgets y budget_allocations).";
export const BUDGET_SCOPE_NOTE = "Es un techo de gasto interno: no es caja, ni ingresos, ni beneficio, ni dinero que haya salido de una cuenta.";
const INCONSISTENCY_TEXT = "Lo reservado y comprometido supera el techo autorizado: el saldo no cuadra. Revisa el libro antes de fiarte de estas cifras.";
const READ_SUBJECT = "el presupuesto";
const CONTRACT = "El contrato del presupuesto cambió:";

export type BudgetStatus = "available" | "partial" | "exhausted" | "inconsistent";

const STATUS_LABEL: Record<Exclude<BudgetStatus, "exhausted">, string> = {
  available: "Disponible",
  partial: "Parcialmente usado",
  inconsistent: "Inconsistente",
};

const PERIOD_LABEL: Record<string, string> = { monthly: "Mensual" };

export interface BudgetLoadedView {
  kind: "loaded";
  status: BudgetStatus;
  statusLabel: string;
  /** Importes ya escritos («1,00 €»); sin símbolo si la moneda no está disponible. */
  hardLimit: string;
  softLimit: string | null;
  reserved: string;
  committed: string;
  spent: string;
  remaining: string;
  /** Lo declarado por la fila («Mensual»); es una etiqueta, no un reinicio automático del saldo. */
  period: string;
  /** El código de moneda solo si el backend lo da con su procedencia contractual; si no, `null` y no se inventa una. */
  currency: string | null;
  currencyNote: string | null;
  /** (reservado + comprometido) / techo, en %, con un decimal y hacia abajo. `null` si el saldo es inconsistente. */
  usedPercent: number | null;
  bar: { reservedPercent: number; committedPercent: number } | null;
  inconsistency: string | null;
  /** «19 oct 2026 · 12:05 UTC», la hora de lectura del backend; `null` si no vino una válida. */
  readAt: string | null;
  sourceNote: string;
  scopeNote: string;
}

export type BudgetView =
  | { kind: "error"; message: string }
  | { kind: "unread"; reason: string }
  | { kind: "empty"; label: string; detail: string }
  | BudgetLoadedView;

/** Lo que la lectura necesita del cliente de la API; así las pruebas leen con una fuente que cuenta sus llamadas. */
export interface BudgetSource {
  getBudget(): Promise<BudgetRead>;
}

/** UNA lectura del presupuesto, clasificada. Es lo que llaman `/ceo` y `/cfo`. */
export async function readBudget(source: BudgetSource): Promise<BudgetView> {
  return budgetView(await readOne(() => source.getBudget(), READ_SUBJECT));
}

const broken = (what: string): BudgetView => ({ kind: "error", message: `${CONTRACT} ${what}.` });

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

/** Un importe del contrato: texto decimal exacto. Cualquier otra cosa (un número, `NaN`, vacío, ausente) es un contrato roto. */
function amount(value: unknown): Decimal | null {
  return typeof value === "string" ? parseDecimal(value) : null;
}

function money(text: string, currency: string | null): string {
  const shown = formatMoney(text, currency ?? "");
  return currency === null ? shown.trimEnd() : shown;
}

const CURRENCY_CODE = /^[A-Z]{3}$/;

/** La moneda solo se da por buena con su procedencia contractual (`accounting_currency`); sin ella, no se inventa EUR. */
function currencyOf(raw: Record<string, unknown>): string | null {
  const { currency, currency_source: source } = raw;
  return typeof currency === "string" && CURRENCY_CODE.test(currency) && source === "accounting_currency" ? currency : null;
}

/** Porcentaje (un decimal, hacia abajo) de `part` sobre `whole`, con enteros: 1/3 ⇒ 33,3 y 99,99/100 ⇒ 99,9. */
function percent(part: Decimal, whole: Decimal): number {
  const permille = (part.units * BigInt(1000)) / whole.units;
  return Number(permille) / 10;
}

export function budgetView(state: ReadState<BudgetRead>): BudgetView {
  switch (state.kind) {
    case "error":
      return { kind: "error", message: state.message };
    case "unread":
      return { kind: "unread", reason: state.reason };
    case "empty":
      return { kind: "empty", label: BUDGET_EMPTY_LABEL, detail: BUDGET_EMPTY_DETAIL };
    case "loaded":
      return loadedView(state.data);
  }
}

function loadedView(data: unknown): BudgetView {
  if (!isRecord(data) || typeof data.authorised !== "boolean") return broken("la respuesta no dice si hay presupuesto autorizado");
  if (!data.authorised) {
    return data.budget === null || data.budget === undefined
      ? { kind: "empty", label: BUDGET_EMPTY_LABEL, detail: BUDGET_EMPTY_DETAIL }
      : broken("dice que no hay presupuesto y trae uno");
  }
  const raw = data.budget as BudgetFigures | null | undefined;
  if (!isRecord(raw)) return broken("dice que hay presupuesto y no lo trae");

  const hard = amount(raw.hard_limit);
  if (hard === null || isNegative(hard) || isZero(hard)) return broken("el techo (hard_limit) falta o no es un importe mayor que cero");
  const reserved = amount(raw.reserved);
  const committed = amount(raw.committed);
  const spent = amount(raw.spent);
  const remaining = amount(raw.remaining);
  if (reserved === null || committed === null || spent === null || remaining === null) {
    return broken("reservado, comprometido, gastado o disponible faltan o no son importes");
  }
  if (isNegative(reserved) || isNegative(committed) || isNegative(spent)) return broken("reservado, comprometido o gastado son negativos");
  const soft = raw.soft_limit === null || raw.soft_limit === undefined ? null : amount(raw.soft_limit);
  if (raw.soft_limit !== null && raw.soft_limit !== undefined && soft === null) return broken("el umbral de aviso no es un importe");

  // El disponible lo calcula el backend con la cuenta del motor; aquí se comprueba que cuadra con la misma cuenta. Si no, las cifras no
  // se enseñan: no hay forma de saber cuál de las dos está mal.
  const used = add(reserved, committed);
  if (remaining.units !== subtract(hard, used).units) {
    return broken("el disponible no cuadra con techo − reservado − comprometido");
  }

  const currency = currencyOf(raw);
  const shown = (text: unknown) => money(String(text), currency);
  const inconsistent = used.units > hard.units;
  const status: BudgetStatus = inconsistent ? "inconsistent" : remaining.units === BigInt(0) ? "exhausted" : isZero(used) ? "available" : "partial";
  const period = typeof raw.period === "string" && raw.period.length > 0 ? (PERIOD_LABEL[raw.period] ?? raw.period) : READ_UNAVAILABLE_VALUE;
  const stamp = typeof data.read_at === "string" ? parseUtc(data.read_at) : Number.NaN;

  return {
    kind: "loaded",
    status,
    statusLabel: status === "exhausted" ? BUDGET_EXHAUSTED_LABEL : STATUS_LABEL[status],
    hardLimit: shown(raw.hard_limit),
    softLimit: soft === null ? null : shown(raw.soft_limit),
    reserved: shown(raw.reserved),
    committed: shown(raw.committed),
    spent: shown(raw.spent),
    remaining: shown(raw.remaining),
    period,
    currency,
    currencyNote: currency === null ? BUDGET_CURRENCY_UNAVAILABLE : null,
    usedPercent: inconsistent ? null : percent(used, hard),
    bar: inconsistent ? null : { reservedPercent: percent(reserved, hard), committedPercent: percent(committed, hard) },
    inconsistency: inconsistent ? INCONSISTENCY_TEXT : null,
    readAt: Number.isNaN(stamp) ? null : formatUtcDateTime(stamp),
    sourceNote: BUDGET_SOURCE_NOTE,
    scopeNote: BUDGET_SCOPE_NOTE,
  };
}
