# Milestone 46 — Procedencia estructurada del dinero, fronteras numéricas, estados de lectura y una interfaz que no dice más de lo que sabe

**Estado: M46 CERRADO.** **Fecha:** 12-10-2026 → 14-10-2026 · **ADR:** [0031](../architecture/adr-0031-structured-money-provenance.md)
· **Depende de:** [0028](../architecture/adr-0028-orders-payments-fulfilment-core.md)
· [0029](../architecture/adr-0029-scheduled-reconciliation-and-unknown-outcome-authority.md)
· [0030](../architecture/adr-0030-verified-revenue-ledger.md) · **Sigue a:** [Milestone 45](milestone-45-demo.md)

**Presupuesto: 0 €. Ninguna cuenta, credencial, pasarela, proveedor ni transportista reales.** Ninguna prueba sale de la máquina (una
guarda de `backend/tests/conftest.py` lo hace cumplir). **M46 no tocó Supabase**: sus migraciones, incluida la de este milestone, no
están aplicadas allí (§«Supabase»).

## La regla

**Una interfaz no puede elevar el nivel de certeza de un dato, y un hecho de pago verificado no dice, por sí solo, de dónde vino el
dinero.** M45 dejó el dinero bien guardado y bien contado, pero con una limitación declarada: «Registro verificado» no era «real»,
porque el registro no guardaba si el cobro lo hizo un simulador, un entorno de pruebas o un proveedor real. M46 la resuelve y
endurece lo que la rodea, en tres frentes:

1. **El origen del dinero es un hecho persistido y estructurado** (`mock` / `sandbox` / `real`), distinto de la procedencia de la cifra
   (`verified` / `declared` / `planned` / `demo`). Nunca se deduce del pedido, de la configuración ni de un nombre, y ninguna cifra
   suma orígenes distintos.
2. **Las fronteras de entrada y de lectura dicen la verdad**: una entrada inválida es un 422, no un 500; un error de lectura no es un
   dato; y una lectura sin hacer no es «Sin datos».
3. **Ninguna etiqueta afirma más de lo que el sistema sabe**: «real», «verificado», «aprobado» o «activo» solo donde el dato lo respalda.

## Qué se construyó

13 commits de M46 sobre `98ffad5` (el cierre documental de M45), contando el de documentación de la línea base de Supabase y el
arreglo de CI del Commit 7; **este documento es el Commit 9**. Cada uno publicado con su CI revisado job por job. **El único CI en
rojo** fue el del Commit 7 (`8fef209`: una prueba anterior fijaba las claves exactas de un proyecto y la guarda nueva de moneda
llevaba un `\b` escrito como carácter de retroceso); lo corrigió `88043da` sin tocar comportamiento, y se añadió una regla de proceso (§«Reglas de
proceso»). Hasta `41d3f9e`, **164 ficheros, +13 214 / −1 211 líneas**: **29 ficheros de `backend/app`, +977 / −121** (el código del
producto), **44 ficheros de pruebas de backend, +6 655 / −67**, **83 ficheros de Control Center** y **una sola migración**.

| # | Commit | Qué | Evidencia |
|---|---|---|---|
| A | `36a9f3f` | **FASE A**: línea base de Supabase corregida (`alembic_version = e1b8d4a62f37`, faltaban 6; el «faltan 24» estaba desactualizado) | solo documentación |
| 1 | `0c19fc5` | **ADR 0031**: procedencia estructurada con dos ejes, evidencia y origen operativo | solo documentación |
| 2A | `296fa8c` | migración 44.ª (`b7e4a1c9d052`): `provider_kind` en `payments`, `payment_events` y `revenue_ledger_entries`; el origen viaja desde el proveedor (`PaymentProvider.kind`) hasta el registro; el emparejado exige el mismo origen | CI verde |
| 2B | `6aa73f0` | `check_ledger` C5 y C6, la prueba que prohíbe deducir el origen, caos y mutaciones | CI verde |
| 3 | `2aabc21` | la API devuelve el origen: agregados **por origen**, filtro `?provider_kind=`, sin ningún total que cruce orígenes | CI verde |
| 4 | `5ec188d` | el Control Center muestra el origen sin inferirlo ni mezclarlo (`Verified<T, O>`, `addVerified` que no compila con orígenes distintos); el margen es por origen; se retira «Real» | CI verde |
| 5 | `af88017` | un canal no declarado en `POST /api/economics/runs` es un 422, no un 500 | CI verde |
| 5b | `f259f1d` | precio de venta > 0 y costes fijos ≥ 0; la procedencia de un tipo de cambio es el enum canónico | CI verde |
| 5c | `e690593` | entradas numéricas finitas, tipadas y representables (`NaN`/`Infinity`, `bool`, desbordes), paridad economics/pipeline/tipos de cambio y manejador global del 422 | CI verde |
| 6 | `cb78fc0` | las **9 lecturas silenciosas del Panel** → estados de lectura `loaded` / `empty` / `unread` / `error`, con «Reintentar» manual | CI verde |
| 7 | `8fef209` + `88043da` | `ProjectOut.created_at` (la fecha de inicio es la persistida); `finance_validation.currency` **no existe y no se inventa** | CI rojo y corregido |
| 8 | `41d3f9e` | **vocabulario de certeza**: «real»→«del backend», insignia `recorded`, GO/NO_GO = «Favorable»/«No viable», READY = «Preparada», «Sin error registrado» y DEMO donde faltaba | CI verde |
| 9 | este | documentación de cierre (`system-overview`, este documento, ADR 0031 §31) | solo documentación |

