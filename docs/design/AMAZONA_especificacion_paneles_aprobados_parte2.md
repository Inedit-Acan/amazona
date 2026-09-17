# AMAZONA — Especificación de UI/UX y arquitectura de paneles aprobados · Parte 2

**Proyecto:** AMAZONA  
**Fecha:** 17 de septiembre de 2026  
**Estado:** paneles restantes aprobados  
**Uso previsto:** referencia funcional y visual para implementación posterior en Claude Code

---

# 1. Principios globales aplicables

Todos los paneles de esta segunda fase deben respetar la identidad ya aprobada para AMAZONA:

- Fondo general negro / negro azulado muy oscuro.
- Tarjetas y superficies en verde esmeralda oscuro.
- Acentos esmeralda/turquesa brillante.
- Blanco para texto principal y gris frío para texto secundario.
- Ámbar para advertencias.
- Rojo para bloqueos, errores críticos o acciones destructivas.
- Estética **2.5D premium**, sobria, empresarial y tecnológica.
- Bordes finos, profundidad suave, glow contenido.
- Alta densidad de información con jerarquía clara.
- No usar estética de videojuego.
- Desktop-first; responsive posterior.
- Diferenciar siempre:
  - dato verificado;
  - dato proporcionado por tercero;
  - estimación AMAZONA;
  - pendiente/no validado.
- El 3D real continúa reservado al grafo de agentes del Director Ejecutivo.
- Los nuevos paneles descritos aquí usan 2.5D.

---

# 2. Orden final del menú principal

```text
1. Panel
2. Director ejecutivo
3. Investigación
4. Proveedores y abastecimiento
5. Economía y rentabilidad
6. Legal y cumplimiento
7. Tienda y canales de venta
8. Marketing y adquisición
9. Operaciones
10. Finanzas y control
11. Proyectos
12. Agentes
13. Aprobaciones
14. Auditoría
15. Estado
```

Nota: el antiguo módulo **Mercado** permanece eliminado como pantalla independiente.

---

# 3. Panel — Operaciones

## 3.1. Propósito

Convertirse en el **Control Tower operativo de AMAZONA**.

Debe centralizar:
- pedidos;
- fulfillment;
- proveedores en ejecución;
- tracking;
- entregas;
- incidencias;
- SLA;
- devoluciones;
- soporte postventa;
- automatizaciones operativas.

No debe ser un generador manual de informes.

## 3.2. KPIs superiores

- Pedidos activos.
- En tránsito.
- Entregados hoy.
- % a tiempo.
- Incidencias abiertas.
- Tasa de devoluciones.
- Tiempo medio de entrega.
- SLA de proveedor.

## 3.3. Pipeline de pedidos

```text
Confirmado
→ Proveedor
→ Preparación
→ Despachado
→ En tránsito
→ Entregado
```

Debe permitir detectar cuellos de botella.

## 3.4. Centro de incidencias

Prioridades:
- Crítica.
- Alta.
- Media.
- Baja.

Ejemplos:
- proveedor no confirma;
- tracking inmóvil;
- retención aduanera;
- cambio de dirección;
- devolución excepcional.

Cada incidencia debe mostrar:
- pedido;
- proveedor;
- tiempo;
- SLA;
- responsable;
- acción recomendada.

## 3.5. Tabla principal de pedidos

Columnas:
- pedido;
- canal;
- producto;
- proveedor;
- estado;
- entrega estimada;
- SLA;
- riesgo;
- acciones.

Filtros:
- Todos
- Pendientes
- Proveedor
- Preparación
- En tránsito
- Retrasados
- Entregados
- Devueltos

## 3.6. Seguimiento de pedido

Timeline:
```text
Pedido realizado
Proveedor acepta
Preparado
Recogido
En tránsito
Entrega estimada
```

Métricas:
- tiempo de procesamiento;
- tiempo hasta recogida;
- tránsito;
- entrega prevista.

## 3.7. Rendimiento de proveedores

