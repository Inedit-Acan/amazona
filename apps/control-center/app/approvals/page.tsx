import { api } from "@/lib/api-server";
import { realInbox } from "@/lib/approvals-inbox";
import { readApprovalsPage } from "@/lib/approvals-reads";
import { listOf } from "@/lib/read-state";
import { ApprovalsWorkspace } from "./approvals-workspace";

export default async function ApprovalsPage() {
  const reads = await readApprovalsPage(api);
  const now = new Date().getTime();
  const inbox = realInbox({ approvals: reads.approvals, reviews: reads.reviews, now });
  const demoNotice = reads.contextFailures.length === 0 ? null : `Al ilustrar la demostración no se pudo leer: ${reads.contextFailures.join("; ")}.`;
  return <ApprovalsWorkspace inbox={inbox} agents={listOf(reads.agents) ?? []} context={reads.contexts} demoNotice={demoNotice} now={now} />;
}
