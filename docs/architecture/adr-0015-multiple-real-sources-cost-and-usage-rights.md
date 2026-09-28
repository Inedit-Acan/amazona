# ADR 0015: Varias fuentes reales, el coste de llamarlas y qué se puede hacer con lo que devuelven

- **Estado:** Aceptada
- **Fecha:** 2026-09-28
- **Depende de:** [ADR 0003](adr-0003-rls-deny-by-default.md), [ADR 0008](adr-0008-demo-production-isolation.md), [ADR 0009](adr-0009-async-job-runtime.md), [ADR 0012](adr-0012-product-intelligence-adapters.md), [ADR 0013](adr-0013-signal-evidence-and-comparison.md), [ADR 0014](adr-0014-entity-resolution.md)
- **Milestone:** 37

## Contexto

La [ADR 0014 §7](adr-0014-entity-resolution.md) dejó **explícitamente sin decidir**
qué significa `real` cuando hay más de una fuente real, y lo remitió «al milestone
que traiga la fuente». Este es ese milestone, y al abrirlo aparecieron tres cosas
más que había que decidir antes de conectar nada.

**Primera: el plan maestro §25 lo exige antes, no después.** Es literal: «Antes de
introducir LLMs o APIs comerciales, añadir: provider, operation, units,
estimated_cost, actual_cost, currency, correlation_id» con límites «per agent, per
run, per day, per provider, per project». No existía nada de eso. `Budget`,
`BudgetAllocation` y `FinancialEvent` son dinero de negocio —campañas, coste de
aterrizaje—, no coste de API; el único techo era `AILimits.max_cost` del gateway de
LLM, en memoria, por llamada y sin persistir. La secuencia recomendada del §32 va
del 29 al 35 y no lo programó en ninguno.

**Segunda: `simulated` era un booleano y hay tres cosas que distinguir.** Una
fuente que **observa** un número y una que lo **modela** con un método propio —a
veces sin decir cuál— no valen lo mismo, y las dos vienen del mundo. Con un
booleano, una estimación propietaria entraba en la base de datos indistinguible de
una medición: exactamente el problema que el Milestone 34 resolvió para los
fixtures, repetido un nivel más arriba.

**Tercera, y la que no estaba prevista: tener el dato no es tener permiso.** Al
leer la licencia de eBay apareció una cláusula que cambia el planteamiento:

> «**Restricted APIs**» refers to any eBay APIs that provide information about
> market trends, pricing strategies, sales volumes, user behavior… Access is
> specially granted to select Developers.

Y para esas APIs prohíbe expresamente incorporar la información a «any artificial
intelligence model, system, or tool… not provided by or licensed from eBay» sin
consentimiento escrito, redistribuirla en bruto o agregada, y usarla «to develop
pricing tools» sin consentimiento expreso previo. Es decir: **una licencia puede
restringir qué se puede hacer con el número, no solo si se puede guardar.** El plan
maestro §26 prevé LLM para síntesis de investigación y KOVA prevé precios; las dos
cosas chocarían con una licencia así.

## Decisión

### 1. `real` con varias fuentes reales es un compuesto **entre reales**

`PRODUCT_INTELLIGENCE_REAL_SOURCES` es una **lista ordenada de nombres de
adaptador**. Con una sola fuente se usa directamente. Con varias se componen con la
misma regla del Milestone 34 —el primero que da una señal de un tipo manda, los
siguientes rellenan lo que falte, nada se promedia ([ADR 0012 §6](adr-0012-product-intelligence-adapters.md))—
pero **sin fixtures de por medio**, así que el resultado **no es simulado** y sirve
donde los datos simulados están prohibidos ([ADR 0008 §4](adr-0008-demo-production-isolation.md)).

`COMPOSITE` sigue significando lo que significaba: puede servir fixtures, y por
tanto cuenta como simulado.

Que las fuentes sean **un diccionario de nombre → constructor** y no una cadena de
condicionales es lo que hace reversible la elección de proveedor: añadir uno es
añadir una entrada, quitarlo es quitarla, y nada por encima sabe cuántos hay. Una
fuente configurada que no existe, o una lista vacía, **abortan el arranque** — el
mismo criterio que `ProviderNotAvailableError` (ADR 0008 §3): un proveedor real sin
fuentes no contestaría nada, y eso se leería como una medición de que no hay nada.

Y la configuración de cada adaptador vive en **su propio espacio de nombres**
(`WIKIMEDIA__MONTHS`, `EBAY__CLIENT_ID`). Con un solo proveedor, tres campos
sueltos en el objeto global eran tolerables; con dos se convierte en un cajón donde
no se sabe qué ajuste es de quién.

### 2. Tres bases de señal, y una estimación no puede fingir ser una medición

`SignalBasis` sustituye al booleano `simulated`:

