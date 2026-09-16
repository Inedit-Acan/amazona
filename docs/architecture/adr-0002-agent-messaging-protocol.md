# ADR 0002: Protocolo de mensajería entre agentes

- **Estado:** Aceptada
- **Fecha:** 2026-09-16
- **Depende de:** [ADR 0001](adr-0001-orchestrator-vs-ceo.md)

## Contexto

En Milestone 1, la frontera CEO ↔ agente especialista se cruzaba con un
`dict` sin tipar en ambas direcciones: `task_input: dict` hacia el agente,
y `AgentResult` (sí tipado) de vuelta. El `task_input` no tenía contrato
formal — cada agente asumía qué claves esperar (`estimated_monthly_searches`,
`unit_cost`, etc.) sin que nada lo validara antes de tiempo de ejecución.

Con Milestone 2 se añade un quinto agente (Product Research) y se sientan
las bases para los 7 agentes restantes de Fase 3. Cuantos más agentes,
más caro se vuelve un drift de esquema silencioso.

## Decisión

Toda comunicación CEO ↔ agente especialista pasa por `AgentMessage`
(`backend/app/messaging/schemas.py`): un sobre versionado
(`schema_version`, `message_id`, `correlation_id`, `sender`, `recipient`,
`capability`, `payload`, `sent_at`).

**Alcance explícito — por qué CEO↔especialistas y no Orquestador↔CEO:**
según ADR 0001, el Orquestador y el CEO son dos capas del mismo proceso
Python, no dos agentes que se comuniquen por red o cola de mensajes. No
hay frontera de proceso que formalizar ahí — `orchestrator.py` llama
directamente a `planner.py`/`decision_engine.py` como funciones Python.
El protocolo formal solo tiene sentido donde ya existe una frontera real:
el `AgentManager` invoca `Agent.run(task_input)` sobre implementaciones
independientes descubiertas por capability (`AgentRegistry`), y ahí es
donde un contrato explícito previene errores.

**Validación de esquema por capability (Tarea 6):** cada `Agent` puede
declarar opcionalmente `input_schema`/`output_schema` (Pydantic models);
el `AgentManager` valida contra ellos antes/después de invocar
`Agent.run()`. Es aditivo — un agente sin esquema declarado (los 4 de
Milestone 1) sigue funcionando exactamente igual que antes.

## Razonamiento

1. Falla rápido y con mensaje claro: un payload que no cumple el
   contrato se rechaza en el `AgentManager`, no como un `KeyError`
   confuso dentro del agente tres líneas después.
2. `schema_version` permite evolucionar el contrato de un agente sin
   romper a los demás — un agente puede declarar que soporta v1.0 y
   v1.1 simultáneamente durante una migración.
3. No se ha migrado *todavía* el paso `task_input`/`AgentResult` actual
   de los 4 agentes de Milestone 1 a pasar literalmente por
   `AgentMessage` en el `AgentManager.execute()` — eso es deliberado:
   la Tarea 6 añade la *validación* de esquema declarado sin forzar un
   refactor de la firma de `execute()`, para no tocar los 4 agentes
   existentes. Si en un futuro milestone el transporte deja de ser una
   llamada a función Python directa (p. ej. agentes en procesos
   separados, o vía cola), `AgentMessage` es el sobre que ya existe
   para envolver esa llamada sin rediseñar el contrato de payload.

## Consecuencias

- Nuevos agentes (Fase 3) deberían declarar `input_schema`/`output_schema`
  desde el principio.
- Los 4 agentes de Milestone 1 no se tocan — siguen sin esquema
  declarado, y el `AgentManager` los trata igual que siempre.
- Si el CEO alguna vez se promueve a agente direccionable propio (ver
  ADR 0001, sección "Consecuencias"), la comunicación
  Orquestador↔CEO empezaría a usar este mismo `AgentMessage` — no haría
  falta un protocolo nuevo.
