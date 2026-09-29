> **ESTADO: PROPUESTA ARQUITECTÓNICA FUTURA. NO ES ESPECIFICACIÓN IMPLEMENTABLE.**
> Auditada el 2026-09-29 contra ADR 0001-0018 y M31-M40; decisión: **APLAZADA**. Ver
> `AMAZONA_KOVA_plan_maestro_continuacion_Claude_Code.md` §23 bis, que fija la
> abstracción (`AutomationPort` + adaptadores) y las prohibiciones. Este texto está
> archivado sin modificar por debajo; varias partes (reintentos, registro de
> ejecuciones, Cost Guard y gateway con permisos propios, pedidos vía n8n) están
> **rechazadas** por la auditoría.

# KOVA --- n8n Automation & Execution Layer

**Proyecto:** AMAZONA → KOVA\
**Tecnología:** n8n\
**Repositorio:** https://github.com/n8n-io/n8n\
**Función propuesta:** capa de automatización y ejecución externa\
**Estado:** POSITIVO\
**Prioridad:** ALTA\
**Clasificación:**
`CORE_INFRASTRUCTURE_CANDIDATE / AUTOMATION / ORCHESTRATION`

------------------------------------------------------------------------

## 1. Decisión ejecutiva

n8n puede aportar mucho valor a KOVA, pero **no debe sustituir al
sistema multiagente**.

Separación recomendada:

``` text
KOVA AGENTS
= pensar / analizar / decidir

n8n
= ejecutar / conectar / automatizar
```

Arquitectura:

``` text
                    KOVA
                      │
                  CEO AGENT
                      │
        ┌─────────────┼─────────────┐
        │             │             │
     COMMERCE     WEB SERVICES   OPERATIONS
        │             │             │
        └─────────────┼─────────────┘
                      │
                 KOVA AGENTS
                      │
               DECISION LAYER
                      │
                     n8n
                      │
     ┌────────┬───────┼───────┬────────┐
     │        │       │       │        │
    APIs   Suppliers CRM   Marketing Finance
```

**Principio:** KOVA mantiene la inteligencia, reglas, memoria,
supervisión y decisiones. n8n ejecuta workflows deterministas y conecta
sistemas externos.

------------------------------------------------------------------------

# 2. Qué aporta n8n

n8n es una plataforma de automatización de workflows que puede:

-   consumir APIs;
-   recibir/enviar webhooks;
-   conectar servicios;
-   ejecutar lógica;
-   transformar datos;
-   ejecutar JavaScript/Python;
-   encadenar procesos;
-   manejar triggers;
-   ejecutar tareas programadas;
-   integrar modelos y agentes IA;
-   registrar ejecuciones;
-   gestionar errores y reintentos;
-   trabajar self-hosted.

Esto evita programar manualmente muchas integraciones repetitivas.

------------------------------------------------------------------------

# 3. Qué NO debe hacer

No convertir n8n en:

``` text
CEO de KOVA
```

ni reemplazar:

-   Product Hunter;
-   Supplier Finder;
-   Marketing Agent;
-   Legal Agent;
-   CFO;
-   Web Builder;
-   Decision Engine;
-   memoria/aprendizaje central.

Evitar dos cerebros compitiendo.

------------------------------------------------------------------------

# 4. División de responsabilidades

## KOVA

Responsable de:

``` text
razonamiento
estrategia
decisiones
priorización
scoring
riesgo
aprendizaje
memoria
supervisión
```

## n8n

Responsable de:

``` text
API calls
webhooks
triggers
movimiento de datos
notificaciones
sincronización
automatizaciones
procesos repetitivos
jobs programados
reintentos
```

------------------------------------------------------------------------

# 5. KOVA Commerce

Ejemplo:

``` text
Product Hunter
      ↓
producto aprobado
      ↓
Supplier Agent
      ↓
decisión de solicitar información
      ↓
n8n
      ↓
API / email / sistema proveedor
      ↓
respuesta
      ↓
KOVA
```

n8n ejecuta; el agente decide.

------------------------------------------------------------------------

