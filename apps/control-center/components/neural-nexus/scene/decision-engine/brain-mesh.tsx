"use client";

import { useEffect, useMemo } from "react";
import * as THREE from "three";
import { hemisphereGeometry, type Hemisphere } from "@/lib/decision-engine";
import { ENGINE_COLOR, ENGINE_OPACITY } from "../../nexus-theme";

/** Silueta cerebral (§4 y §5): dos geometrías separadas —BrainLeft y
 * BrainRight—, no una esfera deformada. El material es oscuro y poco
 * transparente: da el volumen y el borde contra el fondo, mientras que la luz la
 * ponen la red neural y el núcleo (§41). Nada de MeshBasicMaterial como material
 * principal (§5.2) y una sola capa transparente por hemisferio (§33).
 *
 * Se dibuja antes que la red (renderOrder 0) para no apagarla. */
export function BrainMesh({ side, dimmed, selected }: { side: Hemisphere; dimmed: boolean; selected: boolean }) {
  const geometry = useMemo(() => {
    const { positions, indices } = hemisphereGeometry(side);
    const buffer = new THREE.BufferGeometry();
    buffer.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    buffer.setIndex(new THREE.BufferAttribute(indices, 1));
    buffer.computeVertexNormals();
    return buffer;
  }, [side]);

  useEffect(() => () => geometry.dispose(), [geometry]);

  return (
    <mesh geometry={geometry} renderOrder={0}>
      <meshStandardMaterial
        color={ENGINE_COLOR.shell}
        emissive={ENGINE_COLOR.wireframe}
        // Emisividad ínfima: el casco nunca es una masa verde (§19), solo deja
        // de ser negro absoluto.
        emissiveIntensity={dimmed ? 0.01 : 0.06}
        roughness={0.42}
        metalness={0.3}
        transparent
        // Seleccionado, el cerebro va al 100 % (§27).
        opacity={dimmed ? 0.16 : selected ? 1 : ENGINE_OPACITY.shell}
        depthWrite={false}
        side={THREE.FrontSide}
      />
    </mesh>
  );
}
