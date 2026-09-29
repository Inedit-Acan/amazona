# ADR 0019: Requisitos legales declarados, anclados en una fuente, con evidencia aparte

- **Estado:** Aceptada
- **Fecha:** 2026-09-29
- **Depende de:** [ADR 0004](adr-0004-agent-capability-pairs-validate-vs-discover.md), [ADR 0008](adr-0008-demo-production-isolation.md), [ADR 0011](adr-0011-action-gate.md), [ADR 0012](adr-0012-product-intelligence-adapters.md), [ADR 0015](adr-0015-multiple-real-sources-cost-and-usage-rights.md), [ADR 0017](adr-0017-supplier-facts-and-risk.md), [ADR 0018](adr-0018-money-conversion-and-not-evaluable.md)
- **Milestone:** 41

## Contexto

El plan maestro §12 pide sustituir `MockRegulatoryDirectory` —94 líneas de fixture
inventado— por fuentes verificables, conservando por requisito once campos
(jurisdicción, norma, artículo, vigencia, fuente, fecha de obtención, requisito,
alcance, confianza, estado y evidencia) y con cuatro estados de salida.

La tentación es obvia: consultar una base pública y que responda «una freidora de
aire necesita CE». **Ninguna fuente pública responde eso.** EUR-Lex publica el texto,
la vigencia y las fechas de una norma; que esa norma se aplique a *este* producto es
un juicio jurídico que no está en ninguna tabla. Un adaptador que pretendiera
responderlo lo estaría infiriendo —con una heurística o un modelo de lenguaje— y
presentaría esa inferencia como un hecho de una fuente oficial. Es el mismo defecto
que los milestones anteriores cerraron para las señales (ADR 0012), los proveedores
(ADR 0017) y el dinero (ADR 0018): un dato sin quién lo sostiene.

Investigación previa, para no duplicar y para no dar de alta nada:

- **EUR-Lex y Cellar** (verificado el 2026-09-29). El aviso legal de EUR-Lex dice que
  los documentos jurídicos «can be re-used for commercial or non-commercial purposes»
  bajo la Decisión 2011/833/UE, que **los metadatos son CC0**, y que los textos
  consolidados y los resúmenes son CC BY 4.0. Solo el Diario Oficial es auténtico y la
  web declara que no es «professional or legal advice».
- El **«webservice» de EUR-Lex y su volcado masivo exigen cuenta EU Login**: un alta.
  El **punto SPARQL de Cellar** (`publications.europa.eu/webapi/rdf/sparql`) y su API
  REST se consultan **sin registro**; se comprobó con dos consultas anónimas (HTTP
  200) antes de escribir código.
- Para la Directiva 2014/35, Cellar devolvió `resource_legal_in-force = 1`, **dos**
  fechas de entrada en vigor (2014-04-18 y 2016-04-20), `resource_legal_date_end-of-validity
  = 9999-12-31`, el ELI y el tipo de acto (`DIR`).
- No se encontró una **cuota publicada** de Cellar.
- **Ya existe** y se reutiliza: la matriz de derechos (`usage_rights.py`), el libro de
  coste y su contador (`app/costs/`), la procedencia (`SupplierFactProvenance`,
  ADR 0017), `fold` (`app/core/text.py`), el ActionGate (ADR 0011) y el modelo
  `LegalAnalysis`. **No se toca**: `opportunity_score`, `legal_analyses`, el mock y sus
  cifras.

## Decisión

### 1. Tres cuestiones que no se rellenan una con otra

| Cuestión | Quién la sostiene | Dónde vive |
|---|---|---|
| **Aplicabilidad** — «esta norma se aplica a esta clase de producto en esta jurisdicción» | **Una persona** (`declared`). Nunca la fuente, nunca una heurística, nunca un LLM | `regulatory_requirements` |
| **Existencia y vigencia** — «esta norma existe y, según la fuente, está en vigor» | **Un tercero** (`third_party_verified`, emisor: EUR-Lex), sobre una norma que **nosotros nombramos** | `regulatory_anchors` |
| **Evidencia de cumplimiento** — «este producto cumple: aquí está el certificado» | Una persona (`declared`) o quien lo emitió (`third_party_verified`, con emisor) | `compliance_evidence` |

