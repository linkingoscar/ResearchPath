#!/usr/bin/env python3
"""Resolve changed files to a deterministic, fail-safe validation plan."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _normalise(path: str) -> str:
    return path.strip().replace("\\", "/").removeprefix("./")


def _matches(path: str, pattern: str) -> bool:
    path = _normalise(path)
    pattern = _normalise(pattern)
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if pattern.endswith("/**"):
        return path == pattern[:-3]
    return False


def _module_for_path(path: str, mapping: dict[str, Any]) -> dict[str, Any] | None:
    # Test files belong to the same module as their source, including files whose
    # names differ from the source directory. Browser journeys can span modules.
    for entry in mapping["modules"]:
        patterns = entry["patterns"] + [
            pattern for kind, paths in entry["tests"].items() if kind != "e2e"
            for pattern in paths
        ]
        if any(_matches(path, pattern) for pattern in patterns):
            return entry
    return None


def resolve(files: list[str], mapping: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    changed = sorted({_normalise(path) for path in files if _normalise(path)})
    tests: dict[str, set[str]] = {kind: set() for kind in ("api", "web", "r", "e2e")}
    modules: set[str] = set()
    reasons: list[str] = [] if changed else ["No changed-file scope is available."]
    for path in changed:
        if any(_matches(path, pattern) for pattern in mapping["fullPatterns"]):
            reasons.append(f"Shared foundation or validation infrastructure: {path}")
            continue
        if any(_matches(path, pattern) for pattern in mapping["quickPatterns"]):
            continue
        # A changed test runs itself, rather than all tests in its language.
        kind = (
            "api" if path.startswith("apps/api/tests/test_") and path.endswith(".py") else
            "web" if path.startswith("apps/web/src/") and ".test." in path else
            "r" if path.startswith("engine/R/tests/testthat/test-") and path.endswith(".R") else
            "e2e" if path.startswith("tests/e2e/") and path.endswith(".spec.ts") else None
        )
        module = _module_for_path(path, mapping)
        if kind and (root / path).is_file():
            tests[kind].add(path)
            modules.add(module["id"] if module else f"{kind}-tests")
            continue
        if module is None:
            reasons.append(f"Unmapped change: {path}")
            continue
        modules.add(module["id"])
        kinds = (
            ["api"] if path.startswith("apps/api/") else
            ["web", "e2e"] if path.startswith("apps/web/") else
            ["r", "api"] if path.startswith("engine/R/") else []
        )
        for test_kind in kinds:
            patterns = module["tests"].get(test_kind, [])
            if not patterns and test_kind == "e2e":
                continue
            selected = {
                item.relative_to(root).as_posix()
                for pattern in patterns for item in root.glob(pattern) if item.is_file()
            }
            if test_kind != "e2e":
                # A broad parent glob must not pull in a specialized module.
                selected = {path for path in selected
                            if _module_for_path(path, mapping) == module}
            if not selected:
                reasons.append(f"No {test_kind} tests mapped for {module['id']}: {path}")
            tests[test_kind].update(selected)
    if len(modules) > 1:
        reasons.append("Cross-domain change: " + ", ".join(sorted(modules)))
    mode = "Full" if reasons else "Targeted" if modules else "Quick"
    if mode != "Targeted":
        tests = {kind: set() for kind in tests}
    return {
        "schemaVersion": mapping["schemaVersion"],
        "changedFiles": changed,
        "mode": mode,
        "modules": sorted(modules),
        "tests": {kind: sorted(paths) for kind, paths in tests.items()},
        "requiresRuntime": mode == "Full" or any(tests[kind] for kind in ("api", "r", "e2e")),
        "reasons": reasons,
    }


def _git_bytes(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, check=False
    )
    if completed.returncode:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(stderr or f"git {' '.join(arguments)} failed")
    return completed.stdout


_OCTAL_ESCAPE = re.compile(rb"\\([0-7]{3})")


def decode_git_paths(raw: bytes) -> list[str]:
    """Decode NUL-separated git path output.

    ``git --name-only -z`` already returns raw, unquoted bytes, which handles
    Unicode, spaces, backslashes and quotes without touching ``core.quotePath``.
    The C-style quoted fallback below keeps the decoder deterministic when a
    caller (or another tool) still hands it ``core.quotePath`` output containing
    octal-escaped UTF-8 bytes.
    """

    def decode_quoted(part: bytes) -> bytes:
        inner = part[1:-1]
        out = bytearray()
        index = 0
        while index < len(inner):
            byte = inner[index]
            if byte == 0x5C and index + 1 < len(inner):
                following = inner[index + 1]
                if following == 0x5C:
                    out.append(0x5C)
                    index += 2
                    continue
                if following == 0x22:
                    out.append(0x22)
                    index += 2
                    continue
                if 0x30 <= following <= 0x37:
                    octal = inner[index + 1 : index + 4]
                    if len(octal) == 3 and _OCTAL_ESCAPE.fullmatch(inner[index : index + 4]):
                        out.append(int(octal, 8))
                        index += 4
                        continue
                out.append(following)
                index += 2
                continue
            out.append(byte)
            index += 1
        return bytes(out)

    paths: list[str] = []
    for part in raw.split(b"\0"):
        if not part:
            continue
        if part.startswith(b'"') and part.endswith(b'"') and b"\\" in part:
            part = decode_quoted(part)
        paths.append(os.fsdecode(part))
    return paths


def discover_changed_files(
    root: Path, base_ref: str, diff_mode: str = "merge-base"
) -> list[str]:
    # NUL-delimited output bypasses core.quotePath C-style quoting entirely and
    # keeps filenames byte-exact, including spaces, backslashes and quotes.
    # CI compares the event's previous/base tree with the tested checkout.
    # A merge-base diff would miss removals when a push rewinds or replaces history.
    comparison = [base_ref, "HEAD"] if diff_mode == "direct" else [f"{base_ref}...HEAD"]
    # Report both sides of a rename so moving code into docs cannot skip its tests.
    diff_arguments = ("diff", "--name-only", "--no-renames", "-z")
    files = decode_git_paths(_git_bytes(root, *diff_arguments, *comparison))
    files.extend(decode_git_paths(_git_bytes(root, *diff_arguments)))
    files.extend(decode_git_paths(_git_bytes(root, *diff_arguments, "--cached")))
    files.extend(
        decode_git_paths(_git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z"))
    )
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-ref", default="HEAD~1")
    parser.add_argument("--diff-mode", choices=("merge-base", "direct"), default="merge-base")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--map", dest="map_path", type=Path)
    arguments = parser.parse_args()

    root = arguments.root.resolve()
    map_path = arguments.map_path or root / "scripts" / "test-impact-map.json"
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    try:
        files = arguments.changed_file or discover_changed_files(
            root, arguments.base_ref, arguments.diff_mode
        )
        plan = resolve(files, mapping, root)
    except RuntimeError as error:
        plan = resolve([], mapping, root)
        plan["reasons"] = [str(error)]
    # ASCII-escaped JSON survives Windows hosts whose native-command stdout
    # decoding is not UTF-8; ConvertFrom-Json restores the original path.
    json.dump(plan, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
