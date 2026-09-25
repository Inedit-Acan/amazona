"use client";

import { useMemo } from "react";
import { Billboard, Html } from "@react-three/drei";
import * as THREE from "three";
import { BRAIN, NETWORK_DENSITY, neuralRoute, type Hemisphere } from "@/lib/decision-engine";
import type { NeuralZone, NodeStatus } from "@/lib/neural-nexus";
import { STATUS_COLOR } from "../../nexus-theme";
import { BrainMesh } from "./brain-mesh";
import { DecisionCore } from "./decision-core";
import { NeuralFlow } from "./neural-flow";
import { NeuralNetwork, type ActiveRoute } from "./neural-network";
import { TechnicalRing } from "./technical-ring";

const SIDES: Hemisphere[] = ["left", "right"];
/** Estados que encienden la ruta neural de su zona. Un dominio disponible no
 * enciende nada: en reposo la red se ve, pero no pasa nada (§26). */
const ROUTED: NodeStatus[] = ["running", "waiting", "blocked", "error"];

/** Decision Engine: el cerebro operativo del sistema
 * (docs/design/KOVA_Decision_Engine_especificacion_visual_tecnica_final.md).
 *
 * Seis capas independientes (§3), nunca un único objeto brillante: silueta
 * cerebral, red neural, nodos sinápticos, núcleo geométrico, anillo técnico y un
 * halo mínimo. El cerebro es oscuro y técnico; la luz la ponen el wireframe, las
 * rutas activas y el núcleo (§41).
 *
 * El estado no tiñe el cerebro entero (§26): la densidad de la red sube cuando
 * hay trabajo, cada dominio con algo que contar enciende SU ruta con SU color, y
 * solo el núcleo toma el color del estado global. */
export function DecisionEngine({
  status,
  zones,
  animate,
  dimmed,
  selected,
  hovered,
  onSelect,
  onHover,
}: {
  status: NodeStatus;
  zones: NeuralZone[];
  animate: boolean;
  dimmed: boolean;
  selected: boolean;
  hovered: boolean;
  onSelect: () => void;
  onHover: (hovered: boolean) => void;
}) {
  const routes = useMemo<ActiveRoute[]>(
    () =>
      zones
        .filter((zone) => ROUTED.includes(zone.status))
        .map((zone) => ({ route: neuralRoute(zone.angle), color: new THREE.Color(STATUS_COLOR[zone.status]) })),
    [zones],
  );

  const processing = status === "running" || zones.some((zone) => zone.status === "running");
  // §6.3: en reposo se ve entre el 30 y el 40 % de la red; ejecutando, más.
  const density = processing ? NETWORK_DENSITY.active : NETWORK_DENSITY.rest;

  return (
    <group>
      {/* El casco es lo único que se puede pinchar del cerebro: la red y los
          nodos no interceptan el ratón. */}
      <group
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
        }}
        onPointerOver={(event) => {
          event.stopPropagation();
          onHover(true);
        }}
        onPointerOut={() => onHover(false)}
      >
        {SIDES.map((side) => (
          <BrainMesh key={side} side={side} dimmed={dimmed} selected={selected} />
        ))}
      </group>

      {SIDES.map((side) => (
        <NeuralNetwork key={side} side={side} density={density} routes={routes} animate={animate} dimmed={dimmed} />
      ))}

      <NeuralFlow routes={routes} animate={animate} dimmed={dimmed} />

      <DecisionCore
        color={STATUS_COLOR[status]}
        processing={processing}
        animate={animate}
        dimmed={dimmed}
        selected={selected}
        hovered={hovered}
        onSelect={onSelect}
        onHover={onHover}
      />

      <TechnicalRing processing={processing} animate={animate} dimmed={dimmed} />

      {/* Rótulo (§22): debajo, centrado, blanco, sin glow y con tracking ligero.
          Nunca sobre el cerebro. */}
      <Billboard position={[0, BRAIN.labelHeight, 0]}>
        <Html center distanceFactor={10} zIndexRange={[14, 0]} style={{ pointerEvents: "none", opacity: dimmed ? 0.3 : 1 }}>
          <div
            style={{
              color: "#f5f7f7",
              fontSize: 13,
              fontWeight: 600,
              letterSpacing: "0.16em",
              textShadow: "0 1px 3px rgba(0,0,0,0.9)",
              whiteSpace: "nowrap",
            }}
          >
            DECISION ENGINE
          </div>
        </Html>
      </Billboard>
    </group>
  );
}
