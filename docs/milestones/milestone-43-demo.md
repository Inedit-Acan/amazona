# Milestone 43 — Transposición nacional anclada en el BOE

**Fecha:** 30-09-2026 · **ADR:** [0021](../architecture/adr-0021-national-transposition-boe.md)
· **Depende de:** [0008](../architecture/adr-0008-demo-production-isolation.md)
· [0011](../architecture/adr-0011-action-gate.md)
· [0015](../architecture/adr-0015-multiple-real-sources-cost-and-usage-rights.md)
· [0017](../architecture/adr-0017-supplier-facts-and-risk.md)
· [0018](../architecture/adr-0018-money-conversion-and-not-evaluable.md)
· [0019](../architecture/adr-0019-legal-requirements-and-source-anchoring.md)

**Presupuesto: 0 €. Ninguna cuenta, credencial ni servicio de pago.** Las únicas llamadas
externas reales son consultas anónimas y gratuitas a la API de datos abiertos de la AEBOE
(ver «Llamadas externas»).

## La regla

**El sistema no infiere qué norma española traspone una directiva ni qué norma se aplica a
un producto.** Una persona declara la relación; el BOE solo la verifica y la ancla. No hay
búsqueda (no se usa el endpoint de lista), no hay propuesta y no hay LLM.

## Lo que se encontró al revisar (29-09-2026)

- **Sin alta, sin credenciales y sin cuota publicada.** Ni el aviso legal, ni la documentación
  técnica (2-09-2025), ni las FAQ publican un límite. La AEBOE puede suspender el acceso sin
  aviso y no garantiza la continuidad.
- **Licencia:** reutilización comercial y transformación permitidas, con cita («Basado en datos
  de la Agencia Estatal Boletín Oficial del Estado»), aviso expreso de que la legislación
  consolidada es **meramente informativa**, fecha de actualización y no sugerir que es oficial.
- **Cuatro capas distintas:** publicación oficial (el diario; auténtico desde 2009),
  legislación consolidada (sin valor oficial), análisis jurídico (informativo) y metadatos/ELI.
- **El análisis del BOE dice qué directiva traspone una norma.** El Real Decreto 1205/2011
  (juguetes) trae `426 TRANSPONE` hacia `DOUE-L-2009-81173`, con el texto «la Directiva
  2009/48/CE, de 18 de junio de 2009». Es informativo y está escrito en texto.
- **Un `404` no distingue «no consolidada» de «no existe»**: comprobado con un identificador
  que consta en el sumario del día y da 404 en la colección.
- **El identificador `BOE-A-AAAA-NNNNN` es único, pero su número es un control interno**; el
  enlace estable es el ELI.
- **La consolidación va entre 1 y 3 días por detrás** de una modificación
  (`estado_consolidacion = 4`, «desactualizado»).

## Qué cambia

| | |
|---|---|
| **Puerto** | `NationalNormSource` (hermano de `RegulatoryAnchorSource`, que no se toca) |
| **Adaptador** | `app/integrations/regulatory/boe.py`: `metadatos`, `analisis` y `sumario`; `User-Agent` neutro |
| **Dominio** | `app/legal/national.py`: corroboración determinista, estados de la norma nacional |
| **Reglas** | `assess_requirement` recibe las transposiciones estructuradas: una directiva solo llega a `PASS` con norma verificada y corroborada |
| **Datos** | `national_transpositions` (la norma declarada) y `national_anchors` (lo que dijo el BOE); una migración (`b6d2f8a41c93`) |
| **API** | `POST /api/regulatory-requirements/{id}/national-transpositions`, `POST /api/national-transpositions/{id}/verify` y `/withdraw` (`REGULATORY_WRITE`); el listado de requisitos las incluye |
| **Derechos y coste** | `boe-open-data`, escritos antes de la primera llamada; `AI_INGESTION` denegado |
| **Interfaz** | Bloque «Transposición nacional (BOE)» en el panel Legal con el aviso «meramente informativo», la atribución, el enlace oficial y el ELI |
| **Configuración** | `NATIONAL_LAW_PROVIDER=mock|real` (`mock` por defecto) |

### Las capas (ADR 0021 §2)

| Capa | Quién la sostiene |
|---|---|
| Norma declarada | Una persona (`declared`) |
| Publicación oficial | El sumario del diario; comprobación **auxiliar** |
| Texto consolidado, análisis y metadatos | La AEBOE; **informativos** |
| Vigencia y estado | Las banderas de la fuente (`S`/`N`), sin interpretar fechas |
| Relación con la norma UE | La relación `426` del análisis + comparación determinista con el CELEX |
| Evidencia de cumplimiento | Una persona o el emisor (M41) |

### Reglas que conviene recordar

