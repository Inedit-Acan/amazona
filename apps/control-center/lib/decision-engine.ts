// Modelo geométrico del Decision Engine del Neural Nexus —el «cerebro» del
// Director ejecutivo—, según
// docs/design/KOVA_Decision_Engine_especificacion_visual_tecnica_final.md.
//
// Todo lo de aquí es matemática pura y DETERMINISTA: no importa three.js, no usa
// Math.random y no depende de la hora. El mismo cerebro sale en el servidor, en
// el navegador y en los tests. Los componentes de
// components/neural-nexus/scene/decision-engine/ solo lo presentan.
//
// La pieza no es una esfera ni una bola luminosa (§0): dos hemisferios
// diferenciados con un surco central real, una red neural fina que es la que
// dibuja la forma, nodos sinápticos pequeños y un poliedro de decisión en el
// centro.

export type Hemisphere = "left" | "right";
export type Vec3 = [number, number, number];

const RAD = Math.PI / 180;
/** Las coordenadas se redondean: un seno con distinto último decimal entre el
 * servidor y el navegador rompería la hidratación de la vista 2D. */
const round4 = (value: number) => Math.round(value * 10_000) / 10_000;

/** Ancho total del cerebro en unidades de escena. El anillo de dominios mide 7
 * unidades de ancho (2 × LAYOUT.domainRadius), así que el cerebro ocupa el 32 %
 * de su ancho visual: protagonista pero sin tocar los dominios (§11). */
const WIDTH = 2.24;

export const BRAIN = {
  /** Proporciones de §4.3: ancho 1,00 · alto 0,72 · profundidad 0,60. Más ancho
   * que alto, como exige la especificación. */
  width: WIDTH,
  height: round4(WIDTH * 0.72),
  depth: round4(WIDTH * 0.6),
  halfWidth: round4(WIDTH / 2),
  halfHeight: round4(WIDTH * 0.36),
  halfDepth: round4(WIDTH * 0.3),
  /** Surco central (§4.4): 5 % del ancho total, dentro del 3–7 % pedido. */
  gap: round4(WIDTH * 0.05),
  /** Núcleo geométrico (§8.4): 18 % del ancho total, dentro del 15–22 %. */
  coreRadius: round4((WIDTH * 0.18) / 2),
  /** Anillo técnico (§9): uno solo, fino, a la altura de la base del cerebro. */
  ringRadius: round4(WIDTH * 0.66),
  ringHeight: round4(-WIDTH * 0.355),
  /** Rótulo DECISION ENGINE (§22): debajo, centrado, nunca sobre el cerebro. */
  labelHeight: round4(-WIDTH * 0.47),
};

/** Tamaño del nodo sináptico (§7.2): 3,1 % del radio visual del cerebro, dentro
 * del 2–5 % pedido. */
export const SYNAPSE_SIZE = round4(WIDTH * 0.0155);

/** Proporción de enlaces encendidos (§6.3): en reposo 30–40 %, ejecutando
 * 45–65 %. Nunca el 100 % de forma permanente. */
export const NETWORK_DENSITY = { rest: 0.35, active: 0.55 };

/** Punto por el que entra la única conexión vertical del CEO (§12.2): la corona
 * del cerebro, no su centro. */
export const CEO_ANCHOR: Vec3 = [0, round4(WIDTH * 0.36 * 1.03), 0];

/** Nodos sinápticos por hemisferio. */
const SYNAPSES_PER_SIDE = 210;
/** Vecinos a los que se enlaza cada nodo: la malla queda fina, no una maraña. */
const LINKS_PER_SYNAPSE = 2;

// --- Secuencia de procesamiento -------------------------------------------------------

/** Duración del ciclo de procesamiento en segundos (§17). */
export const PROCESSING_CYCLE = 1.9;

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

export interface ProcessingPhase {
  /** Recorrido de la señal de entrada, de la zona al núcleo (0,10–0,70 s). */
  signal: number | null;
  /** Intensidad del núcleo mientras procesa (0,70–1,40 s). */
  core: number;
  /** Pulso de decisión (1,10–1,40 s). */
  pulse: number;
  /** Salida del resultado hacia el dominio (1,40–1,90 s). */
  output: number | null;
}

