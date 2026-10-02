<#
.SYNOPSIS
    Crea el certificado AUTOFIRMADO con el que construir.ps1 firma el instalador y los ejecutables.

.DESCRIPTION
    Genera dj-firma.pfx (clave PRIVADA, protegida con contrasena; no se versiona ni se reparte)
    y dj-firma.cer (clave publica; es lo que se instala en cada PC con confiar-certificado.ps1).
    Se ejecuta UNA vez. Si se regenera, hay que volver a instalar el .cer en todas las PCs.

.EXAMPLE
    .\packaging\firma\crear-certificado.ps1
#>
param(
    [string]$Destino = $PSScriptRoot,
    [SecureString]$Clave,
    [int]$Anios = 5
)

$ErrorActionPreference = "Stop"
$pfx = Join-Path $Destino "dj-firma.pfx"
$cer = Join-Path $Destino "dj-firma.cer"
if (Test-Path $pfx) { throw "Ya existe $pfx. Si lo regenera tendra que reinstalar el .cer en todas las PCs. Borrelo a mano para continuar." }

function ComoTexto([SecureString]$s) {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}
if (-not $Clave) {
    $Clave = Read-Host "Contrasena para proteger dj-firma.pfx" -AsSecureString
    $repetir = Read-Host "Repita la contrasena" -AsSecureString
    $a = ComoTexto $Clave
    if ($a -ne (ComoTexto $repetir) -or $a.Length -lt 8) { throw "Las contrasenas no coinciden o tienen menos de 8 caracteres." }
}

New-Item -ItemType Directory -Force $Destino | Out-Null
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=Distribuidora DJ" `
    -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
    -KeyExportPolicy Exportable -CertStoreLocation Cert:\CurrentUser\My `
    -NotAfter (Get-Date).AddYears($Anios)
try {
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $Clave | Out-Null
    Export-Certificate -Cert $cert -FilePath $cer | Out-Null
}
finally {
    # La clave queda solo en el .pfx; no se deja una copia en el almacen de Windows.
    Remove-Item $cert.PSPath -Force
}
Write-Host "Creado: $pfx  (PRIVADO: haga copia de respaldo y no lo comparta)" -ForegroundColor Green
Write-Host "Creado: $cer  (instalelo en cada PC con confiar-certificado.ps1)" -ForegroundColor Green
Write-Host "Vence: $($cert.NotAfter.ToString('yyyy-MM-dd'))"
