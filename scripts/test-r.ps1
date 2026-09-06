[CmdletBinding()]
param()

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
    & $rscript --vanilla $testEntry $root 'public-data-glmm' 'invert'
    if ($LASTEXITCODE -ne 0) {
        throw "R testthat suite (excluding public-data-glmm) failed with exit code $LASTEXITCODE."
    }
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
