import type { ChannelKind } from "./api.ts";

// Cómo se dice un canal en la pantalla (Milestone 38, ADR 0016). Toda la lógica
// aquí con sus tests; los componentes solo presentan.
//
// La regla que gobierna este fichero: **una señal sin canal se enseña como
// agnóstica, nunca como «válida para todos»**. Es la diferencia entre «esto mide
// una propiedad del producto» y «esto vale para cualquier sitio donde lo vendas»,
// y la segunda lectura es la que hay que impedir.

/** Los tipos son cerrados —son conceptos— y las plataformas abiertas. Añadir un
 * marketplace no toca este mapa: se deduce del prefijo de la clave, que es
 * autodescriptiva a propósito. */
const KIND_LABEL: Record<ChannelKind, string> = {
  own_web: "Web propia",
  marketplace: "Marketplace",
  search: "Búsqueda",
  social: "Social",
};

/** Las plataformas que ya tienen nombre propio en pantalla. Una que no esté aquí
 * se enseña con su clave tal cual — legible, porque las claves lo son — en vez de
 * quedarse sin nombre. */
const PLATFORM_LABEL: Record<string, string> = {
  amazon: "Amazon",
  ebay: "eBay",
  etsy: "Etsy",
  mercado_libre: "Mercado Libre",
  tiktok_shop: "TikTok Shop",
  tiktok: "TikTok",
  reddit: "Reddit",
  google: "Google",
};

/** El tipo estructural de una clave de canal. `null` si no se reconoce: no se
 * adivina, se dice que no se sabe. */
export function channelKindOf(channel: string): ChannelKind | null {
  if (channel === "own_web") return "own_web";
  const [prefix] = channel.split(":");
  if (prefix === "marketplace" || prefix === "search" || prefix === "social") return prefix;
  return null;
}

/** El canal, para leerlo: `marketplace:amazon` → «Amazon (marketplace)». */
export function channelLabel(channel: string | null | undefined): string {
  if (!channel) return "Agnóstico del canal";
  if (channel === "own_web") return KIND_LABEL.own_web;
  const kind = channelKindOf(channel);
  const platform = channel.includes(":") ? channel.slice(channel.indexOf(":") + 1) : channel;
  const name = PLATFORM_LABEL[platform] ?? platform;
  return kind ? `${name} (${KIND_LABEL[kind].toLowerCase()})` : name;
}

/** Si en este canal se cobra. Lo usa la pantalla para no mezclar una superficie de
 * descubrimiento con un sitio donde se vende — TikTok no es TikTok Shop. */
export function isTransactional(channel: string | null | undefined): boolean {
  if (!channel) return false;
  const kind = channelKindOf(channel);
  return kind === "own_web" || kind === "marketplace";
}

/** Para qué canal se puntuó, dicho de forma que un nulo no se lea como un fallo. */
export function scoredForLabel(channel: string | null | undefined): string {
  return channel ? `Puntuado para ${channelLabel(channel)}` : "Puntuado sin canal (agnóstico)";
}

/** Por qué no hay score cuando el motivo es que la señal mide otro canal
 * (Milestone 38).
 *
 * Se separa del motivo de licencia a propósito: los dos se arreglan de formas
 * distintas —uno leyendo un contrato y el otro consiguiendo una fuente del canal
 * que falta— y confundirlos manda a quien lo lea a resolver el problema
 * equivocado. */
export function wrongChannelNote(
  channels: string[],
  scoredFor: string | null | undefined,
): string | null {
  if (channels.length === 0) return null;
  const measured = channels.map((channel) => (channel === "sin canal" ? "sin canal" : channelLabel(channel)));
  const target = scoredFor ? channelLabel(scoredFor) : "una decisión sin canal";
  return `Sin score: lo medido es de ${measured.join(", ")} y no sirve para ${target}`;
}

/** Qué canales ha medido un proveedor, para el informe de contraste. */
export function measuredChannelsLabel(channels: string[] | undefined): string {
  if (!channels || channels.length === 0) return "Agnóstico del canal";
  return channels.map(channelLabel).join(" · ");
}