Que falte una es un hueco visible, nunca un valor por defecto. Un certificado no
verifica que la norma exista; una norma verificada no aporta el certificado ni dice a
qué producto se aplica. `unknown`, `simulated` y `amazona_estimate` **no pueden** sostener
un hecho legal real: construirlo falla.

### 2. Cuatro estados cerrados, y qué significa cada uno

- **`PASS`**: *dentro del alcance y de los requisitos declarados y comprobados, Legal
  no ha encontrado un bloqueo.* **No** significa «producto legal» ni «cumplimiento
  completo». Lo que nadie declaró no se ha mirado. Los demás gates, el presupuesto y
  las aprobaciones humanas siguen aplicándose.
- **`REVIEW_REQUIRED`**: hay algo que una persona debe resolver.
- **`BLOCKED`**: un requisito de tipo `restriction`, con la norma **verificada y en
  vigor**, sin evidencia de cumplimiento (o con evidencia caducada). **Nunca** se
  bloquea sobre una norma que nadie ha podido confirmar: eso sería construir un
  resultado negativo sobre una duda.
- **`UNKNOWN`**: no hay nada declarado para el alcance, o la jurisdicción no la cubre
  la fuente. **La ausencia de requisitos declarados no es la ausencia de requisitos**,
  así que `UNKNOWN` jamás asciende a `PASS`.

Hacia el ActionGate (`legal_recommendation`): `PASS → GO`, `REVIEW_REQUIRED → REVIEW`,
`UNKNOWN → REVIEW`, `BLOCKED → NO_GO`. **`UNKNOWN` sale como `REVIEW` y no como `NO_GO`**
por la misma razón que `NOT_EVALUABLE` (ADR 0018): el gate veta los `NO_GO` que gastan,
y «no se pudo comprobar» no es un resultado negativo.

El agregado de un producto es el peor de sus requisitos (`BLOCKED` > `REVIEW_REQUIRED` >
`PASS`), y `PASS` exige que **todos** los requisitos declarados pasen y que haya al menos
uno.

### 3. Quién escribe: OWNER y ADMIN, con una acción propia

Nueva `ApiAction.REGULATORY_WRITE` (declarar, sustituir y retirar requisitos, aportar
evidencia y pedir una comprobación contra la fuente). **Solo OWNER y ADMIN.** REVIEWER es
de solo lectura. **SYSTEM no la tiene**: ningún proceso automático declara aplicabilidad
normativa por iniciativa propia. Es distinta de `AGENT_RUN` y de `SUPPLIER_WRITE`: correr
el agente de Legal es analizar lo declarado, y esto es **afirmar un juicio jurídico**.
Leer lo declarado es `BUSINESS_READ`, como el resto de Legal.

Modificar es **sustituir**: la fila anterior se conserva marcada (`superseded_by_id`) y la
nueva la reemplaza; retirar es `withdrawn_at`. Lo que Legal concluyó en marzo se concluyó
con la declaración de marzo. La evidencia está ligada a una fila concreta de requisito y
**no se traslada** cuando este se sustituye: quien lo modificó decide si sigue valiendo.

### 4. Tres fechas que no se confunden, y una política que no es jurídica

Cada comprobación guarda, en una fila nueva (nunca se machaca la anterior):

- **`verified_at`** — cuándo se preguntó a la fuente (el `retrieved_at` del §12).
- **`source_effective_from` / `source_effective_to`** — las fechas **que la fuente
  entrega, tal cual y sin interpretar.** `entry_into_force` puede traer varias y **no se
  elige una** (la Directiva 2014/35 devuelve dos). `9999-12-31` se guarda como cadena
  bruta: **no se le asigna el significado «sin fin de validez»**, porque la documentación
  de la fuente que se ha leído no lo define. La evaluación no depende de esa
  interpretación: usa el indicador `in-force` que da la fuente y solo trata el fin de
  validez como contradicción cuando es una fecha real **ya pasada** (un `9999-12-31` no lo
  es en ningún caso, sin necesidad de darle significado).
