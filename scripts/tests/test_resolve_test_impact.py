from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "resolve_test_impact", ROOT / "scripts" / "resolve-test-impact.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MAPPING = json.loads((ROOT / "scripts" / "test-impact-map.json").read_text(encoding="utf-8"))


def test_docs_only_stays_targeted() -> None:
    plan = MODULE.resolve(["docs/04-工程开发与验证.md"], MAPPING)
    assert plan["risk"] == "A"
    assert plan["lanes"] == ["docs-only"]
    assert plan["escalation"] is None


def test_statistical_contract_change_collects_all_required_lanes() -> None:
    plan = MODULE.resolve(["engine/R/lib/regression.R", "specs/result-bundle.schema.json"], MAPPING)
    assert plan["risk"] == "C"
    assert plan["escalation"] is None
    assert plan["lanes"] == [
        "api-no-coverage",
        "contracts",
        "r-goldens",
        "r-statistical",
        "web-unit",
    ]


def test_unknown_or_harness_change_fails_safe_to_full() -> None:
    for path in ("unmapped.file", "scripts/harness.ps1"):
        plan = MODULE.resolve([path], MAPPING)
        assert plan["risk"] == "D"
        assert plan["lanes"] == []
        assert plan["escalation"] == "Full"


def test_decode_git_paths_handles_raw_unicode_and_special_names() -> None:
    raw = (
        "docs/04-工程开发与验证.md".encode("utf-8")
        + b"\0"
        + "docs/带 空格 的 报告.md".encode("utf-8")
        + b"\0"
        + "docs/back\\slash.md".encode("utf-8")
        + b"\0"
        + 'docs/"quoted".md'.encode("utf-8")
        + b"\0"
    )
    assert MODULE.decode_git_paths(raw) == [
        "docs/04-工程开发与验证.md",
        "docs/带 空格 的 报告.md",
        "docs/back\\slash.md",
        'docs/"quoted".md',
    ]


def test_decode_git_paths_falls_back_to_c_style_quoted_octal_escapes() -> None:
    raw = b'"docs/\\346\\226\\207\\346\\241\\243.md"\0'
    assert MODULE.decode_git_paths(raw) == ["docs/文档.md"]


def test_discover_changed_files_decodes_unicode_paths_in_real_git_worktree(
    tmp_path: Path,
) -> None:
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.name", "resolver-test"],
        ["git", "config", "user.email", "resolver-test@example.invalid"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True)
    docs = tmp_path / "docs"
    docs.mkdir()
    changed = docs / "04-工程开发与验证.md"
    changed.write_text("line 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    changed.write_text("line 1\nline 2\n", encoding="utf-8")

    files = MODULE.discover_changed_files(tmp_path, "HEAD")
    assert "docs/04-工程开发与验证.md" in files
    assert not any(path.startswith('"') for path in files)

    plan = MODULE.resolve(files, MAPPING)
    assert plan["unmatchedFiles"] == []
    assert plan["escalation"] is None
    assert plan["risk"] == "A"
    assert plan["lanes"] == ["docs-only"]
    assert plan["deferred"] == ["coverage", "complete-browser-suite", "release-audit"]
