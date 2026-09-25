import assert from "node:assert/strict";
import { test } from "node:test";
import { DOMAINS } from "./demo/neural-nexus.ts";
import { LAYOUT, domainAngle } from "./neural-nexus.ts";
import {
  BRAIN,
  CEO_ANCHOR,
  NETWORK_DENSITY,
  PROCESSING_CYCLE,
  SYNAPSE_SIZE,
  brainOutline,
  hemisphereGeometry,
  neuralMesh,
  neuralRoute,
  processingPhase,
  surfacePoint,
  zoneAnchor,
  type Hemisphere,
} from "./decision-engine.ts";

/** Caja del cerebro completo, medida sobre la malla de los dos hemisferios. */
function boundingBox() {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const side of ["left", "right"] as Hemisphere[]) {
    const { positions } = hemisphereGeometry(side, 72, 54);
    for (let i = 0; i < positions.length; i += 3) {
      for (let axis = 0; axis < 3; axis++) {
        min[axis] = Math.min(min[axis], positions[i + axis]);
        max[axis] = Math.max(max[axis], positions[i + axis]);
      }
    }
  }
  return { min, max, size: [max[0] - min[0], max[1] - min[1], max[2] - min[2]] };
}

test("§4.3: el cerebro es más ancho que alto y respeta las proporciones de la especificación", () => {
  const { size } = boundingBox();
  const [width, height, depth] = size;
  assert.ok(Math.abs(width - BRAIN.width) < 0.01, `ancho ${width}`);
  assert.ok(height / width >= 0.68 && height / width <= 0.75, `alto/ancho ${height / width}`);
  assert.ok(depth / width >= 0.55 && depth / width <= 0.65, `profundidad/ancho ${depth / width}`);
  assert.ok(height < width, "debe ser más ancho que alto");
});

test("§8.3: el volumen está centrado en el origen, que es donde va el núcleo", () => {
  const { min, max } = boundingBox();
  for (let axis = 0; axis < 3; axis++) {
    assert.ok(Math.abs(max[axis] + min[axis]) < 0.01, `eje ${axis} descentrado`);
  }
});

test("§4.4: hay surco central real, del 3–7 % del ancho, y los hemisferios siguen unidos por abajo", () => {
  const ratio = BRAIN.gap / BRAIN.width;
  assert.ok(ratio >= 0.03 && ratio <= 0.07, `surco ${ratio}`);

  // En la bóveda los dos hemisferios están separados por el surco entero…
  const crown = surfacePoint("right", Math.PI / 2, Math.PI * 0.25);
  const mirror = surfacePoint("left", Math.PI / 2, Math.PI * 0.25);
  assert.equal(crown[0], -mirror[0]);
  const vault = surfacePoint("right", 0, Math.PI * 0.3)[0];
  assert.ok(Math.abs(vault - BRAIN.gap / 2) < 1e-6, `surco en la bóveda ${vault}`);

  // …y por debajo se juntan: la separación no parte el cerebro en dos piezas.
  const base = surfacePoint("right", 0, Math.PI * 0.94)[0];
  assert.ok(base < BRAIN.gap * 0.12, `el surco no se cierra por abajo (${base})`);
});

test("§8.4: el núcleo geométrico ocupa entre el 15 % y el 22 % del ancho del cerebro", () => {
  const ratio = (BRAIN.coreRadius * 2) / BRAIN.width;
  assert.ok(ratio >= 0.15 && ratio <= 0.22, `núcleo ${ratio}`);
});

test("§11 y §13.1: el cerebro ocupa el 26–34 % del anillo de dominios y no llega a tocarlos", () => {
  const ringWidth = LAYOUT.domainRadius * 2;
  const ratio = BRAIN.width / ringWidth;
  assert.ok(ratio >= 0.26 && ratio <= 0.34, `escala relativa ${ratio}`);
  // Holgura entre la superficie del cerebro y el nodo de dominio más cercano.
  assert.ok(LAYOUT.domainRadius - BRAIN.halfWidth > 1, "los dominios quedan pegados al cerebro");
  assert.ok(BRAIN.ringRadius < LAYOUT.domainRadius, "el anillo técnico invade el anillo de dominios");
});

test("§12: el CEO entra por la corona, en la vertical exacta y por encima del cerebro", () => {
  assert.equal(CEO_ANCHOR[0], 0);
  assert.equal(CEO_ANCHOR[2], 0);
  assert.ok(CEO_ANCHOR[1] > BRAIN.halfHeight, "el enlace del CEO debe terminar fuera del cerebro");
});

