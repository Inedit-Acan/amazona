# KOVA Neural Decision Engine — Especificación visual y técnica final

**Proyecto:** KOVA  
**Módulo:** Director Ejecutivo → Grafo 3D de agentes  
**Elemento:** Decision Engine / Neural Decision Core  
**Estado:** diseño visual aprobado para implementación  
**Objetivo del documento:** evitar interpretaciones ambiguas y errores de implementación, definiendo con precisión la composición, jerarquía, materiales, proporciones, animaciones, conexiones y criterios de aceptación del nuevo Decision Engine.

---

# 0. Regla principal

**NO reinterpretar libremente el diseño.**

La implementación debe respetar estrictamente la jerarquía visual y funcional descrita aquí.

La referencia conceptual es:

```text
CEO
↓
Decision Engine
↓
Dominios
↓
Agentes
```

El nuevo Decision Engine debe verse como:

> un cerebro digital tridimensional, limpio, oscuro y técnico, formado por una red neural de precisión, con dos hemisferios claramente diferenciados y un pequeño núcleo geométrico de decisión en el centro.

No debe verse como:

- esfera;
- bola luminosa;
- globo holográfico;
- cerebro anatómico;
- cerebro orgánico hiperrealista;
- masa de partículas;
- nube verde;
- objeto cyberpunk recargado.

---

# 1. Referencia visual

Usar como referencia visual aprobada:

`panel_de_decisión_neuronal_kova.png`

La referencia sirve para:

- jerarquía;
- composición;
- proporciones;
- posición relativa;
- estilo del cerebro;
- posición del núcleo;
- distribución del grafo.

No debe copiarse de forma literal si una implementación real 3D exige ajustes técnicos, pero cualquier ajuste debe conservar el mismo lenguaje visual.

---

# 2. Rol del Decision Engine

El Decision Engine representa:

- procesamiento;
- evaluación;
- síntesis;
- toma de decisión;
- coordinación;
- enrutamiento.

Visualmente debe comunicar que:

```text
los agentes producen información
↓
la información entra en la red neural
↓
la red converge hacia el núcleo
↓
el núcleo procesa
↓
la decisión vuelve al sistema
```

---

# 3. Composición general del Decision Engine

El Decision Engine se compone de 6 capas:

```text
1. Silueta cerebral
2. Red neural
3. Nodos sinápticos
4. Núcleo geométrico
5. Anillo técnico inferior
6. Halo de actividad
```

Estas capas deben ser independientes.

No construir el cerebro como un único objeto brillante.

---

# 4. Silueta cerebral

## 4.1. Forma

El cerebro debe:

- verse claramente como cerebro;
- ser simétrico;
- tener dos hemisferios diferenciados;
- tener separación central visible;
- ser tridimensional;
- evitar anatomía médica.

## 4.2. Estilo

Estilo:

```text
geométrico
holográfico
wireframe
neural
premium
sobrio
```

## 4.3. Proporciones

Referencia:

```text
ancho del cerebro = 1.00
alto               = 0.68–0.75
profundidad         = 0.55–0.65
```

Debe ser más ancho que alto.

## 4.4. Separación de hemisferios

Debe existir un surco central real.

No usar una única esfera deformada.

Separación visual recomendada:

```text
3–7 % del ancho total
```

La separación no debe dividir completamente los hemisferios.

---

# 5. Construcción de hemisferios

## 5.1. Recomendación

Crear dos geometrías separadas:

```text
BrainLeft
BrainRight
```

## 5.2. Material

Base:

```text
MeshPhysicalMaterial
o
MeshStandardMaterial
```

Con:

```text
baseColor: muy oscuro
roughness: medio
metalness: bajo/medio
transmission: baja/moderada
opacity: moderada
```

No usar:

```text
MeshBasicMaterial
```

como material principal.

---

# 6. Red neural

## 6.1. Objetivo

La red neural define el cerebro.

Debe existir incluso si el glow está apagado.

## 6.2. Composición

Usar:

- líneas curvas;
- segmentos internos;
- pequeñas conexiones;
- malla neural fina.

## 6.3. Densidad

En reposo:

```text
30–40 % de conexiones visibles
```

En ejecución:

