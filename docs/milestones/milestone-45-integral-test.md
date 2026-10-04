# Primera prueba integral local de AMAZONA / KOVA (Milestone 45)

Una persona puede ejecutar esto **a mano, de principio a fin, en unos 30–40 minutos**, sobre su máquina. Recorre toda la cadena:

> arranque → investigación y decisión → pedido → cobro simulado y verificado → registro de ingresos → fulfillment →
> reconciliación → Panel → Finanzas → Proyectos

y dice, en cada paso, **qué debe observarse y qué resultado es PASS o FAIL**. Se ensayó entera el **04-10-2026** sobre PostgreSQL 17
local desechable (borrada al terminar), con el backend real y el Control Center real; las cifras de abajo son las que salieron.

> **⚠ Nunca contra Supabase.** Todo lo de aquí escribe datos de prueba. La base es una **PostgreSQL local, vacía y desechable**.
> `backend/.env` apunta a Supabase: **por eso el backend se arranca desde una carpeta sin `.env` y con las variables de entorno
> puestas**, y por eso cada bloque empieza comprobando que `DATABASE_URL` contiene `127.0.0.1`. **Coste: 0 €. Ninguna cuenta ni
> credencial.**

## Qué NO prueba

No prueba una pasarela, un proveedor ni un transportista reales (no existen), ni IVA, facturas, clientes o checkout. El «cobro» lo
**simula la consola** emitiendo un evento firmado que entra por la misma puerta que un webhook real. No prueba Supabase (le faltan 24
migraciones: ver [`milestone-45-demo.md`](milestone-45-demo.md)).

## Requisitos

- Windows con **PowerShell 5.1**, Node 20+ (`npm`) y Python 3.12 con el entorno del backend ya instalado
  (`backend\.venv`, `pip install -e ".[dev]"`) y las dependencias del frontend (`npm ci` en `apps\control-center`).
- Un **PostgreSQL local** (cualquiera; el del repositorio de ensayo es portátil, versión 17) y su cliente `psql`.
- Los puertos **8000** (backend) y **3000** (Control Center) libres.
- Sustituye en lo que sigue: `<REPO>` la carpeta del repositorio, `<PGBIN>` la carpeta `bin` de PostgreSQL, `<PUERTO>` su puerto
  y `<CLAVE>` la clave del usuario `postgres` **local** (no la imprimas ni la guardes en ningún fichero del repositorio).

## Paso 0 — Comprobación de seguridad (obligatoria)

En **cada** terminal que vayas a usar, antes de nada:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:<CLAVE>@127.0.0.1:<PUERTO>/amazona_integral"
$env:ENVIRONMENT  = "development"
$env:SUPABASE_URL = ""; $env:SUPABASE_ANON_KEY = ""; $env:SUPABASE_SERVICE_ROLE_KEY = ""
if ($env:DATABASE_URL -notmatch "@127\.0\.0\.1:") { throw "DATABASE_URL no es local: PARA" }
```

**PASS:** no lanza nada. **FAIL / PARA:** si lanza, o si en algún momento ves `supabase.co` en un comando o en un log, detente.

## Paso 1 — Base vacía y migraciones

```powershell
$env:PGPASSWORD = "<CLAVE>"
& "<PGBIN>\psql.exe" -h 127.0.0.1 -p <PUERTO> -U postgres -d postgres -c "DROP DATABASE IF EXISTS amazona_integral" -c "CREATE DATABASE amazona_integral"
Set-Location "<REPO>\backend"
& ".\.venv\Scripts\python.exe" -m alembic upgrade head
& ".\.venv\Scripts\python.exe" -m alembic current
```

**PASS:** termina con `e5a1d7c93b04 (head)` tras **43** líneas `Running upgrade`, la última
`c4e8b1d9a273 -> e5a1d7c93b04`. **FAIL:** cualquier error de migración, o una cabeza distinta.

## Paso 2 — Arrancar el backend (terminal A)

Desde una carpeta **sin `.env`** (aquí la temporal) y con el Paso 0 hecho en esta terminal:

```powershell
New-Item -ItemType Directory -Force "$env:TEMP\amazona-run" | Out-Null
Set-Location "$env:TEMP\amazona-run"
& "<REPO>\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir "<REPO>\backend" --host 127.0.0.1 --port 8000
```

En otra terminal: `Invoke-RestMethod http://127.0.0.1:8000/health` y `.../health/ready`.

