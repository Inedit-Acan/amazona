/** Hash estable 0..1 de un texto (FNV-1a), con una sal para sacar varios valores:
 * los datos de demostración salen siempre iguales para el mismo producto o proveedor. */
export function demoRandom(seed: string, salt: string): number {
  let h = 0x811c9dc5;
  for (const ch of `${seed}:${salt}`) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 0xffffffff;
}
