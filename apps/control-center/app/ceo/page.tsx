import { Suspense } from "react";
import { AgentNetworkCard } from "@/components/ceo/agent-network-card";
import { AssistantDrawer } from "@/components/ceo/assistant-drawer";
import { BottomRow } from "@/components/ceo/bottom-row";
import { BudgetBlock, BudgetSkeleton } from "@/components/ceo/budget-block";
import { CeoAssistantPanel } from "@/components/ceo/ceo-assistant-panel";
import { CeoProvider } from "@/components/ceo/ceo-context";
import { CeoHeader } from "@/components/ceo/ceo-header";
import { CeoLayout } from "@/components/ceo/ceo-layout";
import { DecisionTriptych } from "@/components/ceo/decision-triptych";
import { KpiRow } from "@/components/ceo/kpi-row";
import { MissionDrawer } from "@/components/ceo/mission-drawer";
import { parseRevenueDays, revenueWindow } from "@/lib/revenue-query";

// Director ejecutivo (M47): el centro de mando del mockup aprobado
// (docs/reference/ceo-ia/KOVA_CEO_Dashboard_referencia_aprobada.png). Esta página es un Server Component que solo COMPONE: no
// lee nada ni lleva ningún dato —cada bloque dice su propio estado de lectura— y el formulario de misión, la pantalla completa
// del grafo y el panel del CEO IA son islas de cliente que comparten `CeoProvider`.
//
// Lo único que hace la página con la URL es decidir el periodo de Ingresos (`?dias=`: 7, 14 o 30; cualquier otro valor vuelve a
// 30) y calcular su ventana UTC; la lectura la hace la tarjeta de Ingresos. Leer `searchParams` la vuelve dinámica.
export default async function CeoPage({ searchParams }: PageProps<"/ceo">) {
  const days = parseRevenueDays((await searchParams).dias);
  const window = revenueWindow(new Date().getTime(), days);
  return (
    <CeoProvider>
      <CeoHeader />
      <CeoLayout panel={<CeoAssistantPanel />}>
        <KpiRow window={window} days={days} />
        <Suspense fallback={<BudgetSkeleton />}>
          <BudgetBlock />
        </Suspense>
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
