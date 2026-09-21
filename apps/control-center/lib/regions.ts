/** Regiones que el backend de abastecimiento maneja hoy (origen del proveedor y
 * destino). Las claves son literalmente las que devuelve/acepta la API. */
export const REGION_LABELS: Record<string, string> = {
  china: "China",
  vietnam: "Vietnam",
  mexico: "México",
  eu: "Unión Europea",
};

/** Anclas cartográficas [lon, lat] para dibujar cada región en un mapa. No son
 * datos del backend (que solo conoce la región, no una ciudad): son un punto
 * de referencia geográfico por región, solo para posicionar el pin. */
export const REGION_ANCHORS: Record<string, [number, number]> = {
  china: [104, 35],
  vietnam: [106, 16],
  mexico: [-102, 23],
  eu: [10, 50],
};

export function regionLabel(region: string | null | undefined): string {
  if (!region) return "Sin origen";
  return REGION_LABELS[region] ?? region;
}