- **`MEASURED`**: la fuente lo observó y lo reporta.
- **`ESTIMATED`**: la fuente lo derivó. Viene del mundo y **no es una observación**.
- **`SIMULATED`**: un fixture. No viene del mundo en absoluto.

Tres consecuencias, y ninguna es cosmética:

**Techo de confianza por base**, comprobado al construir la señal: `MEASURED` 1,0 ·
`ESTIMATED` 0,6 · `SIMULATED` 0,4. Los números están razonados: 0,6 queda por
debajo del 0,75 que es el techo del único adaptador que mide de verdad, así que un
número modelado **nunca adelanta por confianza a uno observado**; y 0,4 queda por
encima del 0,3 que emiten los fixtures, así que no cambia ninguna cifra existente.
Exceder el techo **lanza una excepción** en vez de recortarse en silencio: un
recorte callado es la clase de arreglo que esconde el problema, y falla en los tests
de quien escriba el adaptador en vez de en producción.

**Orden de preferencia**: lo medido antes que lo estimado, y lo estimado antes que
lo inventado. Antes competían solo por confianza, así que una estimación optimista
podía ganarle a una medición prudente.

**La columna vieja se elimina.** Dos fuentes de verdad para lo mismo es el problema
que el Milestone 34 vino a arreglar, y dejar `simulated` junto a `basis` lo
reintroduciría con otro nombre. `Signal.simulated` sobrevive como **propiedad
derivada**, porque media aplicación pregunta así.

### 3. Un libro de costes propio, separado del ActionGate

Los siete campos del §25 más tres que hacen que los siete signifiquen algo: `unit`
(qué se cuenta: «8 unidades» sin decir de qué no es un dato), `outcome` y
`denied_reason`. **Una denegación deja fila igual que un permiso**: es lo que
explica por qué una investigación volvió sin señales, y sin ella el sistema
parecería averiado en vez de prudente. `actual_cost` es nulable y **nulo no es
cero**: es que el proveedor todavía no ha dicho lo que cobró.

En filas y no en un contador agregado, por el mismo motivo que los pasos del
pipeline (M32) y las observaciones (M35): se puede preguntar «¿qué gastó esta
ejecución?» y «¿cuánto llevamos hoy con este proveedor?».

**Separado del ActionGate a propósito.** El ActionGate gobierna publicar, anunciar
y gastar dinero del negocio, con vetos que ninguna firma humana levanta
([ADR 0011](adr-0011-action-gate.md)). El coste de API es otra cosa: no es una
acción de negocio, es infraestructura, y tiene sus propias ventanas —por ejecución,
por día, por proveedor—. Mezclarlos habría metido una cuota de API en la misma
puerta que una campaña publicitaria. Los dos los leerá el CFO más adelante.

**Y default-deny donde importa**: un proveedor con coste por unidad mayor que cero
y **sin límite de gasto autorizado no se llama**. El presupuesto no se hereda de
ninguna parte y en este fichero no hay ningún techo futuro escrito: los límites
viven en configuración porque son dinero del propietario. Un proveedor sin política
de coste escrita se trata como **de pago**, que es la lectura conservadora.

**Gratis no es lo mismo que sin límite.** Una fuente gratuita también se agota:
eBay publica 5.000 llamadas al día, Wikimedia pide no pasar de 200 por segundo. Así
que una política declara dos cosas distintas —cuánto cuesta y cuánto se puede
pedir— y la segunda existe aunque la primera sea cero.

El contador **se inyecta** desde quien tiene sesión y `correlation_id` —el servicio,
no el agente—, porque un gasto sin ejecución a la que atribuirlo no se puede
auditar. Y cuando no cabe la llamada, quien la recibe **no produce señal**: una
señal ausente se queda ausente, nunca se convierte en un cero (ADR 0012 §4).

### 4. Los derechos de uso se declaran por proveedor, y lo que no se sabe no se permite

Ocho permisos, cada uno `ALLOWED`, `DENIED` o `UNKNOWN`, **y `UNKNOWN` se comporta
como `DENIED`**: almacenamiento, retención, transformación, métricas derivadas,
scoring/algoritmos, uso con IA/LLM, redistribución o exposición al usuario, y uso
comercial. Más la **atribución**, que va aparte porque no es un permiso sino un
deber: ahí lo conservador no es abstenerse, es citar, y por eso `UNKNOWN` se trata
como «obligatoria».

No se infiere un permiso del silencio de un contrato. Que una licencia no prohíba
algo expresamente no es lo mismo que autorizarlo, y la diferencia la paga el
propietario. Es la misma familia de decisiones que «una señal ausente se queda
ausente»: ante la falta de información, el sistema no rellena con lo que le conviene.

