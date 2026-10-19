<#
.SYNOPSIS
    Hace que ESTA PC confie en el certificado autofirmado de Distribuidora DJ (ejecutar como administrador).

.DESCRIPTION
    Importa dj-firma.cer en "Entidades de certificacion raiz de confianza" y "Editores de confianza".
    Despues de esto, los .exe firmados por construir.ps1 muestran "Distribuidora DJ" como editor
    verificado. Confiar en la raiz significa que quien tenga el .pfx puede firmar programas que esta
    PC aceptara: proteja el .pfx.

.EXAMPLE
    .\confiar-certificado.ps1
    .\confiar-certificado.ps1 -Quitar     # revierte
#>
param(
    [string]$Cer = (Join-Path $PSScriptRoot "dj-firma.cer"),
    [switch]$Quitar
)

$ErrorActionPreference = "Stop"
$esAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $esAdmin) { throw "Ejecute PowerShell como administrador." }
if (-not (Test-Path $Cer)) { throw "No se encontro $Cer" }

$huella = (New-Object Security.Cryptography.X509Certificates.X509Certificate2 (Resolve-Path $Cer).Path).Thumbprint
foreach ($almacen in "Root", "TrustedPublisher") {
    if ($Quitar) {
        Get-ChildItem "Cert:\LocalMachine\$almacen" | Where-Object Thumbprint -eq $huella | Remove-Item
        Write-Host "Quitado de $almacen" -ForegroundColor Yellow
    }
    else {
        Import-Certificate -FilePath $Cer -CertStoreLocation "Cert:\LocalMachine\$almacen" | Out-Null
        Write-Host "Instalado en $almacen" -ForegroundColor Green
    }
}
