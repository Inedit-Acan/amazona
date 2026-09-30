# ADR 0021: Transposición nacional declarada y anclada en el BOE — evidencia en capas, texto informativo y `PASS` que no depende solo del texto consolidado

- **Estado:** Aceptada
- **Fecha:** 2026-09-30
- **Depende de:** [ADR 0008](adr-0008-demo-production-isolation.md), [ADR 0009](adr-0009-async-job-runtime.md), [ADR 0011](adr-0011-action-gate.md), [ADR 0015](adr-0015-multiple-real-sources-cost-and-usage-rights.md), [ADR 0017](adr-0017-supplier-facts-and-risk.md), [ADR 0018](adr-0018-money-conversion-and-not-evaluable.md), [ADR 0019](adr-0019-legal-requirements-and-source-anchoring.md)
- **Enmienda a:** [ADR 0019](adr-0019-legal-requirements-and-source-anchoring.md) (§«Una directiva sola no puede dar `PASS`»: el texto libre de transposición deja de bastar; y «Derecho nacional fuera de alcance»: pasa a poder anclarse, solo como transposición de una directiva ya declarada)
- **Milestone:** 43

## Contexto

La ADR 0019 dejó dicho que una directiva verifica el acto de la UE y no la ley nacional
que lo traspone, y que una directiva con una transposición **escrita a mano en texto libre**
podía llegar a `PASS` con confianza 0,6. Era honesto con lo que había —no había fuente de
Derecho nacional— y dejaba `PASS` optimista: nadie verificaba que esa norma existiera, que
estuviera en vigor ni que dijera traspone lo que se afirmaba.

Al leer la fuente antes de escribir código (29-09-2026) aparecieron hechos que fijan el diseño:

1. **La AEBOE publica una API de datos abiertos sin alta, sin credenciales y sin cuota
   publicada** (ni el aviso legal, ni la documentación técnica, ni las FAQ dan un límite).
   Se puede suspender el acceso sin aviso y no se garantiza la continuidad.
2. **La licencia autoriza la reutilización comercial y la transformación, con condiciones**:
   citar la fuente («Basado en datos de la Agencia Estatal Boletín Oficial del Estado» cuando
   hay obra derivada), indicar **expresamente** que la legislación consolidada es un texto de
   carácter meramente informativo, mencionar la fecha de última actualización, conservar los
   metadatos de fecha, identificar toda modificación y no sugerir que es oficial.
3. **Hay cuatro capas que no son lo mismo**: la *publicación oficial* (el diario; desde 2009
   es la auténtica), la *legislación consolidada* («sin valor oficial», informativa), el
   *análisis jurídico* (materias, notas y relaciones con otras normas; informativo) y los
   *metadatos/ELI* de la norma.
4. **El propio análisis del BOE dice qué directiva traspone una norma.** El análisis del Real
   Decreto 1205/2011 (juguetes) trae la relación `426 TRANSPONE` hacia `DOUE-L-2009-81173` con
   el texto «la Directiva 2009/48/CE, de 18 de junio de 2009». Es una afirmación de la fuente,
   **informativa**, escrita en texto. `427` es `TRANSPONE parcialmente`.
5. **Un `404` no distingue «no consolidada» de «no existe»**: la colección consolida
   principalmente normas con rango de ley. Comprobado con un identificador que consta en el
   sumario del día y da 404 en la colección.
6. **El identificador `BOE-A-AAAA-NNNNN` es único, pero su número es un control interno**, no
   el número oficial de la norma. El enlace estable es la URL ELI y el documento oficial se
   construye del identificador.

## Decisión

### 1. La regla: una persona declara, la fuente verifica

**El sistema no infiere qué norma española traspone una directiva ni qué norma se aplica a un
producto.** Una persona declara «este Real Decreto traspone esta directiva»; el BOE solo
**verifica y ancla** la norma que se le nombra. No se usa el endpoint de lista (no hay búsqueda
por título, por materia ni por texto), no se propone ninguna norma, no se usa un LLM.

### 2. Evidencia en capas, sin que ninguna rellene a otra

| Capa | Quién la sostiene | Dónde |
|---|---|---|
| Norma declarada | Una persona (`declared`) | `national_transpositions` |
| Publicación oficial | El sumario del diario del BOE. **Comprobación auxiliar** | `national_anchors.publication_*` |
| Texto consolidado, análisis y metadatos | La AEBOE. **Informativos** | `national_anchors.source_metadata` y `relations` |
| Vigencia y estado | Las banderas de la fuente (`S`/`N`), sin interpretar fechas | ídem |
| Relación con la norma UE | La relación `426` del análisis + comparación determinista con el CELEX | calculada al evaluar |
| Evidencia de cumplimiento del producto | Una persona o el emisor | `compliance_evidence` (M41, sin cambios) |

`PASS` **no depende solo del texto consolidado**: exige además la evidencia de cumplimiento, y
la corroboración de la transposición descansa en un análisis que la propia fuente califica de
informativo (techo de confianza 0,7, §7).

