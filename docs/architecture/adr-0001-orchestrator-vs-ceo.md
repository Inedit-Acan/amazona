# ADR 0001: Relación entre el Agente 9 (Orquestador) y el Agente CEO

- **Estado:** Aceptada
- **Fecha:** 2026-09-16
- **Contexto de milestone:** al cierre de Milestone 1, antes de empezar Milestone 2

## Contexto

El README original del proyecto describe la arquitectura de agentes objetivo así:

> - **Orquestador (Agente 9):** coordina el flujo entre agentes.
> - **Agente CEO:** define objetivos y toma decisiones de alto nivel.
> - **Agente CFO:** control económico...
> - **8 agentes operativos:** investigación de productos, proveedores, análisis
>   económico, legal, e-commerce, marketplaces, marketing y atención al cliente.

Esto sugiere un diseño objetivo de **11 agentes direccionables** (Orquestador +
CEO + CFO + 8 operativos), cada uno potencialmente un proceso o servicio
independiente que se comunica con los demás.

En Milestone 1 implementamos una única clase, `CEOOrchestrator`
(`backend/app/ceo/orchestrator.py`), que en la práctica asume **ambos** roles:

- **Coordinación técnica** ("cómo se hace el trabajo"): carga el objetivo,
  crea el proyecto, crea las tareas a partir del plan, las despacha al
  `AgentManager` por capability, persiste resultados, emite eventos
  (`InProcessEventBus`) y audita cada transición (`AuditService` +
  tabla `audit_log`).
- **Cognición estratégica** ("qué se decide y por qué"): delega en
  `app/ceo/planner.py` (descompone el objetivo en el grafo de tareas) y
  `app/ceo/decision_engine.py` (sintetiza los resultados de los agentes
  especialistas en `GO | REVIEW | NO_GO | HUMAN_APPROVAL` de forma
  determinista, sin LLM).

Antes de construir Milestone 2 (protocolo de comunicación entre agentes,
memoria compartida, auth/roles) hace falta decidir si Orquestador y CEO son
**la misma pieza** o **dos capas** — porque el protocolo de comunicación que
se diseñe a continuación depende directamente de esta respuesta.

## Decisión

**Son dos capas conceptuales, no dos agentes independientes en tiempo de
ejecución (todavía).**

- **Agente 9 (Orquestador)** = motor de coordinación técnica. Vive en
  `CEOOrchestrator` (los métodos `_create_project`, `_create_tasks`,
  `_execute_tasks`, y el uso de `AgentManager`/`EventBus`/`AuditService`).
  Es infraestructura: sabe *cómo* ejecutar un grafo de tareas y *no* sabe
  nada sobre reglas de negocio (opportunity score, umbrales de confianza,
  vetoes legales/financieros).
- **Agente CEO** = capa cognitiva/estratégica. Vive en `app/ceo/planner.py`
  y `app/ceo/decision_engine.py`, invocada *por* el Orquestador. Sabe *qué*
  decidir (cómo descomponer un objetivo, cuándo vetar, cuándo pedir
  aprobación humana) y no sabe nada sobre SQLAlchemy, sesiones de DB o
  HTTP.

Es decir: el Orquestador es el runtime; el CEO es la política/el cerebro que
ese runtime consulta. Ya existía esta separación a nivel de módulo en
Milestone 1 — esta ADR solo la formaliza como decisión de arquitectura
explícita antes de que Milestone 2 construya sobre ella.

## Razonamiento

1. **Milestone 1 eligió explícitamente un monolito modular** (ninguna
   microservicio). Separar Orquestador y CEO en dos procesos/servicios que
   se comuniquen por red añadiría complejidad operativa real (dos
   despliegues, IPC, nuevos modos de fallo) sin que exista todavía una
   necesidad concreta que lo justifique.
2. La separación de responsabilidades **ya está expresada a nivel de
   módulo** (`planner.py` / `decision_engine.py` vs. el bucle de ejecución
   de `orchestrator.py`), lo que nos deja la puerta abierta a extraer la
   capa CEO como agente direccionable más adelante sin haber diseñado algo
   que nos encierre en una esquina.
3. El **protocolo de comunicación entre agentes** que se construye en
   Milestone 2 (2.3) está pensado para la relación CEO ↔ agentes
   especialistas (Product, Supplier, Finance, Legal, y el nuevo Product
   Research), que **sí** son procesos/lógicas desacopladas hoy (cada uno
   implementa `Agent.run()` de forma independiente y se descubre por
   capability vía `AgentRegistry`). No es necesario para la relación
   Orquestador↔CEO porque siguen siendo el mismo proceso Python.

## Consecuencias

- `CEOOrchestrator` sigue siendo dueño de la coordinación técnica (grafo de
  tareas, persistencia, eventos, auditoría) — responsabilidad de "Agente 9".
- `planner.py` + `decision_engine.py` (y el nuevo chequeo de política de
  permisos/presupuesto) representan colectivamente al "Agente CEO" — se
  mantienen como lógica pura invocada por el Orquestador, no como un
  proceso separado.
- El protocolo de mensajería de Milestone 2 (2.3) se diseña para
  CEO ↔ agentes especialistas, no para Orquestador ↔ CEO.
- Si en un milestone futuro el CEO necesita operar de forma autónoma (por
  ejemplo, crear objetivos proactivamente, o negociar contención de
  recursos entre varios objetivos concurrentes), **entonces** se promovería
  el CEO a un agente direccionable propio usando el mismo protocolo. Esta
  ADR debe revisarse en ese momento.
- Nomenclatura de aquí en adelante en código/docs: "Orchestrator" o
  "Agente 9" = la clase `CEOOrchestrator` y su bucle de ejecución.
  "CEO" o "Agente CEO" = `planner.py` + `decision_engine.py` + las reglas
  de política que aplican sobre el resultado de los agentes especialistas.
