@echo off
REM Levanta la app: contenedor de SQL Server (WSL/Docker), migraciones pendientes y la UI.
REM Requiere que keep_wsl_running.bat este corriendo en otra ventana (ancla de WSL).
cd /d "%~dp0"

set "PROJECT_WSL_PATH=/mnt/c/Users/Luis F/Documents/Desarrollo/distribuidora dj"

echo Levantando SQL Server...
wsl bash -c "cd '%PROJECT_WSL_PATH%' && docker compose up -d"

echo Aplicando migraciones pendientes...
".venv\Scripts\python.exe" -m app.db.migrar
if errorlevel 1 (
    echo Fallo la migracion, no se abre la app.
    pause
    exit /b 1
)

echo Abriendo la app...
".venv\Scripts\python.exe" -m app.main
