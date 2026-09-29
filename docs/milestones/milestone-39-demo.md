# Milestone 39 — Supplier Intelligence real

**Fecha:** 29-09-2026 · **ADR:** [0017](../architecture/adr-0017-supplier-facts-and-risk.md)
· **Depende de:** [0008](../architecture/adr-0008-demo-production-isolation.md)
· [0014](../architecture/adr-0014-entity-resolution.md)
· [0015](../architecture/adr-0015-multiple-real-sources-cost-and-usage-rights.md)

**Presupuesto: 0 €. Ninguna cuenta nueva, ninguna credencial, ningún servicio de
pago, ninguna llamada externa nueva.**

Supplier Intelligence era el único dominio P1 que quedaba cuya fuente real puede ser
el propietario a coste cero: un precio de proveedor negociado se introduce a mano, un
volumen de búsqueda comercial no. Y sin coste de aterrizaje real nada aguas abajo es
real — el margen, el techo de CAC y el `opportunity_score` v2 se calculan sobre él.

## Lo que se encontró al revisar

- `Supplier.verified: bool` y `SupplierQuote.verified: bool` eran **booleanos**,
  cuando el plan §10 exige cuatro niveles y dice «No marcar un proveedor como
  "verified" sin explicar qué significa».
- `Supplier.reliability_score: float = 0.0`: una fiabilidad desconocida era
  indistinguible de una nula.
- `SupplierQuote` **no tenía moneda**. Ni Incoterm, ni condiciones de pago, ni mercado
  de destino, ni vigencia.
- El puerto estaba en fase pre-M34: `get_suppliers(category, max_results) -> list[dict]`.
- **Faltaba entero el §16.** Las ocho capacidades las enseñaba la pantalla desde
  `lib/demo/sourcing.ts`, generadas con una semilla determinista.

## Qué cambia

### Cada hecho dice quién lo sostiene

`SupplierFactProvenance`: `third_party_verified`, `supplier_claim`,
`amazona_estimate`, `simulated`, `unknown`. Los dos booleanos desaparecen.

`unknown` **no se guarda**: es lo que contesta el sistema cuando no hay declaración.
Y `third_party_verified` **falla al construirse** sin emisor — en el dominio, no en la
pantalla, igual que el techo de confianza del Milestone 37.

La procedencia de la **empresa** y la de su **tarifa** son hechos distintos, y la del
coste logístico va aparte de las dos: el precio puede venir del proveedor y el
transporte de un estimador nuestro.

### Una cotización con condiciones comerciales, y lo que falta falta

Moneda, unidad y cantidad cotizadas, MOQ, Incoterm (los once de 2020, cerrados),
condiciones de pago, preparación separada de transporte, modo de transporte, coste
logístico, mercado de destino y vigencia. **Todo nulable**: cinco columnas que eran
`NOT NULL` dejan de serlo, porque un Incoterm por defecto sería una condición pactada
que nadie pactó.

### No se convierte entre monedas, y se dice

Un precio sin moneda se rechaza. Economics añade el aviso al análisis cuando el coste
no está en la moneda contable, en vez de fallar o de callarse. Y el desglose de coste
de aterrizaje del panel **no se calcula** cuando el precio está en otra moneda que el
resto de renglones.

### Las ocho capacidades del §16, declaradas

Enum cerrado y tabla `supplier_capabilities`: qué, si la soporta, quién lo dice, desde
cuándo, y una nota. Por proveedor o **por producto**. Sin fila, la respuesta es
`unknown`, nunca `false`. Una declaración nueva no borra la anterior.

### Identidad de proveedor (la regla del M36 aplicada a empresas)

Nombre normalizado + dónde está. `fold` se movió a `app/core/text.py` para no tener
dos copias que divergen. Un país y una región **no se funden solos**.

### Riesgo por dimensiones (§11), sin puntuación total

