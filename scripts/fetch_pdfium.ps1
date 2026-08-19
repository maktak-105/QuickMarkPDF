param(
    [string]$Release = "chromium/8009"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$thirdParty = Join-Path $repoRoot "third_party"
$sdkRoot = Join-Path $thirdParty "pdfium"
$package = Join-Path $thirdParty "pdfium-win-x64.tgz"
$encodedRelease = $Release -replace "/", "%2F"

New-Item -ItemType Directory -Force -Path $thirdParty | Out-Null
Invoke-WebRequest -Uri "https://github.com/bblanchon/pdfium-binaries/releases/download/$encodedRelease/pdfium-win-x64.tgz" -OutFile $package
if (Test-Path $sdkRoot) {
    Remove-Item -LiteralPath $sdkRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $sdkRoot | Out-Null
tar -xzf $package -C $sdkRoot
if ($LASTEXITCODE -ne 0) {
    throw "tar extraction of $package failed with exit code $LASTEXITCODE"
}
Remove-Item -LiteralPath $package -Force
Write-Host "PDFium $Release extracted to $sdkRoot"