# 6. Pedidos

Posible flujo:

``` text
CLIENTE
   ↓
COMPRA
   ↓
webhook
   ↓
n8n
   ↓
validación técnica
   ↓
KOVA
   ↓
Supplier Workflow
   ↓
proveedor
   ↓
tracking
   ↓
cliente
```

Aplicable al modelo preferente de KOVA sin stock propio cuando
proveedores e integraciones lo permitan.

------------------------------------------------------------------------

# 7. Supplier Finder

Automatizaciones posibles:

``` text
nuevo proveedor
↓
crear registro
↓
solicitar datos
↓
recibir respuesta
↓
normalizar
↓
guardar
↓
avisar Supplier Agent
```

También:

-   actualizaciones de precio;
-   disponibilidad;
-   tracking;
-   catálogo;
-   cambios de condiciones;
-   alertas.

------------------------------------------------------------------------

# 8. Marketing Agent

Ejemplo:

``` text
Marketing Agent
      ↓
campaña aprobada
      ↓
n8n
      ├── CRM
      ├── email
      ├── analytics
      ├── ads API
      └── reporting
```

El Marketing Agent determina la estrategia.

n8n ejecuta los procesos permitidos.

------------------------------------------------------------------------

# 9. CFO

n8n puede ayudar a automatizar:

``` text
ventas
↓
registro
↓
clasificación
↓
CFO
↓
dashboard
```

y conectar:

-   facturación;
-   pagos;
-   bancos/APIs compatibles;
-   gastos;
-   proveedores;
-   contabilidad;
-   reporting.

Las decisiones financieras continúan en KOVA/CFO y bajo supervisión
humana cuando corresponda.

------------------------------------------------------------------------

# 10. Legal Agent

Automatizaciones posibles:

-   alertas de documentos;
-   vencimientos;
-   registros;
-   almacenamiento;
-   workflows de aprobación;
-   actualización de evidencias;
-   envío de información al Legal Agent.

n8n no sustituye revisión legal.

------------------------------------------------------------------------

# 11. Web Builder

Flujo potencial:

``` text
nuevo proyecto
↓
KOVA Web Builder
↓
build
↓
n8n
├── QA
├── deployment
├── analytics
├── monitoring
└── notificación
```

Puede automatizar el ciclo operativo posterior a la decisión del Web
Builder.

------------------------------------------------------------------------

# 12. KOVA Web Services

La nueva línea de negocio puede aprovechar la misma infraestructura.

``` text
KOVA WEB SERVICES

Web
+
E-commerce
+
3D
+
IA
+
Automatización
```

Ejemplo cliente:

``` text
WEB CLIENTE
    ↓
formulario
    ↓
n8n
    ↓
CRM
    ↓
email
    ↓
seguimiento
    ↓
analytics
```

------------------------------------------------------------------------

# 13. Automatización para ecommerce externo

``` text
pedido
↓
n8n
├── CRM
├── proveedor
├── inventario
├── email
├── facturación
└── analytics
```

Esto puede aumentar el valor del servicio frente a vender únicamente una
página web.

------------------------------------------------------------------------

# 14. Producto potencial

KOVA podría ofrecer paquetes como:

``` text
KOVA WEB
KOVA COMMERCE
KOVA 3D
KOVA AUTOMATION
KOVA AI AUTOMATION
```

Pero antes de comercializar n8n como parte directa de un
servicio/producto deben revisarse sus condiciones de licencia vigentes.

------------------------------------------------------------------------

# 15. Self-hosting

n8n dispone de Community Edition self-hosted.

Arquitectura inicial posible:

``` text
Docker
  │
 n8n
  │
PostgreSQL
```

Escalado:

``` text
Load Balancer
      ↓
n8n
      ↓
Redis Queue
      ↓
Workers
      ↓
PostgreSQL
```

KOVA no necesita empezar con infraestructura compleja.

------------------------------------------------------------------------

# 16. Costes

## Software

La Community Edition self-hosted permite comenzar con coste de licencia
de software muy bajo o nulo según el uso permitido por su licencia
vigente.

