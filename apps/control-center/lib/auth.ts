"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const isAuthConfigured = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

let client: SupabaseClient | null = null;

/** Cliente de navegador. Desde el Milestone 29.1 la sesión se guarda en
 * **cookies** y no en `localStorage`: el renderizado en servidor de Next no
 * puede leer `localStorage`, así que las 15 páginas que cargan datos en
 * servidor no podían mandar el token y el backend no podía exigirlo.
 *
 * `createBrowserClient` de `@supabase/ssr` escribe la misma sesión que antes,
 * pero en cookies que el servidor sí ve. La API de este módulo no cambia: quien
 * lo usa (`login/page.tsx`, `session-badge.tsx`) no se entera.
 *
 * Solo se construye si hay credenciales: sin ellas el Control Center funciona
 * como en Milestone 1, sin login. */
export function getSupabaseClient(): SupabaseClient | null {
  if (!isAuthConfigured) return null;
  if (!client) {
    client = createBrowserClient(SUPABASE_URL!, SUPABASE_ANON_KEY!);
  }
  return client;
}

export async function signInWithPassword(email: string, password: string): Promise<void> {
  const supabase = getSupabaseClient();
  if (!supabase) throw new Error("Supabase auth is not configured for this deployment.");

  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) throw error;
}

export async function signOut(): Promise<void> {
  const supabase = getSupabaseClient();
  if (!supabase) return;
  await supabase.auth.signOut();
}

export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabaseClient();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export async function getCurrentEmail(): Promise<string | null> {
  const supabase = getSupabaseClient();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.user.email ?? null;
}