`UNKNOWN` y `DENIED` pesan igual para actuar y **no para resolver**: uno está
cerrado, el otro está por leer. Cada entrada lleva **dónde se leyó y cuándo**,
porque una matriz sin fuente y sin fecha es una opinión. Un adaptador real sin
entrada en la matriz hace fallar un test: no puede entrar un proveedor sin que
alguien haya leído su licencia.

**Esto no es asesoramiento legal y no pretende serlo.** Es un registro de lo leído,
para que una duda sea visible en el código en vez de vivir en la cabeza de quien
escribió el adaptador. Resolver un `UNKNOWN` es trabajo humano: leer el contrato, o
preguntarle al proveedor.

#### La matriz, hoy

| Uso | `fixtures` | `wikimedia-pageviews` | `ebay-browse` |
|---|---|---|---|
| Almacenamiento | ✅ | ✅ | ❓ |
| Retención indefinida | ✅ | ✅ | ❓ |
| Transformación | ✅ | ✅ | ❓ |
| Métricas derivadas | ✅ | ✅ | ❓ |
| **Scoring / algoritmos** | ✅ | ✅ | ❓ |
| **Uso con IA / LLM** | ✅ | ❓ | ❓ |
| Redistribución / exposición | ✅ | ✅ | ⛔ |
| Uso comercial | ✅ | ✅ | ❓ |
| **Atribución** | No hace falta | **Obligatoria** | ❓ → se atribuye |

✅ permitido · ⛔ denegado · ❓ sin resolver, y por tanto **denegado**

- **`fixtures`**: el dato es nuestro, en un fichero del repositorio; no hay tercero
  a quien pedir permiso. Lo que impide que contamine una decisión es su base
  `SIMULATED`, no su licencia. Son dos preguntas distintas: «¿puedo usar esto
  legalmente?» y «¿esto es verdad?».
- **`wikimedia-pageviews`**: verificado el 28-09-2026 en la propia especificación de
  la API, que declara CC-BY-SA 3.0 y GFDL salvo que el endpoint diga otra cosa.
  CC-BY-SA permite copiar, conservar, adaptar y usar comercialmente citando la
  fuente, de ahí los permisos. **`AI_INGESTION` queda sin resolver**: la licencia no
  lo aborda, y no decir nada no es autorizar. Afecta al plan maestro §26.
- **`ebay-browse`**: ver §5.

#### Dónde se aplica, hoy

- **`SCORING`**: una señal cuyo proveedor no lo permite **no entra en el score**, y
  el candidato dice **quién** la retuvo (`scoring_withheld_from`). Un score ausente
  sin explicación es indistinguible de una avería.
- **`STORAGE`**: una señal cuyo proveedor no lo permite **no se persiste**, y la
  auditoría cuenta cuántas se quedaron fuera y de quién. Un dato que desaparece sin
  dejar rastro es peor que un dato que falta.
- **Uso interno no es redistribución.** Enseñar un número en el Control Center del
  propietario no es exponerlo a un tercero, y se dice aquí para que la distinción
  no se improvise más adelante.
- **`AI_INGESTION`** no tiene punto de aplicación todavía porque no hay LLM en el
  camino de las señales. La función existe y está escrita para que el trabajo del
  §26 tenga que llamarla.

### 5. eBay Browse entra como adaptador de referencia, y sus datos no se usan

Se eligió porque es el único candidato verificado que cumple a la vez las cinco
condiciones que importaban: **gratuito** con un keyset de desarrollador —sin cuenta
de vendedor: usa el flujo de credenciales de cliente—, con **entorno de pruebas
propio**, **multicanal** por cabecera de mercado, y **mide** en vez de estimar: su
respuesta trae `total`, el recuento de anuncios activos para una consulta. Es la
primera señal de competencia medida del sistema, y la competencia era el único hueco
que impedía puntuar.

**Es de referencia y no definitivo**, y la arquitectura queda agnóstica: el
contrato, el registro y la lista de fuentes no lo mencionan.

**Y sus datos no se usan.** Casi toda su fila de la matriz está en `UNKNOWN` porque
no se ha podido determinar si Browse entra en las «Restricted APIs»: se obtiene con
un keyset estándar, lo que apunta a que no; devuelve recuentos y precios pedidos, lo
que apunta a que quizá sí. Mientras siga así, sus señales **se leen y no se guardan
ni puntúan**. No es un defecto del adaptador: es la regla del §4 funcionando.

Dos cláusulas más, verificadas, que conviene tener escritas: eBay «shall own any
content created or derived therefrom», de modo que las métricas derivadas serían
contenido suyo; y su obligación de borrar información personal **pronto**, que es
por lo que este sistema guarda una **referencia y unas cifras, nunca el cuerpo de la
respuesta** — los resultados de Browse incluyen nombres de vendedor, y un payload
entero metería datos personales en una tabla de métricas. La ADR 0013 §4 dice
«se persiste el valor crudo de la fuente»; esto lo precisa: el valor crudo **es la
cifra**, no el sobre en que venía.