Medir con datos reales:
- pedidos;
- aceptación;
- despacho en SLA;
- entrega a tiempo;
- cancelaciones;
- devoluciones;
- defectos;
- tracking válido;
- score operativo.

Estos datos deben retroalimentar Proveedores y abastecimiento.

## 3.8. Modelo sin stock

Mostrar por pedido:
- cobro del cliente;
- pago al proveedor;
- capital adelantado;
- desfase temporal;
- cobertura.

## 3.9. Automatizaciones operativas

Ejemplos:
```text
Pago confirmado → enviar pedido al proveedor
Proveedor sin confirmar 2 h → recordatorio
Proveedor sin confirmar 6 h → escalar
Sin tracking 24 h → solicitar tracking
Retraso > SLA → avisar cliente
Retraso crítico → requerir decisión humana
```

## 3.10. Devoluciones

Integradas dentro de Operaciones.

Mostrar:
- abiertas;
- en revisión;
- en tránsito;
- recibidas;
- tasa de devolución;
- principales motivos.

Las causas deben retroalimentar:
- Investigación;
- Marketing;
- Tienda;
- Proveedores.

## 3.11. Transportistas

Tabla con:
- transportista;
- entrega a tiempo;
- tiempo medio;
- incidencias.

## 3.12. Operational Health

Score explicable con:
- pedidos;
- proveedores;
- logística;
- entregas;
- devoluciones;
- automatizaciones;
- incidencias.

## 3.13. Referencias visuales

- AfterShip
- Shopify Orders
- ShipBob
- Loop Returns

---

# 4. Panel — Finanzas y control

## 4.1. Propósito

Centro financiero corporativo de AMAZONA.

Diferencia clave:
- **Economía y rentabilidad** → producto individual.
- **Finanzas y control** → empresa completa.

## 4.2. Nombre aprobado

En menú: **Finanzas y control**  
Dentro: **Director de Finanzas · CFO**

## 4.3. KPIs

- caja disponible;
- ingresos del mes;
- beneficio neto;
- margen neto;
- gasto del mes;
- runway;
- cobros pendientes;
- pagos próximos.

## 4.4. Cash Flow

Gráfico principal:
- entradas;
- salidas;
- saldo;
- forecast;
- escenarios.

Alertas de posibles tensiones de caja.

## 4.5. P&L consolidado

```text
Ingresos
Coste de mercancía
Margen bruto
Marketing
Software / IA
Logística
Devoluciones
Administración
Otros
EBITDA
Impuestos estimados
Resultado neto
```

Cada línea debe permitir drill-down.

## 4.6. Budget vs Real vs Forecast

Tabla por áreas:
- Marketing
- Software
- Logística
- Legal
- Operaciones

Estados:
- dentro del plan;
- riesgo de desviación;
- sobrepresupuesto.

## 4.7. Presupuesto global

Mostrar:
- asignado;
- comprometido;
- gastado;
- disponible;
- distribución por áreas.

## 4.8. Tesorería

- cuenta operativa;
- reserva;
- Stripe pendiente;
- PayPal pendiente;
- Amazon pendiente;
- liquidez total.

## 4.9. Cuentas a pagar

- proveedor;
- importe;
- vencimiento;
- estado.

## 4.10. Cuentas a cobrar

- canal;
- importe;
- estado;
- días hasta liquidación.

## 4.11. Working Capital

Métrica propia de AMAZONA:
```text
Cobros cliente antes de compra
Capital adelantado AMAZONA
Capital cubierto
Capital sin cobertura
Cobertura global
```

Comparar contra objetivo preferido de cobertura: **75–90 %** cuando exista exposición previa.

## 4.12. Rentabilidad por dimensión

Permitir agrupar:
- producto;
- canal;
- país;
- proveedor;
- campaña;
- proyecto.

No recalcular unit economics aquí.

## 4.13. Forecast financiero

Escenarios:
- Base
- Conservador
- Expansión