```text
45–65 %
```

No mostrar 100 % permanentemente.

## 6.4. Grosor

Muy fino.

La línea no debe ser más dominante que los nodos.

---

# 7. Nodos sinápticos

## 7.1. Forma

Pequeños puntos/nodos distribuidos por ambos hemisferios.

## 7.2. Tamaño

Muy pequeños.

Referencia:

```text
2–5 % del radio visual del cerebro
```

## 7.3. Estado

Reposo:

- baja intensidad;
- algunos apagados.

Ejecutando:

- grupos de nodos se activan.

## 7.4. Animación

Nunca parpadear aleatoriamente.

La activación debe seguir rutas.

---

# 8. Núcleo geométrico

## 8.1. Importancia

El núcleo representa la decisión final.

Es el elemento central más importante.

## 8.2. Forma

Recomendado:

```text
icosaedro
octaedro
poliedro facetado
```

No usar esfera.

## 8.3. Posición

Exactamente centrado entre ambos hemisferios.

```text
x = 0
y ≈ centro del cerebro
z ≈ centro visual
```

## 8.4. Escala

Debe ocupar aproximadamente:

```text
15–22 % del ancho total del cerebro
```

No hacerlo grande.

## 8.5. Material

Debe ser:

- cristalino;
- preciso;
- brillante;
- nítido.

## 8.6. Glow

El núcleo sí puede tener glow.

Pero:

```text
intensity: moderada
radius: pequeño
```

No generar halo que cubra el cerebro.

---

# 9. Anillo técnico

## 9.1. Posición

Un único anillo horizontal alrededor/debajo del cerebro.

## 9.2. Función

- referencia espacial;
- soporte visual;
- estado de proceso.

## 9.3. Diseño

Muy fino.

Opcionalmente:

- ticks;
- pequeñas marcas;
- partículas puntuales.

## 9.4. No usar

- múltiples anillos brillantes;
- toros gruesos;
- plataformas de energía.

---

# 10. Halo

## 10.1. Uso

Debe ser mínimo.

No usar halo volumétrico grande.

## 10.2. Objetivo

Separar el cerebro del fondo.

Referencia:

```text
opacity baja
falloff corto
```

---

# 11. Escala respecto al grafo

El cerebro debe ser protagonista.

Pero no debe:

- cubrir dominios;
- tocar nodos;
- invadir labels.

Referencia:

```text
cerebro ≈ 26–34 % del ancho visual del anillo de dominios
```

---

# 12. CEO

## 12.1. Posición

Directamente encima.

No desplazar lateralmente.

## 12.2. Conexión

Una única conexión vertical.

## 12.3. Diseño

Nodo limpio:

- anillo;
- icono;
- microhalo.

No usar esfera rellena.

---

# 13. Dominios

Los dominios rodean el cerebro.

Deben permanecer claramente separados.

## 13.1. Distancia

Nunca deben tocar el cerebro.

## 13.2. Conexión

Cada dominio debe conectar con una zona concreta del cerebro.

No conectar todos al mismo punto.

---

# 14. Mapeo visual dominio → cerebro

Ejemplo:

```text
Investigación  → hemisferio izquierdo superior
Abastecimiento → hemisferio izquierdo medio
Economía       → hemisferio derecho superior
Legal          → hemisferio derecho medio
Comercio       → hemisferio izquierdo inferior
Marketing      → hemisferio izquierdo frontal
Operaciones    → hemisferio derecho inferior
Finanzas       → hemisferio derecho posterior
```

No tiene significado neurocientífico literal.

Sirve para mejorar lectura visual.

---

# 15. Flujo de eventos

## 15.1. Entrada

Cuando un agente emite resultado:

```text
Agente
→ Dominio
→ Zona neural
```

## 15.2. Procesamiento

La activación:

- recorre nodos;
- ilumina rutas;
- converge hacia el centro.

## 15.3. Decisión

El núcleo:

- aumenta brillo;
- aumenta escala 2–4 %;
- emite pulso.

## 15.4. Salida

```text
Núcleo
→ Dominio
→ Agente destino
```

---

# 16. Animación de reposo

Muy suave.

Permitido:

- respiración leve;
- microactividad neural;
- ligera rotación del núcleo;
- anillo técnico lento.

No permitido:

- pulsos fuertes;
- parpadeo;
- movimiento continuo de todo;
- partículas constantes.

---

# 17. Animación de procesamiento

Secuencia recomendada:

```text
0 ms
entra evento

100–350 ms
se activa ruta neural

350–700 ms
la señal converge al núcleo

700–1100 ms
núcleo procesa

1100–1400 ms
pulso de decisión

1400–1900 ms
sale resultado
```

---

# 18. Colores

## Cerebro

Base:

```text
negro / verde petróleo
```

Wireframe:

```text
#00d69a
#15f0b2
```

## Núcleo

Centro:

```text
blanco frío / cian claro
```

Borde:

```text
esmeralda
```

## Nodos

Default:

```text
esmeralda suave
```

Activo:

```text
cian-esmeralda
```

---

# 19. Prohibiciones visuales

No usar:

- cerebro verde sólido;
- cerebro totalmente transparente;
- neón saturado;
- bloom excesivo;
- volumetric glow grande;
- partículas ambientales densas;
- cerebro anatómico realista;
- texturas orgánicas;
- colores azules eléctricos intensos;
- rosa/violeta;
- naranja salvo warning;
- exceso de simetría perfecta en red interna.

---

# 20. Intensidad luminosa

La jerarquía debe ser:

```text
núcleo activo
↓
cerebro activo
↓
CEO
↓
dominio activo
↓
dominio normal
↓
agente normal
↓
órbitas
↓
fondo
```

---

# 21. Bloom

Usar selective bloom.

## Permitido

- núcleo;
- rutas neurales activas;
- nodos activos;
- flujo de datos.

## No permitido

- cerebro entero;
- labels;
- conexiones base;
- órbitas;
- paneles.

---

# 22. Labels

`DECISION ENGINE` debe aparecer:

- debajo;
- centrado;
- en blanco;
- sin glow;
- con tracking ligero.

No colocar texto sobre el cerebro.

---

# 23. Fondo

Fondo prácticamente negro.

Partículas ambientales:

```text
muy pocas
pequeñas
baja intensidad
```

No simular universo/espacio exterior.

---

# 24. Cámara

Vista principal:

- frontal ligeramente elevada;
- cerebro centrado;
- CEO arriba;
- dominios visibles;
- agentes exteriores visibles.

No usar:

- cámara demasiado lateral;
- ojo de pez;
- perspectiva extrema.

---

# 25. Profundidad

Usar:

- Z real;
- perspectiva;
- leve parallax;
- iluminación.

No usar:

- fog fuerte;
- bloom para simular profundidad.

---

# 26. Estados del Decision Engine

## Disponible

- red visible;
- núcleo bajo;
- animación mínima.

## Procesando

- rutas neurales activas;
- núcleo aumentando intensidad.

## Esperando

- ámbar discreto;
- red estable.

## Bloqueado

- zona problemática resaltada;
- núcleo normal.

## Error

- rojo solo en punto/ruta afectada;
- no teñir todo el cerebro.

---

# 27. Estado seleccionado

Cuando el usuario selecciona el Decision Engine:

- cerebro 100 % opacity;
- dominios relacionados 80–100 %;
- agentes no relevantes 25–35 %;
- panel derecho visible.

No aumentar mucho el tamaño.

---

# 28. Panel de detalle

Mostrar:

```text
Decision Engine

Estado
Proyecto
Progreso

Eventos activos
Latencia

Dominios conectados
Agentes involucrados

Decisiones recientes
Handoffs
Human Gates

[Ver trazabilidad]
```

---

# 29. Rendimiento

Objetivo:

```text
50–60 FPS
```

Recomendaciones:

- BufferGeometry;
- InstancedMesh;
- líneas reutilizadas;
- no crear geometría por frame;
- no recrear materiales;
- limitar partículas.

---

# 30. Estabilidad

La apariencia no debe cambiar involuntariamente con el tiempo.

Test:

```text
ejecutar 120 segundos
```

Comprobar:

- glow;
- opacity;
- exposure;
- FPS;
- posición;
- escala.

---

# 31. No degradación temporal

Nunca usar decays permanentes del tipo:

```ts
opacity *= 0.98
```

sin restauración.

Todo valor visual debe volver a baseline.

---

# 32. Tone mapping

Revisar:

```text
ACESFilmicToneMapping
toneMappingExposure
SRGBColorSpace
```

Mantener exposure constante.

---

# 33. Materiales transparentes

Evitar múltiples capas transparentes superpuestas.

Especialmente en:

- hemisferios;
- halo;
- wireframe.

---

# 34. Arquitectura de componentes

```text
DecisionEngine/
│
├── DecisionEngine.tsx
├── BrainMesh.tsx
├── BrainHemisphereLeft.tsx
├── BrainHemisphereRight.tsx
├── NeuralNetwork.tsx
├── SynapseNodes.tsx
├── DecisionCore.tsx
├── TechnicalRing.tsx
├── DecisionPulse.tsx
├── NeuralFlow.tsx
└── DecisionEngineLabel.tsx
```

---

# 35. Componentes mínimos

## BrainMesh
Controla geometría base.

## NeuralNetwork
Controla conexiones.

## SynapseNodes
Controla puntos.

## DecisionCore
Controla poliedro.

## NeuralFlow
Controla rutas activas.

## DecisionPulse
Controla animación de decisión.

---

# 36. Reglas de interacción

Hover:

- resaltar red;
- tooltip.

Click:

- seleccionar;
- abrir panel;
- resaltar conexiones.

Deselect:

- volver al baseline.

---

# 37. Criterios de aceptación visual

La implementación se considera correcta si:

- parece claramente un cerebro;
- no parece una esfera;
- los hemisferios están diferenciados;
- existe separación central;
- el núcleo es geométrico;
- el núcleo es pequeño;
- la red es fina;
- el cerebro no es una masa verde;
- las conexiones son limpias;
- no hay glow excesivo.

---

# 38. Criterios de aceptación funcional

Debe permitir:

- reposo;
- procesamiento;
- decisión;
- salida;
- selección;
- hover;
- conexión con dominios.

---

# 39. Criterios de aceptación de calidad

Debe verse:

```text
profesional
sobrio
premium
técnico
ejecutivo
```

No debe verse:

```text
gaming
demo de IA
cyberpunk
decorativo
recargado
```

---

# 40. Checklist antes de cerrar implementación

## Forma
- [ ] cerebro reconocible
- [ ] dos hemisferios
- [ ] separación central
- [ ] volumen 3D

## Núcleo
- [ ] pequeño
- [ ] geométrico
- [ ] centrado
- [ ] glow controlado

## Red
- [ ] líneas finas
- [ ] nodos pequeños
- [ ] rutas activables

## Efectos
- [ ] selective bloom
- [ ] pulse
- [ ] actividad contextual
- [ ] nada de glow global

## Integración
- [ ] CEO bien posicionado
- [ ] dominios separados
- [ ] conexiones limpias
- [ ] labels legibles

## Estabilidad
- [ ] 120 segundos sin degradación
- [ ] FPS estable
- [ ] luminosidad estable
- [ ] exposición estable

---

# 41. Instrucción crítica para Claude Code

```text
NO simplifiques el Decision Engine a una esfera, globo, mesh redondo o núcleo luminoso genérico.

Debe ser un cerebro 3D claramente reconocible, dividido visualmente en dos hemisferios, formado por una red neural fina y limpia.

El centro debe contener un poliedro geométrico pequeño que representa el núcleo de decisión.

El cerebro debe ser oscuro y técnico. El wireframe y las rutas activas proporcionan la luz.

No aplicar bloom al cerebro completo.

Solo el núcleo, las rutas activas y los nodos activos pueden tener glow relevante.

La arquitectura del grafo existente debe mantenerse.

Prioriza precisión geométrica, legibilidad y estabilidad sobre efectos visuales.
```

---

# 42. Resultado esperado

El Decision Engine debe transmitir visualmente:

```text
KOVA recibe información.
La procesa mediante su red.
Las señales convergen.
El núcleo decide.
La decisión vuelve al sistema.
```

El usuario debe percibir que está viendo el **cerebro operativo de KOVA**, no un elemento decorativo.

---

## Fin del documento