### 3. Puerto hermano, no generalización

`NationalNormSource.lookup(national_id) -> NationalNormRecord`, junto a
`RegulatoryAnchorSource` y **sin tocarlo**. Un `SourceAnchor` forzado a servir a BOE dejaría
campos vacíos (ELI de la UE, fechas de entrada en vigor múltiples) y mezclaría lo oficial con
lo informativo. El adaptador (`app/integrations/regulatory/boe.py`) usa **tres** endpoints:
`legislacion-consolidada/id/{id}/metadatos`, `…/analisis` y `boe/sumario/{aaaammdd}`. No usa
`/texto*` ni `/metadata-eli` (el texto no se guarda; `url_eli` ya viene en los metadatos).

### 4. Identificación

El identificador que se declara es el del BOE (`^BOE-[A-Z]-\d{4}-\d{1,6}$`), validado **antes**
de llamar a nadie. La URL ELI y la URL oficial se guardan y se enseñan; la oficial se construye
del identificador (`boe.es/buscar/doc.php?id=…`). Solo una directiva tiene transposición: se
decide por el CELEX (`3AAAALNNNN`), determinista, sin esperar a EUR-Lex.

### 5. Corroboración: comparación determinista o nada

Una relación `426` (o `427`) nombra la directiva en texto. Se compara con el CELEX declarado
**solo** si año y número se leen sin ambigüedad: una expresión regular sobre cómo numera la UE
sus actos (`2009/48/CE`, `(UE) 2015/1535`; con dos cifras de año solo se acepta ≥ 57, porque el
Tratado de Roma es de 1957). Cuatro resultados:

- `corroborated`: hay una relación `426` cuyo año y número coinciden.
- `partial`: la coincidente es `427`. **No basta.**
- `uncorroborated`: el análisis se leyó y no dice que traspone esa directiva.
- `not_assessable`: hay relaciones de transposición ilegibles o ambiguas (el texto nombra más
  de un acto, o un año de dos cifras sin lectura), o no hay un CELEX de directiva. **No es una
  contradicción.** Nada de similitud textual, de *fuzzy matching* ni de un LLM.

La relación se conserva **tal cual la devuelve el BOE** (id, código, texto de la relación,
texto de detalle).

### 6. Reglas de evaluación (solo pueden bajar el resultado)

Una directiva llega a `PASS` únicamente si **todas** las normas nacionales declaradas para el
requisito cumplen a la vez: declarada por una persona, verificada (comprobación vigente), en
vigor según las banderas de la fuente, sin relaciones de anulación o suspensión, y **corroborada
(`426`)**; y si además hay evidencia de cumplimiento (M41). Cualquier otra combinación es
`REVIEW_REQUIRED` (nunca `BLOCKED`: eso exige una restricción con la norma verificada y en
vigor):

| Estado de la norma | Efecto |
|---|---|
| Sin transposición estructurada (aunque haya texto libre) | `REVIEW_REQUIRED` |
| Nunca comprobada / comprobación vencida (política nuestra) / fuente caída | `REVIEW_REQUIRED` |
| `404`: no consolidada | `REVIEW_REQUIRED`, **conservando el motivo**. Nunca «no existe» |
| `estatus_derogacion`, `estatus_anulacion` o `vigencia_agotada` = `S` | `REVIEW_REQUIRED` |
| `estado_consolidacion` = 4 (desactualizado) o banderas ilegibles | `REVIEW_REQUIRED` |
| Relaciones posteriores `220`, `221`, `230` o `231` (anula, deja sin efecto, suspende) | `REVIEW_REQUIRED`; se muestran; **su efecto jurídico no se interpreta** |
| El sumario del día, **leído bien**, no lista la norma | `REVIEW_REQUIRED` (fuente inconsistente) |
| Vigente y `427` / `uncorroborated` / `not_assessable` | `REVIEW_REQUIRED` |
| Vigente y `426` coincidente | continúa con las reglas de evidencia de M41 |

**Las fechas de la fuente (`fecha_vigencia`, `fecha_derogacion`, `fecha_anulacion`) se
conservan como cadena `AAAAMMDD` y no se comparan con hoy.** Las banderas `S`/`N` se leen tal
cual: es lo que la fuente dice, no una interpretación nuestra. Las modificaciones ordinarias
(`270 MODIFICA`) no marcan nada: un decreto con diez modificaciones sigue en orden.

### 7. `PASS` más estricto que en M41, y la confianza

**Enmienda a la ADR 0019.** El texto libre `transposition_reference` de M41 **se conserva** (no
se migra ni se borra) como declaración humana y pista de auditoría, pero **ya no basta**: una
directiva sin transposición estructurada verificada y corroborada es `REVIEW_REQUIRED`, con la
razón de que el texto libre es una declaración humana. Cuando existe la estructurada, la
evaluación usa esa evidencia. Esto endurece M41 a propósito.

Lo que descansa en datos informativos del BOE no supera **0,7** de confianza: entre EUR-Lex
(0,8) y lo declarado (0,6), porque la fuente advierte de que consolidación y análisis son
informativos y pueden ir con retraso. **Regla interna no calibrada.** No hay ningún score
adicional.