/** Secuencia de la animación de procesamiento (§17): entra el evento, se activa
 * la ruta neural, la señal converge, el núcleo procesa, emite el pulso de
 * decisión y sale el resultado. Todo vuelve al baseline al cerrar el ciclo, así
 * que la escena no se degrada con el tiempo (§31). */
export function processingPhase(elapsed: number): ProcessingPhase {
  const t = ((elapsed % PROCESSING_CYCLE) + PROCESSING_CYCLE) % PROCESSING_CYCLE;
  return {
    signal: t >= 0.1 && t < 0.7 ? clamp01((t - 0.1) / 0.6) : null,
    core: t < 0.7 ? 0 : t < 1.1 ? clamp01((t - 0.7) / 0.4) : t < 1.4 ? 1 : 0,
    pulse: t >= 1.1 && t < 1.4 ? Math.sin(((t - 1.1) / 0.3) * Math.PI) : 0,
    output: t >= 1.4 ? clamp01((t - 1.4) / 0.5) : null,
  };
}

// --- Forma del hemisferio -------------------------------------------------------------

/** Hash entero determinista (sin Math.random y sin Math.sin: mismo valor en
 * cualquier motor). Devuelve [0, 1). */
function hash01(seed: number): number {
  let x = Math.imul(seed ^ 0x9e3779b9, 0x85ebca6b);
  x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35);
  return ((x ^ (x >>> 16)) >>> 0) / 4_294_967_296;
}

/** Parametrización del hemisferio derecho: `v` es el ángulo polar (0 arriba, π
 * abajo) y `u` el azimut dentro de la mitad (0 al frente, π/2 al lateral, π al
 * fondo). El hemisferio izquierdo es su espejo en x. */
function unitDirection(u: number, v: number): Vec3 {
  const sv = Math.sin(v);
  return [sv * Math.sin(u), Math.cos(v), sv * Math.cos(u)];
}

/** Punto del hemisferio unitario, antes de ajustarlo a las proporciones. El
 * elipsoide se convierte en cerebro con tres perfiles independientes —planta
 * ovoide, bóveda alta con base aplanada y lóbulo temporal— más un relieve fino
 * de circunvoluciones. Es geometría de lectura, no anatomía médica (§4.1), y la
 * ondulación usa frecuencias que no son múltiplos para no quedar como una
 * rejilla perfecta (§19). */
function rawPoint(u: number, v: number): Vec3 {
  const [dx, dy, dz] = unitDirection(u, v);
  const front = Math.max(0, dz);
  const back = Math.max(0, -dz);
  const below = Math.max(0, -dy);

  // Relieve: dos ondas de frecuencias no múltiplos.
  const gyri = 1 + 0.028 * Math.sin(7 * u) * Math.sin(5 * v) + 0.015 * Math.sin(11 * u + 2.3) * Math.sin(8 * v + 1.1);
  // Lóbulo temporal: bulto lateral bajo, algo retrasado.
  const temporal = 1 + 0.1 * Math.exp(-6 * ((dx - 0.8) ** 2 + (dy + 0.5) ** 2 + (dz - 0.08) ** 2));
  const shape = gyri * temporal;

  // Planta ovoide: el lóbulo frontal es claramente más estrecho que el parietal
  // y el occipital se cierra un poco. Sin esto la silueta es una caja redondeada.
  const plan = 1 - 0.38 * front ** 1.4 - 0.2 * back ** 1.7;
  // Alzado: bóveda alta y base aplanada, que es donde el cerebro se apoya.
  const vault = 1 - 0.22 * below ** 1.3;
  // La cara inferior es además más corta de delante a atrás.
  const underside = 1 - 0.16 * below ** 1.6;

  return [dx * shape * plan, dy * shape * vault, dz * shape * underside];
}

