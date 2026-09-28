# ADR 0017: Quién sostiene un hecho sobre un proveedor, y por qué el riesgo no es un número

- **Estado:** Aceptada
- **Fecha:** 2026-09-29
- **Depende de:** [ADR 0008](adr-0008-demo-production-isolation.md), [ADR 0014](adr-0014-entity-resolution.md), [ADR 0015](adr-0015-multiple-real-sources-cost-and-usage-rights.md)
- **Milestone:** 39

## Contexto

Supplier Intelligence era el único dominio P1 que quedaba cuya fuente real puede ser
el propietario a coste cero: un precio de proveedor negociado se introduce a mano, un
volumen de búsqueda comercial no. Y sin coste de aterrizaje real nada aguas abajo es
real: el margen, el techo de CAC y el `opportunity_score` v2 se calculan todos sobre
él.

Lo que había antes de este milestone, comprobado en el repositorio:

- `Supplier.verified: bool` y `SupplierQuote.verified: bool` eran **booleanos**,
  cuando el plan maestro §10 exige distinguir *supplier claim* / *third-party
  verified* / *AMAZONA estimate* / *unknown* y dice, con esas palabras: «No marcar un
  proveedor como "verified" sin explicar qué significa».
- `Supplier.reliability_score: float = 0.0`. Una fiabilidad desconocida era
  indistinguible de una nula. Es el cero inventado que el Milestone 34 prohibió para
  las señales, aplicado a una empresa.
- `SupplierQuote` **no tenía moneda**. Tampoco Incoterm, ni condiciones de pago, ni
  mercado de destino, ni vigencia. «4,20» podía ser EXW Shenzhen en dólares —sin
  transporte, sin aduana— o DDP Valencia en euros.
- El puerto estaba en fase pre-M34: `get_suppliers(category, max_results) -> list[dict]`,
  un contrato moldeado sobre el mock.
- **Faltaba entero el §16**: ningún proveedor declaraba envío directo, dropshipping,
  envío ciego, embalaje propio, tracking, devoluciones, dirección de retorno en la UE
  ni SLA. La pantalla de Proveedores las enseñaba desde `lib/demo/sourcing.ts`,
  generadas con una semilla determinista: ocho afirmaciones sobre el mundo salidas de
  un número pseudoaleatorio.

Es el mismo defecto que el Milestone 37 arregló para las señales, en otro dominio y
con una diferencia: allí el eje era **de qué está hecho** un número; aquí es **quién
lo sostiene**, que es la pregunta que importa cuando el dato es un precio negociado o
una promesa de envío directo.

## Decisión

### 1. Cada hecho sobre un proveedor dice quién lo sostiene

`SupplierFactProvenance` sustituye a los dos booleanos:

| Valor | Qué significa |
|---|---|
| `third_party_verified` | Alguien independiente del proveedor lo comprobó. **Exige emisor.** |
| `supplier_claim` | Lo dice el proveedor. Información legítima, de parte interesada. |
| `amazona_estimate` | Lo calculamos nosotros con un método propio. |
| `simulated` | Un fixture. No viene del mundo. |
| `unknown` | **Nadie lo ha dicho.** No se guarda: es lo que contesta el sistema. |

`simulated` no estaba en la lista de cuatro del plan §10 y se añade a propósito: el
mock afirma precios y MOQ, y llamarlos `amazona_estimate` diría que alguien los
calculó. Nadie los calculó; están escritos en un fichero. Sin esta casilla el mock
tendría que mentir para caber en el enum.

`unknown` **no es almacenable**. Una fila que dice «no se sabe» afirma lo mismo que no
tener fila y además es indistinguible de un error de carga.

Y `third_party_verified` **falla al construirse** si no nombra al verificador, en el
dominio y no en la pantalla, por el mismo criterio que el techo de confianza del
Milestone 37: un recorte callado esconde el problema en vez de enseñarlo.

### 2. La procedencia de la empresa y la de su tarifa son hechos distintos

`suppliers.verification` dice quién sostiene que la empresa es quien dice ser;
`supplier_quotes.provenance` dice quién sostiene **esa oferta**. Que una empresa esté
auditada no audita su tarifa, y un precio sacado de un catálogo público no es lo mismo
que uno dicho por WhatsApp.

Y `supplier_quotes.logistics_provenance` va aparte del precio porque el precio puede
venir del proveedor y el transporte de un estimador nuestro: presentarlos con la misma
procedencia mentiría sobre la mitad de la suma.

### 3. Una cotización lleva sus condiciones comerciales, y lo que falta falta

Moneda (ISO 4217, catálogo extensible), unidad y cantidad cotizadas, MOQ, Incoterm
(los once de Incoterms 2020, conjunto **cerrado**), condiciones de pago, días de
preparación separados de los de transporte, modo de transporte, coste logístico,
mercado de destino y vigencia.

Todo **nulable**, y eso es la mitad del punto: un Incoterm por defecto sería una
condición pactada que nadie pactó, y un coste logístico cero sería un transporte
gratis. Cinco columnas que eran `NOT NULL` dejan de serlo.

### 4. No se convierte entre monedas

Convertir exige un tipo de cambio, y un tipo de cambio es un dato de mercado con
fecha, fuente y coste. Inventar uno —o peor, usar uno de hace seis meses— metería un
error del 5 % en el margen sin que nadie lo viera.

Consecuencias, las tres deliberadas:

- Un precio **sin moneda se rechaza**: sin ella no se compara con ningún otro, y
  suponer que coinciden es inventar un tipo de cambio de 1,00.
- Economics **no falla** cuando la moneda del coste no es la contable: añade el aviso
  a los riesgos del análisis y lo dice.
- El desglose de coste de aterrizaje del panel **no se calcula** cuando el precio está
  en otra moneda que el resto de renglones. Un total con símbolo de euro que no son
  euros es la misma mentira.

