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

RISK_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


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


def resolve(files: list[str], mapping: dict[str, Any]) -> dict[str, Any]:
    changed = sorted({_normalise(path) for path in files if _normalise(path)})
    matched_rules: set[str] = set()
    unmatched: list[str] = []
    lanes: set[str] = set()
    risk = "A"
    escalation: str | None = None

    for path in changed:
        path_matches = [
            rule
            for rule in mapping["rules"]
            if any(_matches(path, pattern) for pattern in rule["patterns"])
        ]
        if not path_matches:
            unmatched.append(path)
            continue
        for rule in path_matches:
            matched_rules.add(rule["id"])
            lanes.update(rule.get("lanes", []))
            if RISK_ORDER[rule["risk"]] > RISK_ORDER[risk]:
                risk = rule["risk"]
            if rule.get("escalation"):
                escalation = rule["escalation"]

    if not changed:
        escalation = mapping["defaultEscalation"]
    if unmatched:
        escalation = mapping["defaultEscalation"]
        risk = "D"
    if escalation:
        lanes.clear()

    return {
        "schemaVersion": mapping["schemaVersion"],
        "changedFiles": changed,
        "matchedRules": sorted(matched_rules),
        "unmatchedFiles": unmatched,
        "risk": risk,
        "lanes": sorted(lanes),
        "escalation": escalation,
        "deferred": ["coverage", "complete-browser-suite", "release-audit"]
        if not escalation
        else [],
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


def discover_changed_files(root: Path, base_ref: str) -> list[str]:
    # NUL-delimited output bypasses core.quotePath C-style quoting entirely and
    # keeps filenames byte-exact, including spaces, backslashes and quotes.
    files = decode_git_paths(
        _git_bytes(root, "diff", "--name-only", "-z", f"{base_ref}...HEAD")
    )
    files.extend(decode_git_paths(_git_bytes(root, "diff", "--name-only", "-z")))
    files.extend(decode_git_paths(_git_bytes(root, "diff", "--name-only", "-z", "--cached")))
    files.extend(
        decode_git_paths(_git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z"))
    )
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-ref", default="HEAD~1")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--map", dest="map_path", type=Path)
    arguments = parser.parse_args()

    root = arguments.root.resolve()
    map_path = arguments.map_path or root / "scripts" / "test-impact-map.json"
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    try:
        files = arguments.changed_file or discover_changed_files(root, arguments.base_ref)
        plan = resolve(files, mapping)
    except RuntimeError as error:
        plan = {
            "schemaVersion": mapping["schemaVersion"],
            "changedFiles": [],
            "matchedRules": [],
            "unmatchedFiles": [],
            "risk": "D",
            "lanes": [],
            "escalation": mapping["defaultEscalation"],
            "deferred": [],
            "reason": str(error),
        }
    # ASCII-escaped JSON survives Windows hosts whose native-command stdout
    # decoding is not UTF-8; ConvertFrom-Json restores the original path.
    json.dump(plan, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