### Lo nuevo, de un vistazo

- **1 migración** (cadena: `… → e5a1d7c93b04` [M45] → `b7e4a1c9d052`): la columna `provider_kind` con su relleno, sus restricciones
  (`CHECK`, `UNIQUE (id, provider_kind)`, claves ajenas compuestas) y los disparadores que impiden que un cobro, un evento y una
  entrada del registro discrepen de origen. **No hay tablas nuevas.**
- **Backend:** el origen entra por **una sola puerta** (`PaymentIngress`, que exige un adaptador con tipo estructurado) y se copia,
  sin recalcularse, del cobro al evento y del evento a la entrada. Los agregados salen **siempre separados por origen**.
- **Control Center:** un único vocabulario (`lib/provenance.ts`) para procedencia y para origen; `lib/read-state.ts` (los cuatro
  estados de una lectura); la insignia `recorded` («Registro del backend»); y tres guardas que leen el código
  (`origin-boundary`, `read-boundary` y `certainty-boundary`).
- **Fronteras de entrada:** economics, pipeline y tipos de cambio rechazan lo inválido con un 422 explícito y con la **misma
  respuesta** en los tres endpoints.

## Decisiones tomadas

| Decisión | Quién / dónde | Consecuencia |
|---|---|---|
| **Dos ejes**: la procedencia de la cifra y el origen del dinero son ortogonales | ADR 0031 | «Registro verificado» no afirma nada sobre el origen; el origen no afirma nada sobre la liquidación |
| **El origen se persiste, no se deduce** (ni de `Order.is_simulated`, ni de la configuración, ni de un nombre) | ADR 0031 §4, Commit 2 | Un adaptador sin tipo no abre cobros ni recibe eventos; una prueba arquitectónica impide el uso prohibido |
| **Orígenes distintos son magnitudes distintas** | ADR 0031 §11–12, Commits 3 y 4 | No hay «todo sumado»: `addVerified` no compila con orígenes literales distintos y lanza con orígenes de datos |
| **Una entrada inválida es un 422 en la frontera, nunca un 500** | Commits 5, 5b, 5c | Una sola regla de «representable como `Money`»; el techo técnico se documenta, no se escribe como constante |
| **Un error de lectura no es un dato**, y una lectura sin hacer tampoco | Commit 6 | `error` y `unread` nunca producen un cero, una lista vacía ni «Sin datos»; la demostración solo aparece con un log válido y vacío |
| **La fecha de inicio de un proyecto es su `created_at` persistido**, sin respaldo | Commit 7 | Un proyecto sin decisión también tiene fecha; la auditoría solo fecha los hitos |
| **`finance_validation` no declara moneda: no se añade columna, ni migración, ni `EUR` por defecto** | Commit 7 | La proyección sigue sin símbolo monetario; un test fija que la evidencia no trae moneda |
| **Una recomendación no es una aprobación; un estado técnico no es «activo»** | Commit 8 | GO/NO_GO son «Favorable»/«No viable»; la aprobación humana sigue siendo `HUMAN_APPROVAL` |

## Verificación (cifras del CI del último commit de código)

- **CI de `41d3f9e`, run `38576905734`: success.** Backend **5114 pasadas, 7 omitidas, 1 warning** (745 s) y Control Center
  **996/996** con build de **20/20** páginas. (Cierre de M45: 4229 y 642; +885 y +354.)
- **Warnings, todos heredados:** el `StarletteDeprecationWarning` del backend y, en Control Center, `MODULE_TYPELESS_PACKAGE_JSON`,
  `punycode`, `url.parse` y `eslint` deprecado.
- **Las 7 omitidas** son, como en M45, la variante de SQLite de pruebas que solo tienen sentido en PostgreSQL; su variante
  `[postgres]` se ejecuta y pasa en el CI.
- **Migraciones sobre PostgreSQL limpio:** 44 revisiones hasta `b7e4a1c9d052`, en el CI y en la ejecución local del backend completo
  contra una PostgreSQL desechable.
