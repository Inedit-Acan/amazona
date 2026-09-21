export const MARKET_LABELS: Record<string, string> = {
  us: "Estados Unidos",
  eu: "Unión Europea",
  mx: "México",
};

export function marketLabel(market: string): string {
  return MARKET_LABELS[market] ?? market.toUpperCase();
}

/** Primer elemento (los endpoints de historial devuelven del más reciente al más
 * antiguo) del mercado dado. */
export function latestForMarket<T extends { market: string }>(items: T[], market: string): T | undefined {
  return items.find((item) => item.market === market);
}
