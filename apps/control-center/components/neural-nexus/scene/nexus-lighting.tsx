"use client";

/** Iluminación contenida (§28). Los nodos usan `MeshStandardMaterial`, así que
 * la forma la da la luz y no un emissive a tope: ambiente muy bajo, una luz
 * puntual dentro del núcleo que ilumina hacia fuera, una direccional suave y un
 * contraluz esmeralda que despega los nodos del fondo. Nada de esto genera la
 * neblina verde que había antes. */
export function NexusLighting() {
  return (
    <>
      <ambientLight intensity={0.28} />
      <pointLight position={[0, 0, 0]} intensity={14} distance={11} decay={2} color="#15f0b2" />
      <directionalLight position={[3, 8, 7]} intensity={0.5} color="#dff5ee" />
      {/* Rim light: entra por detrás y dibuja el borde de cada nodo. */}
      <directionalLight position={[-5, 2, -8]} intensity={0.35} color="#28e5d0" />
    </>
  );
}
