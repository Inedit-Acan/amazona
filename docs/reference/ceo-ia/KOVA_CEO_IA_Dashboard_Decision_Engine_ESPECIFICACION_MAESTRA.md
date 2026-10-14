# KOVA / AMAZONA — ESPECIFICACIÓN MAESTRA UNIFICADA
## Dashboard Director Ejecutivo CEO-IA + Neural Decision Engine 3D

**Versión:** 1.0 · **Fecha:** 14/10/2026 · **Destino:** Claude Code · **Estado:** especificación de implementación; NO equivale a software ya verificado.

**Referencia visual principal obligatoria:** `KOVA_CEO_Dashboard_referencia_aprobada.png` (adjuntar a Claude Code junto con este documento). La captura es un **mockup**, con cifras, nombres de proveedores, eventos, actividad y estados ilustrativos: no deben interpretarse como datos reales. Se debe reproducir la composición y lenguaje visual de esta imagen, con ajustes mínimos de accesibilidad, responsive y viabilidad técnica. **El documento anterior de 42 apartados se conserva íntegro más abajo como ANEXO A normativo** para el cerebro/grafo. En caso de conflicto: (1) seguridad e integridad de datos, (2) funcionamiento y accesibilidad, (3) especificación técnica del anexo para el motor 3D, (4) fidelidad de distribución al mockup.

## 1. Objetivo y límites

Transformar la vista existente «Director ejecutivo» de un formulario para crear objetivos en un **centro ejecutivo operativo**, conservando creación de misiones como acción secundaria. CEO-IA debe permitir consultar estado, analizar información trazable, coordinar agentes y proponer acciones. No afirmar autonomía o conexión real cuando el backend no la tenga. Mantener navegación y diseño global de AMAZONA/KOVA, sin rediseñar otros módulos. **No implementar acciones comerciales, pagos, pedidos, cambios de proveedores, publicación, compromisos legales ni movimientos de dinero sin controles de autorización humana existentes o nuevos.**

## 2. Procedimiento obligatorio antes de tocar código

1. Inspeccionar el repositorio real: rama, estado Git, stack, estructura de rutas/componentes, librerías 3D, capa de agentes, APIs, autenticación, permisos, eventos, base de datos, finanzas, tests y CI. No suponer nombres de archivos ni endpoints.
2. Identificar implementación actual de «Director ejecutivo», «Nuevo objetivo», grafo 2D/3D, Decision Engine y orquestación. Registrar componentes reutilizables, contratos y dependencias.
3. Crear un inventario `existente / reutilizable / ausente / bloqueado` para cada función. Si hay carencias, definir adaptadores y modo degradado, no simular como real.
4. Hacer plan incremental, pruebas y puntos de restauración. Preservar rutas, contratos públicos, seguridad, y flujo de misiones. No ejecutar migraciones destructivas. No hacer push sin autorización explícita.
5. Verificar las imágenes y documentación locales: si la imagen de referencia no está disponible en el entorno de Claude Code, detener la implementación visual precisa y solicitarla.

## 3. Layout exacto del mockup (desktop)

- Shell: barra lateral fija a la izquierda (~190 px en referencia), header superior con buscador, estado de sistema y avisos. Fondo negro verdoso; superficies oscuras verde petróleo; líneas/bordes discretos; acento esmeralda.
- Encabezado: «Director ejecutivo», etiqueta «CEO IA», subtítulo ejecutivo; controles a la derecha «Crear misión», «Vista completa» y selector temporal «Este mes».
- Fila superior: **cuatro tarjetas** en el área central: `Ingresos`, `Beneficio`, `Margen neto`, `Cash disponible`, con cifra, tendencia, minigráfico y definición accesible. El coste de agentes puede mostrarse en detalle financiero, no forzar una quinta tarjeta si rompe la referencia.
- Segunda fila: tres tarjetas alineadas `Decisiones pendientes`, `Oportunidades detectadas`, `Riesgos activos`, cada una con contador, tres entradas visibles y «Ver todas»; estados con iconografía y etiquetas textuales.
- Área principal central: tarjeta ancha `Red de agentes (vista general)` con tabs `Vista 3D`, `Vista 2D`, `Arquitectura`, `Ejecución`, `Incidencias`, y `Abrir vista completa`. Cerebro digital central y nodos periféricos. Sobre el grafo, overlays discretos de estado del sistema y agentes.
- Franja inferior: `Actividad reciente`, `Rendimiento por área`, `Próximos hitos`.
- **Columna derecha persistente**: panel `CEO IA` con estado de conexión, pestañas `Chat / Voz / Pantalla`, visualizador de micrófono/ondas en modo voz, controles `Cancelar` y `Silenciar`, transcripción y respuestas, caja de entrada de texto inferior. Debe poder usarse con teclado y sin micrófono.
- Mantener proporciones, alineaciones, radios, densidad, jerarquía, estilo y espaciados similares a la imagen. No incrustar texto de la imagen como bitmap. Tipografía legible y estados claros. Para pantallas estrechas, columna del CEO pasa a drawer o pestaña; tarjetas se apilan y grafo tiene alternativa 2D accesible. No permitir solapamientos ni recortes.