test("§13.2 y §14: cada dominio entra por una zona distinta y por su propio hemisferio", () => {
  const anchors = DOMAINS.map((_, index) => zoneAnchor(domainAngle(index)));
  const keys = new Set(anchors.map((anchor) => anchor.join(",")));
  assert.equal(keys.size, DOMAINS.length, "hay dominios que entran por el mismo punto");

  // El mapeo de §14: hemisferio izquierdo o derecho de cada dominio.
  const expected: Record<string, "left" | "right"> = {
    "Investigación": "left",
    Abastecimiento: "left",
    Comercio: "left",
    Marketing: "left",
    "Economía": "right",
    Legal: "right",
    Operaciones: "right",
    Finanzas: "right",
  };
  DOMAINS.forEach((domain, index) => {
    const side = anchors[index][0] < 0 ? "left" : "right";
    assert.equal(side, expected[domain], `${domain} entra por el hemisferio equivocado`);
  });

  // Y las ocho zonas se reparten en altura, no se amontonan en el ecuador.
  const heights = anchors.map((anchor) => anchor[1]);
  assert.ok(Math.max(...heights) > 0.3, "ninguna zona queda en la parte alta");
  assert.ok(Math.min(...heights) < -0.3, "ninguna zona queda en la parte baja");
});

test("§15.2: la ruta neural entra por la zona del dominio, pasa por nodos reales y converge en el núcleo", () => {
  for (let index = 0; index < DOMAINS.length; index++) {
    const angle = domainAngle(index);
    const route = neuralRoute(angle);
    assert.deepEqual(route.path[0], zoneAnchor(angle), "la ruta no arranca en su zona");
    assert.deepEqual(route.path.at(-1), [0, 0, 0], "la ruta no termina en el núcleo");
    assert.ok(route.synapses.length >= 2, "la ruta no recorre nodos");
    assert.equal(new Set(route.synapses).size, route.synapses.length, "repite nodos");

    const { points } = neuralMesh(route.side);
    for (const synapse of route.synapses) {
      assert.ok(synapse >= 0 && synapse < points.length / 3, "índice de nodo fuera de rango");
    }
    // Cada salto se acerca al centro: la señal converge, no da vueltas.
    const distances = route.path.map((point) => Math.hypot(...point));
    for (let step = 1; step < distances.length; step++) {
      assert.ok(distances[step] < distances[step - 1] + 0.12, "la ruta se aleja del núcleo");
    }
  }
});

test("§6.3: la densidad de enlaces visibles es del 30–40 % en reposo y del 45–65 % ejecutando", () => {
  assert.ok(NETWORK_DENSITY.rest >= 0.3 && NETWORK_DENSITY.rest <= 0.4);
  assert.ok(NETWORK_DENSITY.active >= 0.45 && NETWORK_DENSITY.active <= 0.65);
  for (const side of ["left", "right"] as Hemisphere[]) {
    const { linkThreshold } = neuralMesh(side);
    const visible = (density: number) => linkThreshold.filter((value) => value < density).length / linkThreshold.length;
    assert.ok(Math.abs(visible(NETWORK_DENSITY.rest) - NETWORK_DENSITY.rest) < 0.06, `reposo ${visible(NETWORK_DENSITY.rest)}`);
    assert.ok(visible(NETWORK_DENSITY.active) > visible(NETWORK_DENSITY.rest), "ejecutar no enciende más red");
    assert.ok(visible(1) === 1 && visible(NETWORK_DENSITY.active) < 0.7, "nunca se enciende el 100 %");
  }
});

test("§7: los nodos sinápticos son pequeños, están en los dos hemisferios y algunos apagados en reposo", () => {
  const ratio = SYNAPSE_SIZE / BRAIN.halfWidth;
  assert.ok(ratio >= 0.02 && ratio <= 0.05, `tamaño del nodo ${ratio}`);
  for (const side of ["left", "right"] as Hemisphere[]) {
    const { points, pointBase, links } = neuralMesh(side);
    const count = points.length / 3;
    assert.ok(count > 100, "hemisferio con pocos nodos");
    const off = [...pointBase].filter((value) => value === 0).length;
    assert.ok(off > 0 && off / count < 0.3, `nodos apagados ${off}/${count}`);
    // Todos caen del lado que les toca y dentro del volumen del cerebro.
    for (let i = 0; i < count; i++) {
      const x = points[i * 3];
      assert.ok(side === "left" ? x <= 0 : x >= 0, "nodo en el hemisferio contrario");
      assert.ok(Math.abs(x) <= BRAIN.halfWidth + 1e-3, "nodo fuera del cerebro");
      assert.ok(Math.abs(points[i * 3 + 1]) <= BRAIN.halfHeight + 1e-3, "nodo fuera del cerebro");
    }
    assert.ok(links.length / 2 >= count, "la malla tiene menos enlaces que nodos");
  }
});