**PASS:** `status = ok` en las dos, y `Invoke-RestMethod http://127.0.0.1:8000/api/projects` devuelve una lista **vacía**.
**FAIL:** error de conexión o 500.

*(Opcional: el worker que programa la reconciliación, en otra terminal con el mismo Paso 0:
`& "<REPO>\backend\.venv\Scripts\python.exe" -m app.jobs.worker`. Encola `reconcile.payment_events` cada 2 min y
`reconcile.actions` cada 5. El guion no depende de él: ejecuta la reconciliación a mano en el Paso 11.)*

## Paso 3 — Arrancar el Control Center (terminal B)

```powershell
Set-Location "<REPO>\apps\control-center"
$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8000"
$env:NEXT_PUBLIC_SUPABASE_URL = ""; $env:NEXT_PUBLIC_SUPABASE_ANON_KEY = ""
npm run dev
```

Abre <http://localhost:3000/dashboard>.

**PASS:** el Panel carga. Con la base vacía **no hay ninguna cifra de dinero**: el bloque de ingresos dice que no hay datos, y la
etiqueta «Registro verificado» está visible. **FAIL:** aparece cualquier importe en euros en los ingresos, o un error 500.
*(Nota: `next dev` puede reescribir `apps/control-center/AGENTS.md`; no lo añadas a ningún commit.)*

## Paso 4 — La sesión de órdenes (terminal C, PowerShell)

Un solo bloque que define los gestos. **Cuidado:** `cli` es un alias de `Clear-Item` en PowerShell; por eso la función se llama `Amz`.

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:<CLAVE>@127.0.0.1:<PUERTO>/amazona_integral"
$env:ENVIRONMENT = "development"; $env:AMAZONA_BOOTSTRAP = "1"
$env:SUPABASE_URL = ""; $env:SUPABASE_ANON_KEY = ""; $env:SUPABASE_SERVICE_ROLE_KEY = ""
if ($env:DATABASE_URL -notmatch "@127\.0\.0\.1:") { throw "DATABASE_URL no es local: PARA" }
$api = "http://127.0.0.1:8000"
$py  = "<REPO>\backend\.venv\Scripts\python.exe"

function Post($path, $key, $body) {
  $headers = @{}; if ($key) { $headers["Idempotency-Key"] = $key }
  if ($body) { Invoke-RestMethod -Method Post -Uri "$api$path" -ContentType "application/json" -Headers $headers -Body ($body | ConvertTo-Json -Depth 6) }
  else       { Invoke-RestMethod -Method Post -Uri "$api$path" -Headers $headers }
}
function Amz([string[]]$CliArgs) {          # la consola del backend; los eventos "firmados" se emiten DENTRO de su proceso
  Push-Location "<REPO>\backend"; try { & $py -m app.cli $CliArgs 2>&1 | Select-Object -Last 3 } finally { Pop-Location }
}
function NewOrder($key, $qty, $price, $currency, $withCost) {
  $line = @{ product_id = $ProductId; quantity = $qty; unit_price = @{ amount = $price; currency = $currency } }
  if ($withCost) { $line.supplier_quote_id = $QuoteId; $line.declared_unit_cost = @{ amount = "6.00"; currency = $currency } }
  Post "/api/orders" $key @{ customer_ref = "sim_$key"; market = "eu"; lines = @($line) }
}
```

> **Por qué el cobro se simula con la consola y no con `curl` a `/api/payments/webhooks/…`:** el simulador firma con una clave
> **efímera por proceso**; un humano no puede firmar un webhook desde fuera, y eso es **intencionado** (si pudiera, cualquiera
> podría declarar cobrada una cuenta). Es la misma puerta, el mismo servicio y las mismas reglas que un webhook real.

## Paso 5 — Investigación y decisión (la señal → el proyecto)

```powershell
$research = Post "/api/research/runs" "demo-research-1" @{ category = "home"; max_results = 3 }
$top = $research.candidates[0]; $ProductId = $top.product_id
"candidatos: $($research.candidates.Count)"
"producto: $($top.name)  score=$($top.opportunity_score)  demanda=$($top.data.demand_signal)  competencia=$($top.data.competition_level)"

