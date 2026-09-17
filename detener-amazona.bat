@echo off
title AMAZONA - Detener

echo ============================================
echo   AMAZONA - deteniendo entorno local
echo ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0detener-amazona.ps1"

echo.
pause
