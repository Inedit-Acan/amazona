"use client";

import { useState } from "react";
import type { Agent } from "@/lib/api";
import type { RealInbox } from "@/lib/approvals-inbox";
import { KillSwitchControl } from "@/components/kill-switch-control";
import { PageHeader } from "@/components/page-header";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ApprovalContextData } from "@/lib/approvals-reads";
import { APPROVALS_DESCRIPTION, APPROVALS_TITLE } from "./copy";
import { DemoInbox } from "./demo-inbox";
import { BackendInboxPanel } from "./backend-inbox";

type Panel = "backend" | "demo";

/** /approvals (M47, Commit 6b): dos paneles SEPARADOS. «Solicitudes del backend» es lo único real (por defecto) y nunca contiene una fila de
 * demostración; «Demostración» es la maqueta, con su cartel y sus botones deshabilitados. Nunca se mezclan en una misma lista ni en unos mismos indicadores. */
export function ApprovalsWorkspace({
  inbox,
  agents,
  context,
  demoNotice,
  now,
}: {
  inbox: RealInbox;
  agents: Agent[];
  context: ApprovalContextData[];
  demoNotice: string | null;
  now: number;
}) {
  const [panel, setPanel] = useState<Panel>("backend");
  return (
    <div className="space-y-5">
      <PageHeader title={APPROVALS_TITLE} description={APPROVALS_DESCRIPTION} />
      <Tabs value={panel} onValueChange={(value) => setPanel(value as Panel)}>
        <TabsList className="flex flex-wrap justify-start group-data-horizontal/tabs:h-auto">
          <TabsTrigger value="backend" className="flex-none px-3 text-sm">
            Solicitudes del backend
          </TabsTrigger>
          <TabsTrigger value="demo" className="flex-none px-3 text-sm">
            Demostración
          </TabsTrigger>
        </TabsList>
      </Tabs>
      {panel === "backend" ? <BackendInboxPanel inbox={inbox} /> : <DemoInbox agents={agents} context={context} notice={demoNotice} now={now} />}
      <KillSwitchControl />
    </div>
  );
}
