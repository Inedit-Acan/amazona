import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  GO: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  APPROVED: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  COMPLETED: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  AVAILABLE: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",

  REVIEW: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30",
  VALIDATING: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30",
  PENDING: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30",
  WAITING: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30",
  RUNNING: "bg-sky-500/15 text-sky-600 dark:text-sky-400 border-sky-500/30",
  HUMAN_APPROVAL: "bg-sky-500/15 text-sky-600 dark:text-sky-400 border-sky-500/30",
  BUSY: "bg-sky-500/15 text-sky-600 dark:text-sky-400 border-sky-500/30",

  NO_GO: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
  REJECTED: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
  FAILED: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
  BLOCKED: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
  EXPIRED: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",

  DRAFT: "bg-muted text-muted-foreground border-border",
  CANCELLED: "bg-muted text-muted-foreground border-border",
  DISABLED: "bg-muted text-muted-foreground border-border",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      variant="outline"
      className={cn("font-medium", STATUS_STYLES[status] ?? "bg-muted text-muted-foreground border-border")}
    >
      {status.replace(/_/g, " ")}
    </Badge>
  );
}
