param(
    [string]$Version = "1.0.2903.40"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$thirdParty = Join-Path $repoRoot "third_party"
$sdkRoot = Join-Path $thirdParty "webview2"
$package = Join-Path $thirdParty "Microsoft.Web.WebView2.$Version.nupkg"

New-Item -ItemType Directory -Force -Path $thirdParty | Out-Null
Invoke-WebRequest -Uri "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/$Version" -OutFile $package
if (Test-Path $sdkRoot) {
    Remove-Item -LiteralPath $sdkRoot -Recurse -Force
}
Expand-Archive -LiteralPath $package -DestinationPath $sdkRoot -Force
Remove-Item -LiteralPath $package -Force
Write-Host "WebView2 SDK $Version extracted to $sdkRoot"