### 6. `ProviderKind.SANDBOX` deja de ser una casilla vacía

Existía en el enum desde la ADR 0008 sin nada detrás. Ahora resuelve a los mismos
adaptadores apuntando a su host de pruebas, lo que hace por fin posibles los
«sandbox integration tests» que el plan maestro §31 pide para todo adaptador real. Y
hay un test que comprueba que la configuración de sandbox **nunca** resuelve al host
de producción.

### 7. Los identificadores externos son atributos, y todavía no se construyen

ASIN, GTIN, ePID, id de anuncio y equivalentes serán **atributos del candidato**,
en su propia tabla, con su espacio de nombres y su proveedor. **Nunca** sustituyen
la `identity_key` del Milestone 36: la identidad sigue siendo el nombre resuelto de
forma determinista o declarada ([ADR 0014](adr-0014-entity-resolution.md)).

Es lo que hace reversible la elección de proveedor. Si un adaptador con id propio
—Amazon y su ASIN— entrara en el núcleo de la identidad y luego se abandonara,
quedaría la complejidad sin la fuente.

**La tabla no se construye en este milestone**: nada la consume, y crearla ahora
sería infraestructura por la infraestructura, el mismo motivo por el que la
[ADR 0008 §1](adr-0008-demo-production-isolation.md) no creó los cinco paquetes de
dominio antes de tiempo. Queda el diseño acordado para quien traiga esa fuente.

## Consecuencias

**A favor**

- El día que haya credencial, añadir una fuente es escribir un adaptador y cambiar
  configuración: no hay que decidir qué significa `real`, ni dónde va el gasto, ni
  si el número puede puntuar.
- Ninguna llamada externa del camino real ocurre sin quedar anotada, y ninguna de
  pago ocurre sin autorización explícita.
- De la base de datos se puede responder «¿esto se observó, se modeló o se
  inventó?» — tres respuestas donde antes había dos.
- El plan maestro §25 pasa de estar sin empezar a estar cumplido, y era prerrequisito
  también del §26.
- La pregunta «¿puedo hacer *esto* con el dato de *ese* proveedor?» tiene una
  respuesta en el código, con su fuente y su fecha.

**En contra**

- **Eliminar `simulated` es destructivo.** Probado ida y vuelta con datos; al bajar
  se pierde la distinción entre medido y estimado, porque en el esquema viejo no
  cabe. Es el motivo del milestone, no un defecto de la migración.
- **La matriz de derechos es trabajo manual** y envejece: una licencia cambia y la
  fecha de la entrada es lo único que avisa. No hay ninguna comprobación automática
  de que siga vigente.
- **`UNKNOWN` = denegado tiene un coste real**: configurar eBay hoy produciría
  señales que no se guardan ni puntúan. Es deliberado y puede parecer una avería a
  quien no lea esta ADR; por eso la denegación se anota y la pantalla la nombra.
- **`AI_INGESTION` está sin resolver para las dos fuentes reales**, así que cualquier
  trabajo del §26 sobre estas señales arranca bloqueado.
- **No hay humo real de eBay.** Su adaptador está probado con respuestas grabadas de
  su documentación publicada, que no es lo mismo que sus respuestas reales.
- **`ProviderBinding.name` sigue siendo el nombre de la clase** aunque haya varias
  fuentes; quien quiera la lista mira `sources`. Dos campos para una pregunta
  parecida.
- **El techo de confianza de `ESTIMATED` es un número declarado**, no medido. Está
  razonado y sigue siendo una elección.

## Alternativas descartadas

- **Añadir `SignalKind.PRICE` porque eBay trae precios.** `Signal.value` está
  normalizado a 0-1 y un precio no lo es; hacerlo bien exige una dimensión de moneda
  —multicanal es multimoneda— que es bastante más que «mínimo». Y nada lo consume
  hasta la fórmula v2 del §9. El adaptador **dice en su cabecera qué decide no
  emitir y por qué**, para que no desaparezca sin dejar rastro como los once meses
  que el M35 corrigió.
- **Meter el gasto de API en el ActionGate.** Habría puesto una cuota de API en la
  misma puerta que una campaña publicitaria.
- **Conservar `simulated` junto a `basis`.** Dos fuentes de verdad para lo mismo.
- **Recortar la confianza en silencio** al exceder el techo, en vez de fallar. Un
  adaptador mal escrito habría seguido publicando números con la confianza de otro.
- **Presumir que lo que una licencia no prohíbe está permitido.** Es la decisión
  contraria a la del §4, y la que convierte un `UNKNOWN` en un problema de otro.
- **Escribir un presupuesto por defecto** para que eBay «funcione sin configurar
  nada». El presupuesto es del propietario.
- **Construir ya la tabla de identificadores externos.** Nada la consume.