## Infraestructura

Costes principales:

-   VPS/cloud;
-   base de datos;
-   almacenamiento;
-   backups;
-   observabilidad;
-   APIs externas;
-   modelos IA;
-   tráfico.

Para pruebas iniciales, el coste puede mantenerse bajo.

Escalar únicamente cuando aumente la carga real.

------------------------------------------------------------------------

# 17. Licencia --- punto crítico

n8n **no debe tratarse como software MIT/open-source tradicional**.

El proyecto utiliza un modelo de licencia fair-code/Sustainable Use
License para buena parte de su distribución, con condiciones específicas
sobre determinados usos comerciales.

Antes de:

``` text
revender
redistribuir
white-label
ofrecer acceso directo
integrar n8n como producto SaaS
```

se debe revisar la licencia vigente y, si procede, consultar a n8n.

Uso interno para automatizar operaciones y comercialización de una
plataforma basada directamente en n8n no son necesariamente el mismo
supuesto.

**KOVA Legal Agent deberá controlar este punto antes de producción
comercial.**

------------------------------------------------------------------------

# 18. Arquitectura segura para Web Services

Modelo preferible:

``` text
CLIENTE
   ↓
KOVA SERVICE
   ↓
KOVA BACKEND
   ↓
automation layer
   ↓
n8n
   ↓
APIs
```

El cliente compra un resultado/servicio KOVA.

No asumir automáticamente que puede venderse:

``` text
"acceso a nuestra plataforma n8n"
```

sin revisar licencia.

------------------------------------------------------------------------

# 19. Seguridad

n8n manejará potencialmente:

-   API keys;
-   tokens;
-   datos comerciales;
-   pedidos;
-   clientes;
-   proveedores;
-   credenciales.

Requisitos mínimos:

``` text
Secrets Management
RBAC
HTTPS
Network Isolation
Backups
Audit Logs
Credential Rotation
Least Privilege
```

Nunca introducir secretos directamente en workflows exportables o
repositorios.

------------------------------------------------------------------------

# 20. Reliability Layer

Todo workflow crítico debe incluir:

``` text
TRIGGER
   ↓
VALIDATION
   ↓
ACTION
   ↓
SUCCESS?
 ┌─┴─┐
YES  NO
 │    │
LOG  RETRY
       ↓
    FAILURE?
       ↓
    ALERT
```

Especialmente para:

-   pedidos;
-   pagos;
-   proveedores;
-   facturación;
-   comunicaciones.

------------------------------------------------------------------------

# 21. Idempotencia

Un workflow repetido no debe provocar:

``` text
doble pedido
doble factura
doble email
doble pago
```

Usar identificadores únicos y comprobación de estado antes de ejecutar
acciones críticas.

------------------------------------------------------------------------

# 22. Human-in-the-loop

No automatizar inmediatamente acciones sensibles.

Ejemplo:

``` text
AI recommendation
      ↓
confidence
      ↓
risk
      ↓
¿requiere aprobación?
   ┌──────┴──────┐
  YES            NO
   ↓              ↓
humano        ejecución
   ↓
n8n
```

Con el tiempo pueden reducirse aprobaciones donde los datos demuestren
fiabilidad.

------------------------------------------------------------------------

# 23. Observabilidad

KOVA debe conocer:

``` text
qué workflow
qué agente
qué acción
qué coste
qué resultado
qué duración
qué error
```

Registro sugerido:

``` text
workflow_id
execution_id
agent_id
project_id
action
provider
status
latency
api_cost
timestamp
error
```

------------------------------------------------------------------------

# 24. CFO Cost Guard

Cada workflow puede generar costes externos.

Ejemplo:

``` text
n8n
↓
OpenAI
↓
API
↓
0,04 €
```

o:

``` text
n8n
↓
3D API
↓
1,20 €
```

Registrar costes por:

``` text
producto
cliente
agente
workflow
proyecto
```

El CFO debe poder establecer:

``` text
daily budget
monthly budget
per-workflow limit
per-client limit
```

------------------------------------------------------------------------