$ctx = @{
  product_validation = @{ estimated_monthly_searches = [int]($top.data.demand_signal * 15000); competition_level = $top.data.competition_level }
  supplier_sourcing  = @{ unit_cost = 5.0; lead_time_days = 20; supplier_verified = $true }
  finance_validation = @{ unit_cost = 5.0; sale_price = 20.0; monthly_unit_sales = 300; monthly_fixed_costs = 500.0 }
  legal_validation   = @{ restricted_category = $false }
}
$objective = Post "/api/objectives" $null @{ title = "Validar $($top.name)"; created_by = "owner@amazona.local"; context = $ctx }
$decision  = Invoke-RestMethod -Method Post -Uri "$api/api/objectives/$($objective.id)/run"
"decision: $($decision.status)  confianza=$($decision.confidence)  proyecto=$($decision.project_id)"
```

**PASS:** `candidatos` = 3; la decisión es **`GO`** con confianza **0.85** y hay un `project_id`.
**FAIL:** 0 candidatos, un 500, o una decisión distinta de `GO` con este contexto (es determinista).

## Paso 6 — Proveedores (una cotización con coste conocido)

```powershell
$sourcing = Post "/api/sourcing/runs" "demo-sourcing-1" @{ product_id = $ProductId; category = "home"; destination_region = "eu"; max_results = 3 }
$sourcing.quotes | ForEach-Object { "{0}  {1}  {2}" -f $_.data.name, $_.unit_price, $_.currency }
$QuoteId = ($sourcing.quotes | Where-Object { $_.data.name -like "Bratislava*" }).id
```

**PASS:** 3 cotizaciones (Foshan, Bratislava, Monterrey), `provenance = simulated`. `$QuoteId` no está vacío.

## Paso 7 — Pedidos, cobros y eventos verificados

Cinco pedidos, **cada uno para enseñar un caso**. Las claves de idempotencia hacen que repetir un comando no duplique nada.

```powershell
# A · 2 x 25,00 EUR, con coste de proveedor declarado (6,00 por unidad). Un cobro normal.
$a = NewOrder "demo-a" 2 "25.00" "EUR" $true
$payA = Post "/api/orders/$($a.id)/payments" "demo-a-pay"                   # intento OPEN: aún NO está pagado
Amz @("simulate-payment","--order-id",$a.id,"--outcome","succeeded")        # event ...: applied
(Invoke-RestMethod "$api/api/orders/$($a.id)").status                       # PAID

# B · 1 x 30,00 EUR. Un cobro DUPLICADO: el primer intento caduca, el segundo cobra y el primero llega tarde.
$b  = NewOrder "demo-b" 1 "30.00" "EUR" $false
$b1 = Post "/api/orders/$($b.id)/payments" "demo-b-pay1"
Amz @("simulate-payment","--payment-id",$b1.id,"--outcome","expired")
$b2 = Post "/api/orders/$($b.id)/payments" "demo-b-pay2"
Amz @("simulate-payment","--payment-id",$b2.id,"--outcome","succeeded")
Amz @("simulate-payment","--payment-id",$b1.id,"--outcome","succeeded")     # el tardío: se REGISTRA como duplicado

# D · 3 x 10,00 USD. Otra moneda.
$d = NewOrder "demo-d" 3 "10.00" "USD" $false
Post "/api/orders/$($d.id)/payments" "demo-d-pay" | Out-Null
Amz @("simulate-payment","--order-id",$d.id,"--outcome","succeeded")