Ocho dimensiones, cada una con nivel, motivo y los hechos que miró. Cuarto nivel:
`unknown`. `SupplierRiskProfile` no tiene `score` ni `overall`, y hay un test que lo
comprueba. Se calcula al leer y no se guarda.

### Entrada manual permanente

Tres rutas nuevas bajo `SUPPLIER_WRITE` (OWNER, ADMIN, OPERATOR; **`SYSTEM` no**), y
un formulario en el panel de Proveedores donde casi nada es obligatorio y las
capacidades tienen **tres estados**: sin contestar → sí → no. Una casilla que manda
«no» por omisión inventa siete respuestas por proveedor.

## Qué es real y qué de demostración

| Real | De demostración |
|---|---|
| Proveedores, cotizaciones y capacidades introducidos a mano, con su procedencia | Los ocho proveedores del mock (`simulated`, y lo dicen) |
| La identidad de proveedor y su reutilización entre fuentes | El coste logístico estimado (`amazona_estimate`, factores inventados) |
| Las ocho dimensiones de riesgo, derivadas de hechos guardados | Ciudad, certificaciones, calidad, compliance, escalabilidad y plazos del perfil de pantalla |
| El rechazo de un precio sin moneda, de un Incoterm inexistente y de un «verificado» sin emisor | Los renglones de fulfillment, pasarela y devoluciones del desglose |

**Las cifras del mock no han cambiado**: los mismos ocho proveedores, los mismos
precios, MOQ y plazos que antes de la ADR 0017. Hay un test que lo fija escribiendo
los números a mano, porque comparar el fixture consigo mismo no comprueba nada.

Lo que sí cambia del mock es que ahora **dice que es un fixture**, y que el agente
**no recomienda GO sobre fixtures**: con el mock activo la recomendación es siempre
`REVIEW`.

## Migración

`c7d2f4a90b13_supplier_intelligence` (revisión 30, cabeza única). Diez columnas
nuevas en `suppliers`, trece en `supplier_quotes`, cinco que dejan de ser `NOT NULL`,
tres que se van, y la tabla `supplier_capabilities`.

**Qué se rellena:** `verification = 'simulated'` en todos los proveedores y
`provenance = 'simulated'` en todas las cotizaciones —no depende del booleano
anterior: el único proveedor que el dominio SUPPLIERS ha tenido nunca es el mock—,
`logistics_provenance = 'amazona_estimate'` donde hay coste, y `identity_key` en todos
los proveedores existentes (sin ese relleno, el primer sourcing posterior habría
duplicado cada uno).

**Qué no se rellena:** la moneda y el mercado de destino. Nadie dijo nunca en qué
moneda estaban esos precios ni hasta dónde llegaba ese coste. Y `reliability_score = 0`
pasa a `NULL`: ningún valor del fixture es cero, así que un cero solo puede venir del
`default=0.0`.

**Bajar cuesta información**, y hay un test que lo dice: el esquema anterior no sabe
representar «no se sabe», así que todo lo desconocido vuelve a valer cero.

## Verificación

- **Backend**: `ruff check .`, `mypy app` (195 ficheros) y `pytest` — **1 605 tests en
  verde** (eran 1 463).
- **Frontend**: `npx tsc --noEmit`, `npm test` — **356 tests en verde** (eran 328) —
  y `npx eslint .` sin avisos.
- **Build**: `next build --webpack` sobre una copia en `F:\amz-build-tmp` con
  `node_modules` por junction, sin tocar el `.next` del propietario. Comprobado
  después: 513 entradas en `node_modules` y `.next` intactos.
- **Migración**: arriba y abajo, con datos dentro, sobre el esquema congelado del
  Milestone 38 (`tests/unit/test_migration_supplier_intelligence.py`, 14 tests). La
  cadena completa la cubre CI sobre PostgreSQL.