### 5. Las capacidades del §16 son declaraciones, no booleanos

Ocho capacidades en un enum cerrado, y una tabla `supplier_capabilities` donde cada
fila es **una declaración**: qué, si la soporta, quién lo dice, desde cuándo y una
nota libre. La ausencia de fila se contesta `unknown`, nunca `false`.

Una declaración puede ser del proveedor entero o **de un producto concreto**, porque
§16 dice «cada proveedor/producto debe declarar»: un fabricante puede enviar directo
un artículo pequeño y no uno voluminoso. Lo específico manda sobre lo general; dentro
del mismo alcance manda la procedencia más fuerte, y entre iguales la más reciente.

Una declaración nueva **no borra la anterior**. Que un proveedor dijera una cosa en
marzo y la contraria en septiembre es información.

### 6. Identidad de proveedor: la regla del Milestone 36 aplicada a empresas

Determinista o declarada, nunca por parecido. La clave es el nombre normalizado
(`app.core.text.fold`, extraída de la identidad de productos para no tener dos copias
que divergen) más **dónde está**.

El sitio forma parte de la identidad: dos fabricantes con el mismo nombre comercial en
China y en Polonia no son la misma empresa, y unirlos mezclaría un plazo de tres días
con uno de veinticinco. La clave dice además si el sitio era un país o una región: una
ficha con país y otra sin él **no se funden solas**, porque afirmar que la de región
`eu` es la misma empresa que la de país `PL` es exactamente la inferencia por parecido
que la ADR 0014 prohíbe.

Hasta aquí la reutilización iba por `(name, region)` exactos. Con la entrada manual
—donde el nombre lo teclea una persona— eso habría creado una empresa nueva por cada
espacio de más.

### 7. El riesgo es ocho respuestas, no un número

El plan §11 lo dice: «No convertirlo inicialmente en un único score opaco. Mantener
dimensiones explicables». `SupplierRiskProfile` **no tiene puntuación total**, y no es
un olvido: es la instrucción escrita en el tipo.

Cada dimensión trae nivel, motivo en una frase y los hechos concretos en los que se
apoya. Y hay un cuarto nivel además de bajo/medio/alto: `unknown`. Un riesgo que no se
ha podido evaluar **no es un riesgo bajo** — es la versión de este dominio del cero
inventado, y aquí es más cara: un riesgo de fraude «bajo» porque nadie miró es una
compra a ciegas que parece hecha con los ojos abiertos.

Se calcula al leer y **no se guarda**. Una evaluación guardada envejece sin avisar: el
día que alguien declare la dirección de retorno en la UE, una fila escrita hace tres
meses seguiría diciendo lo contrario.

Todas las evaluaciones que el sistema produce hoy son `amazona_estimate`: no hay
fuente externa de riesgo de proveedor —eso cuesta dinero y el Milestone 39 tiene
presupuesto cero— y ninguna se presenta como comprobada por un tercero.

### 8. La entrada manual es un camino permanente

`POST /api/suppliers`, `POST /api/suppliers/{id}/quotes` y
`POST /api/suppliers/{id}/capabilities`, bajo una acción propia `SUPPLIER_WRITE`.

Es distinta de `AGENT_RUN` a propósito: correr el agente de sourcing es pedirle datos
a un directorio, y esto es **afirmar un hecho** sobre una empresa real. `SYSTEM` no la
tiene: ningún proceso automático afirma hechos sobre una empresa.

## Alternativas descartadas

**Mantener el booleano y añadir una columna `verified_by`.** Dos campos que hay que
leer juntos para entender uno. El día que alguien consulte solo `verified` vuelve el
problema entero.

**Guardar las ocho capacidades como ocho columnas booleanas en `suppliers`.** Un
booleano no puede decir «nadie lo ha preguntado», que es el estado de las ocho hoy, ni
llevar quién lo dice ni desde cuándo.

**Convertir monedas con un tipo de cambio fijo o cacheado.** Es la opción que deja el
panel más bonito y los números mal. Un error de cambio no se ve: se propaga al margen,
del margen al techo de CAC y de ahí a una decisión de compra.

**Guardar el perfil de riesgo en una tabla.** Envejece en silencio. Derivarlo de los
hechos guardados lo mantiene al día y, sobre todo, reconstruible: se puede enseñar de
qué salió.

**Un `risk_score` de 0 a 100 «solo para ordenar la lista».** Es exactamente lo que
§11 prohíbe, y el «solo para ordenar» dura hasta que alguien decide con él. La
pantalla usa el **peor** nivel de las ocho, que es un máximo explicable, y enseña las
ocho al lado.

## Consecuencias

- Una decisión de compra puede ver, por fin, qué sabe y qué no sabe de un proveedor.
- El agente de sourcing **no recomienda GO sobre fixtures**. Con el mock activo la
  recomendación es siempre `REVIEW`, diga lo que diga el precio. Hasta aquí el mock
  decía `verified: True` y eso bastaba.
- Las cotizaciones del mock ya no tienen coste de aterrizaje comparable con un precio
  en euros, porque el fixture declara dólares. Es incómodo y es cierto.
- Bajar la migración cuesta información: el esquema anterior no sabe representar «no
  se sabe», así que todo lo desconocido vuelve a valer cero. Es esta ADR vista del
  revés.
- Quedan cuatro dimensiones de riesgo que casi nunca se podrán evaluar sin fuentes de
  pago (financiera, calidad y fraude más allá de la procedencia) y una que necesita un
  catálogo que no existe: qué países forman cada mercado. Mientras no exista, un
  proveedor con país declarado y un destino expresado como mercado dan riesgo
  geopolítico **desconocido**, no «cruza una frontera».
