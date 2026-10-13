import { AlertTriangle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { RetryButton } from "@/components/retry-button";

/** Una lectura que falló (o que no se hizo), dicho con claridad y sin lenguaje técnico: nada de estados HTTP, `fetch failed`
 * ni trazas. Nunca se sustituye por datos de demostración, por una lista vacía ni por un cero. Con `retry`, enseña el botón
 * de reintento manual (una petición por clic). */
export function ReadErrorNotice({
  title,
  message,
  retry = true,
}: {
  title: string;
  message: string;
  retry?: boolean;
}) {
  return (
    <Alert variant="destructive">
      <AlertTriangle className="size-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{message}</p>
        {retry ? (
          <div className="mt-2">
            <RetryButton />
          </div>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