- **`PASS` de una directiva** = norma declarada + verificada + en vigor + sin relaciones de
  anulación o suspensión + **corroborada (`426`)** + evidencia de cumplimiento. Todo lo demás
  es `REVIEW_REQUIRED` (nunca `BLOCKED`).
- **Se endurece M41:** el texto libre `transposition_reference` se conserva pero **ya no
  basta**. Hay un test de M41 cambiado a propósito por esto.
- **`427` (parcial), relación ilegible o ambigua y análisis que no la menciona → revisión.**
  La comparación con el CELEX solo se hace si año y número se leen sin ambigüedad; si un texto
  nombra más de un acto de la UE, no se compara. Nada de similitud textual.
- **`404` → `REVIEW_REQUIRED`** con su motivo. Nunca «no existe».
- **Todo o nada:** metadatos y análisis o nada. El sumario es auxiliar: si falla se guarda
  `check_failed` (no es una conclusión); solo un sumario leído bien que no lista la norma da
  `absent_from_summary`, y eso sí pide revisión.
- **Fechas de la fuente tal cual** (`AAAAMMDD`), **sin compararlas con hoy**. Relaciones
  `220`, `221`, `230` y `231` se muestran y piden revisión, sin interpretar su efecto.
- **Confianza:** lo que descansa en datos informativos del BOE no supera **0,7** (regla interna
  no calibrada).
- **Privacidad:** el `User-Agent` es `KOVA-Regulatory-Client/0.1`. Sin nombre, correo ni ningún
  dato personal, y un test lo impide.

## Qué es real y qué es demo

- **Real:** la verificación de una norma nacional contra el BOE (`boe-open-data`,
  `third_party_verified` con la salvedad de que es informativa), su auditoría y su coste.
- **Sin cambios:** con `NATIONAL_LAW_PROVIDER=mock` no se llama a nadie; con
  `REGULATORY_PROVIDER=mock` el análisis de Legal es exactamente el de siempre. El resto del
  panel Legal sigue siendo demo y así se rotula.

## Verificación

- **Backend:** `ruff` limpio; `mypy` limpio (223 ficheros); **2234 pruebas pasan** con `pytest`
  a secas (lo que corre CI) y con `python -m pytest` (2033 anteriores + 201 nuevas).
- **Frontend:** `tsc` y `eslint` limpios; **414 pruebas pasan, 0 fallan** (401 + 13 nuevas).
- **Build:** `next build --webpack` correcto, en copia sobre la misma unidad; la copia y su
  junction se retiraron y se comprobó que `node_modules` (513 entradas) y `.next` del
  propietario siguen ahí.
- **Migración:** una cabeza (`b6d2f8a41c93` sobre `e5f8a2c1b7d4`). Prueba aislada arriba y
  abajo **con datos dentro** (`test_migration_national.py`, esquema previo congelado a mano),
  clave foránea comprobada, y el DDL de PostgreSQL generado con `alembic upgrade
  e5f8a2c1b7d4:b6d2f8a41c93 --sql` (y la bajada). La cadena entera de 33 revisiones sobre
  PostgreSQL limpio la ejerce CI.
- **Pruebas nuevas:** respuestas **reales** del BOE como fixtures (norma vigente, análisis con
  `426`, norma derogada, 404 y sumario recortado): `426` coincidente, `427` parcial, relación
  no parseable o ambigua, directiva distinta, no directiva, norma derogada, cada bandera,
  desactualizada, banderas ausentes, `404`, nunca comprobada, recheck vencido, relaciones de
  anulación o suspensión, sumario que no la lista, sumario inaccesible o ilegible con
  metadatos válidos, fecha de vigencia futura no comparada, error de red, HTTP inesperado,
  JSON o XML inválido, cuerpo enorme, presupuesto denegado sin red, identificador inválido sin
  red, `User-Agent` neutro, solo tres endpoints (nunca lista ni texto), todo o nada, el texto
  nunca se guarda, derechos y coste antes de la red, ausencia de evidencia de cumplimiento,
  directiva sin transposición, texto libre solo, `PASS` con techo 0,7, `mock` idéntico,
  endpoints (200/404/409/422/429/502) y análisis de Legal de extremo a extremo.
- **Inventarios:** `test_api_authorization.py` actualizado con las tres rutas nuevas (concretas
  y de plantilla). `test_permission_matrix.py` y `test_api_read_authorization.py` no cambian
  (mismo permiso `REGULATORY_WRITE`, ninguna lectura nueva). Los inventarios del frontend pasan
  sin tocarse.
