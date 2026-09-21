import type { ReactNode } from "react";
import { PackageSearch } from "lucide-react";
import type { Product } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const PRODUCT_STATUS_LABEL: Record<string, string> = { CANDIDATE: "Candidato" };
const PRODUCT_SOURCE_LABEL: Record<string, string> = { research: "Investigación", manual: "Manual" };

/** Cabecera del producto activo (los mockups del pipeline empiezan todos por
 * ella): nombre + categoría/estado/origen reales de `Product`. Sin imagen ni
 * descripción: el backend no las guarda. `children` añade chips propios del panel. */
export function ProductHeader({ product, children }: { product: Product; children?: ReactNode }) {
  return (
    <div className="flex items-center gap-4">
      <div className="flex size-16 shrink-0 items-center justify-center rounded-xl border bg-muted text-primary">
        <PackageSearch className="size-7" />
      </div>
      <div className="min-w-0 space-y-2">
        <p className="truncate text-base font-semibold">{product.name}</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">{product.category}</Badge>
          <Badge variant="outline">{PRODUCT_STATUS_LABEL[product.status] ?? product.status}</Badge>
          <Badge variant="outline">{PRODUCT_SOURCE_LABEL[product.source] ?? product.source}</Badge>
          {children}
        </div>
      </div>
    </div>
  );
}