## 4. Diseño visual y componentes

- Tokens configurables, sin dispersar hexadecimales: `bg #001514` aproximado, `surface #001E1C`, `surfaceRaised #032723`, `accent #00D6A0`, texto primario casi blanco, secundario gris azulado, `warning` ámbar, `danger` rojo. **Ajustar tomando muestras de la imagen**; los valores son aproximaciones, no mediciones exactas.
- Cards consistentes: título, valor, unidad, intervalo, variación contra periodo comparable, tendencia accesible, estado de carga, vacío, error y datos desactualizados. Evitar resplandores intensos y animaciones decorativas.
- Botones y tabs con focus visible, tooltips, estados disabled/loading y confirmaciones donde corresponda. Iconos coherentes, sin depender solo del color.
- Prohibido inventar porcentajes, resultados, nombres de proveedores, actividad de agentes o latencias. En demo, rotular de manera visible `DEMO / SIMULADO` a nivel de vista y de métricas.

## 5. Definiciones financieras y consistencia

**Todas las cifras se filtran por periodo y moneda; definir fuente, timestamp, método, tratamiento de impuestos, devoluciones y estado de conciliación.**

| KPI | Definición operativa | Precaución |
|---|---|---|
| Ingresos | Ventas netas reconocidas del periodo, excluido IVA repercutido, devoluciones y descuentos, según política contable adoptada | Diferenciar pedidos, cobros y ventas reconocidas; si no existe contabilidad fiable, indicar estimación |
| Beneficio neto | Ingresos menos coste de ventas, envíos asumidos, comisiones marketplace/pasarela, marketing, herramientas/IA, costes operativos, impuestos sobre beneficio y otros gastos imputables del periodo | No confundir con margen bruto, EBITDA ni saldo bancario; si no hay impuestos calculados, usar etiqueta «Resultado estimado antes de impuestos» |
| Margen neto | Beneficio neto / ingresos × 100, si ingresos > 0 | Con ingresos 0 mostrar N/D; variaciones en puntos porcentuales, no confundir con % relativo |
| Cash disponible | Efectivo y equivalentes **utilizables** a fecha de corte, con ajustes por fondos restringidos y conciliación | No equivale a beneficios acumulados; nunca derivarlo simplemente de ingresos menos gastos |
| Runway (meses) | Caja disponible / consumo neto mensual de caja (*burn rate*) cuando el consumo es positivo y medible | «8,4 meses» del mockup debe representar autonomía de caja **solo si** existe burn rate válido; si la empresa genera caja o faltan datos, N/D o «no aplicable» |

- Ejemplo del mockup: 46.280 / 184.320 × 100 ≈ 25,11 %, coherente con 25,1 %. **Ejemplo visual, no dato real.**
- Las variaciones deben especificar periodo de comparación y fórmulas; cada cifra debe abrir desglose y fuente. El CFO calcula y valida, el CEO explica; no alterar registros financieros mediante una conversación.
- Mostrar moneda, timezone, fecha de actualización y advertencias por información incompleta. Separar modo simulación de producción en toda la cadena de datos.

## 6. CEO-IA: conversación real por texto y voz

**Estados de conversación:** `idle`, `connecting`, `listening`, `transcribing`, `thinking`, `speaking`, `paused`, `error`, `offline`. Representarlos sin mentir sobre conectividad. `Online` solo si hay comprobación real del servicio.

