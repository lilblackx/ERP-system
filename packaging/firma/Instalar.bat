@echo off
rem Instala el certificado de Distribuidora DJ en esta PC y ejecuta el instalador.
rem Copiar junto a DistribuidoraDJ-Setup-*.exe y dj-firma.cer; doble clic.
rem Pide permisos de administrador (necesarios para instalar el certificado y la aplicacion).
setlocal
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

if not exist "dj-firma.cer" (
    echo Falta dj-firma.cer junto a este archivo.
    pause
    exit /b 1
)

certutil -addstore -f Root "dj-firma.cer" >nul || goto :error
certutil -addstore -f TrustedPublisher "dj-firma.cer" >nul || goto :error

set "SETUP="
for %%F in ("DistribuidoraDJ-Setup-*.exe") do set "SETUP=%%F"
if not defined SETUP (
    echo Falta DistribuidoraDJ-Setup-*.exe junto a este archivo.
    pause
    exit /b 1
)
rem Se pasan al instalador los parametros recibidos (por ejemplo /Tipo=ESTACION ...).
start "" /wait "%SETUP%" %*
exit /b %errorlevel%

:error
echo No se pudo instalar el certificado.
pause
exit /b 1
