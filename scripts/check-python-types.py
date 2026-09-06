from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "apps" / "api" / "pyright-baseline.json"
SOURCE_ROOTS = (ROOT / "apps" / "api" / "app", ROOT / "apps" / "api" / "tests")


def count_explicit_any_usages() -> tuple[int, dict[str, int]]:
    counts: Counter[str] = Counter()
    for source_root in SOURCE_ROOTS:
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            relative = path.relative_to(ROOT).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "Any":
                    counts[relative] += 1
                elif (
                    isinstance(node, ast.Attribute)
                    and node.attr == "Any"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "typing"
                ):
                    counts[relative] += 1
    return sum(counts.values()), dict(sorted(counts.items()))


def run_pyright() -> tuple[dict[str, int], dict[str, Any]]:
    executable = shutil.which("node")
    pyright = ROOT / "node_modules" / "pyright" / "index.js"
    if executable is None or not pyright.exists():
        raise RuntimeError(
            "Install Node dependencies before running the pinned Pyright checker"
        )
    process = subprocess.run(
        [executable, str(pyright), "--outputjson"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        report = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Pyright did not return JSON: {process.stderr}") from error

    rules = Counter(
        diagnostic.get("rule", "unclassified")
        for diagnostic in report.get("generalDiagnostics", [])
        if diagnostic.get("severity") == "error"
    )
    return dict(sorted(rules.items())), report


def build_baseline() -> dict[str, Any]:
    rules, report = run_pyright()
    any_total, any_by_file = count_explicit_any_usages()
    return {
        "schemaVersion": "1.0.0",
        "tool": "pyright@1.1.410",
        "pythonVersion": "3.10",
        "pyrightErrorMaximumByRule": rules,
        "explicitAnyUsageMaximum": any_total,
        "explicitAnyUsagesByFile": any_by_file,
        "summary": report.get("summary", {}),
    }


def _diagnostic_summary(diagnostic: dict[str, Any]) -> str:
    path = diagnostic.get("file", "<unknown>")
    rule = diagnostic.get("rule", "unclassified")
    message = str(diagnostic.get("message", "")).replace("\n", " ").strip()
    start = diagnostic.get("range", {}).get("start", {})
    line = int(start.get("line", 0)) + 1
    character = int(start.get("character", 0)) + 1
    try:
        path = Path(str(path)).resolve().relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        path = str(path)
    return f"  - {path}:{line}:{character} [{rule}] {message}"


def verify(baseline: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    current_rules, report = run_pyright()
    expected_rules = baseline["pyrightErrorMaximumByRule"]
    failed_rules: set[str] = set()
    for rule, count in current_rules.items():
        maximum = int(expected_rules.get(rule, 0))
        if count > maximum:
            failed_rules.add(rule)
            failures.append(f"Pyright {rule}: {count} errors exceeds baseline {maximum}")

    if failed_rules:
        diagnostics = [
            diagnostic
            for diagnostic in report.get("generalDiagnostics", [])
            if diagnostic.get("severity") == "error"
            and diagnostic.get("rule") in failed_rules
        ]
        failures.append("Pyright diagnostics for rules above baseline:")
        failures.extend(_diagnostic_summary(diagnostic) for diagnostic in diagnostics)

    any_total, _ = count_explicit_any_usages()
    any_maximum = int(baseline["explicitAnyUsageMaximum"])
    if any_total > any_maximum:
        failures.append(f"Explicit Any usages: {any_total} exceeds baseline {any_maximum}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prevent Python type diagnostics and explicit Any usages from growing."
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Replace the baseline after an intentional, reviewed type migration.",
    )
    args = parser.parse_args()

    if args.write_baseline:
        BASELINE_PATH.write_text(
            json.dumps(build_baseline(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {BASELINE_PATH.relative_to(ROOT)}")
        return 0

    if not BASELINE_PATH.exists():
        print("Python type baseline is missing.", file=sys.stderr)
        return 1
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    failures = verify(baseline)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Python type baseline checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