- **Chat:** historial por conversación, mensajes de usuario y CEO, timestamps, streaming si soportado, errores/reintentos, cancelación, fuentes y enlaces a decisiones/ejecuciones. Contexto de proyecto, periodo y permisos; indicar alcance contextual. No exponer prompts internos, claves ni información restringida.
- **Voz:** pedir permiso de micrófono solo al iniciar; audio capturado con API disponible en el stack; STT (transcripción) + modelo conversacional + TTS (síntesis) o servicio de voz en tiempo real, según infraestructura existente. Seleccionar proveedor tras auditar código, coste, idioma, privacidad y latencia. No prometer voz hasta probarla extremo a extremo.
- Permitir hablar en español, mostrar transcripción editable antes de acciones sensibles, indicador de captura activa, botón detener, silenciar salida, interrupción/barge-in si soportada, selección de dispositivo si viable, y fallback a texto. Si no hay micrófono, permiso o servicio, mostrar error comprensible.
- **Pestaña Pantalla:** solo para visualizar o compartir contexto cuando exista implementación real y consentimiento explícito; no afirmar control remoto ni capturar pantalla silenciosamente. Si no está implementada, marcar `No disponible`.
- CEO debe responder sobre estado real de agentes, métricas, riesgos y decisiones con referencias a registros. Si la fuente falta, indicar «sin datos verificables»; distinguir análisis, recomendaciones y órdenes ejecutadas.
- Registrar consumo, latencia, fallos, coste estimado por proveedor/modelo, retención de transcripciones y audio conforme a política aprobada; no almacenar audio por defecto sin necesidad y base legal evaluada.

## 7. Coordinación, decisiones y seguridad

- CEO orquesta mediante interfaces de agentes existentes; **no ejecutar herramientas directamente desde texto generado sin validación de intención, permisos y argumentos**. Definir contrato estructurado de propuestas, aprobaciones, ejecución, resultado y auditoría.
- Flujo: petición → interpretación → consulta de fuentes → plan propuesto → evaluación de riesgo/compliance/CFO si procede → aprobación humana (human gate) → ejecución idempotente → verificación → reporte con trazabilidad.
- `Decisiones pendientes`: mostrar quién solicita, contexto, evidencia, alternativas, impacto, riesgo, fecha, permisos, y botones aprobar/rechazar; doble confirmación para operaciones irreversibles. Nunca dar por aprobada una acción por voz ambigua.
- `Oportunidades`: evidencias, fecha, estimaciones con supuestos, nivel de confianza y próxima acción; `Riesgos`: severidad, probabilidad, impacto, responsable, mitigación y estado. No inferir fiabilidad solo por un score de IA.
- Integrar control de acceso del repositorio, separación de roles, registros inmutables o resistentes a manipulación, protección ante prompt injection en datos externos, límites de coste y rate limiting.
- Sin conexión real: mostrar tarjetas vacías/estados simulados explícitos, nunca datos ficticios como operativos.

## 8. Red de agentes 3D/2D y Decision Engine

- **Aplicar íntegramente el ANEXO A** que sigue, incluidos cerebro con dos hemisferios, wireframe neural fino, poliedro central, conexiones y restricciones de bloom; no reemplazar por esfera ni reescribir motor estable por motivos estéticos.
- Los nodos y aristas deben provenir del registro real de agentes; no fijar cantidades ilustrativas como `13/15`. Diferenciar arquitectura (todos los agentes) de ejecución (solo tareas reales) y demo.
- `Vista 3D`: orbit/zoom accesibles, cámara de inicio que mantenga CEO arriba y cerebro centrado; clic/teclado abre panel de detalles. `Vista 2D`: alternativa funcional equivalente; `Arquitectura`, `Ejecución`, `Incidencias`: filtros sobre datos verdaderos.
- Overlays muestran agentes por estado sin doble contabilización; cada estado debe tener semántica única. El progreso se calcula a partir de tareas y pesos definidos, no inventado.
- Renderizado bajo demanda, reducción de movimiento, fallback WebGL y rendimiento medido; pruebas de estabilidad de al menos 120 segundos como exige el anexo.

## 9. Integraciones y contratos (adaptar a repo, no inventar endpoints)

Definir o reutilizar interfaces tipadas para: `ExecutiveSummary`, `FinancialMetric`, `AgentStatus`, `AgentEvent`, `DecisionProposal`, `Opportunity`, `Risk`, `Milestone`, `Conversation`, `VoiceSession` y `AuditEvent`. Cada objeto debe incorporar identificador, `source`, `observedAt`, `mode: live|demo`, y estado de error/desactualización cuando proceda. Validar esquemas en límites cliente/servidor; aplicar permisos en servidor, no solo ocultar botones.

- Financieros: integración CFO/contabilidad; trazabilidad de importes y monedas.
- Agentes: registro, ejecuciones, handoffs y estados reales.
- Conversación: gateway backend con streaming/autenticación y herramientas permitidas; claves únicamente en servidor.
- Eventos: suscripción en tiempo real si existe; si no, polling controlado y estados explícitos.
- Modo demo: fixtures deterministas segregadas, etiqueta visible y cero efectos externos.
- Respetar contratos existentes y añadir migraciones compatibles, pruebas y rollback si son necesarias.

## 10. Plan de implementación por etapas y puertas de calidad