- **Mutaciones:** los Commits 6, 7 y 8 cierran con **38/38**, **22/22** y **44/44** detectadas (las de los anteriores están en los
  addenda de la ADR 0031). Varias primeras pasadas dejaron supervivientes que eran huecos reales de la batería y se cerraron con prueba.
- **Una vigilancia contra bytes de control** (`tests/unit/test_no_control_bytes_in_sources.py`) cubre el código y las pruebas.
- **Ningún cambio de código ni de pruebas en el Commit 9:** el árbol de código es byte a byte el del Commit 8.

## Supabase (solo lecturas, 14-10-2026)

- `alembic_version` de Supabase = **`e1b8d4a62f37`** (una sola fila). La lista `supabase_migrations` sigue en 12.
- El repositorio tiene **44 revisiones**, con un único *head*: **`b7e4a1c9d052`**. **Le faltan 7**, no 6 ni 24: `f6a1c8d3e925`,
  `a9d2e7b4c136`, `b3c8f1a5d742` (M44), `d7e2a9c4f1b8`, `c4e8b1d9a273`, `e5a1d7c93b04` (M45) y `b7e4a1c9d052` (M46). Se comprueba con
  `alembic history -r e1b8d4a62f37:head`.
- **54 tablas en `public`** (53 de aplicación más `alembic_version`). Los modelos declaran 61: **faltan 8**, todas de M44 y M45:
  `orders`, `order_items`, `payments`, `payment_events`, `refunds`, `fulfillments`, `fulfillment_items` y `revenue_ledger_entries`.
- **M46 no migró Supabase.** Las tablas funcionales de M44/M45 **no existen** en la base real y, mientras no se aplique la Fase B,
  ninguna prueba contra ella puede recorrer un pedido, un cobro ni el registro de ingresos. Las columnas de M46 no tienen filas que
  rellenar allí (las tablas no existen).
- La Fase B sigue **pendiente**: se rehace con **7 revisiones**, con autorización expresa, copia previa y ensayo en local antes.

## Las tres pruebas, y en qué punto está cada una

| Prueba | Estado |
|---|---|
| **1 · Primera prueba integral LOCAL** (arranque → decisión → pedido → cobro simulado y verificado → registro → fulfillment → reconciliación → Panel → Finanzas → Proyectos, sobre una PostgreSQL local desechable) | **Superada.** Se ensayó entera el 04-10-2026 (M45) y la misma cadena está automatizada por HTTP en `backend/tests/integration/test_m45_end_to_end.py`, que se ejecuta en el CI de cada commit, M46 incluido. La guía manual [`milestone-45-integral-test.md`](milestone-45-integral-test.md) lleva una nota de vigencia con lo que M46 cambió en pantalla; **el recorrido manual completo no se ha repetido tras M46**. |
| **2 · Primera prueba sobre INFRAESTRUCTURA REAL** (la misma cadena sobre Supabase) | **Pendiente.** Exige aplicar y validar la Fase B (7 revisiones) y un usuario de prueba para la sesión real. |
| **3 · Prueba COMERCIAL real** (un cobro de verdad) | **Posterior.** Exige un adaptador de pasarela, proveedor y transportista que no existen, credenciales, presupuesto autorizado por el propietario y los controles del apartado «Bloqueos» del [Milestone 45](milestone-45-demo.md). |

**Qué está listo para probar en local hoy:** el backend completo contra una PostgreSQL desechable (`pytest`, con `DATABASE_URL`
apuntando a ella: sin una PostgreSQL local se omiten las pruebas que la necesitan, y por eso un `pytest` a secas no basta antes de
publicar), el Control Center (`npm test`, `next build`) y el recorrido manual de la guía. **Atención:** `iniciar-amazona.bat` arranca
el backend con `backend/.env`; si ese fichero apunta a Supabase, el backend que arranca **lee y escribe en Supabase**. Para probar,
usa la base local desechable de la guía y nunca el lanzador.

## Deuda residual (solo lo que sigue siendo verdad)