Horizontes:
- 3 meses;
- 6 meses;
- 12 meses.

## 4.14. Variance Analysis

Mostrar desviaciones respecto a:
- presupuesto;
- forecast;
- objetivo.

El agente debe explicar las causas.

## 4.15. Fiscalidad

Mostrar:
- IVA estimado;
- impuestos estimados;
- próximas obligaciones;
- documentación.

Distinguir:
- estimación/borrador;
- declaración real presentada.

## 4.16. Contabilidad

Resumen:
- transacciones;
- conciliadas;
- pendientes.

Categorías:
- ventas;
- proveedores;
- marketing;
- logística;
- software;
- devoluciones;
- impuestos;
- otros.

## 4.17. Capital y financiación

- subvenciones detectadas;
- aplicables;
- en preparación;
- necesidad prevista de capital;
- reserva disponible.

## 4.18. Alertas financieras

Ejemplos:
- coste logístico por encima del forecast;
- presupuesto próximo a agotarse;
- liquidaciones pendientes;
- margen empresarial mejor/peor de lo previsto.

## 4.19. CFO Copilot

Preguntas permitidas:
- por qué bajó el margen;
- cuánto puede invertirse en marketing;
- pagos próximos;
- mejor producto por beneficio;
- riesgo de caja.

Toda respuesta debe mostrar:
- fuente;
- periodo;
- cálculo.

## 4.20. Financial Health

Score explicable:
- liquidez;
- rentabilidad;
- cash flow;
- presupuesto;
- capital expuesto;
- cobertura fiscal;
- forecast.

## 4.21. Referencias

- Pigment
- Ramp
- Brex
- Xero
- Stripe

---

# 5. Panel — Proyectos

## 5.1. Propósito

Convertirse en la **unidad central de seguimiento y memoria de cada oportunidad empresarial**.

Un proyecto es el expediente completo:

```text
Objetivo CEO
→ Investigación
→ Proveedores
→ Economía
→ Legal
→ Tienda
→ Marketing
→ Operaciones
→ Resultados
→ Aprendizaje
```

## 5.2. Dos niveles de vista

### Portfolio
Vista de todos los proyectos.

### Project Detail
Vista de un proyecto específico.

## 5.3. Portfolio

KPIs:
- activos;
- en validación;
- en lanzamiento;
- operativos;
- en riesgo;
- bloqueados;
- beneficio previsto;
- beneficio real.

Tabla:
- proyecto;
- producto;
- fase;
- salud;
- progreso;
- beneficio previsto;
- fecha de inicio.

## 5.4. Vistas

Tabs:
- Resumen
- Lista
- Pipeline
- Timeline

## 5.5. Lifecycle

```text
BORRADOR
→ VALIDACIÓN
→ PREPARACIÓN
→ LANZAMIENTO
→ OPERATIVO
→ ESCALA
```

Estados alternativos:
- Pausado
- Bloqueado
- Descartado
- Cerrado

## 5.6. Project Health

Score multidimensional:
- mercado;
- proveedor;
- economía;
- legal;
- canal;
- marketing;
- operaciones;
- riesgo general.

Debe ser explicable.

## 5.7. Vista detalle

Cabecera:
- ID proyecto;
- nombre;
- mercado;
- categoría;
- modelo logístico;
- fase;
- Project Health;
- progreso;
- beneficio previsto;
- capital expuesto;
- próximo gate.

## 5.8. Pipeline del proyecto

```text
Investigación     ✓
Proveedores       ✓
Economía          ✓
Legal             ✓
Tienda            ✓
Marketing         ●
Operaciones       ○
Escala            ○
```

Cada fase enlaza al módulo correspondiente.

## 5.9. Próxima decisión

Mostrar:
- solicitud;
- importe;
- CAC máximo;
- estado Legal;
- estado Economía;
- estado Tienda;
- botón para abrir Aprobaciones.

## 5.10. Agentes trabajando

