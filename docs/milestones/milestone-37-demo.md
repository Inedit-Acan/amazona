# Milestone 37 — Preparar la segunda fuente real sin gastar nada

**Fecha:** 28-09-2026 · **ADR:** [0015](../architecture/adr-0015-multiple-real-sources-cost-and-usage-rights.md)
· **Depende de:** [0008](../architecture/adr-0008-demo-production-isolation.md)
· [0012](../architecture/adr-0012-product-intelligence-adapters.md)
· [0013](../architecture/adr-0013-signal-evidence-and-comparison.md)
· [0014](../architecture/adr-0014-entity-resolution.md)

**Presupuesto: 0 €. Ninguna cuenta creada, ninguna credencial introducida, ningún
servicio contratado.**

El objetivo no era conectar una segunda fuente real: era **dejar que conectarla sea
una decisión reversible, medida y sin gasto ciego**. Formulado como criterio: el día
que exista una credencial, añadir la fuente debe ser escribir un adaptador y cambiar
una variable de entorno — no rediseñar la configuración de proveedores, ni inventar
dónde se cuenta el gasto, ni decidir si el número puede puntuar.

## Lo que se midió y se leyó antes de decidir nada

**El plan maestro §25 exigía el control de coste antes, no después.** Es literal:
«Antes de introducir LLMs o APIs comerciales, añadir: provider, operation, units,
estimated_cost, actual_cost, currency, correlation_id» con límites por agente,
ejecución, día, proveedor y proyecto. No existía nada: `Budget` y `FinancialEvent`
son dinero de negocio, y el único techo era `AILimits.max_cost` del gateway de LLM,
en memoria y sin persistir. La secuencia del §32 no lo programó en ningún milestone.

**Verificado en la documentación oficial de eBay el 28-09-2026** (lectura, sin alta
y sin gasto): `GET /buy/browse/v1/item_summary/search` se autentica con **flujo de
credenciales de cliente** —no hace falta cuenta de vendedor—, su respuesta trae
`"total": 260202` para `q=drone`, acepta búsqueda por texto, **GTIN** o ePID, elige
mercado por cabecera `X-EBAY-C-MARKETPLACE-ID`, **tiene entorno de pruebas** en
`api.sandbox.ebay.com`, y su cuota por defecto son **5.000 llamadas al día**,
ampliables con una revisión gratuita.

**Y apareció lo que no estaba previsto**, en el texto de su licencia:

> «**Restricted APIs**» refers to any eBay APIs that provide information about
> market trends, pricing strategies, sales volumes, user behavior…

Para esas, el contrato prohíbe expresamente alimentar IA ajena sin consentimiento
escrito, redistribuir en bruto o agregado, y usarlas «to develop pricing tools» sin
consentimiento previo. Es decir: **una licencia puede restringir qué se puede hacer
con el número, no solo si se puede guardar.** Eso cambió el alcance del milestone.

**Wikimedia sí quedó resuelta**: su propia especificación declara CC-BY-SA 3.0 y
GFDL salvo indicación del endpoint, exige `User-Agent` identificable —el adaptador ya
lo pone— y pide no pasar de 200 peticiones por segundo.

## Qué cambia

### Tres bases de señal, donde antes había un booleano

`MEASURED` (la fuente lo observó) · `ESTIMATED` (lo modeló) · `SIMULATED` (un
fixture). Con techo de confianza por base —1,0 / 0,6 / 0,4— que **falla al construir
la señal** si se excede, en vez de recortarse en silencio. Y con orden de
preferencia: lo medido gana a lo estimado, y lo estimado a lo inventado.

Los números están razonados: 0,6 queda por debajo del 0,75 que es el techo del único
adaptador que mide de verdad, y 0,4 por encima del 0,3 que emiten los fixtures, así
que **ninguna cifra existente cambia**.

La columna `simulated` **se elimina**: dos fuentes de verdad para lo mismo es el
problema que el Milestone 34 vino a arreglar. `Signal.simulated` sobrevive como
propiedad derivada.

