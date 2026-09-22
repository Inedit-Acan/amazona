import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

/** Recuadro de la derecha de la cabecera de los paneles («Producto activo»,
 * «Modo»…). Con `options` es un selector; sin ellas muestra `value` fijo. */
export function HeaderTile({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options?: { value: string; label: ReactNode }[];
  onChange?: (value: string) => void;
}) {
  return (
    <label className="relative flex w-64 max-w-full flex-col rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
      {label}
      {options ? (
        <>
          <select
            value={value}
            onChange={(e) => onChange?.(e.target.value)}
            className="mt-0.5 appearance-none truncate bg-transparent pr-6 text-sm font-medium text-primary outline-none"
          >
            {options.map((o) => (
              <option key={o.value} value={o.value} className="bg-popover text-foreground">
                {o.label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 bottom-2.5 size-4 text-foreground" />
        </>
      ) : (
        <span className="mt-0.5 truncate text-sm font-medium text-primary">{value}</span>
      )}
    </label>
  );
}