Panel:
- ejecutando;
- monitorizando;
- en espera;
- pendientes.

## 5.11. Riesgos

- dependencia de proveedor;
- CAC;
- legal;
- capital;
- operaciones.

## 5.12. Actividad reciente

Timeline:
- agente;
- acción;
- hora.

## 5.13. Hitos

Ejemplos:
- producto validado;
- proveedor seleccionado;
- viabilidad económica;
- Legal Gate;
- tienda preparada;
- campaña aprobada;
- primera venta;
- primeras 100 ventas;
- break-even real.

## 5.14. Previsto vs Real

Mostrar:
- ventas;
- ingresos;
- CAC;
- margen;
- devoluciones;
- entrega.

## 5.15. Aprendizajes del proyecto

Ejemplos:
- demanda prevista correcta;
- CAC mejor;
- lead time peor;
- creative ganador;
- devoluciones mejores.

Estos aprendizajes alimentan al sistema.

## 5.16. Referencias

- Linear
- Asana Portfolios
- monday.com

---

# 6. Panel — Agentes

## 6.1. Propósito

Convertirse en el **Agent Control Center**.

Debe controlar:
- agentes;
- ejecuciones;
- versiones;
- herramientas;
- permisos;
- evaluaciones;
- costes;
- errores;
- rendimiento.

## 6.2. Arquitectura propuesta de 13 agentes operativos

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

El CEO/orquestador queda por encima de este pool y no se cuenta como agente operativo.

## 6.3. Motivo de la reorganización

Eliminar duplicidades actuales:
- validación producto / investigación producto;
- búsqueda proveedor / investigación abastecimiento;
- validación financiera / riesgo económico;
- validación legal / cumplimiento;
- antiguo Agente Mercado.

El antiguo Agente Mercado se redefine como **Marketplace Channel Agent**.

## 6.4. KPIs

- agentes registrados;
- ejecutando;
- disponibles;
- tasa de éxito;
- coste del día;
- alertas.

## 6.5. Tarjetas de agente

Mostrar:
- nombre;
- equipo;
- estado;
- proyecto/tarea;
- progreso;
- éxito;
- evaluación;
- latencia;
- coste;
- versión;
- última actividad.

Estados:
- Ejecutando
- Disponible
- Esperando
- Pausado
- Error
- Requiere revisión

## 6.6. Tabs

- Agentes
- Actividad
- Rendimiento
- Evaluaciones
- Versiones

## 6.7. Rendimiento

Tabla:
- agente;
- runs;
- éxito;
- eval;
- latencia;
- coste;
- errores.

Filtros:
- 24 h;
- 7 días;
- 30 días;
- proyecto;
- agente;
- modelo.

## 6.8. Vista detalle de agente

Tabs:
- Resumen
- Ejecuciones
- Evaluaciones
- Herramientas
- Configuración
- Versiones

## 6.9. Herramientas y permisos

Distinguir:
- herramienta disponible;
- permiso otorgado.

Ejemplos de permisos:
- leer datos;
- crear análisis;
- crear proyecto;
- solicitar acción externa;
- gastar dinero;
- publicar producto.

## 6.10. Versionado

Guardar:
- versión;
- fecha;
- evaluation score;
- producción/staging;
- comparación;
- rollback.

## 6.11. Evaluation Suite

Métricas posibles:
- relevancia;
- errores;
- grounding;
- coste;
- latencia;
- policy compliance.

No desplegar una versión sin superar umbral definido.

## 6.12. Costes de agentes

Mostrar:
- coste por agente;
- tokens;
- API calls;
- búsquedas;
- servicios externos;
- coste agregado.

## 6.13. Trazas operativas

Guardar:
- herramientas;
- inputs relevantes;
- outputs;
- tiempos;
- errores;
- coste;
- fuentes.

No mostrar razonamiento interno privado.

## 6.14. Handoffs

Registrar:
- agente origen;
- agente destino;
- tarea;
- contexto;
- resultado.

