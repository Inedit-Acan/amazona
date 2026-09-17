# Detiene los procesos de AMAZONA arrancados por iniciar-amazona.bat.
#
# Estrategia: en vez de identificar ventanas por titulo o por orden (poco
# fiable — Windows no garantiza numeracion estable de ventanas ni el
# filtro WINDOWTITLE de taskkill es fiable con Windows Terminal como
# terminal por defecto), se buscan los procesos cmd.exe por el contenido
# EXACTO de su linea de comandos (la que puso "start" al crearlos en
# iniciar-amazona.bat) y se mata el arbol completo de cada uno
# (taskkill /T), para arrastrar tambien uvicorn/python/node/next por
# debajo sin tener que enumerarlos uno a uno.

$ErrorActionPreference = "SilentlyContinue"
$stopped = 0

$backendWindows = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "cmd.exe" -and $_.CommandLine -like "*uvicorn app.main:app*"
}
foreach ($p in $backendWindows) {
    Write-Host "Deteniendo backend (ventana PID $($p.ProcessId))..."
    taskkill /F /T /PID $p.ProcessId | Out-Null
    $stopped++
}

$frontendWindows = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "cmd.exe" -and $_.CommandLine -like "*npm run dev*"
}
foreach ($p in $frontendWindows) {
    Write-Host "Deteniendo frontend (ventana PID $($p.ProcessId))..."
    taskkill /F /T /PID $p.ProcessId | Out-Null
    $stopped++
}

if ($stopped -eq 0) {
    Write-Host "No se encontro ninguna ventana de AMAZONA en marcha (backend/frontend)."
    Write-Host "Si ves procesos colgados, cierra a mano las ventanas de consola."
} else {
    Write-Host ""
    Write-Host "Detenidas $stopped ventana(s) de AMAZONA, junto con sus subprocesos (uvicorn/node/next)."
}
