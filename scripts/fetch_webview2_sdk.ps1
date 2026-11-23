param(
    [string]$Version = "1.0.4370.26",
    # SHA-256 of Microsoft.Web.WebView2.<Version>.nupkg for the pinned version (its SHA-512 was checked against
    # the NuGet catalog when the pin was set). A different -Version must come with its own -Sha256.
    [string]$Sha256 = "1C0DACAC84B70109B3FD42F90C53A0BA942ABC3A87590D7A4E0CCD86E4A06CF4"
)

$ErrorActionPreference = "Stop"
$pinnedVersion = "1.0.4370.26"
if ($Version -ne $pinnedVersion -and -not $PSBoundParameters.ContainsKey("Sha256")) {
    throw "Version $Version is not the pinned version ($pinnedVersion). Pass its package hash with -Sha256."
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$thirdParty = Join-Path $repoRoot "third_party"
$sdkRoot = Join-Path $thirdParty "webview2"
$package = Join-Path $thirdParty "Microsoft.Web.WebView2.$Version.nupkg"

New-Item -ItemType Directory -Force -Path $thirdParty | Out-Null
Invoke-WebRequest -Uri "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/$Version" -OutFile $package

# Verify before anything in third_party is touched: a wrong hash leaves the existing SDK as it is.
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $package).Hash
if ($actual -ne $Sha256.ToUpperInvariant()) {
    Remove-Item -LiteralPath $package -Force
    throw "SHA-256 mismatch for Microsoft.Web.WebView2 $Version. Expected $($Sha256.ToUpperInvariant()), got $actual. Nothing was extracted."
}

if (Test-Path $sdkRoot) {
    Remove-Item -LiteralPath $sdkRoot -Recurse -Force
}
$zipPackage = [System.IO.Path]::ChangeExtension($package, ".zip")
Move-Item -LiteralPath $package -Destination $zipPackage -Force
Expand-Archive -LiteralPath $zipPackage -DestinationPath $sdkRoot -Force
Remove-Item -LiteralPath $zipPackage -Force
Write-Host "WebView2 SDK $Version (SHA-256 verified) extracted to $sdkRoot"
