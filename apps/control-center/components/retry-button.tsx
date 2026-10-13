"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Vuelve a pedir la página al servidor: UNA petición por clic (`router.refresh()`). No hay reintentos automáticos ni
 * temporizadores: un error persistente no puede convertirse en un bucle de peticiones. Mientras la petición está en
 * curso el botón se desactiva, así que un doble clic tampoco duplica la lectura. */
export function RetryButton({ label = "Reintentar" }: { label?: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <Button type="button" size="sm" variant="outline" disabled={pending} onClick={() => startTransition(() => router.refresh())}>
      <RefreshCw className={pending ? "animate-spin" : undefined} aria-hidden />
      {pending ? "Reintentando…" : label}
    </Button>
  );
}
