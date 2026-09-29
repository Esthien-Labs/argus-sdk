[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$Installer,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Fa-f0-9]{40}$')]
    [string]$CertificateThumbprint,

    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
    $candidates = @()
    if ($env:SIGNTOOL_PATH) {
        $candidates += $env:SIGNTOOL_PATH
    }
    $sdkRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path -LiteralPath $sdkRoot) {
        $candidates += Get-ChildItem -LiteralPath $sdkRoot -Recurse -Filter "signtool.exe" -File |
            Sort-Object FullName -Descending |
            Select-Object -ExpandProperty FullName
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "signtool.exe was not found. Install the Windows SDK Signing Tools or set SIGNTOOL_PATH."
}

$certificate = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object {
        $_.Thumbprint -eq $CertificateThumbprint -and
        $_.HasPrivateKey -and
        $_.EnhancedKeyUsageList.FriendlyName -contains "Code Signing"
    } |
    Select-Object -First 1

if (-not $certificate) {
    throw "No usable code-signing certificate with the supplied thumbprint was found in Cert:\CurrentUser\My."
}

$signTool = Find-SignTool
$resolvedInstaller = (Resolve-Path -LiteralPath $Installer).Path

& $signTool sign /fd SHA256 /sha1 $certificate.Thumbprint /tr $TimestampUrl /td SHA256 $resolvedInstaller
if ($LASTEXITCODE -ne 0) {
    throw "Authenticode signing failed with exit code $LASTEXITCODE."
}

& $signTool verify /pa /all /v $resolvedInstaller
if ($LASTEXITCODE -ne 0) {
    throw "Authenticode verification failed with exit code $LASTEXITCODE."
}

Get-AuthenticodeSignature -FilePath $resolvedInstaller |
    Select-Object Status, StatusMessage, @{Name = "Signer"; Expression = { $_.SignerCertificate.Subject }}, @{Name = "Thumbprint"; Expression = { $_.SignerCertificate.Thumbprint }}