test("§17 y §31: la secuencia de procesamiento recorre sus fases y vuelve siempre al baseline", () => {
  const rest = processingPhase(0);
  assert.equal(rest.signal, null);
  assert.equal(rest.core, 0);
  assert.equal(rest.pulse, 0);
  assert.equal(rest.output, null);

  // Las fases llegan en el orden de la especificación.
  assert.ok((processingPhase(0.3).signal ?? 0) > 0, "la ruta no se activa entre 100 y 350 ms");
  assert.ok((processingPhase(0.65).signal ?? 0) > 0.8, "la señal no converge hacia el núcleo");
  assert.equal(processingPhase(0.9).signal, null);
  assert.ok(processingPhase(0.9).core > 0 && processingPhase(1.05).core > processingPhase(0.9).core);
  assert.ok(processingPhase(1.25).pulse > 0.9, "no hay pulso de decisión");
  assert.ok((processingPhase(1.6).output ?? 0) > 0, "el resultado no sale");

  // El ciclo se repite igual: el minuto diez se ve como el primero.
  for (const elapsed of [0.05, 0.4, 0.9, 1.25, 1.7]) {
    const phase = processingPhase(elapsed);
    const repeat = processingPhase(elapsed + PROCESSING_CYCLE * 3);
    assert.ok(Math.abs(phase.core - repeat.core) < 1e-6, "el ciclo no es periódico");
    assert.ok(Math.abs(phase.pulse - repeat.pulse) < 1e-6, "el ciclo no es periódico");
  }

  // Y nada crece ni decae de forma permanente: todo queda acotado en [0, 1].
  for (let step = 0; step < 400; step++) {
    const phase = processingPhase(step * 0.37);
    assert.ok(phase.core >= 0 && phase.core <= 1);
    assert.ok(phase.pulse >= 0 && phase.pulse <= 1);
    assert.ok(phase.signal === null || (phase.signal >= 0 && phase.signal <= 1));
    assert.ok(phase.output === null || (phase.output >= 0 && phase.output <= 1));
  }
});

test("la geometría es determinista: dos llamadas dan exactamente lo mismo", () => {
  const first = hemisphereGeometry("right", 12, 10);
  const second = hemisphereGeometry("right", 12, 10);
  assert.deepEqual([...first.positions], [...second.positions]);
  assert.deepEqual([...first.indices], [...second.indices]);
  assert.deepEqual([...neuralMesh("left").points], [...neuralMesh("left").points]);
  assert.deepEqual(neuralRoute(112.5), neuralRoute(112.5));
});

test("la malla del hemisferio es indexada y sus índices apuntan a vértices existentes", () => {
  const { positions, indices } = hemisphereGeometry("left", 16, 12);
  assert.equal(indices.length % 3, 0);
  const vertices = positions.length / 3;
  for (const index of indices) assert.ok(index < vertices, "índice fuera de rango");
});

test("la silueta en planta es simétrica entre hemisferios, arranca y acaba en el surco y mide lo que el cerebro", () => {
  const right = brainOutline("right");
  const left = brainOutline("left");
  assert.equal(right.length, left.length);
  right.forEach((point, index) => {
    assert.equal(point[0], -left[index][0]);
    assert.equal(point[1], left[index][1]);
  });
  const width = Math.max(...right.map(([x]) => x));
  assert.ok(Math.abs(width - BRAIN.halfWidth) < 0.01, `media silueta ${width}`);
  // Los dos extremos caen en la línea media: el contorno se cierra por el surco.
  assert.ok(Math.abs(right[0][0] - BRAIN.gap / 2) < 1e-6, "el contorno no arranca en el surco");
  assert.ok(Math.abs(right.at(-1)![0] - BRAIN.gap / 2) < 1e-6, "el contorno no acaba en el surco");
  const depth = Math.max(...right.map(([, z]) => z)) - Math.min(...right.map(([, z]) => z));
  assert.ok(Math.abs(depth - BRAIN.depth) < 0.02, `profundidad en planta ${depth}`);
});
