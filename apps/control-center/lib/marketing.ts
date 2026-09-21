import type { AudienceSegment, MarketingCampaign } from "./api.ts";

// La propuesta de campaña la genera el agente de marketing con estimaciones de
// rendimiento simuladas (marketing_campaign.py). Este módulo NO calcula CAC,
// ROAS ni funnels: solo etiqueta, filtra y reexpresa lo que el backend devolvió.

export const PLATFORM_LABELS: Record<string, string> = {
  meta: "Meta Ads",
  google: "Google Ads",
};

export function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform] ?? platform;
}

/** Última propuesta (la API las devuelve de la más reciente a la más antigua) de
 * una plataforma y mercado concretos. */
export function latestCampaign<T extends Pick<MarketingCampaign, "market" | "platform">>(
  campaigns: T[],
  market: string,
  platform: string,
): T | undefined {
  return campaigns.find((c) => c.market === market && c.platform === platform);
}

/** Una propuesta por plataforma en el mercado dado (la más reciente de cada una),
 * en el orden habitual de plataformas y luego el resto. */
export function campaignPlan<T extends Pick<MarketingCampaign, "market" | "platform">>(
  campaigns: T[],
  market: string,
): T[] {
  const seen = new Map<string, T>();
  for (const campaign of campaigns) {
    if (campaign.market === market && !seen.has(campaign.platform)) seen.set(campaign.platform, campaign);
  }
  const known = Object.keys(PLATFORM_LABELS);
  const rank = (platform: string) => {
    const index = known.indexOf(platform);
    return index === -1 ? known.length : index;
  };
  return [...seen.values()].sort((a, b) => rank(a.platform) - rank(b.platform) || a.platform.localeCompare(b.platform));
}

export interface AudienceBar {
  name: string;
  ageRange: string;
  interests: string[];
  reach: number;
  /** Alcance relativo al mayor segmento (0-1), solo para dibujar la barra. */
  share: number;
}

export function audienceBars(segments: AudienceSegment[] | undefined): AudienceBar[] {
  const list = segments ?? [];
  const max = Math.max(0, ...list.map((s) => s.estimated_reach));
  return list.map((s) => ({
    name: s.name,
    ageRange: s.age_range,
    interests: s.interests,
    reach: s.estimated_reach,
    share: max > 0 ? s.estimated_reach / max : 0,
  }));
}

export interface CampaignVerdict {
  title: string;
  detail: string;
  tone: "ok" | "warn" | "bad";
}

/** Estado de la propuesta traducido desde `campaign_status` del agente. */
export const CAMPAIGN_VERDICT: Record<MarketingCampaign["campaign_status"], CampaignVerdict> = {
  READY: {
    title: "Propuesta lista para revisión",
    detail:
      "Economía, legal y ROAS proyectado no bloquean. Sigue siendo una propuesta simulada: no se ha gastado nada en ninguna plataforma.",
    tone: "ok",
  },
  NEEDS_REVIEW: {
    title: "Requiere revisión",
    detail: "Falta algún análisis previo o alguno pide revisión humana antes de invertir.",
    tone: "warn",
  },
  BLOCKED: {
    title: "Bloqueada",
    detail: "Un análisis previo recomienda no continuar o el ROAS proyectado no llega al punto de equilibrio.",
    tone: "bad",
  },
};

/** Reglas que el agente aplica hoy al proponer una campaña (marketing_campaign.py).
 * Es documentación fija del comportamiento del backend, no datos de la propuesta. */
export const AGENT_GUARDRAILS: { rule: string; effect: string }[] = [
  { rule: "El análisis económico recomienda NO_GO", effect: "Bloquea la propuesta" },
  { rule: "El análisis legal recomienda NO_GO", effect: "Bloquea la propuesta" },
  { rule: "ROAS proyectado por debajo de 1,0", effect: "Bloquea la propuesta" },
  { rule: "Falta el análisis económico o el legal del mercado", effect: "Pide revisión" },
  { rule: "El listado de marketplace está bloqueado", effect: "Añade un riesgo" },
  { rule: "Plazo de proveedor superior a 45 días", effect: "Añade un riesgo" },
];
