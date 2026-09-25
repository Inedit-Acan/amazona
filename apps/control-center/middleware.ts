import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

/** Si el refresco no llega a tiempo, se sigue con la cookie que hubiera: una
 * sesión sin refrescar es un 401 recuperable; una navegación bloqueada, no. */
const REFRESH_TIMEOUT_MS = 4_000;

/** Refresca el token de acceso en cada navegación (Milestone 29.1).
 *
 * Es el único sitio donde se puede hacer: un componente de servidor lee
 * cookies pero no puede escribirlas, así que si el token caduca mientras el
 * usuario navega, nadie renovaría la sesión y las páginas renderizadas en
 * servidor empezarían a recibir 401. El middleware sí puede escribir, así que
 * llama a `getUser()` —que renueva si hace falta— y devuelve la respuesta con
 * las cookies actualizadas.
 *
 * Deliberadamente NO decide quién pasa: la autorización es del backend, que es
 * quien verifica la firma del token. Esto solo mantiene la sesión viva. */
export async function middleware(request: NextRequest) {
  const response = NextResponse.next({ request });

  // Sin credenciales, el Control Center funciona sin login: no hay nada que
  // refrescar y el middleware se aparta.
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return response;

  const supabase = createServerClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookiesToSet) => {
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
      },
    },
  });

  // Con techo, y por la misma razón que en lib/auth-server.ts: si Supabase no
  // responde, el middleware corre en TODAS las navegaciones y dejaría la
  // aplicación colgada en vez de simplemente sin refrescar. Medido sin límite:
  // 25 s por navegación con Supabase inalcanzable.
  await Promise.race([
    supabase.auth.getUser().catch(() => null),
    new Promise((resolve) => setTimeout(resolve, REFRESH_TIMEOUT_MS)),
  ]);

  return response;
}

export const config = {
  matcher: [
    // Todo menos los estáticos de Next y los archivos con extensión: no tiene
    // sentido renovar una sesión para servir un icono.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
