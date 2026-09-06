from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_quality_workflow_avoids_duplicate_branch_and_pull_request_runs() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    triggers = ci.split("concurrency:", 1)[0]
    assert re.search(r"push:\s*\n\s+branches:\s*\n\s+- main", triggers)
    assert "pull_request:" in triggers


def test_pages_workflow_actions_are_sha_pinned_and_scoped() -> None:
    pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    triggers = pages.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in triggers
    assert "push:" not in triggers
    assert not re.search(r"branches:\s*\n\s*- master", pages)
    assert not re.search(r"uses:\s+[^\s]+@v\d+", pages)
    assert "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10" in pages
    assert "persist-credentials: false" in pages
    assert "pages: write" in pages
    assert "id-token: write" in pages
    build_job = pages.split("build:", 1)[1].split("deploy:", 1)[0]
    assert "pages: write" not in build_job
    deploy_job = pages.split("deploy:", 1)[1]
    assert "pages: write" in deploy_job


def test_process_macro_is_external_and_excluded_from_distribution() -> None:
    source = (ROOT / "specs" / "vendor" / "SOURCE.md").read_text(encoding="utf-8")
    normalized_source = " ".join(source.split())
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert not (ROOT / "specs" / "vendor" / "process5.0.R").exists()
    assert "specs/vendor/process5.0.R" in gitignore
    assert "3D02E6BBEC08A4A3EE9EDEB8E6300678D717A7A08E41E11C8149C04AB64B8648" in source
    assert "ALL RIGHTS RESERVED" in source
    assert "not distributed" in source
    assert "written redistribution permission" in normalized_source
    assert "regeneration of frozen golden-standard evidence only" in normalized_source


def test_rtools_cache_key_is_derived_from_a_version_marker() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    marker = (ROOT / ".github" / "rtools45-cache-key.txt").read_text(encoding="utf-8")
    assert "hashFiles('.github/rtools45-cache-key.txt')" in ci
    assert "windows-rtools45-6768-6492" not in ci
    assert "6768-6492" in marker
    assert "614c7378150a012e70b16edcfe5236dcead47f491f1f54203ea8d451c7743a75" in marker


def test_qs2_source_install_uses_the_locked_archive_and_hash() -> None:
    setup = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")
    assert "$qs2Version = '0.2.2'" in setup
    assert "Archive/qs2/qs2_$qs2Version.tar.gz" in setup
    assert "c59ff879e858aef0afb13de25127239624e65b20179c8631fa1f62edea25f48f" in setup
    assert "Get-FileHash -LiteralPath $qs2Archive -Algorithm SHA256" in setup
    assert "install.packages('$qs2ArchiveForR', repos=NULL" in setup
    assert "install.packages('qs2', repos=" not in setup
