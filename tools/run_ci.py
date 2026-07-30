#!/usr/bin/env python3
"""Run the GitHub Actions CI build locally with act."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess


REPOSITORY = Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY / ".github" / "workflows" / "ci.yml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run .github/workflows/ci.yml locally with act.",
    )
    parser.add_argument(
        "--event",
        choices=("pull_request", "push"),
        default="pull_request",
        help="GitHub event to simulate (default: pull_request).",
    )
    parser.add_argument(
        "--job",
        choices=("lint", "audit", "build", "test", "e2e"),
        help="Run only the selected CI job (default: run the complete workflow).",
    )
    parser.add_argument(
        "act_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments passed to act; place them after --.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    act = shutil.which("act")
    if act is None:
        raise SystemExit(
            "act was not found on PATH. Install nektos/act and ensure Docker is running."
        )

    act_args = args.act_args
    if act_args[:1] == ["--"]:
        act_args = act_args[1:]

    command = [
        act,
        args.event,
        "--workflows",
        str(WORKFLOW),
    ]
    if args.job:
        command.extend(("--job", args.job))
    command.extend(act_args)
    return subprocess.run(command, cwd=REPOSITORY, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
