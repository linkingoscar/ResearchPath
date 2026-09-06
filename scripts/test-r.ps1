[CmdletBinding()]
param([string[]]$TestFile = @())

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$rscript = Join-Path $root '.runtime\R\bin\Rscript.exe'
$testEntry = Join-Path $root 'engine\R\tests\testthat.R'

if (-not (Test-Path -LiteralPath $rscript)) {
    throw "R runtime not found: $rscript"
}

$previousRLibrary = $env:R_LIBS_USER
$previousLocale = $env:LC_ALL
try {
    $env:R_LIBS_USER = Join-Path $root '.runtime\R-library'
    # R 4.6 UCRT starts in the C locale on some Windows hosts. Explicit UTF-8
    # parsing keeps Chinese interpretation boundaries byte-identical between
    # testthat sources, R libraries, JSON exports and the product runner.
    $env:LC_ALL = 'English_United States.utf8'
    # lme4's compiled Windows path can crash after unrelated testthat files
    # have loaded native state. Keep the GLMM oracle in its own R process so
    # the test remains enforced while avoiding cross-file native contamination.
    $selectedNames = @($TestFile | ForEach-Object {
        $path = [IO.Path]::GetFullPath($_, $root)
        $testRoot = [IO.Path]::GetFullPath((Join-Path $root 'engine/R/tests/testthat')) + [IO.Path]::DirectorySeparatorChar
        if (-not $path.StartsWith($testRoot, [StringComparison]::OrdinalIgnoreCase) -or
            [IO.Path]::GetFileName($path) -notmatch '^test-.*\.R$' -or
            -not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Invalid R test selector: $_" }
        [IO.Path]::GetFileNameWithoutExtension($path).Substring(5)
    })
    $regularNames = @($selectedNames | Where-Object { $_ -ne 'public-data-glmm' })
    if ($TestFile.Count -eq 0) {
        & $rscript --vanilla $testEntry $root 'public-data-glmm' 'invert'
        if ($LASTEXITCODE -ne 0) { throw "R testthat suite failed with exit code $LASTEXITCODE." }
    }
    elseif ($regularNames.Count) {
        $filter = '^(' + (($regularNames | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')$'
        & $rscript --vanilla $testEntry $root $filter
        if ($LASTEXITCODE -ne 0) { throw "Selected R tests failed with exit code $LASTEXITCODE." }
    }
    if ($TestFile.Count -gt 0 -and 'public-data-glmm' -notin $selectedNames) { return }
    $accessViolationExitCode = -1073741819
    $glmmExitCode = 0
    for ($attempt = 1; $attempt -le 2; $attempt += 1) {
        & $rscript --vanilla $testEntry $root 'public-data-glmm'
        $glmmExitCode = $LASTEXITCODE
        if ($glmmExitCode -ne $accessViolationExitCode -or $attempt -eq 2) {
            break
        }
        Write-Warning 'The isolated GLMM R process hit Windows access violation 0xC0000005; retrying once in a fresh process.'
    }
    if ($glmmExitCode -ne 0) {
        throw "R testthat suite (public-data-glmm isolated) failed with exit code $glmmExitCode."
    }
}
finally {
    $env:R_LIBS_USER = $previousRLibrary
    $env:LC_ALL = $previousLocale
}
