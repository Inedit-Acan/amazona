# Milestone 41 — Legal Intelligence real: requisitos declarados, anclados en EUR-Lex

**Fecha:** 29-09-2026 · **ADR:** [0019](../architecture/adr-0019-legal-requirements-and-source-anchoring.md)
· **Depende de:** [0008](../architecture/adr-0008-demo-production-isolation.md)
· [0011](../architecture/adr-0011-action-gate.md)
· [0015](../architecture/adr-0015-multiple-real-sources-cost-and-usage-rights.md)
· [0017](../architecture/adr-0017-supplier-facts-and-risk.md)
· [0018](../architecture/adr-0018-money-conversion-and-not-evaluable.md)

**Presupuesto: 0 €. Ninguna cuenta, credencial ni servicio de pago.** Las únicas llamadas
externas reales son consultas anónimas y gratuitas al SPARQL público de Cellar (ver
«Llamadas externas»).

## Lo que se encontró al revisar

- **Ninguna fuente pública dice a qué productos se aplica una norma.** EUR-Lex publica el
  texto, la vigencia y las fechas. «Una freidora de aire necesita CE» es un juicio
  jurídico que no está en ninguna tabla, y un adaptador que lo respondiera lo estaría
  infiriendo. Este milestone **no lo infiere**: lo declara una persona.
- **El «webservice» y el volcado de EUR-Lex exigen cuenta EU Login.** El punto SPARQL de
  Cellar no. Se usa Cellar; si dejara de ser anónimo, el adaptador se retira y no se
  sustituye por una vía con alta.
- **Cellar no es fiable en el primer intento.** En la prueba de humo, dos de tres
  consultas agotaron el tiempo de lectura (20 s) y la tercera dio HTTP 504; a la segunda
  ejecución respondieron todas. Esto cambió el diseño: el tiempo límite baja a 10 s y, si
  la fuente falla una vez, **el resto del análisis no insiste** (un trabajo tiene un
  arriendo de 60 s, ADR 0009).
- **La fuente devuelve dos fechas de entrada en vigor** para la Directiva 2014/35
  (2014-04-18 y 2016-04-20) y un fin de validez `9999-12-31` que ninguna documentación de
  la fuente leída define. Se conservan tal cual.

## Qué cambia

### Tres cuestiones que no se rellenan una con otra

| | Quién la sostiene | Tabla |
|---|---|---|
| **Aplicabilidad** (esta norma se aplica a esta clase de producto) | Una persona (`declared`) | `regulatory_requirements` |
| **Existencia y vigencia** (la norma existe y está en vigor) | EUR-Lex (`third_party_verified`, con emisor), sobre una norma que **nosotros nombramos** | `regulatory_anchors` |
| **Evidencia de cumplimiento** (este producto cumple) | Una persona, o quien emitió el certificado (con emisor) | `compliance_evidence` |

### Cuatro estados, y lo que NO significan

`PASS` = *dentro del alcance y de los requisitos declarados y comprobados, Legal no ha
encontrado un bloqueo.* **No** es «producto legal». `REVIEW_REQUIRED` pide una persona.
`BLOCKED` = restricción con la norma verificada y en vigor y sin evidencia. `UNKNOWN` = no hay
nada declarado (o la jurisdicción no la cubre la fuente): **jamás asciende a `PASS`**.
Hacia el ActionGate: `PASS→GO`, `REVIEW_REQUIRED` y `UNKNOWN→REVIEW`, `BLOCKED→NO_GO`.

### Otras reglas

- **Una directiva sola no llega a `PASS`**: verifica el acto de la UE, no la ley nacional que
  la traspone. Hace falta una transposición nacional declarada.
- **Vencer la recomprobación (30 días, `LEGAL_ANCHOR_RECHECK_DAYS`) es política nuestra**, no
  jurídica: pide revisión y **no** dice que la norma haya dejado de estar en vigor.
- **Nunca se bloquea sobre una norma que nadie ha podido confirmar.**
- **Confianza = el techo del eslabón más débil** (`third_party_verified` 0,8 · `declared`
  0,6), reglas internas **no calibradas**; construir una evaluación que las supere falla.
- **OWNER y ADMIN** declaran, sustituyen y retiran requisitos y aportan evidencia
  (`REGULATORY_WRITE`); REVIEWER solo lee; **SYSTEM no puede**.
- Modificar es **sustituir** (la fila anterior se conserva); la evidencia no se traslada.

### Qué es real y qué es demostración

| Real | Demostración |
|---|---|
| Vigencia, fechas, ELI y tipo de acto de una norma que una persona declaró, leídos de Cellar con su fecha | El agente simulado y `MockRegulatoryDirectory` (con `REGULATORY_PROVIDER=mock`, el valor por defecto): **mismas cifras que antes**, sin `legal_status` |
| El estado de Legal (`legal_status`) sobre lo declarado | La matriz de requisitos, riesgos y documentos de la pantalla Legal (`lib/demo/legal.ts`), que sigue siendo demo y así se rotula |
| Los requisitos y la evidencia que alguien declare | Los textos de términos y condiciones |

