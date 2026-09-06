from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
STEPS = {step["name"]: step for step in WORKFLOW["jobs"]["check"]["steps"]}
PWSH = shutil.which("pwsh")


def _pwsh(script: str, root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    assert PWSH, "PowerShell 7 is required for CI script regression tests"
    return subprocess.run(
        [PWSH, "-NoLogo", "-NoProfile", "-Command", script],
        cwd=root, env={**os.environ, **env}, capture_output=True, text=True, encoding="utf-8",
        check=False,
    )


@pytest.mark.parametrize(
    ("changed_path", "runtime_required", "mode"),
    [("docs/说明.md", "false", "Quick"), ("apps/web/src/App.tsx", "true", "Full"),
     ("engine/R/lib/regression.R", "true", "Full"), (".github/workflows/ci.yml", "true", "Full"),
     ("apps/api/tests/test_measurement.py", "true", "Targeted"),
     ("apps/web/src/components/model-builder/pathEvidence.test.ts", "false", "Targeted")],
)
def test_workflow_prepares_dependencies_for_actual_impact(
    tmp_path: Path, changed_path: str, runtime_required: str, mode: str
) -> None:
    repository = tmp_path / "repo"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    for name in ("resolve-test-impact.py", "test-impact-map.json"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    for args in (
        ["init", "-q"], ["config", "user.name", "ci-test"],
        ["config", "user.email", "ci-test@example.invalid"],
        ["add", "-A"], ["commit", "-qm", "initial"],
    ):
        subprocess.run(["git", *args], cwd=repository, check=True)
    changed = repository / changed_path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("changed\n", encoding="utf-8")
    output_path = tmp_path / "github-output"
    result = _pwsh(STEPS["Resolve test impact"]["run"], repository, {
        "RESEARCHPATH_CI_BASE_REF": "HEAD", "GITHUB_OUTPUT": str(output_path),
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    })
    assert result.returncode == 0, result.stdout + result.stderr
    outputs = dict(line.split("=", 1) for line in output_path.read_text(encoding="utf-8").splitlines())
    assert outputs["runtime-required"] == runtime_required
    assert outputs["mode"] == mode


@pytest.mark.parametrize("mode", ["Quick", "Targeted", "Full"])
def test_daily_ci_passes_selected_mode_and_event_base(tmp_path: Path, mode: str) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "harness.ps1").write_text(
        "param($Mode, $BaseRef, $DiffMode)\n"
        "@{mode=$Mode; base=$BaseRef; comparison=$DiffMode} | ConvertTo-Json -Compress\n",
        encoding="utf-8",
    )
    result = _pwsh(STEPS["Run selected checks"]["run"], tmp_path, {
        "RESEARCHPATH_CI_BASE_REF": "a" * 40,
        "RESEARCHPATH_CI_MODE": mode,
    })
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "mode": mode, "base": "a" * 40, "comparison": "direct",
    }


@pytest.mark.parametrize("failing_command", ["", "build:web", "test:e2e"])
def test_selected_browser_file_builds_first_and_propagates_failure(
    tmp_path: Path, failing_command: str
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(ROOT / "scripts/run-targeted-tests.ps1", scripts / "run-targeted-tests.ps1")
    browser_tests = tmp_path / "tests/e2e"
    browser_tests.mkdir(parents=True)
    (browser_tests / "selected.spec.ts").write_text("", encoding="utf-8")
    (browser_tests / "unrelated.spec.ts").write_text("", encoding="utf-8")
    log = tmp_path / "commands.jsonl"
    result = _pwsh(
        """
        function npm {
            @{command=($args -join ' '); preview=$env:RESEARCHPATH_E2E_PREVIEW_API_PORT} |
                ConvertTo-Json -Compress | Add-Content -LiteralPath $env:CI_TEST_LOG
            $global:LASTEXITCODE = if ($args -contains $env:CI_TEST_FAIL) { 19 } else { 0 }
        }
        $failed = $false
        try { & ./scripts/run-targeted-tests.ps1 -E2ETest tests/e2e/selected.spec.ts }
        catch { $failed = $true }
        @{failed=$failed; preview=$env:RESEARCHPATH_E2E_PREVIEW_API_PORT} |
            ConvertTo-Json -Compress | Add-Content -LiteralPath $env:CI_TEST_LOG
        """,
        tmp_path,
        {"CI_TEST_LOG": str(log), "CI_TEST_FAIL": failing_command,
         "RESEARCHPATH_E2E_PREVIEW_API_PORT": "12345"},
    )
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert records[0]["command"] == "run build:web"
    if failing_command != "build:web":
        assert len(records) == 3
        assert records[1]["command"].startswith("run test:e2e ")
        assert records[1]["command"].endswith("/tests/e2e/selected.spec.ts")
        assert "unrelated.spec.ts" not in records[1]["command"]
        assert 1 <= int(records[1]["preview"]) <= 65535
    else:
        assert len(records) == 2
    assert records[-1] == {"failed": bool(failing_command), "preview": "12345"}


@pytest.mark.parametrize("argument", ["", "-WebTest missing.test.tsx", "-WebTest ../escape.test.tsx"])
def test_empty_or_invalid_selection_cannot_run_the_full_suite(tmp_path: Path, argument: str) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(ROOT / "scripts/run-targeted-tests.ps1", scripts / "run-targeted-tests.ps1")
    result = _pwsh(
        "function npm { throw 'Unexpected test invocation' }; "
        f"& ./scripts/run-targeted-tests.ps1 {argument}", tmp_path, {},
    )
    assert result.returncode != 0
    assert "Unexpected test invocation" not in result.stderr


def test_full_escalation_does_not_run_quick_first(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("harness.ps1", "resolve-test-impact.py", "test-impact-map.json"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    (scripts / "check-architecture.ps1").write_text("throw 'Quick unexpectedly executed'", encoding="utf-8")
    (scripts / "test.ps1").write_text("param($PytestWorkers)\nWrite-Output 'FULL_RAN'", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / ".venv")], check=True)
    result = _pwsh(
        "& ./scripts/harness.ps1 -Mode Targeted -ChangedFile specs/model-spec.schema.json", tmp_path, {},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FULL_RAN" in result.stdout
    assert "Quick unexpectedly executed" not in result.stderr
