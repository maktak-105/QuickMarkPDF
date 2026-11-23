param(
    [string]$Release = "chromium/8165",
    # SHA-256 of pdfium-win-x64.tgz for the pinned release (matches the digest GitHub publishes for the asset).
    # A different -Release must come with its own -Sha256.
    [string]$Sha256 = "CA7338AE7779B8B1B82F4580305C4D762D214F8DF1D54B47647FE3CC75989DED"
)

$ErrorActionPreference = "Stop"
$pinnedRelease = "chromium/8165"
if ($Release -ne $pinnedRelease -and -not $PSBoundParameters.ContainsKey("Sha256")) {
    throw "Release $Release is not the pinned release ($pinnedRelease). Pass its archive hash with -Sha256."
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$thirdParty = Join-Path $repoRoot "third_party"
$sdkRoot = Join-Path $thirdParty "pdfium"
$package = Join-Path $thirdParty "pdfium-win-x64.tgz"
$encodedRelease = $Release -replace "/", "%2F"

New-Item -ItemType Directory -Force -Path $thirdParty | Out-Null
Invoke-WebRequest -Uri "https://github.com/bblanchon/pdfium-binaries/releases/download/$encodedRelease/pdfium-win-x64.tgz" -OutFile $package

# Verify before anything in third_party is touched: a wrong hash leaves the existing SDK as it is.
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $package).Hash
if ($actual -ne $Sha256.ToUpperInvariant()) {
    Remove-Item -LiteralPath $package -Force
    throw "SHA-256 mismatch for pdfium-win-x64.tgz ($Release). Expected $($Sha256.ToUpperInvariant()), got $actual. Nothing was extracted."
}

if (Test-Path $sdkRoot) {
    Remove-Item -LiteralPath $sdkRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $sdkRoot | Out-Null
tar -xzf $package -C $sdkRoot
if ($LASTEXITCODE -ne 0) {
    throw "tar extraction of $package failed with exit code $LASTEXITCODE"
}
Remove-Item -LiteralPath $package -Force
Write-Host "PDFium $Release (SHA-256 verified) extracted to $sdkRoot"
