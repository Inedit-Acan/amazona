# KOVA Neural Nexus — Corrección visual y técnica · Iteración 2

**Proyecto:** KOVA  
**Módulo:** Grafo 3D de agentes del panel Director Ejecutivo  
**Documento:** corrección visual/técnica posterior a la primera implementación  
**Estado:** aprobado para segunda iteración en Claude Code  
**Base de revisión:** vídeo de la implementación actual enviado el 24/09/2026

---

# 1. Objetivo de esta iteración

Mantener **la arquitectura y jerarquía actuales del Neural Nexus**, pero corregir el acabado visual para pasar de una estética de holograma difuso a una interfaz 3D:

- más limpia;
- más precisa;
- más sobria;
- más profesional;
- más técnica;
- más legible;
- más estable visualmente;
- más cercana al concepto aprobado.

La estructura general se considera correcta:

```text
CEO
↓
Decision Engine
↓
Dominios
↓
Agentes
```

**No rehacer la arquitectura.**  
La prioridad de esta iteración es **refinar el render, la geometría, la jerarquía visual y la estabilidad**.

---

# 2. Diagnóstico de la implementación actual

## 2.1. Aspectos correctos

La versión actual ya respeta de forma razonable:

- CEO en posición superior;
- Decision Engine en el centro;
- dominios en anillo intermedio;
- agentes en anillo exterior;
- organización radial;
- órbitas/conexiones;
- disposición general 3D.

Por tanto, no se requiere rediseñar el sistema desde cero.

---

# 3. Problemas visuales observados

## 3.1. Exceso de masa luminosa verde

Los nodos y halos actuales generan grandes áreas translúcidas que se solapan.

Consecuencias:

- pérdida de definición;
- sensación de “nube verde”;
- jerarquía visual más débil;
- aspecto menos profesional;
- el núcleo central se mezcla con los dominios;
- disminuye la legibilidad de labels y conexiones.

### Corrección

Reducir drásticamente:

- halos grandes;
- discos translúcidos;
- superficies emissive extensas;
- bloom permanente.

Objetivo:

> cada nodo debe leerse como una pieza técnica independiente, no como una mancha luminosa.

---

## 3.2. Bloom y glow excesivos

La implementación actual depende demasiado del glow.

Problema:

- todos los elementos parecen activos;
- no existe una jerarquía de intensidad;
- el brillo base compite con el estado activo;
- la interfaz se percibe más como demo visual que como herramienta ejecutiva.

### Corrección

Usar glow selectivo.

Regla:

```text
Núcleo                 glow medio
CEO                    glow bajo/medio
Dominio inactivo       glow mínimo
Agente inactivo        casi sin glow
Nodo activo            glow visible
Warning                glow ámbar
Error                   glow rojo controlado
```

La escena debe seguir siendo atractiva **con bloom prácticamente desactivado**.

---

## 3.3. Geometría de nodos poco precisa

Los nodos actuales se perciben como círculos o burbujas con demasiado relleno.

### Objetivo

Rediseñar cada nodo con una estructura técnica:

```text
1. núcleo/icono central
2. anillo principal fino
3. anillo secundario opcional
4. microhalo
5. etiqueta externa
```

### Evitar

- grandes discos transparentes;
- relleno esmeralda del tamaño de la zona de influencia;
- superficies difusas que oculten conexiones.

---

## 3.4. Decision Engine poco dominante

El núcleo central existe pero queda visualmente lavado por la iluminación general.

### Corrección

El Decision Engine debe convertirse en:

- elemento central de mayor complejidad;
- centro de atención;
- única zona con detalle holográfico importante.

Debe incluir:

- esfera/malla neural;
- wireframe fino;
- filamentos internos;
- partículas internas;
- halo controlado;
- pulsación lenta;
- anillo de energía discreto.

El brillo debe provenir principalmente **del interior**.

---

## 3.5. Órbitas demasiado presentes

Actualmente varias órbitas y líneas compiten con los nodos.

### Corrección

Reducir:

- grosor;
- opacidad;
- saturación;
- cantidad visible simultáneamente.

Las órbitas deben funcionar como guía espacial, no como elemento protagonista.

### Valores de referencia visual

```text
Órbita base:
opacity ≈ 0.08–0.18

Órbita activa:
opacity ≈ 0.35–0.55

Conexión jerárquica:
opacity ≈ 0.20–0.35

Flujo activo:
opacity ≈ 0.65–1.00 solo temporalmente
```

No son valores obligatorios; ajustar visualmente.