### 8. Todo o nada, y una comprobación auxiliar que no degrada

Una verificación son tres peticiones con dos papeles distintos:

- **Núcleo: metadatos y análisis.** Si cualquiera falla, no hay observación: no se guarda nada
  y no se puede leer después como «la fuente dijo que no». Un HTTP inesperado, un cuerpo mayor
  de 3 MB, un JSON inválido o una fila que no se entiende hacen fallar la lectura entera.
- **Auxiliar: el sumario del día de publicación.** Cuatro estados: `confirmed`,
  `absent_from_summary` (la **única** respuesta negativa, y solo si el sumario se leyó bien),
  `check_failed` (red, formato o presupuesto: **no es una conclusión**) y `not_checked` (sin
  fecha, o anterior a 2009, cuando solo es oficial el papel). Que falle el sumario **no
  degrada** la norma y la observación se guarda con `check_failed`, que no cuenta para el
  estado.

Tres peticiones, una observación coherente: metadatos y análisis o nada; la publicación, con su
estado explícito.

### 9. Lo informativo viaja con el dato

`informational` se guarda **explícito** en cada comprobación (siempre `true`), con el aviso
(«Texto consolidado de carácter meramente informativo. Para fines jurídicos debe consultarse la
publicación oficial.») y la atribución («Basado en datos de la Agencia Estatal Boletín Oficial
del Estado») **del momento**. La API los devuelve con cada norma; la pantalla los muestra siempre
junto a cualquier dato del BOE, con el enlace oficial y el ELI. No se guarda el texto de las
normas. Los datos se conservan sin alterar; lo que normalizamos (forma de las relaciones) no
cambia su contenido.

### 10. Derechos, coste y privacidad, antes de la primera llamada

- **Derechos** (`boe-open-data`, leídos el 29-09-2026): `STORAGE`, `RETENTION`,
  `TRANSFORMATION`, `DERIVED_METRICS`, `SCORING`, `REDISTRIBUTION` y `COMMERCIAL_USE` permitidos
  por la licencia (autoriza expresamente fines comerciales), con atribución requerida.
  **`AI_INGESTION` sigue `UNKNOWN`, es decir denegado.** Los permisos se leen de la
  autorización general, no de una cláusula por uso, y las notas lo dicen.
- **Coste:** gratis, sin cuota publicada (`None` = «no sé»), tope propio de 12 peticiones por
  ejecución. Cada petición pasa por el `CostMeter`.
- **Privacidad:** el `User-Agent` es un identificador técnico neutro del proyecto,
  `KOVA-Regulatory-Client/0.1`: **sin nombre, correo ni ningún dato personal**, y hay un test
  que lo impide. Las consultas de investigación anteriores a esta ADR incluyeron por error el
  correo del propietario en el `User-Agent`; el código de producción no lo hace ni lo hará.

### 11. Configuración e independencia

`NATIONAL_LAW_PROVIDER=mock|real` (`ProviderKind`, coherente con `EXCHANGE_RATE_PROVIDER`; `real`
es el BOE). `mock` (por defecto) no llama a nadie: las normas declaradas quedan «nunca
comprobadas». Independiente de `REGULATORY_PROVIDER` (EUR-Lex): con `REGULATORY_PROVIDER=mock`
el análisis es exactamente el de siempre, con las mismas cifras. Escribir es `REGULATORY_WRITE`
(solo OWNER y ADMIN; REVIEWER lee; SYSTEM no).

## Consecuencias

- Una directiva puede llegar a `PASS` de forma verificable, pero solo con una norma española
  declarada, verificada en el BOE y corroborada por su análisis, más evidencia de cumplimiento.
- **`PASS` se endurece respecto a M41**: los requisitos con transposición en texto libre pasan a
  `REVIEW_REQUIRED` hasta que alguien declare la norma estructurada. El texto libre no se pierde.
- **La cobertura del BOE es incierta**: solo consolida principalmente normas con rango de ley.
  Un real decreto u orden no consolidado da `404` y el requisito queda en revisión.
- El análisis del BOE es informativo y puede omitir la relación `426` aunque exista la
  transposición: eso baja a revisión, no bloquea.
- Las derogaciones parciales no aparecen en las banderas (son de la norma entera): solo se ven
  como relaciones posteriores.
- Una transposición ligada a una fila de requisito **no se traslada** si el requisito se
  sustituye (igual que la evidencia): quien lo modifica decide.
- Si el BOE deja de ser anónimo o cambia de formato, el adaptador falla en voz alta y no se
  sustituye por otra vía con alta.

## Lo que esta ADR no decide

Derecho nacional genérico (normas españolas independientes de una directiva, jurisdicción `es`),
búsqueda normativa, inferencia de aplicabilidad, Safety Gate, ECHA, otros países y otras
fuentes; verificar transposiciones de fuentes no consolidadas por el sumario; y cualquier LLM en
el camino de decisión legal (plan maestro §26).
