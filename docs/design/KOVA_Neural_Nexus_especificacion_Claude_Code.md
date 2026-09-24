# KOVA Neural Nexus — Especificación para Claude Code

**Proyecto:** KOVA  
**Módulo:** Grafo 3D de agentes del panel Director Ejecutivo  
**Nombre interno:** `KOVA Neural Nexus`  
**Estado:** especificación aprobada para implementación  
**Objetivo:** construir una visualización 3D premium, funcional y ejecutiva del sistema multiagente de KOVA.

---

# 1. Objetivo del módulo

Construir un grafo 3D interactivo que represente el sistema multiagente de KOVA como un **núcleo de inteligencia operativo**, con:

- CEO como orquestador superior;
- Decision Engine como núcleo central;
- 8 dominios funcionales;
- 13 agentes operativos reales;
- conexiones jerárquicas y dinámicas;
- actividad visible en tiempo real;
- estados operativos;
- interacción por nodo;
- modos:
  - Arquitectura
  - Ejecución
  - Incidencias
- vista 3D principal;
- vista 2D como alternativa técnica/fallback.

El módulo debe ser útil para entender:
- quién está activo;
- qué agente ejecuta una tarea;
- qué dominio interviene;
- qué relaciones existen;
- qué flujo de información se está produciendo;
- dónde hay bloqueos o dependencias.

No debe ser una animación decorativa.

---

# 2. Principios visuales

La escena debe transmitir:

- inteligencia;
- control;
- precisión;
- coordinación;
- jerarquía;
- actividad;
- sofisticación tecnológica.

La estética debe ser:

- premium;
- empresarial;
- tecnológica;
- sobria;
- futurista sin estética gaming.

## Evitar

No usar:

- exceso de efectos;
- rayos eléctricos;
- humo pesado;
- saturación de partículas;
- colores innecesarios;
- conexiones permanentes demasiado densas;
- movimiento caótico;
- force-layout libre como composición principal;
- estética cyberpunk extrema;
- cámara totalmente libre;
- elementos ornamentales sin función.

---

# 3. Identidad visual

## Paleta base

```css
--bg-0: #030606;
--bg-1: #050a09;
--panel: #071713;
--panel-2: #0a221c;

--emerald: #00d69a;
--emerald-bright: #15f0b2;
--cyan-green: #28e5d0;

--text-primary: #f5f7f7;
--text-secondary: #9ca9a5;

--warning: #f3b63f;
--danger: #ef5a5a;
--inactive: #52615d;
```

## Estados por color

| Estado | Color principal |
|---|---|
| Disponible | verde esmeralda suave |
| Ejecutando | esmeralda/cian brillante |
| Esperando | ámbar |
| Bloqueado | rojo |
| Error | rojo |
| Inactivo | gris verdoso |
| Seleccionado | halo esmeralda intenso |
| Relacionado | verde/cian normal |
| Atenuado | baja opacidad |

No depender solo del color: usar también iconos, etiquetas y texto.

---

# 4. Stack técnico recomendado

Implementar preferentemente con:

```text
Next.js
React
React Three Fiber
Three.js
@react-three/drei
Zustand o store equivalente
Framer Motion para UI 2D si se necesita
```

## Reglas técnicas

- La escena principal debe usar `React Three Fiber`.
- Three.js se usa como motor base.
- El layout debe ser determinista.
- No depender de force-graph automático para posiciones principales.
- El estado del grafo debe estar desacoplado de la visualización.
- La vista 2D debe consumir los mismos datos que la vista 3D.

---

# 5. Jerarquía conceptual

```text
CEO
↓
Decision Engine
↓
Dominios
↓
Agentes
```

La jerarquía debe entenderse visualmente sin necesidad de explicación adicional.

---

# 6. Entidades del grafo

## Nivel 1 — CEO

Nodo superior.

Función:
- orquestador global;
- coordina agentes;
- supervisa misiones;
- inicia decisiones.

No debe aparecer como un agente operativo más.

---

## Nivel 2 — Decision Engine

Núcleo central de la escena.

Función:
- procesa inputs;
- evalúa estados;
- coordina decisiones;
- enruta tareas;
- representa la inteligencia central del sistema.

Debe ser el elemento visual dominante.

---

## Nivel 3 — 8 dominios