- **`recheck_after`** — **política operativa nuestra**, configurable
  (`LEGAL_ANCHOR_RECHECK_DAYS`, 30 por defecto y conservador). Superarlo produce
  `REVIEW_REQUIRED` hasta una nueva comprobación. **No significa que la norma haya dejado
  de estar en vigor**, y la pantalla y los motivos lo dicen así. Treinta días no es un
  plazo jurídico.

Si la fuente no contesta, se conserva el ancla anterior —que seguirá vencida— y el
análisis pide revisión. **No se guarda nada**: un fallo no puede leerse después como «la
fuente dijo que no existe».

### 5. Una directiva no basta

Una directiva verifica el acto de la UE, **no la ley nacional que la traspone**, que es lo
que obliga. Una directiva sola —aunque esté verificada y en vigor y haya evidencia—
**no puede producir `PASS`**: hace falta una referencia de transposición nacional
declarada, con su procedencia. Sin ella, el resultado es `REVIEW_REQUIRED` y lo dice.
Tampoco se bloquea con una directiva sin transposición. Un acto cuyo tipo la fuente no
establece como directamente aplicable (`OTHER`/`UNKNOWN`) también pide revisión: el mapa
de códigos a `regulation`/`directive` es cerrado y lo que no está en él **no se supone**.
Consecuencia asumida: hoy no hay fuente de Derecho nacional, así que la transposición solo
puede ser `declared`.

### 6. Un adaptador real, y no decide nada

`EurLexCellarSource` (`app/integrations/regulatory/eur_lex.py`) implementa el puerto nuevo
`RegulatoryAnchorSource.lookup(celex) -> SourceAnchor`. Dado un CELEX **declarado**,
devuelve existencia, vigencia, fechas, ELI y tipo de acto, con todo lo que la fuente
devolvió como evidencia. **No busca normas, no trae textos, no traduce y no decide a qué
se aplica nada.** El CELEX se valida (`3` + año + letra + número) **antes** de
interpolarse en la consulta. El cliente HTTP y el contador de coste se inyectan, como en
los adaptadores de Product Intelligence: los tests no tocan la red y cada llamada real
queda anotada. Solo jurisdicción `eu`; cualquier otra es `UNKNOWN`.

Se usa el **SPARQL de Cellar y no el «webservice» de EUR-Lex** precisamente porque este
exige alta, y este proyecto no da de alta nada. Si Cellar dejara de ser anónimo, el
adaptador deja de usarse: **no se sustituye por una vía con alta**.

### 6 bis. Derechos y coste antes de la primera llamada

Se escriben **antes** de que el adaptador exista (regla del Milestone 37). Derechos
(`usage_rights.py`, leídos el 2026-09-29): metadatos CC0, así que almacenar, conservar,
transformar, derivar, puntuar y redistribuir están permitidos **para lo que se guarda**
—solo metadatos: existencia, vigencia, fechas, ELI—, y no se extienden al contenido de
los documentos, que no se toca. Coste (`costs/policy.py`): gratuito, **sin cuota escrita**
porque no se encontró una publicada (`None` significa «no sé», no «sin límite»), con un
tope por ejecución propio. Antes de preguntar, `verify` comprueba que los derechos permiten
guardar lo que devuelve.

### 7. Confianza: procedencia más techos internos, no calibrados

Cada eslabón tiene un techo según quién lo sostiene: `third_party_verified` 0,8;
`declared` 0,6 (y `amazona_estimate` 0,5 y `simulated` 0,4, que no pueden sostener un hecho
legal real y se listan por completitud). La confianza de un requisito es el techo **de su
eslabón más débil** (aplicabilidad, existencia y evidencia), y construir una evaluación que
lo supere **falla**, como el techo por base de las señales del Milestone 37. Sin ancla
verificada, la existencia descansa en lo declarado. El agregado es el mínimo de los
requisitos; `UNKNOWN` reutiliza el 0,3 con el que el agente simulado ya decía «datos
insuficientes».

