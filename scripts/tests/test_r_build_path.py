from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RSCRIPT = ROOT / ".runtime/R/bin/Rscript.exe"
pytestmark = pytest.mark.skipif(not RSCRIPT.is_file(), reason="Pinned R runtime is not installed")


@pytest.mark.parametrize("name,allowed", [("ascii-library", True), ("中文库", False)])
def test_source_build_path_checks_physical_encoding(tmp_path: Path, name: str, allowed: bool) -> None:
    directory = tmp_path / name
    directory.mkdir()
    result = subprocess.run(
        [str(RSCRIPT), "--vanilla", str(ROOT / "scripts/check-r-build-path.R"), str(directory)],
        env={**os.environ, "LC_ALL": "English_United States.utf8"},
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert (result.returncode == 0) is allowed
    if not allowed:
        assert "non-ASCII physical path" in result.stderr


def test_ascii_junction_does_not_hide_unicode_target(tmp_path: Path) -> None:
    target = tmp_path / "中文库"
    target.mkdir()
    alias = tmp_path / "alias"
    shell = shutil.which("pwsh")
    assert shell
    result = subprocess.run(
        [shell, "-NoLogo", "-NoProfile", "-Command", """
        New-Item -ItemType Junction -Path $env:RP_ALIAS -Target $env:RP_TARGET | Out-Null
        try {
            & $env:RP_RSCRIPT --vanilla $env:RP_CHECK $env:RP_ALIAS
            $resultCode = $LASTEXITCODE
        } finally { [IO.Directory]::Delete($env:RP_ALIAS) }
        exit $resultCode
        """],
        env={**os.environ, "RP_ALIAS": str(alias), "RP_TARGET": str(target),
             "RP_RSCRIPT": str(RSCRIPT), "RP_CHECK": str(ROOT / "scripts/check-r-build-path.R"),
             "LC_ALL": "English_United States.utf8"},
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode != 0
    assert "non-ASCII physical path" in result.stderr
    assert target.is_dir()
    assert not alias.exists()
