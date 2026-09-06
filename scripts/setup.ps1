[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root '.runtime'
$rVersion = '4.6.1'
$rInstallerHash = 'c5424c40cd70ef85765a55d2ff96bb602b5f30ed536938ff004f14db5db3c2df'
$rtoolsInstallerHash = '614c7378150a012e70b16edcfe5236dcead47f491f1f54203ea8d451c7743a75'
$renvVersion = '1.2.4'
$renvArchiveHash = 'e63c637dc785d55848d9dbc6c9599378103803efd47c1f3f1f82057c00575e8c'
$qs2Version = '0.2.2'
$qs2ArchiveHash = 'c59ff879e858aef0afb13de25127239624e65b20179c8631fa1f62edea25f48f'
$jsonliteVersion = '2.0.0'
$glmmTmbVersion = '1.1.14'
$glmmTmbArchiveHash = '623c81cfe4b3c6825db15d44781eccf7a357cf15b423fe9f00459f52beeffbbd'
$rscript = Join-Path $runtime 'R\bin\Rscript.exe'
$rLibrary = Join-Path $runtime 'R-library'
$renvBootstrapLibrary = Join-Path $runtime 'renv-bootstrap-library'

New-Item -ItemType Directory -Force -Path $runtime, $rLibrary, $renvBootstrapLibrary | Out-Null

if (-not (Test-Path -LiteralPath $rscript)) {
    $installer = Join-Path $runtime "R-$rVersion-win.exe"
    $uri = "https://cloud.r-project.org/bin/windows/base/old/$rVersion/R-$rVersion-win.exe"
    Write-Host "Downloading R $rVersion..."
    Invoke-WebRequest -Uri $uri -OutFile $installer
    $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $rInstallerHash) {
        throw "R installer hash mismatch: $actualHash"
    }
    $target = Join-Path $runtime 'R'
    $process = Start-Process -FilePath $installer -ArgumentList @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/CURRENTUSER',
        "/DIR=$target",
        '/TASKS='
    ) -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "R installation failed with exit code $($process.ExitCode)"
    }
}

# Windows 从源码构建 R 包需要 Rtools；CI 干净环境缺失时 renv::restore
# 对无预编译二进制版本的包（如 qs2）会编译失败（DLL 无法加载）。
$rtoolsBin = 'C:\rtools45\x86_64-w64-mingw32.static.posix\bin'
$rtoolsUsrBin = 'C:\rtools45\usr\bin'
if (-not (Test-Path -LiteralPath $rtoolsBin)) {
    $rtoolsInstaller = Join-Path $runtime 'rtools45.exe'
    $rtoolsUri = 'https://cran.r-project.org/bin/windows/Rtools/rtools45/files/rtools45-6768-6492.exe'
    Write-Host 'Downloading Rtools 4.5...'
    Invoke-WebRequest -Uri $rtoolsUri -OutFile $rtoolsInstaller
    $actualRtoolsHash = (
        Get-FileHash -LiteralPath $rtoolsInstaller -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($actualRtoolsHash -ne $rtoolsInstallerHash) {
        throw "Rtools installer hash mismatch: $actualRtoolsHash"
    }
    $rtoolsProcess = Start-Process -FilePath $rtoolsInstaller -ArgumentList @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART'
    ) -WindowStyle Hidden -Wait -PassThru
    if ($rtoolsProcess.ExitCode -ne 0) {
        throw "Rtools installation failed with exit code $($rtoolsProcess.ExitCode)"
    }
}
if (-not $env:PATH.Contains($rtoolsBin)) {
    $env:PATH = "$rtoolsBin;$rtoolsUsrBin;$env:PATH"
}

