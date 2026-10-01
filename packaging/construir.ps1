<#
.SYNOPSIS
    Construye el instalador de Distribuidora DJ: PyInstaller (carpeta con la app y el servicio + herramientas del instalador) +
    Inno Setup (instalador unico con la opcion Servidor / Estacion).

.DESCRIPTION
    Requisitos en la PC de construccion: el entorno virtual del proyecto (.venv) con
    requirements-dev.txt + pyinstaller, e Inno Setup 6. Los valores de licenciamiento
    (LICENCIA_URL, LICENCIA_PUBLIC_KEY) se leen del .env del proyecto y se HORNEAN en el
    ejecutable: el programa instalado no lee ningun .env para eso.

.EXAMPLE
    .\packaging\construir.ps1 -Version 1.0.0
    .\packaging\construir.ps1 -Version 1.0.0 -SoloEmpaquetar     # sin Inno Setup
    .\packaging\construir.ps1 -Version 0.0.1-prueba -SinLicencia # build de prueba SIN control de licencia
#>
param(
    [string]$Version = "1.0.0",
    [switch]$SinLicencia,
    [switch]$SoloEmpaquetar
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No se encontro .venv. Cree el entorno virtual (ver README.md)." }

# 1. Licenciamiento horneado -------------------------------------------------------------
$env_file = Join-Path $raiz ".env"
$valores = @{}
if (Test-Path $env_file) {
    Get-Content $env_file | ForEach-Object {
        if ($_ -match '^\s*(LICENCIA_URL|LICENCIA_PUBLIC_KEY)\s*=\s*(.+?)\s*$') { $valores[$Matches[1]] = $Matches[2] }
    }
}
$url = $valores["LICENCIA_URL"]; $clave = $valores["LICENCIA_PUBLIC_KEY"]
if ($SinLicencia) { $url = ""; $clave = ""; Write-Warning "Build SIN control de licencia: no distribuir a clientes." }
elseif (-not $url -or -not $clave) { throw "Faltan LICENCIA_URL y/o LICENCIA_PUBLIC_KEY en .env (use -SinLicencia solo para pruebas)." }
$embebida = Join-Path $raiz "app\licencia_embebida.py"
"# Generado por packaging/construir.ps1. NO editar ni versionar.`nLICENCIA_URL = `"$url`"`nLICENCIA_PUBLIC_KEY_B64 = `"$clave`"`n" |
    Set-Content -Path $embebida -Encoding utf8

# 2. PyInstaller -------------------------------------------------------------------------
$build = Join-Path $raiz "build"
Write-Host "==> PyInstaller (puede tardar varios minutos)..." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean --distpath (Join-Path $build "dist") --workpath (Join-Path $build "work") (Join-Path $PSScriptRoot "DistribuidoraDJ.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo (aplicacion)." }
Write-Host "==> PyInstaller (herramientas del instalador)..." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --distpath (Join-Path $build "herramientas") --workpath (Join-Path $build "work-herramientas") (Join-Path $PSScriptRoot "Herramientas.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo (herramientas)." }
$dist = Join-Path $build "dist\DistribuidoraDJ"
$herramientas = Join-Path $build "herramientas\DJ-Herramientas.exe"
foreach ($ruta in (Join-Path $dist "DistribuidoraDJ.exe"), (Join-Path $dist "DJ-Servicio.exe"), $herramientas) {
    if (-not (Test-Path $ruta)) { throw "Falta $ruta" }
}

if ($SoloEmpaquetar) { Write-Host "Listo (solo empaquetado): $dist" -ForegroundColor Green; return }

# 3. Controlador ODBC redistribuible -----------------------------------------------------
$redist = Join-Path $PSScriptRoot "redist"
New-Item -ItemType Directory -Force $redist | Out-Null
$msi = Join-Path $redist "msodbcsql.msi"
if (-not (Test-Path $msi)) {
    Write-Host "==> Descargando Microsoft ODBC Driver 18 para SQL Server..." -ForegroundColor Cyan
    # Enlace oficial permanente de Microsoft al instalador x64 de ODBC Driver 18.
    Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/?linkid=2266640" -OutFile $msi -UseBasicParsing
    if ((Get-Item $msi).Length -lt 1MB) { Remove-Item $msi; throw "La descarga de msodbcsql.msi no es valida. Descargue 'ODBC Driver 18 x64' y copielo a $redist" }
}

# 4. Inno Setup --------------------------------------------------------------------------
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "No se encontro Inno Setup 6 (ISCC.exe)." }
Write-Host "==> Inno Setup..." -ForegroundColor Cyan
& $iscc "/DVersion=$Version" "/DOrigen=$dist" "/DHerramientas=$herramientas" "/DSalida=$(Join-Path $build 'instalador')" (Join-Path $PSScriptRoot "instalador.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo." }
Write-Host "Instalador listo en $(Join-Path $build 'instalador')" -ForegroundColor Green
