"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { isAuthConfigured, signInWithPassword } from "@/lib/auth";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!isAuthConfigured) {
    return (
      <div>
        <PageHeader title="Iniciar sesión" />
        <Card className="max-w-md">
          <CardContent className="py-8 text-sm text-muted-foreground">
            La autenticación de Supabase no está configurada para este despliegue — el Control Center está abierto, no requiere inicio de sesión.
          </CardContent>
        </Card>
      </div>
    );
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signInWithPassword(email, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <PageHeader title="Iniciar sesión" description="Inicia sesión con tu cuenta de propietario/operador de AMAZONA." />
      <Card className="max-w-md">
        <CardHeader>
          <CardTitle>Iniciar sesión</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-sm font-medium">
                Correo electrónico
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="password" className="text-sm font-medium">
                Contraseña
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              />
            </div>
            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>No se pudo iniciar sesión</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <Button type="submit" disabled={submitting}>
              {submitting ? "Iniciando sesión…" : "Iniciar sesión"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