- **Prueba de humo real** sobre SQLite, nunca contra `backend/.env`: sourcing sobre el
  mock, alta manual de un proveedor real con su cotización y dos capacidades,
  reutilización de la ficha al escribir mal el nombre, las ocho capacidades, las ocho
  dimensiones de riesgo, y los dos rechazos (precio sin moneda, verificación sin
  emisor).
- **Inspección visual en navegador**, la que quedaba pendiente de dos milestones:
  - **M37** — la tarjeta «Proveedores externos y consumo» de Estado: los cuatro
    proveedores con su cuota, su coste estimado y «sin gasto autorizado (no hace
    falta: es gratuito)». ✔
  - **M38** — la nota de canal en Investigación: «Puntuado sin canal (agnóstico)». ✔
  - **M39** — Proveedores: precios con su moneda, «Sin nota (6/7)» en el proveedor sin
    fiabilidad declarada, las ocho dimensiones de riesgo con su motivo, las ocho
    capacidades como «Nadie lo ha declarado», y el desglose de coste negándose a
    mezclar dólares con euros. Se dio de alta un proveedor **desde el formulario del
    navegador** y se comprobó en la base que llegó con su identidad, su moneda y su
    capacidad declarada. ✔

Las capturas no se pudieron tomar (el panel del navegador arranca con viewport 0×0 y
congela el repintado cuando está oculto); la inspección se hizo leyendo el DOM, que es
lo que esa limitación recomienda.

## Lo que NO cambia

- **`opportunity_score` no se toca.** §9 queda fuera de este milestone.
- **`SEARCH_DEMAND` y `MARKETPLACE_DEMAND` siguen sin emisor.**
- **§12 Legal Intelligence queda fuera**, con milestone propio.
- **El mock no se elimina** y da exactamente las mismas cifras.
- Ninguna llamada externa nueva: el contador del Milestone 37 marca lo mismo.

## Limitaciones que este milestone deja en pie

1. **No hay fuente de tipos de cambio.** Dos cotizaciones en monedas distintas no se
   comparan: se dice que no se pueden comparar. Bloquea un margen real sobre el mock,
   que cotiza en dólares.
2. **Cuatro dimensiones de riesgo casi nunca se podrán evaluar sin fuentes de pago**:
   financiera, calidad, y fraude más allá de la procedencia.
3. **No existe el catálogo de qué países forman cada mercado.** Mientras no exista, un
   proveedor con país declarado y un destino expresado como mercado dan riesgo
   geopolítico **desconocido**, no «cruza una frontera».
4. **Las certificaciones siguen siendo de demostración.** El plan §10 las pide y este
   milestone no las modela: necesitan emisor, alcance y caducidad, que es una tabla
   propia.
5. **El coste logístico sigue siendo un estimador con factores inventados**
   (`app/sourcing/logistics.py`), ahora marcado `amazona_estimate` en cada fila.
6. **Los filtros de Incoterm y método de pago de la pantalla siguen deshabilitados.**
   El dato ya se guarda; falta construir el filtro.
7. **No hay directorio real de proveedores.** El único adaptador sigue siendo el mock;
   el camino real de este milestone es la mano del propietario.

## Qué queda preparado para el M40 (Economics por canal y techo de CAC)

- **Un coste de aterrizaje real y atribuible**, con su moneda, su Incoterm y su
  mercado de destino, que es la cifra sobre la que se calculan margen y techo de CAC.
- **La distinción de moneda ya está en el modelo**, así que el día que haya fuente de
  tipos de cambio se conecta en un sitio y no en veinte.
- **`EconomicAnalysis` ya recibe la verificación de identidad en tres estados**
  (`supplier_identity_verified`): verificado, no verificado, y **nadie lo ha mirado**.
  Hasta aquí los dos últimos eran el mismo `False`.
- **El CAC sigue sin existir** en `EconomicAnalysis`: es la deuda registrada en
  [system-overview §21](../architecture/system-overview.md#21-deuda-funcional-registrada) y el trabajo del M40.