### Un libro de costes, con default-deny

`external_api_costs` con los siete campos del §25 más `unit`, `outcome` y
`denied_reason`. **Una denegación deja fila igual que un permiso**: es lo que explica
por qué una investigación volvió sin señales. `actual_cost` nulable, y **nulo no es
cero**.

Función pura `evaluate_api_call` —al estilo de `evaluate_action`— y un contador que
se **inyecta** desde quien tiene sesión y `correlation_id`. Un proveedor de pago sin
límite autorizado **no se llama**; un proveedor sin política escrita se trata como de
pago. Y **gratis no es sin límite**: las cuotas se respetan aunque el precio sea cero.

Separado del ActionGate a propósito: aquello gobierna publicar, anunciar y gastar del
negocio; esto es infraestructura con sus propias ventanas.

### Qué significa `real` con varias fuentes reales

Una lista **ordenada** de nombres de adaptador. Una sola fuente se usa directamente;
varias se componen **entre reales**, y el resultado **no es simulado**, así que sirve
donde los fixtures están prohibidos. Una fuente inexistente o una lista vacía abortan
el arranque. Y cada adaptador tiene su configuración en **su propio espacio de
nombres** (`WIKIMEDIA__MONTHS`, `EBAY__CLIENT_ID`).

### Una matriz de derechos de uso por proveedor

Ocho permisos —almacenamiento, retención, transformación, métricas derivadas,
scoring, IA/LLM, redistribución, uso comercial— más la atribución, que va aparte
porque es un deber y no un permiso. **`UNKNOWN` se comporta como `DENIED`**: no se
infiere un permiso del silencio de un contrato.

Y **se aplica**, no solo se documenta: una señal cuya licencia no permite puntuar no
entra en el score y se dice **quién** la retuvo; una cuya licencia no permite
almacenar no se persiste y la auditoría cuenta cuántas quedaron fuera.

### eBay Browse, implementado y sin usar

30 tests offline. Es la primera señal de **competencia medida** del sistema, que era
el único hueco que impedía puntuar. **Y sus datos no se usan**: casi toda su fila está
en `UNKNOWN`, así que sus señales se leen y no se guardan ni puntúan. No es un defecto
del adaptador: es la regla funcionando.

### `ProviderKind.SANDBOX` deja de ser una casilla vacía

Resuelve a los mismos adaptadores apuntando a su host de pruebas. Con un test que
comprueba que **nunca** resuelve al host de producción.

### Y la pantalla lo dice

Estado gana una tarjeta de **proveedores externos y consumo**: quién responde en
Product Intelligence —la lista en orden, no «real» a secas—, cuánta cuota se lleva
hoy, lo estimado, lo que el proveedor ha cobrado de verdad o que no lo ha dicho, lo
autorizado o que no hay autorización, y las denegaciones con su motivo. Si la
petición falla **no se rellena con demostración**: un gasto inventado es peor que un
gasto desconocido.

Investigación distingue ahora tres procedencias en vez de dos, y dice cuándo un
candidato no tiene score **porque una licencia no lo permite** — no porque falte el
dato.

## Lo que NO cambia, a propósito

- **`opportunity_score` intacto** (plan maestro §9) y la fórmula v2 sin empezar.
- **`SignalKind.PRICE` no se añade**, aunque eBay traiga precios: `Signal.value` está
  normalizado a 0-1, un precio necesita moneda —multicanal es multimoneda—, y nada lo
  consume hasta el §9. El adaptador **dice en su cabecera qué decide no emitir y por
  qué**, para que no desaparezca sin dejar rastro.
- **La tabla de identificadores externos no se construye**: el diseño queda en la ADR
  (atributos con espacio de nombres, nunca sustituyendo `identity_key`), y nada la
  consume todavía.
- **El mock sigue entero** con sus mismas cifras.
- **Ausencia sigue siendo ausencia.** Ni ceros, ni medias, ni imputaciones.
- **Redis, los otros cuatro dominios y la caducidad de `WAITING_APPROVAL`** siguen
  fuera de alcance.

