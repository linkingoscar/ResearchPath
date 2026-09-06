[CmdletBinding()]
param(
    [switch]$NoLockCache,
    [switch]$NoNumericBaselineCache
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$taskNames = @(
    'python-quality',
    'web-and-contracts',
    'python-lock',
    'r-quality'
)

$jobs = foreach ($taskName in $taskNames) {
    Start-ThreadJob -Name $taskName -ArgumentList $root, $PSScriptRoot, $taskName, ([bool]$NoLockCache), ([bool]$NoNumericBaselineCache) -ScriptBlock {
        param(
            [string]$Root,
            [string]$Scripts,
            [string]$TaskName,
            [bool]$DisableLockCache,
            [bool]$DisableNumericBaselineCache
        )

        $ErrorActionPreference = 'Stop'

        function Assert-ExitCode {
            param([Parameter(Mandatory)][string]$Step)
            if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
                throw "$Step failed with exit code $LASTEXITCODE."
            }
        }

        Push-Location $Root
        try {
            Write-Host "Full quality task: $TaskName" -ForegroundColor DarkCyan
            switch ($TaskName) {
                'python-quality' {
                    & (Join-Path $Scripts 'check-architecture.ps1')
                    Assert-ExitCode 'Architecture check'
                    & (Join-Path $Root '.venv\Scripts\ruff.exe') check apps/api/app apps/api/tests
                    Assert-ExitCode 'Python lint'
                    & (Join-Path $Root '.venv\Scripts\python.exe') (Join-Path $Scripts 'check-python-types.py')
                    Assert-ExitCode 'Python type baseline'
                    $harnessTestRoot = Join-Path ([IO.Path]::GetTempPath()) ('researchpath-harness-' + [guid]::NewGuid().ToString('N'))
                    & (Join-Path $Root '.venv\Scripts\python.exe') -m pytest `
                        scripts/tests/test_resolve_test_impact.py scripts/tests/test_ci_workflow.py scripts/tests/test_r_build_path.py `
                        --basetemp $harnessTestRoot
                    Assert-ExitCode 'Validation harness regression tests'
                }
                'web-and-contracts' {
                    & npm run lint:web
                    Assert-ExitCode 'Web lint'
                    & (Join-Path $Scripts 'generate-contracts.ps1') -Check
                    Assert-ExitCode 'Contract generation check'
                }
                'python-lock' {
                    $lockArguments = @{}
                    if ($DisableLockCache) {
                        $lockArguments.NoCache = $true
                    }
                    & (Join-Path $Scripts 'check-python-lock.ps1') @lockArguments
                    Assert-ExitCode 'Python lock verification'
                }
                'r-quality' {
                    $previousRLibrary = $env:R_LIBS_USER
                    $previousLocale = $env:LC_ALL
                    try {
                        $env:R_LIBS_USER = Join-Path $Root '.runtime\R-library'
                        # R 4.6 UCRT may inherit an unavailable C.UTF-8 locale on
                        # Windows. Keep every R quality command in one UTF-8 locale
                        # so startup warnings are neither lost nor misclassified as
                        # an execution failure by the parallel job collector.
                        $env:LC_ALL = 'English_United States.utf8'
                        & (Join-Path $Root '.runtime\R\bin\Rscript.exe') --vanilla (Join-Path $Scripts 'check-r-lock.R') $Root
                        Assert-ExitCode 'R lock verification'
                        $baselineArguments = @((Join-Path $Scripts 'check-r-numeric-baselines.py'))
                        if ($DisableNumericBaselineCache) {
                            $baselineArguments += '--no-cache'
                        }
                        & (Join-Path $Root '.venv\Scripts\python.exe') @baselineArguments
                        Assert-ExitCode 'R numeric baseline verification'
                        & (Join-Path $Scripts 'test-r.ps1')
                        Assert-ExitCode 'R numeric tests'
                    }
                    finally {
                        $env:R_LIBS_USER = $previousRLibrary
                        $env:LC_ALL = $previousLocale
                    }
                }
                default {
                    throw "Unknown full quality task: $TaskName"
                }
            }
        }
        finally {
            Pop-Location
        }
    }
}

$failures = @()
try {
    $jobs | Wait-Job | Out-Null
    foreach ($job in $jobs) {
        # 并行任务中 native 命令（Rscript 等）的 stderr 会作为 ErrorRecord
        # 进入 job 的 Error stream；在 $ErrorActionPreference='Stop' 下
        # Receive-Job 会把诊断文本（如 RcppEigen 的 S3 覆盖提示）升级为
        # 终止错误，误杀已成功完成的任务。任务成败由 job state 与各步骤
        # Assert-ExitCode 决定，诊断 stderr 不应决定状态。
        Receive-Job -Job $job -ErrorAction Continue
        if ($job.State -ne 'Completed') {
            $reason = $job.ChildJobs[0].JobStateInfo.Reason
            $failures += if ($reason) {
                "$($job.Name): $($reason.Message)"
            }
            else {
                "$($job.Name): state=$($job.State)"
            }
        }
    }
}
finally {
    $jobs | Remove-Job -Force
}

if ($failures.Count -gt 0) {
    throw "Full quality tasks failed:`n$($failures -join "`n")"
}

Write-Host 'Parallel full quality tasks passed.' -ForegroundColor Green
