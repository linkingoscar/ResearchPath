[CmdletBinding()]
param(
    [string]$Url = "https://www.afhayes.com/public/hayes2022data.zip",
    [string]$ExpectedSha256 = "8459974F96EDA74430EDC609CFE1F02F881CA59A240CFD3C552120CA2719692A",
    [string]$Destination = ""
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrEmpty($Destination)) {
    $Destination = Join-Path $root 'output/validation-datasets/hayes'
}
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$zip = Join-Path $Destination 'hayes2022data.zip'

if (Test-Path -LiteralPath $zip) {
    $existing = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
    if ($existing -eq $ExpectedSha256) {
        Write-Host 'Public validation data already present and verified.'
        exit 0
    }
    Remove-Item -LiteralPath $zip -Force
}

Invoke-WebRequest -Uri $Url -OutFile $zip -UseBasicParsing
$actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
if ($actual -ne $ExpectedSha256) {
    Remove-Item -LiteralPath $zip -Force
    throw "SHA-256 mismatch for ${Url}: expected $ExpectedSha256, got $actual"
}

Expand-Archive -LiteralPath $zip -DestinationPath $Destination -Force
Write-Host 'Public validation data fetched, verified and extracted.'