---

## 3.6. Exceso de conexiones permanentes

Mostrar demasiadas conexiones simultáneas genera ruido.

### Regla nueva

En estado normal:

```text
CEO → Decision Engine
Decision Engine → Dominios
Dominios → sus agentes
```

Las conexiones agente-agente o dominio-dominio:

- ocultas por defecto;
- aparecen en modo Ejecución;
- aparecen al seleccionar un nodo;
- aparecen en modo Incidencias cuando sean relevantes.

---

## 3.7. Profundidad 3D insuficientemente clara

Aunque la escena es 3D, en varios momentos se percibe casi plana.

### Corrección

Aumentar la separación real entre planos:

```text
CEO                 plano superior
Dominios            plano intermedio alto
Decision Engine     centro
Agentes             plano exterior/inferior
órbitas              distintos radios y Z
```

Aplicar:

- profundidad Z real;
- perspectiva moderada;
- tamaños por distancia;
- ligeros cambios de parallax;
- iluminación suave por profundidad.

Evitar perspectiva extrema.

---

## 3.8. Etiquetas poco legibles

Las etiquetas compiten con el brillo y algunas quedan pequeñas.

### Corrección

Usar labels 2D HTML/CSS sobre la escena cuando convenga.

Requisitos:

- blanco roto;
- sombra muy suave;
- sin glow fuerte;
- tamaño mínimo legible;
- posición consistente;
- ocultar labels secundarios cuando haya zoom lejano.

### Prioridad de labels

```text
CEO              siempre visible
Decision Engine  siempre visible
Dominios         siempre visibles
Agentes          visibles según zoom/hover
```

---

## 3.9. Inestabilidad de intensidad / “apagado”

En el vídeo se observa variación de intensidad visual que puede percibirse como que el grafo “se apaga”.

No se debe asumir una única causa sin revisar el código final.

### Posibles causas a inspeccionar

- bloom global demasiado agresivo;
- `AdditiveBlending` acumulativo;
- demasiados materiales transparentes;
- `depthWrite=false` usado de forma extensa;
- problemas de orden de transparencias;
- opacity animada incorrectamente;
- shader dependiente del tiempo;
- tone mapping/exposure;
- postprocessing;
- carga progresiva de materiales;
- cambios de DPR/resolution;
- frame-rate dependent animation.

### Requisito

La intensidad base debe permanecer estable.

No permitir que una animación ambiental reduzca progresivamente:

- glow;
- opacity;
- emissive;
- exposición.

---

# 4. Nueva dirección visual

## 4.1. Principio central

Cambiar de:

> holograma difuso

a:

> visualización técnica de precisión.

Palabras clave:

- limpio;
- geométrico;
- preciso;
- sobrio;
- ejecutivo;
- nítido;
- modular;
- premium.

---

# 5. Diseño corregido de cada elemento

## 5.1. Fondo

Usar:

- negro profundo;
- degradado verde petróleo muy sutil;
- fog mínimo;
- pocas partículas ambientales.

Eliminar cualquier iluminación ambiental que genere una gran neblina esmeralda.

---

## 5.2. Decision Engine

### Composición

```text
CoreSphere
NeuralWireframe
InnerParticles
EnergyRing
MicroBloom
DecisionPulse
```

### Reglas

- no usar esfera sólida demasiado brillante;
- wireframe fino;
- máximo detalle en el centro;
- glow contenido;
- pulsación de ±2–4 % como máximo;
- flash de decisión breve.

---

## 5.3. CEO

Diseño:

- nodo limpio;
- anillo exterior;
- icono central;
- tamaño mayor que dominio;
- halo leve;
- conexión vertical clara.

No usar gran círculo relleno.

---

## 5.4. Dominios

Cada dominio:

```text
[ anillo exterior ]
      icono
[ microhalo ]
   nombre
```

### Diferencias frente a agentes

- 15–25 % más grandes;
- borde más grueso;
- nombre siempre visible;
- mayor contraste.

---

## 5.5. Agentes

Cada agente:

- nodo pequeño;
- anillo fino;
- icono;
- halo casi inexistente;
- etiqueta exterior;
- estado visible por borde/punto indicador.

Los agentes no deben competir con los dominios.

---

# 6. Sistema de estados revisado

## Disponible

- borde esmeralda;
- glow casi nulo;
- estado estable.

## Ejecutando

- borde esmeralda/cian brillante;
- pulso suave;
- partículas activas;
- microhalo.

## Esperando

