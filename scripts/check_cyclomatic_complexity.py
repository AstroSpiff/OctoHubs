#!/usr/bin/env python3
"""Reject new or worsened Ruff C901 findings against the reviewed baseline."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = PROJECT_ROOT / "quality" / "cyclomatic_complexity_baseline.json"
MESSAGE_PATTERN = re.compile(r"`(?P<name>[^`]+)` is too complex \((?P<value>\d+) > \d+\)")


def _ruff_findings() -> dict[str, int]:
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--select",
        "C901",
        "--output-format=json",
        ".",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        print(completed.stderr or completed.stdout, file=sys.stderr)
        raise SystemExit(completed.returncode)

    findings: dict[str, int] = {}
    for item in json.loads(completed.stdout or "[]"):
        match = MESSAGE_PATTERN.fullmatch(str(item.get("message") or ""))
        if not match:
            continue
        path = Path(str(item["filename"])).resolve().relative_to(PROJECT_ROOT)
        key = f"{path.as_posix()}::{match.group('name')}"
        complexity = int(match.group("value"))
        if key in findings:
            row = int(item.get("location", {}).get("row") or 0)
            key = f"{key}@{row}"
        findings[key] = complexity
    return findings


def main() -> int:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    current = _ruff_findings()
    regressions = {
        key: complexity
        for key, complexity in current.items()
        if key not in baseline or complexity > int(baseline[key])
    }
    if regressions:
        print("Cyclomatic-complexity regressions detected:", file=sys.stderr)
        for key, complexity in sorted(regressions.items()):
            previous = baseline.get(key, "new")
            print(f"- {key}: {complexity} (baseline: {previous})", file=sys.stderr)
        return 1

    reductions = len(set(baseline) - set(current)) + sum(
        1 for key, complexity in current.items() if complexity < int(baseline[key])
    )
    print(
        f"C901 baseline respected: {len(current)} active findings; "
        f"{reductions} removed or reduced."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