## 6.15. Alertas

Ejemplos:
- error rate alto;
- coste anómalo;
- latencia alta;
- fallos de tool;
- versión degradada.

## 6.16. Frontera con Estado

**Agentes** → salud y rendimiento de trabajadores IA.  
**Estado** → salud de la infraestructura.

## 6.17. Referencias

- CrewAI AMP
- LangSmith
- Datadog Agent Observability
- n8n

---

# 7. Panel — Aprobaciones

## 7.1. Propósito

Convertirse en el **Human Decision Center**.

No limitarlo a aprobaciones de gasto.

Debe autorizar:
- presupuesto;
- lanzamiento;
- proveedor;
- stock;
- excepción legal;
- campaña;
- activación de canal;
- pago extraordinario;
- reembolso excepcional;
- deploy de agente;
- automatización crítica.

## 7.2. Nombre

Menú: **Aprobaciones**  
Encabezado: **Aprobaciones y decisiones**

## 7.3. KPIs

- pendientes;
- críticas;
- vencen pronto;
- aprobadas hoy;
- tiempo medio.

## 7.4. Bandeja principal

Diseño:
- lista izquierda;
- detalle derecha.

Cada solicitud:
- tipo;
- criticidad;
- proyecto;
- solicitante;
- importe;
- antigüedad;
- estado.

## 7.5. Tipos de prioridad

- Crítica
- Alta
- Media
- Baja

## 7.6. Vista detalle

Debe reunir:
- solicitud;
- contexto;
- Economía;
- Legal;
- Finanzas;
- Tienda;
- Riesgo;
- documentos;
- análisis de agentes;
- impacto.

Acciones:
- Rechazar
- Solicitar cambios
- Aprobar

## 7.7. Análisis AMAZONA

Mostrar:
- agentes consultados;
- condiciones cumplidas;
- evidencias;
- riesgos.

Evitar recomendaciones autoritarias tipo “la IA decide”.

## 7.8. Cadena de aprobación

```text
Acquisition Agent
→ CFO
→ Legal
→ Owner
→ Ejecución
```

## 7.9. Separation of Duties

Regla:
quien solicita no debe aprobar si la política exige independencia.

## 7.10. Presupuesto visible

Antes de aprobar:
- asignado;
- gastado;
- comprometido;
- disponible;
- impacto de la solicitud.

## 7.11. Impacto de decisión

Separar:

### Si apruebas
- alcance;
- importe;
- mercado;
- duración;
- límites.

### No se autoriza
- superar presupuesto;
- otros mercados;
- claims no aprobados;
- cambios fuera de condiciones.

## 7.12. Guardrails

Aprobaciones condicionadas:
```text
Presupuesto ≤ 1.500 €
CAC ≤ 8,10 €
Mercado = España
Duración ≤ 14 días
```

Si cambia una condición:
→ nueva aprobación.

## 7.13. Reglas de autoaprobación

Configurable por:
- tipo;
- importe;
- riesgo;
- canal;
- usuario;
- proyecto.

## 7.14. Workflow Builder

Editor visual 2.5D:
- condiciones;
- bifurcaciones;
- aprobadores;
- resultado.

## 7.15. Simulador de políticas

Antes de activar una regla:
- introducir tipo;
- importe;
- proyecto;
- mostrar ruta resultante.

## 7.16. Historial

Tabs:
- Pendientes
- Decididas
- Reglas
- Historial

## 7.17. Rechazo

Motivo obligatorio:
- riesgo;
- presupuesto;
- documentación;
- política;
- alternativa;
- otro.

El feedback alimenta agentes.

## 7.18. Referencias

- Ramp
- Coupa
- ServiceNow
- Linear

---

# 8. Panel — Auditoría

## 8.1. Propósito

Convertirse en el **registro forense e inmutable de AMAZONA**.

Pregunta:
> ¿Qué ocurrió exactamente y podemos demostrarlo?