```text
Investigación
Abastecimiento
Economía
Legal
Comercio
Marketing
Operaciones
Finanzas
```

Los dominios actúan como agrupadores visuales y funcionales.

---

## Nivel 4 — 13 agentes

### Investigación
1. Product Hunter
2. Market Analyst

### Abastecimiento
3. Supplier Finder
4. Trade & Logistics Analyst

### Economía
5. Unit Economics Analyst
6. Risk Analyst

### Legal
7. Product Compliance Agent
8. Commerce & Consumer Law Agent

### Comercio
9. Storefront Builder
10. Marketplace Channel Agent

### Marketing
11. Acquisition Agent

### Operaciones
12. Operations & Customer Service Agent

### Finanzas
13. CFO / Financial Controller

---

# 7. Composición espacial

## 7.1. Decision Engine

Posición central:

```text
(0, 0, 0)
```

Debe estar formado por una combinación de:

- núcleo energético;
- esfera/cerebro holográfico;
- partículas;
- filamentos internos;
- malla neural;
- glow;
- anillos internos;
- pulsación suave.

No usar un cerebro anatómico literal.

---

## 7.2. CEO

Posición:
- centrado;
- por encima del Decision Engine;
- físicamente separado del resto.

Ejemplo conceptual:

```text
CEO
 |
 |
Decision Engine
```

Debe tener conexión permanente y clara con el núcleo.

---

## 7.3. Anillo de dominios

Disposición radial fija alrededor del núcleo.

Orden recomendado, en sentido horario:

```text
Investigación
Abastecimiento
Economía
Legal
Finanzas
Operaciones
Marketing
Comercio
```

La distribución debe ser estable entre sesiones.

No recolocar nodos automáticamente.

---

## 7.4. Anillo de agentes

Radio exterior.

Los agentes deben colocarse cerca del dominio al que pertenecen.

Ejemplo:

```text
Investigación
 ├─ Product Hunter
 └─ Market Analyst
```

La posición espacial debe ser memorizable por el usuario.

---

# 8. Capas visuales

La escena debe componerse de las siguientes capas:

## Capa 1 — Fondo
- negro profundo;
- degradado radial muy sutil;
- fog ligero;
- pocas partículas ambientales.

## Capa 2 — Decision Engine
- núcleo central;
- filamentos;
- malla;
- partículas;
- glow;
- halo;
- anillos.

## Capa 3 — CEO
- nodo superior;
- conexión vertical.

## Capa 4 — Dominios
- 8 nodos en órbita intermedia.

## Capa 5 — Agentes
- 13 nodos exteriores.

## Capa 6 — Conexiones
- jerarquía;
- flujo;
- dependencia;
- incidencia.

## Capa 7 — Partículas de actividad
- solo en conexiones activas.

## Capa 8 — HUD 2D
- controles;
- métricas;
- leyenda;
- filtros.

## Capa 9 — Panel de detalle
- aparece al seleccionar nodo.

---

# 9. Tipos de nodos

```ts
type NodeType =
  | "ceo"
  | "core"
  | "domain"
  | "agent";
```

## Estados

```ts
type NodeStatus =
  | "available"
  | "running"
  | "waiting"
  | "blocked"
  | "error"
  | "inactive";
```

---

# 10. Modelo de datos sugerido

```ts
interface GraphNode {
  id: string;
  type: NodeType;
  label: string;

  domain?: string;

  position: [number, number, number];

  status: NodeStatus;

  icon?: string;
  description?: string;

  projectId?: string;
  projectName?: string;

  task?: string;
  progress?: number;

  metrics?: {
    successRate?: number;
    latencyMs?: number;
    costToday?: number;
    evaluationScore?: number;
    runs?: number;
  };
}
```

## Conexiones

```ts
interface GraphEdge {
  id: string;

  source: string;
  target: string;

  type:
    | "hierarchy"
    | "flow"
    | "dependency"
    | "incident";

  active?: boolean;

  intensity?: number;

  hiddenInArchitecture?: boolean;

  status?: "normal" | "warning" | "error";
}
```

---

# 11. Tipos de conexión

## CEO → Decision Engine

Siempre visible.

Características:
- conexión principal;
- sobria;
- estable;
- opacidad media.

---

## Decision Engine → Dominios

Siempre visibles en modo Arquitectura.

