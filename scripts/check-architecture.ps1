[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $root 'project.manifest.json'

if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw 'project.manifest.json is required.'
}

$manifest = Get-Content -LiteralPath $manifestPath -Encoding UTF8 -Raw | ConvertFrom-Json
$commandPaths = $manifest.commands.PSObject.Properties.Value | ForEach-Object {
    ($_ -split '\s+', 2)[0]
}
$governanceMetadataKeys = @('licensingModel')
$governancePaths = $manifest.governance.PSObject.Properties |
    Where-Object { $_.Name -notin $governanceMetadataKeys } |
    ForEach-Object { $_.Value }
$declaredPaths = @(
    $manifest.entrypoints.path
    $manifest.backendRoutes.path
    $manifest.frontendModules.api
    $manifest.frontendModules.types
    $manifest.contracts.path
    $governancePaths
    $manifest.assetPacks.path
    $manifest.assetPacks.restoreGuide
    $manifest.restoredAssetSlices.activePaths
    $commandPaths
) | Sort-Object -Unique

foreach ($relativePath in $declaredPaths) {
    $resolved = Join-Path $root $relativePath
    if (-not (Test-Path -LiteralPath $resolved)) {
        throw "Manifest path does not exist: $relativePath"
    }
}

$serviceFiles = Get-ChildItem -LiteralPath (Join-Path $root 'apps/api/app/services') -Filter '*.py'
$layerViolations = $serviceFiles | Select-String -Pattern '(from|import) app\.api'
if ($layerViolations) {
    throw "Service layer must not import the HTTP layer: $($layerViolations.Path -join ', ')"
}

$forbiddenGenerated = @('temp_pytest')
foreach ($name in $forbiddenGenerated) {
    if (Test-Path -LiteralPath (Join-Path $root $name)) {
        throw "Generated directory must not remain in the repository root: $name"
    }
}

# docs/09-修改日志.md must stay append-only above the frozen-history marker and
# its historical region must match the pinned digest.
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'check_changelog_governance.py')
if ($LASTEXITCODE -ne 0) {
    throw 'Changelog governance check failed.'
}

# Physical line counts (blank lines included) via the Python helper so the
# limit cannot be bypassed by padding files with empty lines. Pre-existing
# offenders are pinned in docs/baselines/source-line-baselines.json and may
# never grow; reductions are the only allowed edit.
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'check_source_lines.py') `
    --root $root `
    --baselines (Join-Path $root 'docs\baselines\source-line-baselines.json')
if ($LASTEXITCODE -ne 0) {
    throw 'Source line ceilings failed.'
}

# Inline style objects are frozen and must only migrate into tokens.css/CSS
# modules; growth fails the architecture gate.
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'check_web_style_budget.py') `
    --root $root `
    --baseline (Join-Path $root 'docs\baselines\web-style-budget.json')
if ($LASTEXITCODE -ne 0) {
    throw 'Web inline style budget failed.'
}

Write-Host 'Architecture checks passed.' -ForegroundColor Green