## 8.2. Nombre

Menú: **Auditoría**  
Encabezado: **Auditoría y trazabilidad**

## 8.3. Principio de inmutabilidad

El registro debe ser:
- append-only;
- no editable desde UI normal;
- no eliminable desde UI normal.

Las correcciones deben generar nuevos eventos.

## 8.4. KPIs

- eventos del día;
- acciones críticas;
- aprobaciones;
- cambios configuración;
- errores;
- % evidencias completas.

## 8.5. Tabs

- Eventos
- Timeline
- Proyectos
- Agentes
- Seguridad
- Integridad
- Retención

## 8.6. Tabla de auditoría

Columnas:
- fecha/hora;
- tipo;
- acción;
- actor;
- proyecto;
- resultado;
- criticidad;
- Correlation ID.

## 8.7. Correlation Trace

```text
Solicitud
→ Economía
→ Legal
→ CFO
→ Aprobación humana
→ Ejecución
```

## 8.8. Detalle de evento

Guardar:
- event ID;
- tipo;
- timestamp;
- actor;
- proyecto;
- agente origen;
- resultado;
- criticidad;
- correlation ID;
- origen del evento;
- IP si aplica;
- user agent si aplica.

## 8.9. Antes / Después

Mostrar cambios de estado.

## 8.10. Evidencias

Asociar:
- informes;
- Legal Gate;
- presupuesto;
- solicitud;
- aprobación;
- configuración;
- documentos.

Guardar:
- hash;
- versión;
- timestamp;
- origen;
- estado.

## 8.11. Provenance

Etiquetas:
- dato verificado;
- proveedor;
- estimación AMAZONA;
- usuario humano;
- fuente externa.

## 8.12. Historial de versiones

Registrar cambios de:
- agente;
- modelo;
- prompt/configuración;
- herramientas;
- deploy;
- aprobación.

## 8.13. Vista por proyecto

Expediente forense:
- creación;
- investigación;
- proveedores;
- economía;
- legal;
- tienda;
- marketing;
- aprobaciones;
- operaciones.

## 8.14. Vista por agente

Mostrar:
- runs;
- acciones;
- errores;
- cambios de versión;
- aprobaciones;
- incidencias.

## 8.15. Integridad

Bloque:
- eventos íntegros;
- hashes;
- cadena de hashes;
- última verificación;
- eventos modificados = 0.

No usar blockchain salvo necesidad real.

## 8.16. Retención

Configuración por tipo de evento.

## 8.17. Exportación

- CSV
- JSON
- PDF evidencia
- paquete de auditoría

## 8.18. Audit Package

Por proyecto/período:
- eventos;
- aprobaciones;
- evidencias;
- cambios;
- documentos;
- versiones;
- fuentes;
- hashes.

## 8.19. Anomalías

Detectar:
- precio cambiado sin aprobación;
- acción fuera de política;
- cambios de configuración anómalos;
- proveedor modificado tras aprobación.

## 8.20. Seguridad

Eventos:
- login;
- permisos;
- API keys;
- integraciones;
- owner;
- políticas.

## 8.21. Auditoría IA

Guardar:
- agente;
- versión;
- modelo;
- herramientas;
- fuentes;
- input reference;
- output reference;
- coste;
- duración.

No almacenar razonamiento interno privado.

## 8.22. Audit Health

Score explicable:
- cobertura;
- integridad;
- evidencias;
- trazabilidad;
- retención;
- errores.

## 8.23. Referencias

- AWS CloudTrail
- Drata
- Vanta
- Datadog

---

# 9. Panel — Estado

## 9.1. Propósito

Convertirse en el **System Operations Center**.

Pregunta:
> ¿Está sana la infraestructura que permite que AMAZONA funcione?

## 9.2. Nombre

Menú: **Estado**  
Encabezado: **Estado e infraestructura**

## 9.3. KPIs

- uptime;
- API p95;
- errores 5xx;
- servicios operativos;
- incidentes activos;
- jobs en cola;
- versión desplegada;
- último deploy.

