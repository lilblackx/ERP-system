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
    .\packaging\construir.ps1 -Version 1.0.0 -SinFirma           # no firma aunque exista firma\dj-firma.pfx

    Firma: si existe packaging\firma\dj-firma.pfx (ver firma\crear-certificado.ps1) se firman los .exe y el
    instalador con ese certificado autofirmado. La contrasena sale de la variable de entorno DJ_FIRMA_CLAVE o se pide.
#>
param(
    [string]$Version = "1.0.0",
    [switch]$SinLicencia,
    [switch]$SoloEmpaquetar,
    [switch]$SinFirma
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No se encontro .venv. Cree el entorno virtual (ver README.md)." }

# Firma (opcional) ----------------------------------------------------------------------------
$pfx = Join-Path $PSScriptRoot "firma\dj-firma.pfx"
$cer = Join-Path $PSScriptRoot "firma\dj-firma.cer"
$firmar = -not $SinFirma
$signtool = $null; $claveFirma = $null
if ($firmar) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    if (-not $signtool) { throw "No se encontro signtool.exe (Windows SDK). Instale el Windows SDK o use -SinFirma." }
    $claveFirma = $env:DJ_FIRMA_CLAVE
    $nuevo = -not (Test-Path $pfx)
    if (-not $claveFirma) {
        $mensaje = if ($nuevo) { "Se creara el certificado de firma (primera vez). Elija una contrasena para dj-firma.pfx" } else { "Contrasena de dj-firma.pfx" }
        $s = Read-Host $mensaje -AsSecureString
        $claveFirma = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
    }
    if ($nuevo) {
        # Primera vez: el certificado se crea solo, con la misma contrasena. Respaldar el .pfx (ver README).
        & (Join-Path $PSScriptRoot "firma\crear-certificado.ps1") -Clave (ConvertTo-SecureString $claveFirma -AsPlainText -Force)
    }
}
else { Write-Warning "Build SIN firma (-SinFirma): el instalador saldra sin firmar." }

function Firmar([string[]]$archivos) {
    if (-not $firmar) { return }
    foreach ($archivo in $archivos) {
        & $signtool sign /f $pfx /p $claveFirma /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /d "Distribuidora DJ" $archivo | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "No se pudo firmar $archivo" }
        Write-Host "    firmado: $(Split-Path -Leaf $archivo)"
    }
}

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

if ($firmar) { Write-Host "==> Firmando ejecutables..." -ForegroundColor Cyan }
Firmar @((Join-Path $dist "DistribuidoraDJ.exe"), (Join-Path $dist "DJ-Servicio.exe"), $herramientas)

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
$salida = Join-Path $build "instalador"
$argsIscc = @("/DVersion=$Version", "/DOrigen=$dist", "/DHerramientas=$herramientas", "/DSalida=$salida")
# El certificado publico viaja dentro del instalador: al instalar, la PC pasa a confiar en lo firmado por DJ.
if ($firmar) { $argsIscc += "/DCer=$cer" }
& $iscc @argsIscc (Join-Path $PSScriptRoot "instalador.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo." }
if ($firmar) {
    Write-Host "==> Firmando instalador..." -ForegroundColor Cyan
    Firmar @((Join-Path $salida "DistribuidoraDJ-Setup-$Version.exe"))
    # Para la PRIMERA vez en cada equipo (el instalador aun no pudo instalar el certificado, y SmartScreen
    # desconfia de el hasta entonces): el .bat instala el certificado y lanza el instalador.
    Copy-Item $cer (Join-Path $salida "dj-firma.cer") -Force
    Copy-Item (Join-Path $PSScriptRoot "firma\Instalar.bat") (Join-Path $salida "Instalar.bat") -Force
}
Write-Host "Listo en ${salida}:" -ForegroundColor Green
Get-ChildItem $salida | ForEach-Object { Write-Host "    $($_.Name)" }