Características:
- líneas curvas;
- esmeralda tenue;
- poco glow.

---

## Dominios → Agentes

Visibles por defecto.

Características:
- más finas;
- menor opacidad;
- agrupadas visualmente.

---

## Agente → Agente

Solo mostrar cuando exista:
- flujo activo;
- dependencia;
- handoff;
- incidencia.

No mostrar todas las relaciones cruzadas simultáneamente.

---

# 12. Animaciones principales

## 12.1. Pulsación del núcleo

El Decision Engine debe respirar visualmente.

Animación:
- escala muy leve;
- variación del glow;
- frecuencia lenta.

Evitar oscilaciones exageradas.

---

## 12.2. Flujo de eventos

Cuando exista una transmisión:

```text
Agent A
→ Domain
→ Decision Engine
→ Domain
→ Agent B
```

Representar con:
- partículas luminosas;
- recorrido por curvas;
- pequeña estela;
- pulso al llegar.

---

## 12.3. Flash de decisión

Cuando el Decision Engine procese una decisión:

- incremento breve de brillo;
- onda radial;
- retorno suave al estado normal.

No usar flashes agresivos.

---

## 12.4. Rotación orbital

Puede existir rotación:
- muy lenta;
- decorativa;
- solo en anillos secundarios.

Los nodos no deben girar constantemente alrededor del núcleo si eso rompe la memoria espacial.

---

## 12.5. Scan

Añadir un barrido de escáner muy sutil:

- plano vertical;
- línea horizontal;
- onda radial;

solo ocasionalmente.

---

# 13. Estados visuales por nodo

## Disponible
- brillo bajo;
- animación mínima.

## Ejecutando
- brillo alto;
- pulsación;
- flujo activo.

## Esperando
- ámbar;
- pulso lento.

## Bloqueado
- rojo;
- halo controlado.

## Error
- rojo;
- animación breve y visible.

## Inactivo
- gris;
- baja opacidad.

---

# 14. Selección y foco

Cuando el usuario haga clic en un nodo:

1. aumentar glow del nodo;
2. aumentar ligeramente su escala;
3. mostrar conexiones directas;
4. atenuar nodos no relacionados;
5. abrir panel lateral;
6. mantener cámara estable.

## Deselect

Click en fondo:
- cerrar detalle;
- recuperar opacidades;
- volver al estado normal.

---

# 15. Hover

Al hacer hover:

- ligero incremento del glow;
- tooltip;
- nombre;
- estado;
- tarea corta;
- relaciones directas resaltadas.

No abrir panel completo por hover.

---

# 16. Modo Arquitectura

Objetivo:
mostrar la estructura global.

Debe mostrar:

```text
CEO
Decision Engine
8 dominios
13 agentes
conexiones jerárquicas
```

Debe minimizar:
- partículas;
- tráfico;
- conexiones cruzadas.

---

# 17. Modo Ejecución

Objetivo:
mostrar lo que está ocurriendo.

Debe:

- atenuar agentes inactivos;
- resaltar agentes activos;
- mostrar rutas activas;
- mostrar partículas;
- mostrar handoffs;
- hacer reaccionar el núcleo;
- mostrar métricas dinámicas.

Ejemplo:

```text
Product Hunter
→ Market Analyst
→ Decision Engine
→ Supplier Finder
```

---

# 18. Modo Incidencias

Objetivo:
mostrar problemas.

Debe:

- atenuar actividad normal;
- resaltar errores;
- resaltar dependencias;
- mostrar bloqueos;
- usar ámbar/rojo;
- mostrar Human Gate si aplica.

Ejemplos:
- Legal bloquea publicación.
- Supplier Finder espera documentación.
- Marketing supera CAC máximo.
- CFO bloquea presupuesto.

---

# 19. Human Gate

No crear como agente persistente.

Debe aparecer únicamente cuando:
- se requiere aprobación humana;
- existe una excepción;
- un guardrail exige intervención.

Representación:
- nodo temporal;
- badge;
- elemento contextual;
- color ámbar.

---

# 20. Aprobar / Rechazar

No deben aparecer como nodos permanentes.

Deben mostrarse como:
- resultado;
- outcome;
- estado;
- acción en panel contextual.

---

# 21. Toolbar superior

Debe incluir:

```text
Arquitectura
Ejecución
Incidencias

Vista 3D
Vista 2D

Pantalla completa
Reset cámara
Configuración
```

---

# 22. HUD

Panel discreto con:

```text
Decision Engine
Estado

Eventos activos
Agentes activos
Latencia media
Proyecto actual
Progreso
```

Ejemplo:

```text
DECISION ENGINE
Procesando

Eventos activos    3
Agentes activos    5 / 13
Latencia media     1.2 s
Proyecto           KOVA-2026-003
Progreso           68 %
```

---

# 23. Leyenda

Mostrar:

```text
● Ejecutando
● Disponible
● Esperando
● Bloqueado / Error
● Inactivo
```

---

# 24. Panel lateral — agente

Al seleccionar un agente mostrar:

```text
Nombre
Dominio
Estado

Proyecto actual
Tarea actual
Progreso

Última actividad

Conectado con

Success rate
Evaluation score
Latency
Cost today

[Ver agente]
```

---

# 25. Panel lateral — dominio

Mostrar:

```text
Nombre del dominio
Estado

Agentes asociados
Agentes ejecutando
Tareas activas
Incidencias
Carga de trabajo

[Ver módulo]
```

---

# 26. Panel lateral — CEO

Mostrar:

```text
CEO
Orquestador del sistema

Estado
Proyectos supervisados
Decisiones activas
Agentes activos
Gates pendientes

[Ver Director ejecutivo]
```

---

# 27. Panel lateral — Decision Engine

Mostrar:

```text
Decision Engine

Estado
Eventos activos
Latencia
Handoffs
Decisiones recientes
Dependencias
Human Gates pendientes
```

---

# 28. Cámara

Usar controles orbit.

Permitir:
- rotación;
- zoom;
- pequeños movimientos.

## Restricciones

Evitar:
- cámara invertida;
- ángulos extremos;
- atravesar el núcleo;
- perder la orientación;
- zoom demasiado cerca/lejos.

## Botón reset
Debe volver a una vista ejecutiva estándar.

---

# 29. Vista inicial

La cámara inicial debe mostrar:

- CEO arriba;
- Decision Engine centrado;
- anillo de dominios completo;
- agentes visibles;
- profundidad perceptible;
- sin perspectiva excesiva.

---

# 30. View 2D

Debe usar el mismo dataset.

Objetivo:
- accesibilidad;
- debugging;
- equipos menos potentes;
- capturas;
- lectura precisa.

Debe conservar:
- colores;
- estados;
- selección;
- panel lateral;
- filtros;
- modos.

---

# 31. Rendimiento

Objetivo:
- 50–60 FPS en hardware desktop razonable.

Aplicar:
- `InstancedMesh` cuando sea conveniente;
- limitar partículas;
- geometrías simples;
- `useMemo`;
- evitar re-renders innecesarios;
- animaciones controladas;
- reducir efectos si la pestaña pierde foco.

---

# 32. Reduced motion

Respetar:

```css
prefers-reduced-motion
```

Si está activo:

- detener rotaciones ambientales;
- reducir pulsos;
- reducir partículas;
- conservar información funcional.

---

# 33. Responsive

Prioridad:

```text
Desktop
Laptop
Tablet
Mobile
```

## Desktop
Experiencia completa.

## Laptop
Reducir HUD.

## Tablet
Ocultar métricas secundarias.

## Mobile
Priorizar vista 2D o vista 3D simplificada.

---

# 34. Accesibilidad

Obligatorio:

- contraste suficiente;
- estado no dependiente solo de color;
- labels;
- tooltips;
- navegación por teclado cuando aplique;
- foco visible en UI 2D;
- alternativa 2D.

---

# 35. Arquitectura de componentes sugerida

```text
src/
└── components/
    └── neural-nexus/
        ├── NeuralNexusGraph.tsx
        ├── NeuralNexusCanvas.tsx
        ├── NeuralNexusToolbar.tsx
        ├── NeuralNexusHud.tsx
        ├── NeuralNexusLegend.tsx
        ├── NeuralNexusDetails.tsx
        │
        ├── scene/
        │   ├── SceneBackground.tsx
        │   ├── AmbientParticles.tsx
        │   ├── DecisionCore.tsx
        │   ├── CeoNode.tsx
        │   ├── DomainNode.tsx
        │   ├── AgentNode.tsx
        │   ├── GraphConnection.tsx
        │   ├── FlowParticle.tsx
        │   └── CameraController.tsx
        │
        ├── modes/
        │   ├── ArchitectureMode.ts
        │   ├── ExecutionMode.ts
        │   └── IncidentMode.ts
        │
        ├── data/
        │   ├── graphNodes.ts
        │   ├── graphEdges.ts
        │   └── graphLayout.ts
        │
        └── store/
            └── neuralNexusStore.ts
```