## 9.4. Estados

- Operativo
- Degradado
- Incidencia
- Mantenimiento
- Caído

No depender solo del color.

## 9.5. Service Health

Servicios:
- frontend;
- API;
- Postgres/Supabase;
- Auth;
- Storage;
- Realtime;
- Edge Functions;
- Workers;
- Queue;
- Scheduler/Cron;
- Integraciones externas;
- Email;
- Monitoring;
- Logs;
- Backup;
- CDN;
- DNS;
- Certificates.

Cada servicio:
- estado;
- uptime;
- latencia.

## 9.6. Base de datos

Mostrar:
- CPU;
- memoria;
- conexiones;
- cache hit;
- queries lentas;
- locks;
- storage;
- IOPS.

## 9.7. API Health

- requests/min;
- p50;
- p95;
- p99;
- 2xx;
- 4xx;
- 5xx;
- error budget.

## 9.8. Service Map

Representación 2.5D:
```text
Usuarios
→ Frontend
→ API Gateway
→ Backend
→ Auth / Storage / Postgres / Queue
→ Workers
→ Agents / Integraciones
```

## 9.9. Agent Runtime

Solo infraestructura:
- workers activos;
- workers ocupados;
- jobs ejecutándose;
- jobs pendientes;
- jobs fallidos;
- tiempo de cola.

No duplicar métricas de calidad de agentes.

## 9.10. Queues

Mostrar por cola:
- tasks pendientes;
- dead-letter;
- tarea más antigua.

## 9.11. Scheduler / Cron

Monitorizar:
- actualización mercados;
- proveedores;
- legal;
- forecast;
- competitor scan;
- backup.

## 9.12. Integraciones externas

Ejemplos:
- Stripe;
- Google Ads;
- Meta Ads;
- Amazon SP-API;
- Google Shopping;
- Shipping API;
- OpenAI;
- Supabase.

Mostrar:
- estado;
- latencia;
- rate limits;
- errores.

## 9.13. Rate Limits

Mostrar consumo por proveedor externo y alertas.

## 9.14. Coste técnico

Infraestructura:
- AI inference;
- database;
- storage;
- functions;
- APIs externas.

El CFO recibe el total; el detalle queda aquí.

## 9.15. Logs Explorer

Filtros:
- servicio;
- nivel;
- request;
- correlation ID;
- proyecto;
- tiempo.

Diferencia:
- Logs = diagnóstico técnico.
- Auditoría = trazabilidad empresarial.

## 9.16. Deployments

Guardar:
- versión;
- fecha;
- commit;
- estado;
- cambios.

## 9.17. Migraciones

Mostrar:
- schema actual;
- última migración;
- anteriores;
- pendientes;
- fallidas.

## 9.18. Incidentes

Lista:
- incidente;
- causa;
- impacto;
- duración;
- estado.

Cuando haya incidente activo, cambiar prioridad visual superior.

## 9.19. System Copilot

Preguntas:
- por qué está lenta la API;
- qué servicio falla;
- qué cambió antes del incidente;
- cuánto falta para alcanzar un rate limit.

Mostrar evidencia y correlaciones.

No ejecutar acciones destructivas sin aprobación.

## 9.20. System Health

Score explicable:
- API;
- Database;
- Auth;
- Storage;
- Queues;
- Workers;
- Integrations;
- Security;
- Observability.

## 9.21. Capacidad

Mostrar:
- DB connections;
- storage;
- queue throughput;
- workers;
- API capacity;
- forecast de capacidad.

## 9.22. Security Health

Solo salud técnica:
- failed logins;
- blocked requests;
- auth anomalies;
- secrets;
- certificates;
- dependencies críticas.

## 9.23. Fronteras funcionales

| Panel | Pregunta |
|---|---|
| Agentes | ¿Funcionan correctamente los trabajadores IA? |
| Auditoría | ¿Qué ocurrió y podemos demostrarlo? |
| Estado | ¿Está sana la infraestructura? |