**Fase 0 — Auditoría:** inventario y riesgos; confirmar stack, infraestructura de voz, datos y permisos. No codificar a ciegas.

**Fase 1 — UI estática fiel:** shell, cuatro KPI, tres paneles, grafo, franja inferior, CEO a la derecha; capturas a tamaños desktop/tablet/móvil; comparar visualmente con referencia.

**Fase 2 — Datos reales:** conectar métricas, estados, listas, fechas, fuentes; manejo de carga/error/vacío/desactualizado y separación demo/live. Validar aritmética.

**Fase 3 — CEO conversacional:** chat real y contexto seguro; luego voz STT/TTS, estados, cancelación y fallback. No marcar «completo» si falta la prueba de voz real.

**Fase 4 — Acciones gobernadas:** propuestas, human gates, auditoría, prevención de dobles ejecuciones y verificación de resultados. Restaurar flujo de crear misión desde botón superior.

**Fase 5 — Grafo:** integrar motor 3D existente y anexo, vista 2D, selección, eventos y accesibilidad; benchmark de rendimiento y estabilidad.

**Fase 6 — Validación y entrega:** pruebas unitarias, integración, e2e y regresión; revisión de seguridad, coste y privacidad; documentación, capturas y reporte final.

## 11. Matriz de aceptación (no cerrar si falla una crítica)

| ID | Prueba | Resultado requerido |
|---|---|---|
| UI-01 | Comparación visual desktop | Misma composición, jerarquía y estética de referencia; diferencias justificadas |
| UI-02 | Responsive 1440/1024/768/390 px | Sin cortes, solapes ni pérdida de funciones |
| UI-03 | Accesibilidad | Navegación teclado, focus, labels, contraste revisado y reduced motion |
| FIN-01 | Fórmulas y desglose | Ingresos, beneficio, margen, caja y runway con fuente, fechas y cálculo coherentes |
| FIN-02 | Datos incompletos | N/D o estimación claramente etiquetada; nunca cifras inventadas |
| AI-01 | Chat | Consulta autenticada → respuesta contextual con evidencia → registro y cancelación |
| AI-02 | Voz | Permiso → capturar → transcribir → responder → sintetizar → detener; errores y fallback |
| AI-03 | Estados | Online, escuchando, hablando, error, desconectado reflejan estado real |
| GOV-01 | Aprobaciones | Ninguna acción sensible sin permiso, confirmación, auditoría e idempotencia |
| AG-01 | Grafo | Nodos reales, filtros, detalles, 3D/2D, fallback y estados consistentes |
| AG-02 | Motor neural | Todos los criterios del anexo; 120 s sin degradación visual |
| REG-01 | Regresión | Crear misión y módulos existentes siguen funcionando |
| SEC-01 | Seguridad | Sin claves en cliente, control servidor, aislamiento demo/live y revisión prompt injection |
| OPS-01 | Operación | Logs útiles, manejo de errores, límites de coste, CI y rollback documentado |

**Si una prueba no puede realizarse** por falta de servicios/credenciales, marcar `NO VERIFICADA / BLOQUEADA`, nunca `OK` por inspección visual. No declarar «funciona perfectamente» sin evidencias de pruebas en el entorno real.

## 12. Entregables y protocolo de cierre Claude Code

1. Implementación incremental y comprobada, sin pérdida de funciones existentes.
2. Capturas de pantalla comparativas y resultados de pruebas, cuando el entorno lo permita.
3. Inventario de dependencias, configuración y servicios necesarios, con costes y límites cuando puedan verificarse.
4. **Documento Markdown final descargable** `HANDOFF_KOVA_CEO_DASHBOARD.md` con: resumen del trabajo, cambios, archivos tocados, decisiones, pruebas y resultados, errores/warnings, estado de Git/CI, riesgos, pendientes y siguiente paso recomendado; incluir tabla de criterios de aceptación con `PASS / FAIL / BLOCKED / NOT TESTED`, evidencia y fecha.
5. No realizar push, deploy, pagos ni cambios irreversibles sin autorización del propietario.

---

# ANEXO A — ESPECIFICACIÓN ORIGINAL ÍNTEGRA DEL NEURAL DECISION ENGINE

> El contenido que sigue se preserva íntegramente del archivo original suministrado. Su referencia de imagen original `panel_de_decisión_neuronal_kova.png` es **específica del motor 3D**; la imagen `KOVA_CEO_Dashboard_referencia_aprobada.png` es la referencia para el **dashboard completo**. Si la primera imagen no está disponible, el texto del anexo sigue siendo vinculante y debe indicarse que no se pudo hacer una comparación visual exacta de esa referencia secundaria.

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