| Deuda | Detalle |
|---|---|
| **35 lecturas silenciosas fuera del Panel** | 32 de negocio (`approvals` 8, `status` 6, `ceo` 3, `economics` 3, `legal` 3, `audit` 2, `research` 2, `neural-nexus` 2, `agents` 1, `operations` 1, `sourcing` 1) y 3 de otra naturaleza (`auth-server` ×2, `kill-switch-control`). El trinquete `REMAINING_SILENT_READS` fija el número y solo puede bajar; la infraestructura (`readList`, `ReadState`, `ReadErrorNotice`, `RetryButton`) está lista para reutilizarse |
| **Test intermitente `lib/intent-key.test.ts`** («la clave es opaca…») | Comprueba que una clave **aleatoria** no contiene fragmentos como «ana» o «600» y, por azar, a veces los contiene: un rojo falso, ocasional. Pendiente de un commit aparte |
| **El worker ante un fallo de base de datos a mitad de un paso** | Su manejo de `PendingRollbackError` sigue sin ser robusto (defecto propio del worker, documentado en el Commit 5c): solo se impide que una entrada inválida lo alcance |
| **Límites técnicos de `Numeric` y `Money` y deuda multidivisa** | Con precisión 28 y 4 decimales, y columnas `Numeric(12, 4)`, un precio ≥ ~1e8 se rechaza con un 422 (antes, un 500 en PostgreSQL): una **limitación del esquema**, no una política. El caso de `VND`, de la deuda multidivisa, sigue sin resolver (ADR 0031 §27) |
| **Ausencia de política comercial de máximos** | Hoy el techo es el técnico. Un máximo de negocio para precios, costes, presupuestos y volúmenes no está definido |
| **`finance_validation.currency` no existe** | La proyección de Proyectos va sin símbolo ni total. Solo se denominará cuando el especialista de finanzas declare una moneda real |
| **Derivaciones de Auditoría** | `resultOf` y `criticalityOf` (en `lib/audit-view.ts`) **infieren** el resultado y la criticidad del nombre de la acción: se corrigió cómo se llaman («Sin error registrado»), no la derivación |
| **`Project.status = APPROVED`** | Lo asigna el orquestador automáticamente ante `GO`, sin persona; se mantiene como estado técnico del backend |
| **Contenido de ejemplo de la tienda y `lib/demo/**`** | Textos de demostración («Pago seguro», «Envío gratis»…) no barridos más allá de lo rotulado; `components/cash-flow-chart.tsx` («Saldo real») no se usa en ningún sitio |
| **Heredadas de M45** | Agregados de backend para el CFO, relación producto ↔ proyecto y reparto del ingreso, gasto sin moneda ni lectura, cierre de un cobro `OPEN` sin evento, y las condiciones de la ADR 0029 antes del primer proveedor real |

**Cerradas por M46** (y ya no son deuda): la procedencia estructurada SIMULATED/REAL, las 9 lecturas silenciosas del Panel, el 500 de
un canal desconocido, el `ProjectOut` sin `created_at` y los textos que afirmaban más de lo que se sabía.

## Qué queda fuera de M46, expresamente

La Fase B de Supabase; cualquier pasarela, proveedor o transportista reales; la prueba comercial real; la política de máximos de
negocio; la relación producto ↔ proyecto; el resto de lecturas silenciosas; la pantalla del Director ejecutivo / CEO IA; IVA/OSS,
facturas y contabilidad.

## Siguiente orden de trabajo

1. **M46 CERRADO** (este documento).
2. **Nuevo milestone: Director ejecutivo / CEO IA — Control Center.** Tomará como fuente de verdad
   `KOVA_CEO_Dashboard_referencia_aprobada.png` y `KOVA_CEO_IA_Dashboard_Decision_Engine_ESPECIFICACION_MAESTRA.md`. **Esos dos
   ficheros todavía no están en el repositorio** (no existen en `docs/design/` ni en el historial de Git): hay que incorporarlos a
   `docs/design/` antes de empezar, y no se implementa nada de esa pantalla hasta entonces. Este documento no inventa su contenido.
3. **Fase B: migración controlada de Supabase** (7 revisiones), con autorización expresa, copia previa y ensayo en local.
4. **Primera prueba integral sobre infraestructura real.**

## Reglas de proceso (aprendidas en M46)

- **Los hashes de Git se obtienen con `git rev-parse HEAD` y `git rev-parse origin/main`; no se transcriben a mano desde mensajes.**
  Un hash tecleado salió con un carácter de más en los Commits 7 y 8.
- **Antes de publicar:** la suite de backend **completa** contra una PostgreSQL local desechable (las pruebas que la necesitan se
  omiten sin ella; el Commit 7 dejó el CI en rojo por una de ellas) y `tests/unit/test_no_control_bytes_in_sources.py`; comprobar
  que ningún fichero editado contiene el byte `0x08` (una herramienta puede convertir `\b` en un carácter de retroceso).
- **Un único commit por responsabilidad**, CI completo revisado job por job entre commits, y publicación solo con autorización
  expresa; un CI en rojo se clasifica antes de concluir nada y no se reintenta buscando verde.
- **No matar procesos ajenos** ni asumir quién escucha en un puerto: antes de una prueba visual, comprobar con
  `Get-NetTCPConnection -LocalPort <puerto>` quién lo tiene (el backend y el frontend de desarrollo del propio usuario pueden estar
  en marcha).
