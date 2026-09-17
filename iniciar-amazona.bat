@echo off
setlocal enabledelayedexpansion
title AMAZONA - Iniciar

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "BACKEND_DIR=%ROOT%\backend"
set "FRONTEND_DIR=%ROOT%\apps\control-center"

echo ============================================
echo   AMAZONA - arrancando entorno local
echo ============================================
echo.

if not exist "%BACKEND_DIR%\.venv\Scripts\activate.bat" (
    echo [ERROR] No se encontro el entorno virtual del backend en:
    echo   %BACKEND_DIR%\.venv
    echo.
    echo Para crearlo, abre PowerShell y ejecuta:
    echo   cd "%BACKEND_DIR%"
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
    echo [ERROR] No se encontraron las dependencias del frontend en:
    echo   %FRONTEND_DIR%\node_modules
    echo.
    echo Para instalarlas, abre PowerShell y ejecuta:
    echo   cd "%FRONTEND_DIR%"
    echo   npm install
    echo.
    pause
    exit /b 1
)

echo [1/3] Arrancando backend (uvicorn) en una ventana nueva...
start "AMAZONA - backend (uvicorn)" /D "%BACKEND_DIR%" cmd /k "call .venv\Scripts\activate.bat && uvicorn app.main:app --reload"

echo [2/3] Arrancando frontend (next dev) en una ventana nueva...
start "AMAZONA - frontend (next dev)" /D "%FRONTEND_DIR%" cmd /k "npm run dev"

echo [3/3] Esperando a que el backend responda en http://localhost:8000/health ...
set "BACKEND_READY=0"
for /l %%i in (1,1,60) do (
    if "!BACKEND_READY!"=="0" (
        set "HTTP_CODE="
        for /f %%c in ('curl -s -o NUL -w "%%{http_code}" http://localhost:8000/health 2^>NUL') do set "HTTP_CODE=%%c"
        if "!HTTP_CODE!"=="200" (
            set "BACKEND_READY=1"
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)

if "!BACKEND_READY!"=="0" (
    echo.
    echo [AVISO] El backend no respondio en 60s en http://localhost:8000/health
    echo         Revisa la ventana "AMAZONA - backend (uvicorn)" por errores.
    echo         Abriendo el frontend de todas formas...
) else (
    echo Backend listo.
)

echo.
echo Abriendo http://localhost:3000 ...
start "" "http://localhost:3000"

echo.
echo Backend y frontend corriendo, cada uno en su propia ventana de consola.
echo Cierra esas dos ventanas para pararlos, o ejecuta detener-amazona.bat
echo.
pause