/** Apertura del surco a cada altura (§4.4): abierto en toda la bóveda y cerrado
 * por debajo, donde los hemisferios se unen. La separación no divide el cerebro
 * en dos piezas sueltas. */
function gapFactor(v: number): number {
  const start = Math.PI * 0.55;
  const end = Math.PI * 0.95;
  if (v <= start) return 1;
  const t = Math.min(1, (v - start) / (end - start));
  return 1 - 0.88 * t * t * (3 - 2 * t); // smoothstep
}

/** Extremos del hemisferio sin escalar, medidos una sola vez sobre una malla
 * densa. Sirven para que las proporciones finales sean EXACTAMENTE las de §4.3
 * aunque se retoque `shapeFactor`. */
const RAW = (() => {
  let maxX = 0;
  let minY = Infinity;
  let maxY = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  const steps = 96;
  for (let i = 0; i <= steps; i++) {
    for (let j = 0; j <= steps; j++) {
      const [x, y, z] = rawPoint((i / steps) * Math.PI, (j / steps) * Math.PI);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
      minZ = Math.min(minZ, z);
      maxZ = Math.max(maxZ, z);
    }
  }
  return { maxX, minY, maxY, minZ, maxZ };
})();

/** Ajuste a las proporciones de §4.3 y centrado del volumen en el origen: el
 * núcleo, que va en [0, 0, 0], queda así en el centro real del cerebro (§8.3). */
const FIT = {
  x: (BRAIN.halfWidth - BRAIN.gap / 2) / RAW.maxX,
  y: BRAIN.height / (RAW.maxY - RAW.minY),
  yShift: -(RAW.maxY + RAW.minY) / 2,
  z: BRAIN.depth / (RAW.maxZ - RAW.minZ),
  zShift: -(RAW.maxZ + RAW.minZ) / 2,
};

/** Punto del hemisferio para (u, v). `radial` = 1 es la superficie; por debajo
 * de 1, el interior. */
export function surfacePoint(side: Hemisphere, u: number, v: number, radial = 1): Vec3 {
  const [rx, ry, rz] = rawPoint(u, v);
  const sign = side === "left" ? -1 : 1;
  const x = FIT.x * rx * radial;
  const y = FIT.y * (ry + FIT.yShift) * radial;
  const z = FIT.z * (rz + FIT.zShift) * radial;
  return [round4(sign * (x + (BRAIN.gap / 2) * gapFactor(v))), round4(y), round4(z)];
}

/** (u, v) de una dirección cualquiera, para poder anclar algo en la zona del
 * cerebro que mira hacia ella. */
export function directionToUV(direction: Vec3): [number, number] {
  const [x, y, z] = direction;
  const length = Math.hypot(x, y, z) || 1;
  const v = Math.acos(Math.min(1, Math.max(-1, y / length)));
  const u = Math.atan2(Math.abs(x) / length, z / length);
  return [u, v];
}

/** Punto de la superficie (o del interior) en la dirección dada. */
export function surfaceFromDirection(direction: Vec3, radial = 1): Vec3 {
  const [u, v] = directionToUV(direction);
  return surfacePoint(direction[0] < 0 ? "left" : "right", u, v, radial);
}

// --- Malla del hemisferio (silueta cerebral) ------------------------------------------

export interface HemisphereGeometry {
  positions: Float32Array;
  indices: Uint16Array;
}

/** Geometría de un hemisferio como BufferGeometry indexada (§29: nada de crear
 * geometría por frame). Son dos piezas separadas, BrainLeft y BrainRight (§5.1),
 * no una esfera deformada. */
