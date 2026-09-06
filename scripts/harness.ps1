[CmdletBinding()]
param(
    [ValidateSet('Quick', 'Targeted', 'Full')]
    [string]$Mode = 'Quick',
    [ValidateRange(1, 16)]
    [int]$PytestWorkers = 4,
    [string]$BaseRef = 'HEAD~1',
    [string[]]$ChangedFile = @()
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$ruff = Join-Path $root '.venv\Scripts\ruff.exe'

function Assert-LastExitCode {
    param([Parameter(Mandatory)][string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Invoke-QuickHarness {
    & (Join-Path $PSScriptRoot 'check-architecture.ps1')

    & $ruff check apps/api/app apps/api/tests
    Assert-LastExitCode 'Python lint'

    & $python (Join-Path $PSScriptRoot 'check-python-types.py')
    Assert-LastExitCode 'Python type baseline'

    & npm run lint:web
    Assert-LastExitCode 'Web lint'

    & npm run typecheck:web
    Assert-LastExitCode 'Web typecheck'

    & (Join-Path $PSScriptRoot 'generate-contracts.ps1') -Check
}

Push-Location $root
try {
    Write-Host "ResearchPath harness: $Mode" -ForegroundColor Cyan
    switch ($Mode) {
        'Quick' {
            Invoke-QuickHarness
        }
        'Targeted' {
            Invoke-QuickHarness
            $impactArguments = @(
                (Join-Path $PSScriptRoot 'resolve-test-impact.py'),
                '--root', $root,
                '--base-ref', $BaseRef
            )
            foreach ($path in $ChangedFile) {
                $impactArguments += @('--changed-file', $path)
            }
            $impactJson = & $python @impactArguments
            Assert-LastExitCode 'Test impact resolution'
            $impact = $impactJson | ConvertFrom-Json
            Write-Host ($impact | ConvertTo-Json -Depth 5) -ForegroundColor DarkCyan
            if ($impact.escalation -eq 'Full') {
                Write-Host 'Cross-cutting change detected; running Full.' -ForegroundColor Yellow
                & (Join-Path $PSScriptRoot 'test.ps1') -PytestWorkers $PytestWorkers
            }
            elseif ($impact.escalation) {
                throw "Unsupported targeted escalation: $($impact.escalation)"
            }
            else {
                & (Join-Path $PSScriptRoot 'run-targeted-tests.ps1') `
                    -Lane @($impact.lanes) `
                    -PytestWorkers $PytestWorkers
            }
        }
        'Full' {
            & (Join-Path $PSScriptRoot 'test.ps1') -PytestWorkers $PytestWorkers
        }
    }
    Write-Host "ResearchPath harness passed: $Mode" -ForegroundColor Green
}
finally {
    Pop-Location
}
