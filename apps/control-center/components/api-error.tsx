import { AlertTriangle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function ApiErrorAlert({ message }: { message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTriangle className="size-4" />
      <AlertTitle>Could not reach the AMAZONA backend</AlertTitle>
      <AlertDescription>
        {message}. Make sure the API is running (see backend/README or run{" "}
        <code className="font-mono">uvicorn app.main:app --reload</code>) and{" "}
        <code className="font-mono">NEXT_PUBLIC_API_URL</code> points to it.
      </AlertDescription>
    </Alert>
  );
}
