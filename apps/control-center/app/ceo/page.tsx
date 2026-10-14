import { Suspense } from "react";
import { AgentNetworkCard } from "@/components/ceo/agent-network-card";
import { AssistantDrawer } from "@/components/ceo/assistant-drawer";
import { BottomRow } from "@/components/ceo/bottom-row";
import { CeoAssistantPanel } from "@/components/ceo/ceo-assistant-panel";
import { CeoProvider } from "@/components/ceo/ceo-context";
import { CeoHeader } from "@/components/ceo/ceo-header";
import { CeoLayout } from "@/components/ceo/ceo-layout";
import { DecisionTriptych } from "@/components/ceo/decision-triptych";
import { KpiRow } from "@/components/ceo/kpi-row";
import { MissionDrawer } from "@/components/ceo/mission-drawer";

// Director ejecutivo (M47, Commit 2): el centro de mando del mockup aprobado
// (docs/reference/ceo-ia/KOVA_CEO_Dashboard_referencia_aprobada.png). Esta página es un Server Component que solo COMPONE: no
// lee nada ni lleva ningún dato —cada bloque dice su propio estado de lectura— y el formulario de misión, la pantalla completa
// del grafo y el panel del CEO IA son islas de cliente que comparten `CeoProvider`.
export default function CeoPage() {
  return (
    <CeoProvider>
      <CeoHeader />
      <CeoLayout panel={<CeoAssistantPanel />}>
        <KpiRow />
        <DecisionTriptych />
        <AgentNetworkCard />
        <BottomRow />
      </CeoLayout>
      <AssistantDrawer />
      {/* `useSearchParams` (la precarga desde otras pantallas) exige un límite de Suspense. */}
      <Suspense fallback={null}>
        <MissionDrawer />
      </Suspense>
    </CeoProvider>
  );
}