**Son reglas internas de AMAZONA, no calibradas.** No salen de ninguna medición y se
mantendrán así mientras no haya evidencia empírica suficiente; su único trabajo es que un
dato declarado no parezca tan sólido como uno emitido por un tercero. **No hay ningún
score adicional** y la salida lleva escrita la regla (`confidence_rule`).

### 8. El mock se queda, y el camino real es aparte

Con `REGULATORY_PROVIDER=mock` (el valor por defecto) `LegalComplianceService` hace
**exactamente lo que hacía**: mismo agente, mismos datos, mismas cifras, sin
`legal_status`. Con `real`, el análisis evalúa los requisitos declarados para el alcance
del producto y guarda su resultado en `LegalAnalysis.data` (`legal_status`, requisitos con
las tres cuestiones separadas, motivos, aviso, regla de confianza). **No se envuelve el
mock en el puerto nuevo**: habría exigido inventar números CELEX para los fixtures, es
decir, fabricar datos legales. El alcance se empareja por `fold(category)` — determinista,
sin similitud—: `Juguete` no es `Juguetes`.

La salida real **no inventa lo que no hay**: sin `required_certifications` ni
`terms_and_conditions` (nadie los ha escrito), `restricted` solo es `true` cuando hay un
bloqueo y en cualquier otro caso queda ausente, y el flag heredado
`certification_available` **se informa como ignorado** (`certification_flag_ignored`) en
vez de descartarse en silencio: un booleano no es evidencia de ningún requisito concreto.
Toda salida real lleva un aviso: Legal ayuda a detectar y estructurar requisitos y no
sustituye la revisión profesional.

## Alternativas descartadas

- **Que la fuente diga qué se aplica a cada categoría** (o que lo infiera un LLM o una
  tabla de palabras clave). Es la decisión que esta ADR existe para no tomar: presentaría
  un juicio jurídico como dato de EUR-Lex.
- **El webservice o el volcado de EUR-Lex.** Exigen alta.
- **Envolver el mock con CELEX inventados** para que pase por el puerto nuevo. Sería
  fabricar normativa.
- **Un score de cumplimiento.** Un número único es justo lo que el plan §11 rechaza para
  el riesgo.
- **Tratar el «vencido» como derogación.** Lo vence nuestra política, no la norma.
- **`9999-12-31` como «sin fin de validez».** Es una interpretación probable y no está
  documentada por la fuente que se leyó.
- **Bloquear (`BLOCKED`) cuando la norma no se puede comprobar.** Un veto sobre una duda.
- **Aplicar `PASS` a una directiva verificada.** Aplicaría el acto de la UE como si fuera
  la ley nacional.

## Consecuencias

- Legal puede, por primera vez, decir **de dónde sale cada afirmación**: quién declaró la
  aplicabilidad, cuándo y contra qué fuente se comprobó la norma y qué evidencia tiene el
  producto.
- **Hoy Legal real dice `UNKNOWN` para casi todo**, porque nadie ha declarado requisitos.
  Es el resultado correcto y es incómodo: el sistema deja de parecer que sabe.
- Solo cubre **Derecho de la UE**. Los mercados `es`, `us`, `mx` (y cualquiera que no sea
  `eu`) salen `UNKNOWN`. No hay fuente de Derecho nacional.
- Una directiva nunca llega a `PASS` sin transposición nacional declarada, y esa
  declaración no la verifica nadie.
- **`PASS` puede ser optimista** si la lista declarada está incompleta: nadie comprueba
  que no falte una norma. Por eso se llama «sin bloqueo en lo declarado» y no «legal».
- La evidencia no se traslada al sustituir un requisito: quien modifica el requisito
  vuelve a aportarla.
- Migración `e5f8a2c1b7d4`: tres tablas nuevas, **sin tocar `legal_analyses`**. Bajarla
  elimina lo declarado, comprobado y aportado, que solo existe ahí.
- Deuda registrada: sin verificación de la transposición nacional, sin más de una fuente,
  sin textos de artículos, sin Safety Gate ni BOE (aplazados a milestones posteriores), y
  el mapa de códigos de tipo de acto solo cubre `REG*` y `DIR*`.
- **n8n y Redis siguen aplazados** exactamente según el plan §23 bis; este milestone no los
  toca ni los necesita.