export function hemisphereGeometry(side: Hemisphere, segmentsU = 40, segmentsV = 30): HemisphereGeometry {
  const positions = new Float32Array((segmentsU + 1) * (segmentsV + 1) * 3);
  const indices: number[] = [];
  let cursor = 0;
  for (let i = 0; i <= segmentsU; i++) {
    for (let j = 0; j <= segmentsV; j++) {
      const [x, y, z] = surfacePoint(side, (i / segmentsU) * Math.PI, (j / segmentsV) * Math.PI);
      positions[cursor++] = x;
      positions[cursor++] = y;
      positions[cursor++] = z;
    }
  }
  const stride = segmentsV + 1;
  for (let i = 0; i < segmentsU; i++) {
    for (let j = 0; j < segmentsV; j++) {
      const a = i * stride + j;
      const b = a + stride;
      // El devanado se invierte en el hemisferio izquierdo, que está reflejado.
      if (side === "right") indices.push(a, b, a + 1, b, b + 1, a + 1);
      else indices.push(a, a + 1, b, b, a + 1, b + 1);
    }
  }
  return { positions, indices: new Uint16Array(indices) };
}

/** Silueta del hemisferio en planta —pares (x, z)— para la vista 2D, que
 * proyecta la escena por arriba. Recorre el contorno del ecuador desde el surco
 * frontal hasta el surco posterior, así que se cierra sola: el primer y el
 * último punto están en la línea media. */
export function brainOutline(side: Hemisphere, steps = 40): [number, number][] {
  const outline: [number, number][] = [];
  const heights = 32;
  for (let i = 0; i <= steps; i++) {
    const u = (i / steps) * Math.PI;
    // El borde en planta es el punto más lateral de cada meridiano, que no
    // siempre cae en el ecuador: el lóbulo temporal ensancha algo más abajo.
    let best: [number, number] = [0, 0];
    for (let j = 1; j < heights; j++) {
      const [x, , z] = surfacePoint(side, u, (j / heights) * Math.PI);
      if (Math.abs(x) >= Math.abs(best[0])) best = [x, z];
    }
    outline.push(best);
  }
  return outline;
}

// --- Red neural y nodos sinápticos ----------------------------------------------------

export interface NeuralMesh {
  /** Posiciones de los nodos sinápticos, tres componentes por nodo. */
  points: Float32Array;
  /** Intensidad de reposo de cada nodo (0–1). Algunos quedan apagados (§7.3). */
  pointBase: Float32Array;
  /** Pares de índices de cada enlace. */
  links: Uint16Array;
  /** Umbral de densidad de cada enlace: visible si umbral < densidad (§6.3). */
  linkThreshold: Float32Array;
}

const MESH_CACHE = new Map<Hemisphere, NeuralMesh>();

/** Red neural de un hemisferio: nodos repartidos por la superficie y el interior
 * con una espiral de ángulo áureo, y enlaces a los vecinos más cercanos. Se
 * calcula una vez y se reutiliza. */
export function neuralMesh(side: Hemisphere): NeuralMesh {
  const cached = MESH_CACHE.get(side);
  if (cached) return cached;

  const count = SYNAPSES_PER_SIDE;
  const points = new Float32Array(count * 3);
  const pointBase = new Float32Array(count);
  const seed = side === "left" ? 1_000 : 7_000;

  for (let i = 0; i < count; i++) {
    const v = Math.acos(1 - (2 * (i + 0.5)) / count);
    const u = ((i * 2.399_963_23) % (Math.PI * 2)) / 2;
    // Algo más de la mitad de los nodos van en la piel: son los que dibujan la
    // forma. El resto se reparte por dentro y da volumen.
    const radial = i % 2 === 0 ? 0.995 : 0.6 + 0.3 * hash01(seed + i * 3);
    const [x, y, z] = surfacePoint(side, u, v, radial);
    points[i * 3] = x;
    points[i * 3 + 1] = y;
    points[i * 3 + 2] = z;
    const level = hash01(seed + i * 11 + 1);
    pointBase[i] = level < 0.18 ? 0 : 0.18 + level * 0.44;
  }

  const pairs = new Set<number>();
  const links: number[] = [];
  for (let i = 0; i < count; i++) {
    const near: { index: number; distance: number }[] = [];
    for (let j = 0; j < count; j++) {
      if (j === i) continue;
      const dx = points[i * 3] - points[j * 3];
      const dy = points[i * 3 + 1] - points[j * 3 + 1];
      const dz = points[i * 3 + 2] - points[j * 3 + 2];
      near.push({ index: j, distance: dx * dx + dy * dy + dz * dz });
    }
    near.sort((a, b) => a.distance - b.distance);
    for (let k = 0; k < LINKS_PER_SYNAPSE; k++) {
      const other = near[k].index;
      const key = Math.min(i, other) * count + Math.max(i, other);
      if (pairs.has(key)) continue;
      pairs.add(key);
      links.push(i, other);
    }
  }

  const linkThreshold = new Float32Array(links.length / 2);
  for (let i = 0; i < linkThreshold.length; i++) linkThreshold[i] = hash01(seed + i * 17 + 5);

  const mesh: NeuralMesh = { points, pointBase, links: new Uint16Array(links), linkThreshold };
  MESH_CACHE.set(side, mesh);
  return mesh;
}