- punto o borde ámbar;
- sin gran halo;
- pulsación lenta.

## Bloqueado

- borde rojo;
- badge de bloqueo;
- conexión problemática resaltada.

## Error

- rojo;
- microflash inicial;
- después estado estable.

## Inactivo

- gris;
- opacidad reducida.

---

# 7. Selective Bloom obligatorio

No aplicar bloom a toda la escena.

## Elementos que pueden usar bloom

- Decision Engine;
- CEO;
- nodo activo;
- warning;
- error;
- partículas de flujo.

## Elementos sin bloom o casi sin bloom

- textos;
- órbitas base;
- conexiones inactivas;
- paneles;
- labels;
- agentes inactivos.

---

# 8. Materiales recomendados

Priorizar materiales físicamente coherentes y simples.

## Nodos

Base recomendada:

```text
MeshStandardMaterial
o
MeshPhysicalMaterial
```

Usar emissive bajo.

Evitar usar `MeshBasicMaterial` emissive/bright para todo.

## Líneas

Usar:
- líneas finas;
- shaders simples;
- opacity baja.

## Partículas

Additive blending solo donde sea necesario.

---

# 9. Transparencias

Reducir al mínimo el número de capas transparentes que se solapan.

### Regla

No usar simultáneamente:

- disco translúcido grande;
- halo grande;
- bloom fuerte;
- sprite luminoso;
- anillo transparente;

para un mismo nodo.

Máximo recomendado:

```text
nodo sólido/semi-sólido
+
anillo
+
microhalo
```

---

# 10. Cámara y encuadre

## Vista inicial

Debe mostrar:

- CEO completo;
- Decision Engine centrado;
- anillo de dominios claramente separado;
- agentes exteriores visibles;
- margen suficiente alrededor.

No empezar demasiado alejado.

No empezar con perspectiva tan inclinada que comprima la escena.

## Orbit controls

Limitar:

```text
minPolarAngle
maxPolarAngle
minDistance
maxDistance
```

Mantener el sistema siempre comprensible.

---

# 11. Diseño de conexiones

## Jerarquía base

### CEO → núcleo
- línea más clara;
- estable.

### núcleo → dominios
- línea fina;
- poca opacidad.

### dominio → agentes
- línea aún más ligera.

## Ejecución

Cuando hay flujo:

- aumentar temporalmente la luminosidad;
- mover 1–3 partículas;
- no iluminar la conexión completa durante demasiado tiempo.

---

# 12. Partículas de flujo

Las partículas deben:

- ser pequeñas;
- viajar por una spline;
- tener estela corta;
- desaparecer al llegar;
- producir micro-pulso en destino.

Evitar decenas de partículas simultáneas.

Objetivo:
mostrar información, no crear espectáculo.

---

# 13. Órbitas

Las órbitas deben ser casi instrumentales.

Usar:

- líneas extremadamente finas;
- discontinuidad opcional;
- pequeñas marcas/ticks opcionales;
- opacidad baja.

No usar anillos brillantes sólidos.

---

# 14. HUD

El HUD debe ser independiente del render 3D.

No aplicar bloom.

Diseño:

- panel negro/translúcido;
- borde fino esmeralda;
- tipografía limpia;
- valores claros.

Debe mostrar:

```text
Decision Engine
Estado
Eventos activos
Agentes activos
Latencia
Proyecto
Progreso
```

---

# 15. Jerarquía tipográfica

## Títulos
Blanco.

## Labels principales
Blanco roto.

## Secundarios
Gris frío.

## Estado activo
Esmeralda/cian.

## Warning
Ámbar.

## Error
Rojo.

No usar glow en texto.

---

# 16. Refinamiento del modo Arquitectura

Debe ser el modo más limpio.

Mostrar:

```text
CEO
Decision Engine
8 dominios
13 agentes
jerarquía base
```

Eliminar:
- tráfico continuo;
- cross-links;
- efectos fuertes.

Este modo debe servir como referencia visual principal.

---

# 17. Refinamiento del modo Ejecución

Mostrar solo actividad útil.

Cuando un flujo está activo:

```text
Product Hunter
→ Market Analyst
→ Decision Engine
→ Supplier Finder
```

El resto:
- visible;
- atenuado;
- sin glow.

---

# 18. Refinamiento del modo Incidencias

Ocultar gran parte de la actividad normal.

Resaltar:

- nodo afectado;
- dependencia;
- dominio;
- Human Gate;
- ruta bloqueada.

La escena debe volverse más sobria, no más brillante.

