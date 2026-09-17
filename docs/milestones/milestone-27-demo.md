# Milestone 27 Demo

**Origen:** petición directa de Ivan — arrancar AMAZONA en local con
doble clic, sin escribir comandos en PowerShell. **Sin ADR nueva** —
tooling de desarrollo local, ninguna decisión de arquitectura del
sistema.

## Qué se entrega

### `iniciar-amazona.bat` (raíz del repo)

1. **Comprobaciones previas con mensaje claro** (no error críptico):
   si falta `backend\.venv` o `apps\control-center\node_modules`, imprime
   qué falta y el comando exacto para crearlo (`python -m venv .venv` +
   `pip install -e ".[dev]"`, o `npm install`), y sale sin arrancar nada.
2. **Backend en su propia ventana**: `start "AMAZONA - backend (uvicorn)"
   /D "<repo>\backend" cmd /k "call .venv\Scripts\activate.bat &&
   uvicorn app.main:app --reload"` — ventana persistente (`/k`, no `/c`),
   así que cerrarla para el backend es tan simple como cerrar esa
   ventana.
3. **Frontend en otra ventana independiente**: mismo patrón,
   `npm run dev` desde `apps\control-center`.
4. **Espera activa a `GET http://localhost:8000/health`** (hasta 60
   intentos, 1s entre cada uno, vía `curl.exe` — ya viene con Windows
   10/11, sin depender de PowerShell para el polling) antes de abrir el
   navegador en `http://localhost:3000`. Si el backend no responde en
   60s, avisa y abre el frontend igualmente (en vez de colgarse sin
   explicación).

### `detener-amazona.bat` + `detener-amazona.ps1`

**Sí es razonable hacerlo de forma fiable** — la reserva del propio
encargo (depender de cómo Windows numera las ventanas) no aplica aquí
porque **no se usa numeración de ventanas en absoluto**: `taskkill /FI
"WINDOWTITLE eq ..."` (la alternativa que sí sería frágil, especialmente
con Windows Terminal como terminal por defecto, donde varias pestañas
comparten una sola ventana) se descartó a favor de
`Get-CimInstance Win32_Process` filtrando por **contenido exacto de la
línea de comandos** (`*uvicorn app.main:app*` / `*npm run dev*`) — el
mismo texto literal que `iniciar-amazona.bat` puso en cada `start`. Cada
ventana encontrada se detiene con `taskkill /F /T /PID` (`/T` = árbol
completo), así que arrastra automáticamente a los procesos hijos
(uvicorn, los workers de `--reload`, node, next, los workers de
Turbopack) sin tener que enumerarlos uno a uno.

La lógica vive en un `.ps1` aparte (`detener-amazona.ps1`), invocado por
el `.bat` vía `-File` — no incrustada en una línea de `.bat` con
`powershell -Command "..."`. Se probó primero esa vía (script inline) y
se abandonó: anidar comillas dobles (el propio literal `WINDOWTITLE`,
los strings de PowerShell, y el escapado de `%` de `.bat`) resultaba
frágil y difícil de depurar; un `.ps1` con `-File` no tiene ninguno de
esos problemas y el `.bat` con doble clic sigue siendo el único punto de
entrada, tal como pediste.

## Investigación durante la implementación (hallazgos no obvios)

- **`start "Título" /D "ruta" comando` no respetó `/D`** en una de las
  primeras pruebas — resultó ser un artefacto de mi arnés de prueba
  (invocar el `.bat` vía `Start-Process -WorkingDirectory` con un
  directorio *distinto* al del propio `.bat` interfiere con el `/D`
  anidado). Con un doble clic real (o `Start-Process` sin forzar
  `-WorkingDirectory`, que es como Explorer lo hace), `/D` funciona
  correctamente — confirmado con un fichero de log escrito desde la
  ventana hija.
- **La comprobación de salud usa `curl.exe`, no `Invoke-WebRequest`**:
  durante las pruebas, un script de verificación mío basado en
  `Invoke-WebRequest` (PowerShell 5.1) tardó >30s en detectar un backend
  que `curl` veía sano al instante — un problema del cliente HTTP de esa
  prueba, no del backend. Confirma que la elección de `curl.exe` para el
  polling dentro del `.bat` (en vez de PowerShell) fue la correcta.

## Verificación

**Probado de verdad, no solo revisado** — dos ciclos completos de
arranque/parada en esta misma máquina, simulando un doble clic real
(`Start-Process` sin forzar directorio de trabajo):

1. `iniciar-amazona.bat` comprobado con `.venv`/`node_modules` ya
   presentes (camino feliz) — las dos ventanas se abrieron
   (`Get-CimInstance` confirmó los procesos `cmd.exe` con la línea de
   comandos exacta esperada), `uvicorn` y `next dev` arrancaron
   (confirmado por los procesos `python.exe`/`node.exe` hijos), y
   `curl http://localhost:8000/health` respondió
   `{"status":"ok","service":"amazona-backend"}` con código 200 — igual
   que documenta el `README.md`.
2. **El navegador se abrió de verdad**: `Get-Process chrome` mostró una
   ventana con título literal **"AMAZONA Control Center - Google
   Chrome"** tras el arranque — confirmación inequívoca de que
   `start "" "http://localhost:3000"` abrió el Control Center real (no
   una pestaña en blanco ni un error) en el navegador del propio Ivan.
3. `detener-amazona.bat` verificado contra los procesos reales de la
   prueba anterior: detuvo las dos ventanas y toda su descendencia —
   confirmado con `Get-NetTCPConnection` (sin nada escuchando ya en
   3000/8000) y `Get-CimInstance` (cero procesos `uvicorn`/`next`
   restantes).
4. Segundo ciclo completo (arrancar → confirmar → parar) repetido para
   confirmar que no es un resultado de una sola vez.
5. Entorno de prueba limpiado al terminar (ventanas de consola
   cerradas, ficheros temporales de prueba borrados) — no queda ningún
   proceso ni ventana de AMAZONA corriendo en la máquina tras este
   milestone.

```bash
cd backend && ruff check . && mypy app && pytest       # 498 tests, sin regresiones
```

No se tocó ningún archivo de `backend/` ni `apps/control-center/` — solo
los 3 archivos nuevos en la raíz (`git status` lo confirma). El
frontend no requiere `lint`/`tsc`/`build` porque no se modificó ningún
`.ts`/`.tsx`.

## Nota sobre Supabase

`uvicorn --reload` arranca contra la base configurada en
`backend/.env` (Supabase real, según documenta el propio `README.md`).
`GET /health` (el endpoint que usa el chequeo de arranque) **no toca la
base de datos** — solo `/health/detailed` lo hace. Abrir el navegador en
`localhost:3000` sí dispara peticiones reales de solo lectura del
Control Center contra esa base (las mismas lecturas que cualquier uso
normal de la app) — es el comportamiento esperado del propio lanzador
que pediste probar, no una acción mía por iniciativa propia contra
Supabase.

## Cómo usarlo

Doble clic en `iniciar-amazona.bat` (o `detener-amazona.bat` para
parar). Ambos viven en la raíz del repo, junto a `README.md`.