/** Índice del nodo sináptico más cercano a un punto, dentro de un hemisferio. */
function nearestSynapse(side: Hemisphere, target: Vec3): number {
  const { points } = neuralMesh(side);
  let best = 0;
  let bestDistance = Infinity;
  for (let i = 0; i < points.length / 3; i++) {
    const dx = points[i * 3] - target[0];
    const dy = points[i * 3 + 1] - target[1];
    const dz = points[i * 3 + 2] - target[2];
    const distance = dx * dx + dy * dy + dz * dz;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = i;
    }
  }
  return best;
}

// --- Zonas neurales de cada dominio ---------------------------------------------------

/** Dirección de la zona del cerebro con la que conecta un dominio (§13.2 y §14).
 * Sale de su propio ángulo en el anillo: el hemisferio es siempre el de su lado
 * de la pantalla y la altura sube con la profundidad, así que los ocho dominios
 * entran por ocho zonas distintas y ninguna conexión cruza el cerebro. */
export function zoneDirection(angleDeg: number): Vec3 {
  const rad = angleDeg * RAD;
  const lateral = Math.sin(rad);
  // Los dominios del fondo entran por arriba y los del frente, por abajo: es lo
  // que reparte las ocho zonas de §14 entre superior, medio e inferior.
  const depth = Math.cos(rad);
  const vector: Vec3 = [lateral, depth * 0.62, -depth * 0.8];
  const length = Math.hypot(...vector) || 1;
  return [round4(vector[0] / length), round4(vector[1] / length), round4(vector[2] / length)];
}

/** Punto exacto de entrada de un dominio en el cerebro, un pelo por fuera de la
 * superficie para que la conexión se vea llegar. */
export function zoneAnchor(angleDeg: number): Vec3 {
  return surfaceFromDirection(zoneDirection(angleDeg), 1.03);
}

export interface NeuralRoute {
  /** Recorrido desde la zona del dominio hasta el núcleo (§15.2). */
  path: Vec3[];
  /** Nodos sinápticos que la ruta enciende a su paso (§7.4). */
  synapses: number[];
  side: Hemisphere;
}

/** Ruta neural de un dominio: entra por su zona, salta de nodo en nodo y
 * converge en el núcleo. La activación sigue esta ruta; nunca son parpadeos
 * sueltos (§7.4, §15.2). */
export function neuralRoute(angleDeg: number): NeuralRoute {
  const anchor = zoneAnchor(angleDeg);
  const side: Hemisphere = anchor[0] < 0 ? "left" : "right";
  const { points } = neuralMesh(side);
  const path: Vec3[] = [anchor];
  const synapses: number[] = [];
  const steps = 4;
  for (let step = 1; step <= steps; step++) {
    const t = (step / (steps + 1)) * 0.82;
    const target: Vec3 = [anchor[0] * (1 - t), anchor[1] * (1 - t), anchor[2] * (1 - t)];
    const index = nearestSynapse(side, target);
    if (synapses.includes(index)) continue;
    synapses.push(index);
    path.push([round4(points[index * 3]), round4(points[index * 3 + 1]), round4(points[index * 3 + 2])]);
  }
  path.push([0, 0, 0]);
  return { path, synapses, side };
}