## 9.24. Referencias

- Datadog
- Supabase Observability
- Better Stack
- Grafana-style observability

---

# 10. Arquitectura final de responsabilidad

| Dominio | Panel responsable |
|---|---|
| Orquestación multiagente | Director ejecutivo |
| Descubrimiento y mercado | Investigación |
| Sourcing y proveedores | Proveedores y abastecimiento |
| Rentabilidad producto | Economía y rentabilidad |
| Legal/compliance | Legal y cumplimiento |
| Ecommerce/canales | Tienda y canales de venta |
| Adquisición | Marketing y adquisición |
| Pedidos/fulfillment | Operaciones |
| Finanzas corporativas | Finanzas y control |
| Expediente oportunidad | Proyectos |
| Workforce IA | Agentes |
| Decisión humana | Aprobaciones |
| Registro forense | Auditoría |
| Infraestructura | Estado |

---

# 11. Flujo completo de AMAZONA

```text
Director ejecutivo
      ↓
Investigación
      ↓
Proveedores y abastecimiento
      ↓
Economía y rentabilidad
      ↓
Legal y cumplimiento
      ↓
Tienda y canales de venta
      ↓
Marketing y adquisición
      ↓
Operaciones
      ↓
Resultados reales
      ↓
Aprendizajes
      ↺
```

Capas transversales:
```text
Finanzas y control
Proyectos
Agentes
Aprobaciones
Auditoría
Estado
```

---

# 12. Paneles aprobados en esta segunda fase

1. Operaciones
2. Finanzas y control
3. Proyectos
4. Agentes
5. Aprobaciones
6. Auditoría
7. Estado

---

# 13. Reglas para implementación en Claude Code

## 13.1. No duplicar lógica

- Proyectos resume; no recalcula.
- Finanzas consolida; no sustituye Economía.
- Agentes monitoriza agentes; no sustituye Estado.
- Auditoría registra; no aprueba.
- Aprobaciones decide; no ejecuta análisis.
- Estado monitoriza infraestructura; no contiene métricas comerciales.

## 13.2. Reutilizar componentes

Sugeridos:
```text
KpiCard
StatusChip
RiskBadge
AgentCard
ProjectHealth
FinancialHealth
SystemHealth
AuditHealth
OperationalHealth
DataTable
FilterBar
Timeline
CorrelationTrace
ApprovalDetail
BudgetImpact
ServiceMap
IncidentCard
QueueStatus
VersionCard
EvidenceBadge
DataProvenanceBadge
```

## 13.3. Estados comunes

- Loading
- Empty
- Error
- Simulado
- Real
- Verificado
- Pendiente
- Bloqueado
- Requiere aprobación
- Degradado
- Offline

## 13.4. Acciones sensibles

Requieren confirmación/permisos:
- aprobar gastos;
- desplegar agentes;
- activar campañas;
- publicar canales;
- cambiar precios;
- ejecutar pagos;
- asumir stock;
- cambiar permisos;
- modificar políticas;
- borrar/deshabilitar recursos;
- acciones destructivas de infraestructura.

## 13.5. Trazabilidad

Toda acción material debe generar:
- event ID;
- timestamp;
- actor;
- proyecto;
- correlation ID;
- resultado;
- evidencia asociada;
- before/after cuando aplique.

---

# 14. Estado final

Con esta segunda fase quedan definidos y visualmente aprobados todos los paneles principales de AMAZONA.

La arquitectura final contiene **15 entradas principales de menú**, con **Mercado eliminado como módulo independiente** y sus funciones redistribuidas.

Este documento debe utilizarse junto con:
- `AMAZONA_especificacion_paneles_aprobados_v0.5.md`
- `AMAZONA_cambio_arquitectura_eliminacion_modulo_mercado.md`

para obtener la especificación completa de implementación.

---

## Fin del documento
