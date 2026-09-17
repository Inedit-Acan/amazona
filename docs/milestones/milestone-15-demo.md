# Milestone 15 Demo

**Ticket:** IVA-34 (Fase 4.6, "Documentar el sistema") — Linear, proyecto
"Fase 4 — Integración y pruebas". **Último milestone de Fase 4.**

Plan: [`docs/superpowers/plans/2026-09-17-amazona-milestone-15.md`](../superpowers/plans/2026-09-17-amazona-milestone-15.md).
**Sin ADR** — documentación pura, ninguna decisión de arquitectura nueva.

## Qué se entrega

Antes de este milestone, entender el sistema completo requería leer 14
`milestone-N-demo.md` en orden (cada uno documenta un incremento, no el
estado agregado) más el `README.md`, que había quedado congelado en el
estado de Milestone 2 — su sección "Arquitectura de agentes" seguía
describiendo el diseño aspiracional original de 11 agentes del README
inicial, y "Estado" no mencionaba nada después de Milestone 2.

Se entregan tres documentos:

1. **[`docs/architecture/system-overview.md`](../architecture/system-overview.md)**
   (nuevo, el punto de entrada real): documenta, tal como quedó el
   sistema tras Milestones 1-14 —
   - Las dos capas de orquestación paralelas y por qué están separadas
     (`CEOOrchestrator` de Milestone 1 vs `PipelineOrchestrator` de
     Milestone 12, ADR 0001 y ADR 0005).
   - El catálogo completo de los 13 agentes (capability, patrón
     validar-uno/descubrir-muchos, tabla, endpoint API) en una sola
     tabla.
   - El modelo de datos agrupado por dominio.
   - Los dos mecanismos de control humano en sus dos capas distintas
     (aprobación de gasto de Milestone 1 + revisión/kill-switch de
     Milestone 14).
   - Seguridad (RLS deny-by-default, ADR 0003) y el protocolo de
     mensajería entre agentes (ADR 0002).
   - Un índice de las 6 ADRs y los 15 milestones, cada uno con un
     resumen de una línea y su enlace.
2. **`README.md`** actualizado: arquitectura real (no la de 11 agentes
   aspiracional original), estado real de las 4 fases, y remite a
   `system-overview.md` como punto de entrada para el detalle.
3. Este documento, cerrando Fase 4.

## Decisión de alcance

- No se reescribió ningún `milestone-N-demo.md` existente — siguen
  siendo el registro histórico de lo que se verificó en cada momento
  (incluye, por ejemplo, cifras de conteo de tests que ya no son las
  actuales). `system-overview.md` es el documento que se mantiene al día
  con el estado agregado; los milestones quedan como bitácora.
- No se generó ningún diagrama fuera de Markdown (ASCII inline) — no hay
  herramienta de diagramación ya establecida en este repo, y añadir una
  sería una decisión nueva fuera del alcance de "documentar lo que ya
  existe".

## Verificación

Todo enlace interno de los tres documentos apunta a un archivo real del
repo (comprobado a mano — no hay link-checker en este proyecto). Ningún
código se tocó:

```bash
cd backend && ruff check . && mypy app && pytest       # 488 tests, sin cambios
cd apps/control-center && npm run lint && npx next typegen && npx tsc --noEmit && npm test && npm run build
```

## Cierre de Fase 4

Con esto se completan los 6 tickets de "Fase 4 — Integración y pruebas":

- **4.1/4.2 (IVA-29/30, Milestone 12):** `PipelineOrchestrator` encadena
  los 9 agentes de Fase 3 automáticamente, con tests de flujo completo
  internos (no solo llamadas HTTP secuenciales manuales).
- **4.3/4.4 (IVA-31/32, Milestone 13):** validación contra el espacio
  combinatorio real (categoría × mercado × precio), 3 correcciones
  reales encontradas y corregidas (colisión de `store_slug`, ausencia
  total de índices, `CFOService` cargando tablas completas).
- **4.5 (IVA-33, Milestone 14):** revisión humana obligatoria post-hoc
  sobre ejecuciones de riesgo + kill switch pre-hoc — los dos controles
  críticos que faltaban sobre el pipeline ya automatizado.
- **4.6 (IVA-34, Milestone 15):** este documento.

No queda ningún hueco abierto conocido en el diseño de tres capas
(Orquestador/CEO/CFO) ni en la integración de Fase 3 (pipeline +
controles humanos). Trabajo futuro razonable, no bloqueante, señalado a
lo largo de Fase 4: persistir de verdad las reservas de `BudgetEngine`
más allá de lo que Milestone 11 ya cerró si el volumen de aprobaciones
crece; ampliar el dataset de `MockTrendsProvider`/`MockRegulatoryDirectory`
más allá de las 3 categorías/3 mercados actuales si se necesita validar
casos más diversos; y, si el pipeline alguna vez ejecuta una acción
externa real, revisar ADR 0005/0006 explícitamente antes de introducir
pausas intermedias.
