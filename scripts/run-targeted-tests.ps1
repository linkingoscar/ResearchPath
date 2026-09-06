[CmdletBinding()]
param(
    [string[]]$ApiTest = @(),
    [string[]]$WebTest = @(),
    [string[]]$RTest = @(),
    [string[]]$E2ETest = @()
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

function Resolve-TestFiles {
    param([string[]]$Paths, [string]$Directory, [string]$Pattern)
    $allowedRoot = [IO.Path]::GetFullPath((Join-Path $root $Directory)) + [IO.Path]::DirectorySeparatorChar
    foreach ($path in ($Paths | Sort-Object -Unique)) {
        $absolute = [IO.Path]::GetFullPath($path, $root)
        if (-not $absolute.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase) -or
            [IO.Path]::GetFileName($absolute) -notmatch $Pattern -or
            -not (Test-Path -LiteralPath $absolute -PathType Leaf)) {
            throw "Invalid targeted test file: $path"
        }
        $absolute
    }
}

# Validate every selector before invoking any test runner; empty selections never mean "all".
$apiFiles = @(Resolve-TestFiles $ApiTest 'apps/api/tests' '^test_.*\.py$')
$webFiles = @(Resolve-TestFiles $WebTest 'apps/web/src' '\.test\.tsx?$')
$rFiles = @(Resolve-TestFiles $RTest 'engine/R/tests/testthat' '^test-.*\.R$')
$e2eFiles = @(Resolve-TestFiles $E2ETest 'tests/e2e' '\.spec\.ts$')
if ($apiFiles.Count + $webFiles.Count + $rFiles.Count + $e2eFiles.Count -eq 0) {
    throw 'Targeted requires an explicit, non-empty module test selection.'
}

function Assert-LastExitCode {
    param([Parameter(Mandatory)][string]$Step)
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE." }
}

Push-Location $root
try {
    if ($apiFiles.Count) {
        $previousLocale = $env:LC_ALL
        try {
            $env:LC_ALL = 'English_United States.utf8'
            # Run the selected files once. Serial execution also respects their serial markers.
            & $python -m pytest -c (Join-Path $root 'apps/api/pytest.ini') @apiFiles -n 0
            Assert-LastExitCode 'Selected API tests'
        }
        finally { $env:LC_ALL = $previousLocale }
    }
    if ($rFiles.Count) {
        & (Join-Path $PSScriptRoot 'test-r.ps1') -TestFile $rFiles
        Assert-LastExitCode 'Selected R tests'
    }
    if ($webFiles.Count) {
        & npm run test:web -- @webFiles
        Assert-LastExitCode 'Selected Web tests'
    }
    if ($e2eFiles.Count) {
        # Playwright also starts the production preview API.
        & npm run build:web
        Assert-LastExitCode 'Browser production build'
        $portNames = @('RESEARCHPATH_E2E_API_PORT', 'RESEARCHPATH_E2E_WEB_PORT', 'RESEARCHPATH_E2E_PREVIEW_API_PORT')
        $previousPorts = @{}
        try {
            foreach ($name in $portNames) {
                $previousPorts[$name] = [Environment]::GetEnvironmentVariable($name)
                $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
                $listener.Start()
                $port = $listener.LocalEndpoint.Port
                $listener.Stop()
                [Environment]::SetEnvironmentVariable($name, [string]$port)
            }
            $selectors = @($e2eFiles | ForEach-Object { $_.Replace('\', '/') })
            & npm run test:e2e -- @selectors
            Assert-LastExitCode 'Selected browser tests'
        }
        finally {
            foreach ($name in $previousPorts.Keys) {
                [Environment]::SetEnvironmentVariable($name, $previousPorts[$name])
            }
        }
    }
}
finally { Pop-Location }
Write-Host 'Selected module tests passed.' -ForegroundColor Green