# 25. Workflow Registry

No permitir workflows descontrolados.

Crear:

``` text
KOVA WORKFLOW REGISTRY
```

Ejemplo:

``` text
WF-001 Supplier Contact
WF-002 Order Processing
WF-003 Tracking Update
WF-004 Marketing Campaign
WF-005 Invoice Processing
WF-006 Web Deployment
```

Cada workflow debe incluir:

``` text
owner
version
purpose
permissions
cost
risk
status
```

------------------------------------------------------------------------

# 26. Versionado

Guardar workflows como código/configuración cuando sea posible.

``` text
Git
↓
workflow JSON
↓
review
↓
test
↓
production
```

Beneficios:

-   rollback;
-   auditoría;
-   historial;
-   control de cambios.

------------------------------------------------------------------------

# 27. Entornos

Separar:

``` text
DEV
↓
STAGING
↓
PRODUCTION
```

Nunca probar automatizaciones peligrosas directamente sobre sistemas
reales.

------------------------------------------------------------------------

# 28. AI Agents de n8n

n8n también dispone de capacidades para construir workflows con agentes
y modelos IA.

Esto es útil, pero debe evitarse duplicar la arquitectura de KOVA.

Regla:

``` text
KOVA AGENT
= inteligencia principal

n8n AI
= inteligencia localizada dentro de un workflow
```

Ejemplo válido:

``` text
clasificar email
extraer datos
resumir
normalizar
```

Ejemplo que conviene mantener en KOVA:

``` text
decidir estrategia empresarial
priorizar productos
decidir inversión
coordinar agentes
```

------------------------------------------------------------------------

# 29. Cuándo usar n8n

Usar cuando exista:

``` text
trigger
+
datos
+
reglas
+
acción externa
```

Ejemplo:

``` text
pedido recibido
→ validar
→ registrar
→ contactar proveedor
→ enviar confirmación
```

------------------------------------------------------------------------

# 30. Cuándo NO usar n8n

No utilizar automáticamente para:

-   razonamiento complejo;
-   memoria central;
-   estrategia;
-   lógica nuclear del producto;
-   cálculos críticos que deberían estar en backend;
-   procesos donde una implementación directa sea más sencilla.

Evitar convertir n8n en un monolito.

------------------------------------------------------------------------

# 31. Arquitectura recomendada final

``` text
                         KOVA
                           │
                    DECISION ENGINE
                           │
                ┌──────────┴──────────┐
                │                     │
             AGENTS                BACKEND
                │                     │
                └──────────┬──────────┘
                           │
                  AUTOMATION GATEWAY
                           │
                          n8n
                           │
       ┌──────────┬────────┼────────┬─────────┐
       │          │        │        │         │
   Suppliers    CRM      APIs    Finance   Marketing
```

Añadir un **Automation Gateway** entre KOVA y n8n evita acoplar toda la
plataforma directamente a workflows.

------------------------------------------------------------------------

# 32. Automation Gateway

Responsabilidades:

-   autenticar;
-   validar acciones;
-   aplicar permisos;
-   imponer presupuestos;
-   registrar ejecución;
-   controlar versiones;
-   gestionar callbacks.

KOVA solicita:

``` text
execute(WF-003)
```

en vez de conocer todos los detalles internos de n8n.

Esto permite reemplazar n8n en el futuro si fuese necesario.

------------------------------------------------------------------------

# 33. Ventaja estratégica

n8n puede reducir significativamente el desarrollo de integraciones.

En vez de:

``` text
KOVA
↓
programar 100 integraciones
```

podemos aprovechar:

``` text
KOVA
↓
Automation Gateway
↓
n8n
↓
ecosistema de integraciones
```

Resultado potencial:

-   desarrollo más rápido;
-   menor código propio;
-   automatización visual;
-   workflows modificables;
-   integración rápida de servicios.

------------------------------------------------------------------------