$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & python -m venv (Join-Path $root '.venv')
}
& $venvPython -m pip install --disable-pip-version-check --require-hashes -r (Join-Path $root 'apps\api\requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

$env:R_LIBS_USER = $rLibrary
$env:LC_ALL = 'English_United States.utf8'
$renvBootstrapLibraryForR = $renvBootstrapLibrary.Replace('\', '/')
$renvBootstrapPrelude = ".libPaths(unique(c('$renvBootstrapLibraryForR', .libPaths())));"
$installedRenvVersion = & $rscript --vanilla -e "$renvBootstrapPrelude if (requireNamespace('renv', lib.loc='$renvBootstrapLibraryForR', quietly=TRUE)) cat(as.character(packageVersion('renv', lib.loc='$renvBootstrapLibraryForR')))"
if ($installedRenvVersion -ne $renvVersion) {
    $renvArchive = Join-Path $runtime "renv_$renvVersion.tar.gz"
    # CRAN 将非当前版本放在 Archive；当前版本位于 src/contrib/。
    # 先尝试版本归档，404 时再尝试当前目录。
    $renvUri = "https://cloud.r-project.org/src/contrib/Archive/renv/renv_$renvVersion.tar.gz"
    try {
        Invoke-WebRequest -Uri $renvUri -OutFile $renvArchive
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
        $renvUri = "https://cloud.r-project.org/src/contrib/renv_$renvVersion.tar.gz"
        Invoke-WebRequest -Uri $renvUri -OutFile $renvArchive
    }
    $actualRenvHash = (Get-FileHash -LiteralPath $renvArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualRenvHash -ne $renvArchiveHash) {
        throw "renv archive hash mismatch: $actualRenvHash"
    }
    $renvArchiveForR = $renvArchive.Replace('\', '/')
    & $rscript --vanilla -e "install.packages('$renvArchiveForR', repos=NULL, type='source', lib='$renvBootstrapLibraryForR')"
    if ($LASTEXITCODE -ne 0) { throw 'Pinned renv installation failed.' }
}
$rLockPath = Join-Path $root 'renv.lock'
$rLockPathForR = $rLockPath.Replace('\', '/')
# qs2 0.2.2 的 CRAN Windows binary 与 R 4.6.1 不兼容（本地与 CI 均复现
# qs2.dll 加载失败）。
# 先经 renv 按 lock 版本装好 qs2 依赖链（Rcpp/RcppParallel/stringfish），
# 再以 dependencies=FALSE 源码编译 qs2 本体——install.packages 默认会升级
# 已装依赖到 CRAN 最新（如 RcppParallel 6.2.0），使 qs2.dll 链接锁外版本，
# 后续 renv restore 降回 lock 版本后 DLL 加载失败。
#
# 注意：renv 1.2.x 在本仓库场景（无 renv/ 目录、cwd 有 renv.lock）会在
# restore 计划里产生一条 NULL 幽灵记录（"package 'NULL' is not available"），
# 该失败会让默认 transactional restore 判定整体失败并回滚——已成功安装的
# 包会从目标库消失（.runtime/R-library 因此为空，后续 qs2 编译的依赖检查
# 失败）。因此所有 restore 必须 transactional=FALSE（成功包保留），并且
# 不能依赖 restore 的退出码（幽灵记录使其恒非 0）——以 requireNamespace
# 与 check-r-lock.R 做权威验证。
& $rscript --vanilla -e "$renvBootstrapPrelude renv::restore(lockfile='$rLockPathForR', library=Sys.getenv('R_LIBS_USER'), packages=c('Rcpp','RcppParallel','stringfish'), transactional=FALSE, prompt=FALSE)"
& $rscript --vanilla -e "stopifnot(requireNamespace('Rcpp', quietly=TRUE), requireNamespace('RcppParallel', quietly=TRUE), requireNamespace('stringfish', quietly=TRUE))"
if ($LASTEXITCODE -ne 0) { throw 'qs2 dependency restore verification failed.' }
$qs2Ready = & $rscript --vanilla -e "if (requireNamespace('qs2', quietly=TRUE) && identical(as.character(packageVersion('qs2')), '$qs2Version')) cat('ready')"
if ($qs2Ready -ne 'ready') {
    $qs2Archive = Join-Path $runtime "qs2_$qs2Version.tar.gz"
    $qs2Uri = "https://cloud.r-project.org/src/contrib/Archive/qs2/qs2_$qs2Version.tar.gz"
    Invoke-WebRequest -Uri $qs2Uri -OutFile $qs2Archive
    $actualQs2Hash = (Get-FileHash -LiteralPath $qs2Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualQs2Hash -ne $qs2ArchiveHash) {
        throw "qs2 archive hash mismatch: $actualQs2Hash"
    }
    $qs2ArchiveForR = $qs2Archive.Replace('\', '/')
    & $rscript --vanilla -e "install.packages('$qs2ArchiveForR', repos=NULL, lib=Sys.getenv('R_LIBS_USER'), type='source', dependencies=FALSE)"
    if ($LASTEXITCODE -ne 0) { throw 'qs2 source installation failed.' }
}
# 版本相同仍必须验证 DLL 可加载；有效缓存不得重复源码编译。
& $rscript --vanilla -e "stopifnot(requireNamespace('qs2', quietly=TRUE), identical(as.character(packageVersion('qs2')), '$qs2Version'))"
if ($LASTEXITCODE -ne 0) { throw 'qs2 source installation verification failed.' }
$jsonliteReady = & $rscript --vanilla -e "if (requireNamespace('jsonlite', quietly=TRUE) && identical(as.character(packageVersion('jsonlite')), '$jsonliteVersion')) cat('ready')"
if ($jsonliteReady -ne 'ready') {
    & $rscript --vanilla -e "$renvBootstrapPrelude renv::restore(lockfile='$rLockPathForR', library=Sys.getenv('R_LIBS_USER'), packages='jsonlite', rebuild=TRUE, transactional=FALSE, prompt=FALSE)"
}
& $rscript --vanilla -e "stopifnot(requireNamespace('jsonlite', quietly=TRUE))"
if ($LASTEXITCODE -ne 0) { throw 'R lock parser bootstrap verification failed.' }
& $rscript --vanilla -e "$renvBootstrapPrelude renv::restore(lockfile='$rLockPathForR', library=Sys.getenv('R_LIBS_USER'), transactional=FALSE, prompt=FALSE)"
& $rscript --vanilla (Join-Path $root 'scripts\check-r-lock.R') $root
if ($LASTEXITCODE -ne 0) { throw 'Installed R dependency verification failed.' }

# CRAN may rebuild a Windows glmmTMB binary in place without changing its
# package version. A binary built against a newer TMB passes the version-only
# lock check but emits an ABI mismatch warning and can make estimators hundreds
# of seconds slower. Rebuild the pinned glmmTMB source against the locked TMB
# only when the runtime probe detects that mismatch.
$glmmTmbAbiProbe = Join-Path $root 'scripts\check-glmmtmb-abi.R'
& $rscript --vanilla $glmmTmbAbiProbe
if ($LASTEXITCODE -ne 0) {
    $glmmTmbArchive = Join-Path $runtime "glmmTMB_$glmmTmbVersion.tar.gz"
    $glmmTmbUris = @(
        "https://cloud.r-project.org/src/contrib/glmmTMB_$glmmTmbVersion.tar.gz",
        "https://cloud.r-project.org/src/contrib/Archive/glmmTMB/glmmTMB_$glmmTmbVersion.tar.gz"
    )
    $downloaded = $false
    foreach ($glmmTmbUri in $glmmTmbUris) {
        try {
            Invoke-WebRequest -Uri $glmmTmbUri -OutFile $glmmTmbArchive
            $downloaded = $true
            break
        }
        catch {
            if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
        }
    }
    if (-not $downloaded) {
        throw "Pinned glmmTMB source archive $glmmTmbVersion was not found."
    }
    $actualGlmmTmbHash = (
        Get-FileHash -LiteralPath $glmmTmbArchive -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($actualGlmmTmbHash -ne $glmmTmbArchiveHash) {
        throw "glmmTMB source archive hash mismatch: $actualGlmmTmbHash"
    }
    $glmmTmbArchiveForR = $glmmTmbArchive.Replace('\', '/')
    $previousMakeFlags = $env:MAKEFLAGS
    try {
        $env:MAKEFLAGS = '-j1'
        & $rscript --vanilla -e "install.packages('$glmmTmbArchiveForR', repos=NULL, type='source', dependencies=FALSE, lib=Sys.getenv('R_LIBS_USER'))"
        if ($LASTEXITCODE -ne 0) { throw 'Pinned glmmTMB source build failed.' }
    }
    finally {
        $env:MAKEFLAGS = $previousMakeFlags
    }
    & $rscript --vanilla (Join-Path $root 'scripts\check-r-lock.R') $root
    if ($LASTEXITCODE -ne 0) { throw 'Source-built glmmTMB changed the R lock state.' }
    & $rscript --vanilla $glmmTmbAbiProbe
    if ($LASTEXITCODE -ne 0) { throw 'Source-built glmmTMB still has a TMB ABI mismatch.' }
}

Push-Location $root
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Node dependency installation failed.' }
    & (Join-Path $root 'node_modules\.bin\playwright.cmd') install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Playwright Chromium installation failed.' }
}
finally {
    Pop-Location
}

Write-Host 'ResearchPath development environment is ready.' -ForegroundColor Green