## Límites que hay que tener presentes

1. **`UNKNOWN` = denegado tiene un coste real.** Configurar eBay hoy produce señales
   que no se guardan ni puntúan. Es deliberado, y a quien no lea la ADR le puede
   parecer una avería: por eso la denegación se anota y la pantalla la nombra.
2. **`AI_INGESTION` está sin resolver para las dos fuentes reales.** Cualquier trabajo
   del §26 sobre estas señales arranca bloqueado.
3. **La matriz envejece.** Una licencia cambia y lo único que avisa es la fecha de la
   entrada. No hay comprobación automática de vigencia.
4. **No hay humo real de eBay.** Sus tests usan respuestas grabadas de su
   documentación publicada, que no es lo mismo que sus respuestas reales.
5. **El techo de confianza de `ESTIMATED` es un número declarado**, no medido.
6. **Bajar la migración pierde la distinción entre medido y estimado**, porque en el
   esquema viejo no cabe. Es el motivo del milestone, no un defecto.

## Probarlo

```bash
cd backend && alembic upgrade head
```

```bash
curl -s localhost:8000/api/costs/api-usage | python -m json.tool
```

```bash
curl -X POST localhost:8000/api/research/runs -H 'Content-Type: application/json' -d '{"category":"home","max_results":3}'
```

## Verificación

- Backend: `ruff` y `mypy` limpios · **1381 tests** (1257 antes, +124).
- Frontend: `tsc` y `eslint` limpios · **312 tests** (293 antes, +19).
- `next build --webpack` en una copia, sin tocar el `.next` de desarrollo.
- **Dos migraciones nuevas, arriba y abajo con datos dentro**: ver abajo.
- **Los tests de inventario del Milestone 29 hicieron su trabajo**: la ruta nueva
  falló hasta darle su categoría de lectura (diagnóstico, la misma que
  `/health/detailed`).
- **30 tests offline del adaptador de eBay**, cubriendo lo que el plan maestro §31
  exige de un adaptador real: 404, 429, 500, 503, cuerpo no-JSON, forma inesperada,
  **timeout**, **límite de ritmo**, tope de peticiones y cuota agotada. Todos acaban
  igual: **sin señal, nunca un cero**.
- **Humos que se pueden hacer sin credenciales ni gasto**: Wikimedia contra la fuente
  real siguió midiendo con el contador de costes puesto; el libro de costes registró
  permisos y denegaciones; la matriz de derechos retuvo señales de un proveedor sin
  licencia leída.

## No verificado

- **El recorrido real contra eBay**: necesita el keyset gratuito, y además está
  bloqueado por decisión propia hasta resolver la licencia.
- **La tarjeta nueva de Estado no se ha visto en un navegador** con datos dentro. Su
  lógica está cubierta por tests de `lib` y del endpoint; el render a ojo, no.
- **`AI_INGESTION` de Wikimedia**: CC-BY-SA no lo aborda.
- **Los cinco pendientes de integración** siguen igual
  ([system-overview §20](../architecture/system-overview.md#20-pendientes-de-integración)).
- **La incidencia del test intermitente del Milestone 35** no ha reaparecido en
  ninguna pasada de este milestone. Sigue sin explicación y sigue anotada.

## Lo que queda abierto

1. **Resolver si Browse es «Restricted API»** y qué usos permite exactamente. Es lo
   que desbloquea la competencia medida.
2. **El keyset gratuito de desarrollador de eBay** (0 €), que solo puede dar de alta
   el propietario.
3. **La segunda fuente real de verdad en uso**: hasta entonces un candidato real sigue
   sin score.
4. **`SignalKind.PRICE`** con su unidad, moneda, mercado y semántica, cuando un
   milestone funcional lo necesite.
5. **La tabla de identificadores externos**, cuando entre una fuente con id propio.
6. **`opportunity_score` v2** del §9.
7. **Discovery real**, los otros cuatro dominios, la caducidad de `WAITING_APPROVAL` y
   la limpieza de Redis.