---

# 36. Store sugerido

Estado mínimo:

```ts
interface NeuralNexusState {
  mode: "architecture" | "execution" | "incidents";

  selectedNodeId: string | null;
  hoveredNodeId: string | null;

  fullScreen: boolean;

  nodes: GraphNode[];
  edges: GraphEdge[];

  activeEvents: GraphEvent[];

  selectNode: (id: string | null) => void;
  setMode: (
    mode: "architecture" | "execution" | "incidents"
  ) => void;
}
```

---

# 37. Eventos

```ts
interface GraphEvent {
  id: string;

  type:
    | "handoff"
    | "decision"
    | "incident"
    | "human_gate"
    | "task_started"
    | "task_completed";

  source?: string;
  target?: string;

  timestamp: string;

  projectId?: string;

  severity?: "info" | "warning" | "critical";
}
```

---

# 38. Simulación inicial

Hasta tener backend real, permitir una capa de demo:

```text
Simular evento
Simular decisión
Simular incidencia
Reset
```

Esto debe estar disponible solo en desarrollo/demo.

---

# 39. Integración futura con backend

El grafo deberá poder recibir:

```text
agent.status.changed
agent.task.started
agent.task.completed
agent.handoff
decision.started
decision.completed
approval.requested
incident.created
incident.resolved
```

Idealmente mediante:
- WebSocket;
- Supabase Realtime;
- SSE;
- sistema equivalente.

---

# 40. Reglas semánticas

## CEO
- no es agente operativo.

## Decision Engine
- no es dominio.

## Dominios
- no ejecutan tareas por sí solos;
- agrupan agentes.

## Agentes
- ejecutan tareas.

## Human Gate
- aparece solo cuando se requiere intervención.

## Aprobar / Rechazar
- son resultados/acciones, no entidades permanentes.

---

# 41. Reglas de limpieza visual

Nunca mostrar simultáneamente:

- todas las conexiones cruzadas;
- todas las partículas;
- todos los tooltips;
- todos los estados detallados.

Usar contexto.

Principio:

```text
Mostrar solo lo necesario para entender el estado actual.
```

---

# 42. Efectos imprescindibles

Implementar como mínimo:

1. núcleo pulsante;
2. glow de nodos;
3. partículas en rutas activas;
4. pulse al recibir evento;
5. rotación lenta de elementos secundarios;
6. selección con focus;
7. fade de nodos no relacionados;
8. estados por color;
9. scan suave;
10. panel lateral.

---

# 43. Efectos opcionales

Solo después de tener rendimiento estable:

- bloom;
- postprocessing;
- aberración cromática mínima;
- trails;
- light shafts;
- volumetric fog.

No introducirlos si empeoran:
- lectura;
- FPS;
- contraste.

---

# 44. Requisitos de aceptación visual

La implementación se considera correcta si:

- CEO es inmediatamente reconocible.
- Decision Engine domina el centro.
- Los 8 dominios son identificables.
- Los 13 agentes están agrupados correctamente.
- Se percibe profundidad 3D.
- La escena sigue siendo legible.
- La identidad negro + esmeralda se mantiene.
- No parece un gráfico genérico.
- No parece un videojuego.

---

# 45. Requisitos de aceptación funcional

Debe funcionar:

- selección de nodos;
- hover;
- panel lateral;
- zoom;
- orbit;
- reset camera;
- fullscreen;
- modo Arquitectura;
- modo Ejecución;
- modo Incidencias;
- estado visual;
- partículas de flujo;
- vista 2D.

---

# 46. Requisitos de aceptación conceptual

Debe respetar:

```text
CEO
↓
Decision Engine
↓
Dominios
↓
Agentes
```

Además:

- Human Gate temporal;
- Aprobar/Rechazar como outcomes;
- agentes agrupados por dominio;
- conexiones cruzadas contextuales;
- layout estable.

---

# 47. Fases de implementación

## Fase 1 — Estructura base

Implementar:
- canvas;
- cámara;
- núcleo;
- CEO;
- dominios;
- agentes;
- conexiones base.

Objetivo:
estructura completa sin efectos avanzados.

---

## Fase 2 — Interacción

Implementar:
- hover;
- click;
- focus;
- panel lateral;
- reset;
- fullscreen.

---

## Fase 3 — Modos

Implementar:
- Arquitectura;
- Ejecución;
- Incidencias.

---

## Fase 4 — Animación

Implementar:
- pulsos;
- flujo;
- núcleo;
- estados;
- scan.

---

## Fase 5 — Integración de datos

Conectar:
- backend;
- eventos;
- estados;
- proyectos.

---

## Fase 6 — Optimización

Revisar:
- FPS;
- memoria;
- responsive;
- reduced motion;
- fallback 2D.

---

# 48. Prompt maestro para Claude Code

```text
Implementa un módulo llamado “KOVA Neural Nexus” dentro del panel Director Ejecutivo.

Objetivo:
crear un grafo 3D premium y funcional que represente la arquitectura multiagente de KOVA.

Stack:
Next.js + React + React Three Fiber + Three.js + @react-three/drei. Usa Zustand o un store equivalente para el estado.

Jerarquía visual obligatoria:
CEO arriba → Decision Engine como núcleo central → 8 dominios en anillo intermedio → 13 agentes reales en anillo exterior agrupados por dominio.

Dominios:
Investigación, Abastecimiento, Economía, Legal, Comercio, Marketing, Operaciones y Finanzas.

Agentes:
Product Hunter,
Market Analyst,
Supplier Finder,
Trade & Logistics Analyst,
Unit Economics Analyst,
Risk Analyst,
Product Compliance Agent,
Commerce & Consumer Law Agent,
Storefront Builder,
Marketplace Channel Agent,
Acquisition Agent,
Operations & Customer Service Agent,
CFO / Financial Controller.

El layout debe ser determinista y espacialmente estable. No usar un force graph libre como composición principal.

El Decision Engine debe ser un núcleo holográfico 3D con partículas, filamentos, glow y pulsación suave. El CEO debe aparecer separado encima del núcleo.

Añade conexiones jerárquicas permanentes y conexiones cruzadas solo cuando exista contexto operativo real.

Añade tres modos:
1. Arquitectura: muestra la estructura completa.
2. Ejecución: resalta agentes y rutas activas, añade partículas en las conexiones.
3. Incidencias: atenúa actividad normal y resalta bloqueos, dependencias y errores.

Estados visuales:
Disponible = verde suave.
Ejecutando = esmeralda/cian brillante.
Esperando = ámbar.
Bloqueado/Error = rojo.
Inactivo = gris.

La interacción debe incluir:
hover,
click,
focus del nodo,
fade del resto,
panel lateral,
zoom,
orbit,
reset cámara,
fullscreen.

Al seleccionar un agente, mostrar:
nombre,
dominio,
estado,
proyecto,
tarea,
progreso,
última actividad,
conexiones,
success rate,
evaluation score,
latencia,
coste.

Human Gate no debe existir como agente permanente. Solo debe aparecer de forma contextual cuando se necesita aprobación humana.

Aprobar y Rechazar no deben ser nodos persistentes.

Añade una vista 2D que consuma los mismos datos como fallback y alternativa técnica.

Paleta:
negro profundo + esmeralda + cian verdoso; ámbar para warnings y rojo para errores.

El resultado debe sentirse como el cerebro operativo vivo de KOVA, no como una visualización genérica ni como un videojuego.
```

---

# 49. Resultado esperado

El usuario debe percibir inmediatamente:

```text
KOVA tiene un cerebro central.
El CEO lo orquesta.
Los dominios organizan la empresa.
Los agentes ejecutan.
Los flujos muestran lo que ocurre.
Las incidencias muestran dónde intervenir.
```

El Neural Nexus debe funcionar simultáneamente como:

- representación visual de arquitectura;
- monitor operativo;
- navegador de agentes;
- instrumento ejecutivo;
- identidad visual diferencial de KOVA.

---

## Fin de la especificación
