import Link from "next/link";
import { ArrowRight, Package } from "lucide-react";
import type { Product } from "@/lib/api";
import { DEMO_PRODUCT_META } from "@/lib/demo/economics";
import { categoryLabel } from "@/lib/research-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const PRODUCT_STATUS_LABEL: Record<string, string> = { CANDIDATE: "Candidato" };

/** Ficha del producto activo de los paneles del pipeline (mockups de Economía,
 * Legal…): imagen, nombre, categoría y estado, descripción y enlace al detalle.
 * La imagen y la descripción son de demostración: el backend no las guarda. */
export function ProductSummary({ product, detailsHref = "/research" }: { product: Product; detailsHref?: string }) {
  return (
    <div className="flex min-w-0 gap-4">
      <div className="flex size-24 shrink-0 items-center justify-center rounded-xl border bg-background/60 text-primary">
        <Package className="size-10" />
      </div>
      <div className="min-w-0 space-y-1.5">
        <p className="truncate text-base font-semibold">{product.name}</p>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline" className="border-primary/40 text-primary">
            {categoryLabel(product.category)}
          </Badge>
          <Badge variant="outline">{PRODUCT_STATUS_LABEL[product.status] ?? product.status}</Badge>
        </div>
        <p className="line-clamp-2 text-xs text-muted-foreground">{DEMO_PRODUCT_META.description}</p>
        <Button size="xs" variant="outline" nativeButton={false} render={<Link href={detailsHref} />}>
          Ver detalles del producto <ArrowRight />
        </Button>
      </div>
    </div>
  );
}