- **Prueba de humo real** (esquema `create_all` en SQLite en memoria; nunca `backend/.env`; EUR-Lex
  sustituido por una fuente falsa): el Real Decreto 1205/2011 sale `consolidated`, publicación
  `confirmed`, banderas `N/N/N`, **corroborada** (`426 TRANSPONE la Directiva 2009/48/CE`), y el
  análisis de Legal con evidencia declarada da **`PASS` / `GO` con confianza 0,6**; un
  identificador publicado pero no consolidado da `consolidated = false`; la Ley 30/1992 sale
  derogada (`S`, 20210402). Seis peticiones, todas en el libro de coste.
- **Inspección visual** (DOM y consola; copia de compilación contra una SQLite desechable
  sembrada con las respuestas reales guardadas): el bloque muestra norma declarada, «En vigor
  según el BOE», «426 TRANSPONE», «El BOE dice: TRANSPONE la Directiva 2009/48/CE…», fechas
  `20110831` / `20110901` sin interpretar, publicación confirmada, el aviso «meramente
  informativo», la atribución, «Publicación oficial» y ELI; y una segunda norma sin comprobar.
  Sin errores de consola.

## Llamadas externas y coste

Todas gratuitas y anónimas, contra `www.boe.es`:

- **Investigación previa al código:** unas **14 peticiones directas** a la API y **1** a una
  página de documento, y **4 lecturas de páginas de documentación** (datos abiertos, aviso
  legal, PDF técnico y FAQ). **Todas las directas llevaron por error el correo del propietario
  en el `User-Agent`** (campo «contact»); no debía haber salido. Solo lo ve BOE en sus registros
  de acceso. **El código de producción no lo hace** (`KOVA-Regulatory-Client/0.1`, con un test
  que lo impide) y se guardó como regla de trabajo.
- **Prueba de humo:** **6** peticiones con el identificador neutro, registradas por el
  `CostMeter`.
- **Pruebas automáticas e inspección visual:** ninguna a la red.

**Total ≈ 21 peticiones directas, 0 €.** Ninguna cuenta, credencial ni servicio contratado.

## Lo que NO se verificó

- **CI de GitHub Actions:** no se ha hecho `push` (lo autoriza el propietario), así que la
  cadena de migraciones sobre PostgreSQL limpio no se ha ejercido con esta migración.
- **Migración contra PostgreSQL/Supabase real:** no hay PostgreSQL en esta máquina; se generó
  el DDL.
- **El rol real** (403 con un token de REVIEWER/SYSTEM) lo cubren los inventarios contra tokens
  fabricados, no contra Supabase.
- **Ninguna captura de pantalla** (el panel se congela oculto); se comprobó por DOM.
- Que el BOE mantenga el acceso anónimo, su formato ni su disponibilidad: no hay SLA ni cuota
  publicada. **La cobertura para las normas que realmente se declaren**: solo se probó con dos
  normas reales (una vigente y una derogada) y con un identificador no consolidado.
- **Concurrencia real** de dos verificaciones simultáneas.

## Desviaciones y decisiones de interpretación

- **El sumario es auxiliar** aunque se pidió «tres consultas, una observación coherente». Se
  interpretó así: metadatos y análisis son el núcleo (todo o nada); el sumario se guarda con su
  propio estado explícito, y un fallo suyo (`check_failed`) no degrada la norma ni cuenta como
  conclusión.
- **`NATIONAL_LAW_PROVIDER` usa `mock|real`** (`ProviderKind`, coherente con
  `EXCHANGE_RATE_PROVIDER`); `real` es el BOE.
- **Endurece M41:** con `REGULATORY_PROVIDER=real`, una directiva con solo texto libre pasa de
  `PASS` a `REVIEW_REQUIRED`. Un test de M41 se cambió por esto.
- **La interfaz decide «es una directiva» por el CELEX** y no por lo que EUR-Lex haya dicho,
  para poder declarar la norma antes de la primera comprobación.

## Limitaciones y deuda

- **Solo transposición de una directiva ya declarada.** Sin Derecho nacional genérico
  (jurisdicción `es` sin CELEX), sin búsqueda normativa, sin inferencia de aplicabilidad.
- **Cobertura del BOE incierta:** un real decreto u orden no consolidado da `404` y queda en
  revisión.
- **El análisis del BOE es informativo y puede omitir la relación `426`** aunque exista la
  transposición: baja a revisión, no bloquea. Una relación con un texto que nombra varias
  directivas no se compara.
- **Derogaciones parciales:** las banderas son de la norma entera; solo se elevan las
  relaciones `220`/`221`/`230`/`231` y sin interpretar su efecto.
- **Una transposición no se traslada** si el requisito se sustituye.
- **Sin planificador:** la comprobación es una acción de OWNER/ADMIN o la del análisis al vencer
  la política de 30 días; nada la dispara sola.
- Las razones de evaluación las redacta el backend en inglés y la pantalla las muestra tal cual.
- Sigue en demo, deuda ya registrada: el resto del panel Legal, la matriz de requisitos, los
  riesgos y las certificaciones de proveedor.
