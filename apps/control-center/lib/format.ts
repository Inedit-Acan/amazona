// es-ES omite el separador de miles en números de 4 cifras por defecto
// ("1234,50"); se fuerza (`useGrouping: true`) para que coincida con los mockups
// ("1.234,50").

/** Importe sin símbolo de divisa: el backend no especifica moneda. */
export function formatAmount(value: number): string {
  return value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: true });
}

/** Entero con separador de miles. */
export function formatInteger(value: number): string {
  return Math.round(value).toLocaleString("es-ES", { useGrouping: true });
}

/** Recibe una fracción (0,578 → "57,8 %"). */
export function formatPercent(fraction: number, digits = 1): string {
  const text = (fraction * 100).toLocaleString("es-ES", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: true,
  });
  return `${text} %`;
}
