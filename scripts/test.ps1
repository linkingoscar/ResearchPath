[CmdletBinding()]
param(
    [ValidateRange(1, 16)]
    # Benchmarked on the pinned R workload: 4 workers outperform 6 and 8 without
    # adding avoidable R subprocess contention.
    [int]$PytestWorkers = 4,
    [switch]$NoLockCache,
    [switch]$NoNumericBaselineCache
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$fullTimer = [System.Diagnostics.Stopwatch]::StartNew()
$timings = [System.Collections.Generic.List[object]]::new()

function Write-StepDuration {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][System.Diagnostics.Stopwatch]$Timer
    )
    $Timer.Stop()
    $timings.Add([pscustomobject]@{
        name = $Name
        seconds = [Math]::Round($Timer.Elapsed.TotalSeconds, 3)
    })
    Write-Host ("Harness timing: {0} = {1:N2}s" -f $Name, $Timer.Elapsed.TotalSeconds) -ForegroundColor DarkCyan
}

function Write-TimingEvidence {
    $performanceDirectory = Join-Path $root 'output\test-performance'
    New-Item -ItemType Directory -Force -Path $performanceDirectory | Out-Null
    $commit = (& git rev-parse HEAD).Trim()
    $dirty = [bool](& git status --porcelain)
    $record = [ordered]@{
        schemaVersion = '1.0.0'
        recordedAt = [DateTimeOffset]::Now.ToString('o')
        mode = 'Full'
        commit = $commit
        dirty = $dirty
        pytestWorkers = $PytestWorkers
        caches = [ordered]@{
            pythonLock = -not [bool]$NoLockCache
            rNumericBaseline = -not [bool]$NoNumericBaselineCache
        }
        steps = @($timings)
    }
    $json = $record | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText(
        (Join-Path $performanceDirectory 'harness-timing.json'),
        $json + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::AppendAllText(
        (Join-Path $performanceDirectory 'harness-timing.ndjson'),
        (($record | ConvertTo-Json -Depth 6 -Compress) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
}

$qualityTimer = [System.Diagnostics.Stopwatch]::StartNew()
& (Join-Path $PSScriptRoot 'invoke-full-quality.ps1') `
    -NoLockCache:$NoLockCache `
    -NoNumericBaselineCache:$NoNumericBaselineCache
Write-StepDuration -Name 'quality-and-locks' -Timer $qualityTimer

$apiTimer = [System.Diagnostics.Stopwatch]::StartNew()
Push-Location (Join-Path $root 'apps\api')
$previousLocale = $env:LC_ALL
$threadLimitVariables = @(
    'OMP_NUM_THREADS',
    'OMP_THREAD_LIMIT',
    'OPENBLAS_NUM_THREADS',
    'MKL_NUM_THREADS',
    'NUMEXPR_NUM_THREADS',
    'RCPP_PARALLEL_NUM_THREADS'
)
$previousThreadLimits = @{}
try {
    # Tests launch R through both product services and independent fixtures.
    # Keep their child processes in the same UTF-8 locale as the production
    # runner, rather than allowing an unavailable host C.UTF-8 locale to turn
    # valid Chinese result labels into mojibake.
    $env:LC_ALL = 'English_United States.utf8'
    # xdist workers launch native Python and R estimators. Bound each child
    # process to one native thread so four workers do not multiply OpenMP/BLAS
    # pools and starve wall-clock-bounded statistical subprocesses on CI.
    foreach ($variableName in $threadLimitVariables) {
        $previousThreadLimits[$variableName] = [Environment]::GetEnvironmentVariable($variableName)
        [Environment]::SetEnvironmentVariable($variableName, '1')
    }
    try {
        $coverageDirectory = Join-Path $root 'output\coverage'
        $performanceDirectory = Join-Path $root 'output\test-performance'
        New-Item -ItemType Directory -Force -Path $coverageDirectory | Out-Null
        New-Item -ItemType Directory -Force -Path $performanceDirectory | Out-Null
        # Keep wall-clock-bounded glmmTMB cases out of the general xdist pool.
        # They retain their original data, simulations, and subprocess timeout,
        # but execute after the parallel lane so unrelated R estimators cannot
        # consume the hosted runner while their timeout is running.
        & (Join-Path $root '.venv\Scripts\python.exe') -m pytest `
            -m 'not serial' `
            -n $PytestWorkers `
            --dist=worksteal `
            --max-worker-restart=0 `
            --durations=40 `
            "--junitxml=$(Join-Path $performanceDirectory 'api-parallel.xml')" `
            --cov=app `
            --cov-branch `
            "--cov-report="
        if ($LASTEXITCODE -ne 0) { throw 'Parallel API tests failed.' }
        & (Join-Path $root '.venv\Scripts\python.exe') -m pytest `
            -m serial `
            -n 0 `
            --durations=40 `
            "--junitxml=$(Join-Path $performanceDirectory 'api-serial.xml')" `
            --cov=app `
            --cov-branch `
            --cov-append `
            --cov-fail-under=78 `
            --cov-report=term-missing:skip-covered `
            "--cov-report=json:$(Join-Path $coverageDirectory 'api.json')"
        if ($LASTEXITCODE -ne 0) { throw 'Serial API tests failed.' }
        & (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'scripts\check-coverage-baseline.py') `
            --report (Join-Path $coverageDirectory 'api.json') `
            --baseline (Join-Path $root 'docs\baselines\api-coverage.json') `
            --module-baseline (Join-Path $root 'docs\baselines\module-coverage.json') `
            --pragma-root (Join-Path $root 'apps\api\app')
        if ($LASTEXITCODE -ne 0) { throw 'API coverage baseline regressed.' }
    }
    finally {
        $env:LC_ALL = $previousLocale
        foreach ($variableName in $threadLimitVariables) {
            [Environment]::SetEnvironmentVariable(
                $variableName,
                $previousThreadLimits[$variableName]
            )
        }
    }
}
finally {
    Pop-Location
}
Write-StepDuration -Name 'api-tests-and-coverage' -Timer $apiTimer

$webTimer = [System.Diagnostics.Stopwatch]::StartNew()
Push-Location $root
try {
    & npm run test:web
    if ($LASTEXITCODE -ne 0) { throw 'Web tests failed.' }

    # Production E2E is served from the freshly built dist by FastAPI
    # (RESEARCHPATH_SERVE_WEB=1), so build must complete before Playwright
    # starts its dev and preview web servers.
    & npm run build:web
    if ($LASTEXITCODE -ne 0) { throw 'Web build failed.' }

    $apiListener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $apiListener.Start()
    $e2eApiPort = $apiListener.LocalEndpoint.Port
    $apiListener.Stop()
    $webListener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $webListener.Start()
    $e2eWebPort = $webListener.LocalEndpoint.Port
    $webListener.Stop()
    $previewListener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $previewListener.Start()
    $e2ePreviewApiPort = $previewListener.LocalEndpoint.Port
    $previewListener.Stop()

    $previousApiPort = $env:RESEARCHPATH_E2E_API_PORT
    $previousWebPort = $env:RESEARCHPATH_E2E_WEB_PORT
    $previousPreviewApiPort = $env:RESEARCHPATH_E2E_PREVIEW_API_PORT
    try {
        $env:RESEARCHPATH_E2E_API_PORT = [string]$e2eApiPort
        $env:RESEARCHPATH_E2E_WEB_PORT = [string]$e2eWebPort
        $env:RESEARCHPATH_E2E_PREVIEW_API_PORT = [string]$e2ePreviewApiPort
        & npm run test:e2e
        if ($LASTEXITCODE -ne 0) {
            throw 'Browser E2E and accessibility tests failed.'
        }
    }
    finally {
        $env:RESEARCHPATH_E2E_API_PORT = $previousApiPort
        $env:RESEARCHPATH_E2E_WEB_PORT = $previousWebPort
        $env:RESEARCHPATH_E2E_PREVIEW_API_PORT = $previousPreviewApiPort
    }

    & npm run test:bundle-budget
    if ($LASTEXITCODE -ne 0) { throw 'Web bundle budget regression test failed.' }
    & npm run check:bundle
    if ($LASTEXITCODE -ne 0) { throw 'Web bundle budget failed.' }
}
finally {
    Pop-Location
}
Write-StepDuration -Name 'web-tests-e2e-build' -Timer $webTimer
Write-StepDuration -Name 'full-quality-gate' -Timer $fullTimer
Write-TimingEvidence