# 34. Riesgos

  Riesgo                Nivel   Mitigación
  --------------------- ------- ---------------------------
  Dependencia n8n       Medio   Automation Gateway
  Licencia              Medio   Legal review
  Credenciales          Alto    Secrets + least privilege
  Workflow incorrecto   Alto    staging + approvals
  Duplicación           Alto    idempotencia
  Costes API            Medio   CFO Cost Guard
  Complejidad           Medio   Workflow Registry
  Duplicar agentes      Medio   separación clara

------------------------------------------------------------------------

# 35. Roadmap

## Fase 1 --- PoC

Instalar n8n local/self-hosted.

Crear 3 workflows:

``` text
Webhook Test
Supplier Test
Notification Test
```

## Fase 2 --- Gateway

Construir:

``` text
KOVA Automation Gateway
```

## Fase 3 --- Registry

Crear catálogo y versionado de workflows.

## Fase 4 --- Commerce

Automatizar procesos no críticos.

## Fase 5 --- Monitoring

Añadir:

-   logs;
-   métricas;
-   costes;
-   alertas.

## Fase 6 --- Web Services

Crear automatizaciones reutilizables para clientes.

## Fase 7 --- Scale

Solo si el volumen lo requiere:

``` text
queue
Redis
workers
HA
```

------------------------------------------------------------------------

# 36. Primeros workflows recomendados

Prioridad inicial:

``` text
1. Supplier Data Intake
2. Supplier Price Update
3. Product Alert
4. Web Lead Capture
5. CRM Sync
6. Web Deployment Notification
7. Order Event
8. Tracking Update
9. Cost Logging
10. Failure Alert
```

Evitar empezar por pagos o decisiones financieras automáticas.

------------------------------------------------------------------------

# 37. Valoración KOVA

  Área                       Valoración interna
  ------------------------ --------------------
  Automatización                          10/10
  Integraciones                          9.5/10
  KOVA Commerce                          9.5/10
  Web Services                             9/10
  Rapidez de desarrollo                  9.5/10
  Self-hosting                             9/10
  Sustitución de agentes                   3/10
  Complemento de agentes                  10/10
  Riesgo técnico                          Medio
  Prioridad                                Alta

Las puntuaciones son valoraciones internas para priorización.

------------------------------------------------------------------------

# 38. Decisión

**INTEGRAR COMO CANDIDATO DE INFRAESTRUCTURA.**

Pero con una regla arquitectónica estricta:

``` text
KOVA piensa.
n8n ejecuta.
```

No:

``` text
KOVA = n8n
```

La arquitectura recomendada es:

``` text
KOVA
↓
Agents
↓
Decision Engine
↓
Automation Gateway
↓
n8n
↓
External Systems
```

Esto conserva la independencia tecnológica de KOVA y aprovecha el
ecosistema de automatización de n8n.

------------------------------------------------------------------------

# 39. Impacto sobre el modelo KOVA

Con esta incorporación:

``` text
KOVA
│
├── COMMERCE
│   └── productos propios
│
├── WEB SERVICES
│   ├── webs
│   ├── ecommerce
│   ├── 3D
│   └── automatizaciones
│
├── AI AGENTS
│   └── inteligencia
│
└── AUTOMATION LAYER
    └── ejecución
```

Esto permite que infraestructura desarrollada para la operación interna
pueda, cuando licencia y arquitectura lo permitan, ayudar también a
generar servicios facturables externos.

------------------------------------------------------------------------

# 40. Fuentes oficiales para implementación

-   n8n: https://n8n.io/
-   GitHub: https://github.com/n8n-io/n8n
-   Documentación: https://docs.n8n.io/
-   Self-hosting: https://docs.n8n.io/hosting/
-   Licencia: https://github.com/n8n-io/n8n/blob/master/LICENSE.md
-   Sustainable Use License:
    https://github.com/n8n-io/n8n/blob/master/LICENSE.md

**Requisito:** verificar nuevamente documentación, licencia, precios y
condiciones comerciales antes de producción.

------------------------------------------------------------------------

**Clasificación final:**\
`KOVA / CORE_INFRASTRUCTURE_CANDIDATE / AUTOMATION_GATEWAY / N8N / PRIORIDAD_ALTA`