---

# 19. Rendimiento

La mejora visual no debe reducir rendimiento.

## Objetivo

```text
50–60 FPS desktop normal
```

## Medidas

- reducir transparent meshes;
- limitar partículas;
- instancing donde aplique;
- evitar actualizar materiales innecesariamente;
- no crear geometría cada frame;
- usar `useMemo`;
- evitar React re-render en animación;
- usar `useFrame` solo para cambios visuales necesarios.

---

# 20. Estabilidad temporal

Todas las animaciones deben usar `delta` o tiempo normalizado.

Evitar:

```ts
value *= 0.97
```

si genera decay permanente no deseado.

Preferir:

```ts
lerp(baseValue, targetValue, factor)
```

o:

```ts
Math.sin(time * speed)
```

cuando sea animación periódica.

Los valores visuales deben volver siempre a un **baseline conocido**.

---

# 21. Gestión de exposición y tone mapping

Revisar:

```text
toneMapping
toneMappingExposure
outputColorSpace
renderer pixel ratio
postprocessing exposure
```

No modificar exposure dinámicamente salvo decisión explícita.

La escena no debe oscurecerse tras varios segundos.

---

# 22. Postprocessing

Si existe:

```text
EffectComposer
Bloom
SMAA/FXAA
Vignette
```

usar con moderación.

## Bloom

- selective bloom;
- threshold alto;
- intensity baja/media;
- radius contenido.

## Vignette

Muy sutil.

## Chromatic aberration

No usar por defecto.

---

# 23. Debug de la pérdida de brillo

Claude Code debe revisar específicamente:

1. materiales con opacity animada;
2. `AdditiveBlending`;
3. `depthWrite`;
4. `depthTest`;
5. shaders dependientes de `time`;
6. exposure;
7. bloom;
8. fog;
9. renderer color space;
10. DPR/resolution;
11. cambios de estado React que sustituyan materiales;
12. carga tardía de assets;
13. limpieza/recreación del canvas;
14. degradación por FPS.

Registrar los valores relevantes si el problema persiste.

---

# 24. Proceso de corrección recomendado

## Fase A — eliminar ruido

Antes de añadir efectos:

- desactivar bloom;
- ocultar partículas ambientales;
- ocultar cross-links;
- quitar halos grandes;
- dejar nodos y conexiones base.

Validar que la escena ya se vea profesional.

---

## Fase B — reconstruir nodos

Crear componente base común:

```text
PrecisionNode
```

Con variantes:

```text
CeoNode
DomainNode
AgentNode
```

Todos deben compartir el mismo lenguaje visual.

---

## Fase C — reconstruir Decision Engine

Crear núcleo de precisión.

Validar primero sin bloom.

---

## Fase D — conexiones

Añadir jerarquía base.

Después flujos activos.

---

## Fase E — selective effects

Añadir:
- selective bloom;
- pulse;
- scan;
- partículas.

Uno por uno.

---

## Fase F — validar estabilidad

Dejar la escena ejecutándose al menos:

```text
60–120 segundos
```

Comprobar:
- intensidad;
- FPS;
- memoria;
- legibilidad.

La apariencia no debe degradarse.

---

# 25. Componentes sugeridos

```text
neural-nexus/
│
├── PrecisionNode.tsx
├── CeoNode.tsx
├── DomainNode.tsx
├── AgentNode.tsx
├── DecisionCore.tsx
│
├── HierarchyEdge.tsx
├── ActiveFlowEdge.tsx
├── FlowParticle.tsx
│
├── OrbitRing.tsx
├── AmbientParticles.tsx
│
├── SelectiveBloom.tsx
├── NexusLighting.tsx
├── NexusCamera.tsx
│
├── NexusHud.tsx
├── NodeLabel.tsx
└── NodeDetailsPanel.tsx
```

---

# 26. `PrecisionNode` — especificación

Cada nodo debe aceptar:

```ts
interface PrecisionNodeProps {
  size: number;
  status: NodeStatus;
  selected?: boolean;
  active?: boolean;
  icon: ReactNode;
  label: string;
}
```

Visual:

```text
outer ring
inner ring
core surface
icon
small status indicator
microhalo
```

No incluir un gran disco de glow.

---

# 27. `DecisionCore` — especificación

Debe ser más complejo que cualquier otro nodo.

Capas recomendadas:

```text
coreSphere
wireframeSphere
innerParticleCloud
neuralLines
energyRing1
energyRing2
softHalo
```

Cada capa:
- baja intensidad;
- combinada con precisión.