## Qué se ve

En la pantalla Legal, una tarjeta **«Requisitos regulatorios de la UE»** con el resultado
real (título, motivos, aviso) y, por cada requisito, **tres bloques separados**:
1 · Aplicabilidad (quién la declaró) · 2 · Existencia y vigencia (estado, fecha de
comprobación, fechas de la fuente sin interpretar, ELI) · 3 · Evidencia de cumplimiento;
con «Comprobar en EUR-Lex», «Aportar evidencia» y «Retirar», y un formulario para declarar
un requisito. Con un análisis real la cabecera nunca dice «favorable», se oculta la casilla
heredada de certificaciones y el «cumplimiento general» de la matriz demo, y el banner de
decisión de un `PASS` es «SIN BLOQUEO EN LO DECLARADO».

## Migración

`e5f8a2c1b7d4` (encadenada tras `d8b4c1e70a29`; cabeza única): tres tablas nuevas, **sin tocar
`legal_analyses`**. Subida y bajada probadas con datos en
`tests/unit/test_migration_regulatory.py`; el DDL de PostgreSQL se generó con
`alembic upgrade d8b4c1e70a29:e5f8a2c1b7d4 --sql` (modo desconectado). La cadena completa
sobre PostgreSQL real la cubre CI (ver «Lo que NO se verificó»). Bajar elimina lo
declarado, comprobado y aportado.

## Verificación

- **Backend:** `ruff` limpio · `mypy app` limpio (215 ficheros) · `pytest` **1898 passed** (1729 + 169).
- **Frontend:** `tsc --noEmit` limpio · `npm test` **393** (375 + 18) · `eslint .` limpio ·
  `next build --webpack` en copia, sin tocar el `.next` del propietario.
- **Humo real controlado** contra Cellar con base temporal SQLite (nunca `backend/.env`): tres
  normas declaradas (GPSR, la Directiva de Baja Tensión y un CELEX inexistente). Primer intento:
  fallo de la fuente → `REVIEW_REQUIRED`, todo «nunca comprobada», **nada guardado**. Segundo:
  GPSR en vigor (reglamento, dos fechas de entrada en vigor); la directiva en vigor pero
  `REVIEW_REQUIRED` por falta de transposición; el CELEX inexistente `not_found`. Con evidencia
  declarada solo en GPSR y las otras dos retiradas: `PASS` → `GO`, confianza 0,6.
- **Inspección visual** (DOM y consola, no captura: el panel del navegador se congela con la
  ventana oculta): tarjeta, tres bloques, formulario con validaciones, cabecera sin
  «favorable», sin errores de consola.

## Llamadas externas y coste

Todas gratuitas y anónimas, contra `publications.europa.eu`: **2** de sondeo previo al
código (fuera del medidor), **6** en la prueba de humo (registradas por el `CostMeter`, 0 €,
3 con fallo) y **2** al sembrar la inspección visual (a través de la API del propio sistema).
**Total 10 llamadas, 0 €.** Ninguna cuenta, credencial ni servicio contratado.

## Lo que NO se verificó

- **CI de GitHub Actions**: no se ha hecho `push` (lo autoriza el propietario), así que la cadena
  de 32 migraciones sobre PostgreSQL limpio no se ha ejercido con esta migración.
- **Migración contra PostgreSQL/Supabase real**: no hay PostgreSQL en esta máquina.
- El **rol real** (403 con un token de REVIEWER/SYSTEM) lo cubren los inventarios parametrizados
  contra tokens fabricados, no contra Supabase.
- Ninguna **captura de pantalla** (el panel se congela oculto); se comprobó por DOM.
- Que Cellar mantenga el acceso anónimo y su disponibilidad: no hay SLA ni cuota publicada.

## Limitaciones y deuda

- **Solo Derecho de la UE.** Cualquier otro mercado sale `UNKNOWN`. Sin BOE ni Safety Gate
  (aplazados).
- **La transposición nacional solo puede ser `declared`**: no hay fuente de Derecho nacional.
- **`PASS` puede ser optimista si la lista declarada está incompleta.**
- El mapa de tipos de acto solo cubre `REG*` y `DIR*`; lo demás pide revisión.
- **La UI no tiene «modificar»**: sustituir un requisito solo existe en la API.
- Sin textos de artículos, sin traducciones, sin búsqueda de normas.
- La evidencia no se traslada al sustituir un requisito.
- Los motivos del análisis los redacta el backend en inglés y la pantalla los muestra tal cual.
- Cellar puede tardar más de 20 s o dar 504: el sistema lo degrada a `REVIEW_REQUIRED`, pero un
  análisis con la fuente caída no concluye nada.
- Sigue en demo, deuda ya registrada: el resto del panel Legal, la matriz de requisitos, los
  riesgos, las certificaciones de proveedor (§21 del `system-overview`).
