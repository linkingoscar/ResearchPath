#!/usr/bin/env python3
"""Source line ceilings using physical line counts (blank lines included)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LIMITS: dict[str, object] = {
    "hardCeiling": 800,
    "excludeNames": ["generated-api.ts"],
    "thinEntryPoints": {
        "apps/api/app/main.py": 80,
        "apps/web/src/api.ts": 20,
        "apps/web/src/types.ts": 20,
    },
    "scopes": [
        {"path": "apps/api/app/services", "filter": "*.py", "maximum": 500},
        {"path": "apps/api/tests", "filter": "test_*.py", "maximum": 500},
        {"path": "engine/R", "filter": "run_*.R", "maximum": 800},
        {"path": "apps/web/src/components", "filter": "*.tsx", "maximum": 800},
    ],
    "sourceRoots": ["apps/api/app", "apps/web/src", "engine/R"],
}


def count_lines(path: Path) -> int:
    # splitlines counts blank lines and, unlike Measure-Object -Line, cannot be
    # gamed by padding a file with empty lines.
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def scan(
    root: Path,
    limits: dict[str, object],
    baselines: dict[str, int] | None = None,
) -> list[str]:
    errors: list[str] = []
    exclude_names = set(limits.get("excludeNames") or [])
    baselines = baselines or {}

    def relative(path: Path) -> str:
        return path.relative_to(root).as_posix()

    def allowed(path: Path, nominal: int) -> int:
        return max(nominal, baselines.get(relative(path), nominal))

    for relative_path, maximum in (limits.get("thinEntryPoints") or {}).items():
        path = root / relative_path
        if not path.exists():
            continue
        lines = count_lines(path)
        ceiling = allowed(path, int(maximum))
        if lines > ceiling:
            errors.append(
                f"{relative_path} has {lines} lines; facade entrypoints "
                f"must stay under {ceiling}."
            )

    for relative_root in limits.get("sourceRoots") or []:
        source_root = root / relative_root
        if not source_root.exists():
            continue
        for path in source_root.rglob("*"):
            if (
                path.is_file()
                and path.name not in exclude_names
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
            ):
                lines = count_lines(path)
                ceiling = allowed(path, int(limits["hardCeiling"]))
                if lines > ceiling:
                    errors.append(
                        f"Hand-written source exceeds the {ceiling}-line "
                        f"hard ceiling: {path} ({lines} lines)"
                    )

    for scope in limits.get("scopes") or []:
        scope_root = root / str(scope["path"])
        if not scope_root.exists():
            continue
        for path in scope_root.rglob(str(scope["filter"])):
            if not path.is_file() or path.name in exclude_names:
                continue
            lines = count_lines(path)
            ceiling = allowed(path, int(scope["maximum"]))
            if lines > ceiling:
                errors.append(
                    f"{scope['path']} file exceeds its {ceiling}-line ceiling: "
                    f"{path} ({lines} lines)"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--limits", type=Path)
    parser.add_argument("--baselines", type=Path)
    arguments = parser.parse_args()
    limits = LIMITS
    if arguments.limits is not None:
        limits = json.loads(arguments.limits.read_text(encoding="utf-8"))
    baselines: dict[str, int] = {}
    if arguments.baselines is not None:
        payload = json.loads(arguments.baselines.read_text(encoding="utf-8"))
        baselines = {
            str(relative): int(lines) for relative, lines in payload.get("files", {}).items()
        }
    errors = scan(arguments.root, limits, baselines)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Source line ceilings passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
