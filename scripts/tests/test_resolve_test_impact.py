from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "resolve_test_impact", ROOT / "scripts" / "resolve-test-impact.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MAPPING = json.loads((ROOT / "scripts" / "test-impact-map.json").read_text(encoding="utf-8"))


def test_docs_only_uses_quick() -> None:
    plan = MODULE.resolve(["docs/04-工程开发与验证.md"], MAPPING)
    assert plan["mode"] == "Quick"
    assert not any(plan["tests"].values())
    assert plan["requiresRuntime"] is False


def test_statistical_contract_foundations_require_full() -> None:
    plan = MODULE.resolve(["engine/R/lib/regression.R", "specs/result-bundle.schema.json"], MAPPING)
    assert plan["mode"] == "Full"
    assert not any(plan["tests"].values())


def test_unknown_or_harness_change_fails_safe_to_full() -> None:
    for path in ("unmapped.file", "scripts/harness.ps1"):
        plan = MODULE.resolve([path], MAPPING)
        assert plan["mode"] == "Full"
        assert not any(plan["tests"].values())


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
    assert plan["mode"] == "Quick"
    assert plan["reasons"] == []


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()


@pytest.fixture
def git_repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "resolver-test")
    _git(tmp_path, "config", "user.email", "resolver-test@example.invalid")
    _git(tmp_path, "commit", "--allow-empty", "-qm", "initial")
    return tmp_path


def _commit_file(root: Path, name: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test content\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "add file")


def test_direct_diff_covers_all_commits_in_push(git_repository: Path) -> None:
    base = _git(git_repository, "rev-parse", "HEAD")
    _commit_file(git_repository, "engine/R/lib/regression.R")
    _commit_file(git_repository, "docs/notes.md")
    files = MODULE.discover_changed_files(git_repository, base, "direct")
    plan = MODULE.resolve(files, MAPPING)
    assert plan["mode"] == "Full"
    assert set(files) == {"engine/R/lib/regression.R", "docs/notes.md"}


def test_direct_diff_detects_statistical_removal_on_rewind(git_repository: Path) -> None:
    initial = _git(git_repository, "rev-parse", "HEAD")
    _commit_file(git_repository, "engine/R/lib/regression.R")
    before = _git(git_repository, "rev-parse", "HEAD")
    _git(git_repository, "checkout", "--detach", initial)
    _commit_file(git_repository, "docs/replacement.md")
    # Local branch comparison still excludes changes belonging only to the base.
    assert MODULE.discover_changed_files(git_repository, before) == ["docs/replacement.md"]
    files = MODULE.discover_changed_files(git_repository, before, "direct")
    assert MODULE.resolve(files, MAPPING)["mode"] == "Full"
    assert "engine/R/lib/regression.R" in files


@pytest.mark.parametrize("committed", [False, True])
def test_cross_domain_rename_preserves_source_test_lane(
    git_repository: Path, committed: bool
) -> None:
    _commit_file(git_repository, "engine/R/lib/regression.R")
    base = _git(git_repository, "rev-parse", "HEAD")
    (git_repository / "docs").mkdir()
    _git(git_repository, "mv", "engine/R/lib/regression.R", "docs/example.md")
    if committed:
        _git(git_repository, "commit", "-qm", "move code")
    files = MODULE.discover_changed_files(git_repository, base, "direct")
    assert set(files) == {"engine/R/lib/regression.R", "docs/example.md"}
    assert MODULE.resolve(files, MAPPING)["mode"] == "Full"


@pytest.mark.parametrize("base", ["0" * 40, "missing-ci-base"])
def test_unavailable_ci_base_escalates_to_full(git_repository: Path, base: str) -> None:
    output = subprocess.check_output(
        [
            sys.executable, str(ROOT / "scripts/resolve-test-impact.py"),
            "--root", str(git_repository), "--base-ref", base, "--diff-mode", "direct",
            "--map", str(ROOT / "scripts/test-impact-map.json"),
        ],
        text=True,
    )
    plan = json.loads(output)
    assert plan["mode"] == "Full"
    assert not any(plan["tests"].values())
    assert plan["reasons"]


def test_module_change_selects_its_tests_without_other_domains() -> None:
    plan = MODULE.resolve(["apps/api/app/services/measurement.py"], MAPPING)
    assert plan["mode"] == "Targeted"
    assert "apps/api/tests/test_measurement.py" in plan["tests"]["api"]
    assert "apps/api/tests/test_diary_multilevel.py" not in plan["tests"]["api"]
    assert not plan["tests"]["web"]
    assert not plan["tests"]["r"]


def test_cross_domain_change_requires_full() -> None:
    plan = MODULE.resolve([
        "apps/api/app/services/measurement.py", "apps/api/app/services/dataset_import.py",
    ], MAPPING)
    assert plan["mode"] == "Full"
    assert plan["modules"] == ["data", "measurement"]


def test_statistical_leaf_selects_relevant_r_and_api_tests() -> None:
    plan = MODULE.resolve([
        "engine/R/lib/longitudinal_panel.R",
        "engine/R/tests/testthat/test-longitudinal-goldens.R",
    ], MAPPING)
    assert plan["mode"] == "Targeted"
    assert plan["modules"] == ["longitudinal"]
    assert "engine/R/tests/testthat/test-longitudinal-goldens.R" in plan["tests"]["r"]
    assert "engine/R/tests/testthat/test-power-goldens.R" not in plan["tests"]["r"]
    assert plan["tests"]["api"]


def test_parent_module_does_not_select_specialized_module_tests() -> None:
    plan = MODULE.resolve(["apps/web/src/components/empirical/EmpiricalWizard.tsx"], MAPPING)
    assert plan["mode"] == "Targeted"
    assert plan["tests"]["web"]
    assert not any(Path(path).name.startswith(("Longitudinal", "Diary", "Power"))
                   for path in plan["tests"]["web"])


def test_missing_module_tests_fail_closed(tmp_path: Path) -> None:
    plan = MODULE.resolve(["apps/api/app/services/measurement.py"], MAPPING, tmp_path)
    assert plan["mode"] == "Full"
    assert any("No api tests" in reason for reason in plan["reasons"])


def test_changed_test_runs_itself_and_styles_remain_quick() -> None:
    path = "apps/web/src/components/model-builder/ProcessQuickSetupForm.test.tsx"
    if not (ROOT / path).is_file():
        path = next(ROOT.glob("apps/web/src/components/model-builder/*.test.tsx")).relative_to(ROOT).as_posix()
    plan = MODULE.resolve([path], MAPPING)
    assert plan["mode"] == "Targeted"
    assert plan["tests"]["web"] == [path]
    assert plan["requiresRuntime"] is False
    assert MODULE.resolve(["apps/web/src/components/ModelBuilder.module.css"], MAPPING)["mode"] == "Quick"
