import type { MarketingCampaign } from "./api.ts";

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
