import { INITIAL_HEALTH, type BackendHealthState } from "./backend-health.ts";

// UN solo monitor de salud por pestaña (M47, Commit 2). La cabecera del shell y la del Director ejecutivo (bajo 768 px, donde
// el shell no enseña la suya) enseñan el mismo indicador: si cada una creara su `HealthMonitor`, habría dos peticiones por
// disparo. Este almacén cuenta sus suscriptores: crea el monitor con el primero, lo destruye con el último y reparte el mismo
// estado a todos. Al quedarse sin suscriptores vuelve a «comprobando»: un estado antiguo no se sirve como si fuera actual.

/** Lo mínimo que el almacén necesita de un monitor: nada (lo arranca y lo para `attach`). */
export interface HealthStoreOptions {
  /** Crea el monitor, lo arranca (con los disparadores del navegador) y devuelve cómo pararlo. Recibe dónde publicar. */
  attach(publish: (state: BackendHealthState) => void): () => void;
}

export interface HealthStore {
  subscribe(listener: () => void): () => void;
  getSnapshot(): BackendHealthState;
  getServerSnapshot(): BackendHealthState;
  /** Suscriptores actuales (para las pruebas). */
  subscribers(): number;
}

export function createHealthStore(options: HealthStoreOptions): HealthStore {
  const listeners = new Set<() => void>();
  let state: BackendHealthState = INITIAL_HEALTH;
  let detach: (() => void) | null = null;

  const publish = (next: BackendHealthState) => {
    state = next;
    for (const listener of [...listeners]) listener();
  };

  return {
    subscribe(listener) {
      listeners.add(listener);
      if (detach === null) detach = options.attach(publish);
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0 && detach !== null) {
          detach();
          detach = null;
          state = INITIAL_HEALTH;
        }
      };
    },
    getSnapshot: () => state,
    getServerSnapshot: () => INITIAL_HEALTH,
    subscribers: () => listeners.size,
  };
}
