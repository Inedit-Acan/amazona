import "server-only";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { cache } from "react";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const isAuthConfigured = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

/** Techo para cualquier consulta de sesión durante un render.
 *
 * Medido: con Supabase inalcanzable, `getSession()` reintenta y una página
 * renderizada en servidor tardaba 51 segundos en responder. Sin límite, la
 * disponibilidad de Supabase se convierte en la de cada página. Con él, una
 * sesión que no se puede leer se trata como «sin sesión»: el backend
 * responderá 401 y el usuario verá un error inmediato en vez de una pestaña
 * colgada. */
const SESSION_TIMEOUT_MS = 4_000;

async function withTimeout<T>(work: Promise<T>, fallback: T): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const ceiling = new Promise<T>((resolve) => {
    timer = setTimeout(() => resolve(fallback), SESSION_TIMEOUT_MS);
  });
  try {
    return await Promise.race([work, ceiling]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function serverClient(store: Awaited<ReturnType<typeof cookies>>) {
  return createServerClient(SUPABASE_URL!, SUPABASE_ANON_KEY!, {
    cookies: {
      getAll: () => store.getAll(),
      // Sin escritura: escribir cookies durante el render de un componente de
      // servidor no está permitido, y `middleware.ts` ya las ha dejado al día.
      setAll: () => {},
    },
  });
}

/** La otra mitad de `lib/auth.ts`: lee la misma sesión, pero desde las cookies
 * de la petición, que es lo único que un componente de servidor tiene.
 *
 * `import "server-only"` es deliberado: si algún día un componente de cliente
 * importa esto por error, el build falla en vez de intentar meter
 * `next/headers` en el bundle del navegador.
 *
 * Va envuelto en `cache()` de React —una lectura por render, no una por llamada
 * a la API—. Sin esto, una página con tres peticiones leía la sesión tres
 * veces: medido, 12 s de los 16 que tardaba en responder con Supabase caído. */
export const getServerAccessToken = cache(async (): Promise<string | null> => {
  if (!isAuthConfigured) return null;

  const store = await cookies();
  const read = serverClient(store)
    .auth.getSession()
    .then(({ data }) => data.session?.access_token ?? null)
    .catch(() => null);

  return withTimeout(read, null);
});

export async function getServerEmail(): Promise<string | null> {
  if (!isAuthConfigured) return null;

  const store = await cookies();
  const read = serverClient(store)
    .auth.getUser()
    .then(({ data }) => data.user?.email ?? null)
    .catch(() => null);

  return withTimeout(read, null);
}