# E · 1 x 40,00 EUR. Capturan solo 12,50: OTRO IMPORTE.
$e = NewOrder "demo-e" 1 "40.00" "EUR" $false
Post "/api/orders/$($e.id)/payments" "demo-e-pay" | Out-Null
Amz @("simulate-payment","--order-id",$e.id,"--outcome","succeeded","--amount","12.50")
```

**PASS:** cada `simulate-payment` termina en `event <id>: applied`; el pedido A pasa a `PAID` **solo después** del evento;
ningún comando da `Traceback`. **FAIL:** un pedido queda `PAID` sin evento, o un `Traceback`.

## Paso 8 — Reembolsos: uno que cabe y uno que no

```powershell
# C · 1 x 20,00 EUR, cobrado. Reembolso parcial de 8,00 (cabe) y de 13,00 (NO cabe: solo quedan 12,00).
$c = NewOrder "demo-c" 1 "20.00" "EUR" $false
$payC = Post "/api/orders/$($c.id)/payments" "demo-c-pay"
Amz @("simulate-payment","--order-id",$c.id,"--outcome","succeeded")
$rf = Post "/api/orders/$($c.id)/refunds" "demo-c-rf1" @{ payment_id = $payC.id; amount = @{ amount = "8.00"; currency = "EUR" }; reason = "customer_request" }
"reembolso: $($rf.status)"                                                  # SENDING: aún NO está devuelto
Amz @("simulate-refund","--refund-id",$rf.id,"--outcome","succeeded")        # event ...: applied  <- ahora sí
try { Post "/api/orders/$($c.id)/refunds" "demo-c-rf2" @{ payment_id = $payC.id; amount = @{ amount = "13.00"; currency = "EUR" }; reason = "customer_request" } | Out-Null; "ACEPTADO (MAL)" }
catch { "rechazado con HTTP $([int]$_.Exception.Response.StatusCode) (BIEN)" }
```

**PASS:** el reembolso nace `SENDING`; el de 13,00 se **rechaza con HTTP 409**. **FAIL:** se acepta un reembolso que supera lo capturado.

## Paso 9 — Fulfillment del pedido A (el coste de proveedor era conocido)

```powershell
$ordA = Invoke-RestMethod "$api/api/orders/$($a.id)"
$ful  = Post "/api/orders/$($a.id)/fulfillments" "demo-a-ful" @{ lines = @(@{ order_item_id = $ordA.items[0].id; quantity = 2 }) }
"asignado: $($ful.status)"                                                  # READY
"compra: "  + (Post "/api/fulfillments/$($ful.id)/purchase" "demo-a-buy").status   # PURCHASED
"envio: "   + (Post "/api/fulfillments/$($ful.id)/ship"     "demo-a-ship").status  # SHIPPED
"entrega: " + (Post "/api/fulfillments/$($ful.id)/complete" $null).status          # COMPLETED (lo confirma una persona)
"pedido: "  + (Invoke-RestMethod "$api/api/orders/$($a.id)").status                # COMPLETED
```

**PASS:** `READY → PURCHASED → SHIPPED → COMPLETED` y el pedido `COMPLETED`. **FAIL:** un 409 en la compra con el mensaje
«the cost of this action is unknown…» (significa que el pedido se creó **sin** `$withCost`).

## Paso 10 — La API dice lo mismo que dirán las pantallas

```powershell
$s = Invoke-RestMethod "$api/api/revenue/summary"
"entradas: $($s.entries)"
$s.verified     | Format-Table currency, revenue, refunds, net
$s.under_review | Format-Table currency, classification, received
"pendiente: $($s.pending_evidence.count)"
$s.consolidated_eur | Format-List
$s.non_aggregable_currencies | Format-Table currency
```

| Comprobación | Valor esperado |
|---|---|
| `entries` | **7** (6 capturas + 1 reembolso) |
| `verified` EUR | ingresos **100.0000**, reembolsos **8.0000**, neto **92.0000** (= 50 + 30 + 20) |
| `verified` USD | ingresos **30.0000**, reembolsos 0, neto 30.0000 — **aparte** |
| `under_review` | EUR `DUPLICATE_RECEIPT` **30.0000** y EUR `MISMATCH_RECEIPT` **12.5000** |
| `pending_evidence.count` | **0** |
| `consolidated_eur` | revenue 100.0000 · net 92.0000 · `under_review_outstanding` **42.5000** (30 + 12,5) |
| `non_aggregable_currencies` | `USD` |

**PASS:** todas las filas coinciden. **FAIL:** el duplicado (30,00) o el de otro importe (12,50) cuentan dentro de los 100,00; el
USD aparece sumado al euro; o `entries` ≠ 7.

## Paso 11 — Reconciliación

```powershell
Amz @("reconcile-payment-events")           # applied: nothing to apply
Amz @("reconcile-actions")                  # released (never sent): 0 | now unknown (may have been sent): 0
Amz @("show-actions")                       # todas SUCCEEDED: ninguna abierta
$r = Invoke-RestMethod "$api/api/reconciliation/status"
"habilitada: $($r.enabled)  desconocidos: $($r.actions.unknown_outcomes.Count)  eventos en espera: $($r.events.waiting.count)"
"registro: $($r.revenue.ledger.entries) entradas, $($r.revenue.ledger.divergences.count) divergencias, $($r.revenue.pending_evidence.count) pendientes"
```

**PASS:** nada que aplicar, nada atascado; `habilitada: True`; **0 desconocidos**, **0 eventos en espera**; el registro tiene **7
entradas y 0 divergencias** con el estado de los cobros. **FAIL:** una divergencia (el registro y los cobros no cuentan lo mismo),
o una acción abierta sin motivo.

## Paso 12 — (Opcional) Una proyección para la zona PLAN de Finanzas

```powershell
$eco = Post "/api/economics/runs" $null @{ product_id = $ProductId; supplier_quote_id = $QuoteId; sale_price = 20.0; monthly_fixed_costs = 100.0; monthly_unit_sales_base = 200; channel = "own_web"; currency = "USD"; units_per_order = 1; payment_cost_per_unit = "0.60"; other_variable_cost_per_unit = "0.40" }
"recomendacion=$($eco.recommendation) evaluable=$($eco.margin_evaluability) margen/unidad=$($eco.contribution_margin_per_unit) $($eco.currency)"
```

**PASS:** `GO`, `evaluable`, **15.0420 USD**. *(El canal tiene que ser uno declarado —`own_web`—; con uno desconocido el backend da un
500: ver P2-10 en el milestone.)*

## Paso 13 — Panel (<http://localhost:3000/dashboard>)

| Qué mirar | Debe verse |
|---|---|
| Cabecera y etiquetas | «Ingresos tomados del registro de hechos de pago verificados, aparte de lo demostrativo…», con las etiquetas **Registro verificado** y **Datos de demostración** |
| **Ingresos verificados · últimos 30 días** | **100,00 €** · «Reembolsos 8,00 € · Neto 92,00 €. Hay entradas en USD: se enseñan aparte, no se suman ni se convierten» |
| **En revisión** | **42,50 €** · «Duplicados y discrepancias pendientes de resolver. No suman a lo verificado» |
| **Evidencia pendiente** | **0** · «Ningún evento de pago sin asentar» |
| Lo demás (agentes, decisiones de ejemplo, oportunidades) | Lo que es de ejemplo está **etiquetado «Demo»** |

**PASS:** las cifras y etiquetas coinciden. **FAIL:** una cifra de dinero **sin** etiqueta de procedencia; el USD sumado al euro; o
algún importe que no salga del registro. Prueba también el selector de periodo (7 / 14 / 30 días): las etiquetas **no desaparecen**.

## Paso 14 — Finanzas (<http://localhost:3000/cfo>)

| Zona | Debe verse |
|---|---|
| **1 · Registro verificado** | Ingresos **100,00 €** · Reembolsos **8,00 €** · Neto **92,00 €**; tabla por moneda: EUR 100,00/8,00/92,00 y **USD 30,00/0,00/30,00** en su propia línea; «Nada se suma ni se convierte entre monedas: sólo el euro se consolida». **Fuera de lo verificado:** «Duplicado · en revisión **30,00 €**», «Discrepancia · en revisión **12,50 €**», «Ningún evento de pago sin asentar» |
| **2 · Coste y margen declarados** | **Margen de contribución declarado: «Sin datos»** con «Cobertura de costes incompleta: alguna línea de pedido no declara su coste». **Coste declarado: «Sin datos»** y «Costes conocidos: **1 / 3** líneas · Cobertura: **33 %**». Tabla por pedido: **A** neto 50,00 € · coste 12,00 € · **margen 38,00 €** · «1 / 1 líneas»; **B** 30,00 € · «Sin datos»; **C** 12,00 € (20 − 8) · «Sin datos». «3 de estos pedidos están marcados como simulados» |
| **3 · Proyección (PLAN)** | Sin el Paso 12: «Sin análisis económicos». Con él: **Silicone kitchen organizer · 15,0420 USD · 15,0420 USD · GO** y «Total proyectado por pedido: 15,0420 USD», con «no ha ocurrido» y «no es beneficio» |
| **Evaluación CFO** | «El agente CFO no ha emitido ninguna evaluación todavía», **aparte** y sin ninguna cifra de dinero |
| **Lo que no puede calcular** | IVA y OSS, impuestos, caja y runway, comisiones, conversión de divisas, costes no declarados, beneficio neto y EBITDA, cuentas por pagar y cobrar |

**PASS:** las tres zonas están **separadas y etiquetadas** (Registro / Declarado / PLAN), el margen agregado dice «Sin datos» **y por
qué** (no un cero), y el margen solo existe pedido a pedido donde el coste está entero. **FAIL:** un margen agregado con cobertura
< 100 %; un cero donde falta el coste; una cifra PLAN con etiqueta de registro; o USD y EUR sumados.

## Paso 15 — Proyectos (<http://localhost:3000/projects>)

| Qué mirar | Debe verse |
|---|---|
| Cartera | **1 proyecto** — «Validar Silicone kitchen organizer» con su **id real** como identificador (no un `AMZ-…` ni un `CEO-…`); estado **Aprobado**; tareas **5/5**; inicio **la fecha de hoy** (sale de la entrada `project.created` de la auditoría, no se calcula) |
| Proyección (PLAN) | **4000,00** (sin símbolo de moneda) y margen **75 %**: `(20 − 5) × 300 − 500 = 4000` sobre los supuestos del objetivo; con las etiquetas **Verificado** y **PLAN** |
| Detalle | Decisión **Aprobada**, confianza **85 %**; etapas Investigación / Proveedores / Economía / Legal en **GO**; «Todas las etapas del grafo están completadas» |
| **Lo que no calcula** | «Beneficio, ingresos y ventas por proyecto» (y por qué: un pedido puede llevar varios productos y no hay regla de reparto), capital expuesto, mercado y categoría, documentos |
| Pie | «1 proyectos del backend. Esta pantalla no convierte productos, oportunidades ni señales en proyectos, y no contiene ningún dato de demostración» |

**PASS:** **ni un solo importe de ingresos, beneficio real, capital ni pedidos** en la pantalla; solo la proyección PLAN
etiquetada. **FAIL:** aparece un «Beneficio real», un proyecto que no creaste, una fecha calculada, o cualquier cifra sin fuente.

## Paso 16 — Operaciones (<http://localhost:3000/operations>), para contrastar

Debe decir «Datos reales · eventos simulados» y «5 pedidos · son todos los que existen»: **Pagados 3**, **Completados 1**,
**Pendientes de cobro 1**, **Requieren atención 2** (el de importe distinto y el del segundo cobro confirmado),
**Cobrado 142,50 € · 30,00 US$**, **Reembolsado 8,00 €**.

> **No es una contradicción con el Panel:** Operaciones cuenta **todo el dinero cobrado** (100 + 30 duplicado + 12,50 = 142,50);
> el Panel y Finanzas cuentan el **ingreso verificado** (100) y enseñan el duplicado y la discrepancia **aparte**, como dinero en
> revisión. (Su texto «realmente cobrado» es deuda de redacción: P3-3 del milestone.)

## Paso 17 — Cuando el backend falla

Detén el backend (terminal A, `Ctrl+C`) y recarga **Panel, Finanzas y Proyectos**.

**PASS:** las **tres** muestran el aviso «Could not reach the AMAZONA backend» y **ninguna cifra de dinero**, ni cero, ni datos de
ejemplo. **FAIL:** cualquiera enseña un importe, un cero o una lista vacía como si fuera un dato. Vuelve a arrancarlo (Paso 2) para
seguir.

## Paso 18 — Limpieza

Cierra las terminales A y B; y:

```powershell
$env:PGPASSWORD = "<CLAVE>"
& "<PGBIN>\psql.exe" -h 127.0.0.1 -p <PUERTO> -U postgres -d postgres -c "DROP DATABASE IF EXISTS amazona_integral WITH (FORCE)"
Remove-Item -Recurse -Force "$env:TEMP\amazona-run"
```

Comprueba que **Supabase no cambió**: sigue con **12 migraciones**, la última `20260917114106`.

## Resultado global

| | |
|---|---|
| **PASS** | Los pasos 1, 2, 3, 5, 7, 8, 9, 10, 11, 13, 14, 15 y 17 dan PASS, y el 18 deja Supabase como estaba. (El 12 y el 16 son opcionales/contraste.) |
| **FAIL** | Cualquier FAIL de arriba. **No sigas**: guarda la salida del comando y el log del backend, y apunta el paso. Un FAIL en el 10, 11 o 14 es un fallo de **dinero**: es el más grave |

## Para repetir lo mismo sin teclear (automatizado)

La misma cadena, por HTTP y sobre una PostgreSQL efímera, con cifras fijadas a mano y los casos incómodos, es
`backend/tests/integration/test_m45_end_to_end.py`:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:<CLAVE>@127.0.0.1:<PUERTO>/postgres"   # solo local
Set-Location "<REPO>\backend"
& ".\.venv\Scripts\python.exe" -m pytest tests/integration/test_m45_end_to_end.py tests/integration/test_m45_chaos.py tests/integration/test_m45_walk.py -q
```