No usar una única esfera extremadamente brillante.

---

# 28. Iluminación

Usar iluminación contenida.

Ejemplo conceptual:

```text
AmbientLight muy bajo
PointLight interno del core
DirectionalLight suave
Rim light esmeralda sutil
```

Los nodos no deben depender completamente de emissive.

---

# 29. Profundidad visual

Mejorar profundidad mediante:

- separación Z;
- tamaño;
- iluminación;
- perspectiva;
- parallax;
- ligera diferencia de opacidad.

No mediante fog intenso.

---

# 30. Estado seleccionado

Cuando se selecciona un nodo:

```text
selected node       100 %
related nodes        85–100 %
unrelated nodes      20–35 %
related edges        70–100 %
unrelated edges       5–10 %
```

Valores orientativos.

Debe sentirse limpio.

---

# 31. Estado base

En reposo:

- nada debe parpadear;
- nada debe competir con el núcleo;
- agentes disponibles deben verse tranquilos;
- las conexiones deben ser discretas.

---

# 32. Objetivo visual final

El resultado debe recordar más a:

```text
instrumento ejecutivo de observabilidad
+
arquitectura de agentes
+
escultura digital controlada
```

y menos a:

```text
demo holográfica
+
neón
+
nube de partículas
```

---

# 33. Prioridades de corrección

## P0 — obligatorio

1. eliminar halos grandes;
2. reducir bloom global;
3. estabilizar intensidad;
4. mejorar Decision Engine;
5. rediseñar nodos;
6. adelgazar órbitas;
7. simplificar conexiones;
8. mejorar labels.

## P1 — alta prioridad

9. mejorar profundidad;
10. selective bloom;
11. flujos más precisos;
12. estados más limpios.

## P2 — polish

13. scan;
14. microanimaciones;
15. partículas ambientales;
16. efectos extra.

---

# 34. Criterios de aceptación

## A. Limpieza

La escena no genera grandes masas translúcidas verdes.

## B. Jerarquía

Se distingue inmediatamente:

```text
CEO
Decision Engine
Dominios
Agentes
```

## C. Precisión

Nodos, anillos y conexiones tienen bordes claramente definidos.

## D. Estabilidad

La escena mantiene su luminosidad y contraste después de 2 minutos.

## E. Legibilidad

Todos los dominios son legibles.

Los agentes son legibles al zoom normal o mediante hover.

## F. Profesionalidad

La escena debe parecer una interfaz de software empresarial premium.

## G. Rendimiento

Mantener FPS estable.

---

# 35. Instrucción maestra para Claude Code

```text
No cambies la arquitectura funcional del KOVA Neural Nexus ya implementado.

La estructura actual CEO → Decision Engine → dominios → agentes es correcta.

Esta iteración debe centrarse exclusivamente en elevar el acabado visual y técnico.

Elimina la estética actual de grandes halos/discos translúcidos verdes y sustituye el lenguaje visual por nodos de precisión: superficies oscuras, anillos finos, microhalos y glow selectivo.

Reduce drásticamente el bloom global. La escena debe verse bien con bloom casi desactivado.

El Decision Engine debe ser el único elemento con complejidad holográfica importante: núcleo interno, wireframe, partículas internas, filamentos y anillos de energía finos.

Haz mucho más finas y discretas las órbitas y conexiones base. Muestra conexiones cruzadas solo cuando haya contexto.

Revisa la pérdida progresiva de luminosidad observada durante la ejecución. Inspecciona opacity, additive blending, depthWrite, shaders temporales, bloom, tone mapping, exposure y cualquier decay multiplicativo.

Los valores visuales deben tener un baseline estable y no degradarse con el tiempo.

Usa selective bloom solo para el núcleo, CEO, nodos activos, warnings, errores y partículas de flujo.

Mejora la separación 3D mediante posición Z, perspectiva moderada y parallax, no mediante fog o glow.

Los labels deben ser limpios, sin glow, con buena legibilidad y jerarquía.

Objetivo final:
una interfaz 3D de precisión, limpia, sobria, tecnológica y premium, más cercana a un instrumento ejecutivo de observabilidad que a una demo holográfica.
```

---

# 36. Resultado esperado

La segunda iteración debe conservar exactamente lo que ya funciona a nivel estructural, pero producir un salto claro en calidad:

```text
ANTES:
bonito
holográfico
difuso
brillante

DESPUÉS:
preciso
limpio
estable
profesional
premium
técnico
```

---

## Fin del documento
