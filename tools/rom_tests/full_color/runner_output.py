"""Bounded, presentation-only output shared by full-color runners."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import json
import os
from pathlib import Path
import shlex
import sys
import time
from typing import TextIO


class OutputMode(StrEnum):
    HUMAN = "human"
    JSON = "json"


def _display_path(path: Path) -> str:
    """Return an actionable path, relative to the current repository when possible."""
    resolved = path.expanduser().resolve()
    cwd = Path.cwd().resolve()
    try:
        displayed = resolved.relative_to(cwd).as_posix()
    except ValueError:
        displayed = resolved.as_posix()
    return shlex.quote(displayed or ".")


@dataclass(slots=True)
class RunnerReporter:
    """Render runner state without participating in evidence generation."""

    profile: str
    mode: OutputMode | None
    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)
    _attempt_path: Path | None = field(default=None, init=False, repr=False)
    _failure_reported: bool = field(default=False, init=False, repr=False)

    def attempt(self, path: Path) -> None:
        if self.mode is None:
            return
        self._failure_reported = False
        self._attempt_path = path.resolve()
        if self.mode is OutputMode.HUMAN:
            print(f"RUN {self.profile} evidence={_display_path(path)}", file=self.stdout)

    @property
    def attempt_path(self) -> Path | None:
        """Return the attempt allocated by this invocation, if it has one."""
        return self._attempt_path

    def running(self, component: str) -> float:
        if self.mode is not OutputMode.HUMAN:
            return 0.0
        started = time.monotonic()
        print(f"RUN {component}", file=self.stdout)
        return started

    def passed(self, component: str, started: float) -> None:
        if self.mode is OutputMode.HUMAN:
            elapsed = max(0.0, time.monotonic() - started)
            print(f"PASS {component} {elapsed:.2f}s", file=self.stdout)

    def failed(
        self, component: str, error: BaseException, evidence: Path | None = None
    ) -> None:
        if self.mode is not OutputMode.HUMAN or self._failure_reported:
            return
        self._failure_reported = True
        detail = evidence or self._attempt_path or Path.cwd()
        message = str(error).splitlines()[0].strip() or type(error).__name__
        print(f"FAIL {component}: {message}", file=self.stderr)
        print(f"EVIDENCE {_display_path(detail)}", file=self.stderr)

    def finish(
        self,
        summary: Mapping[str, object],
        summary_path: Path | None,
    ) -> None:
        if self.mode is OutputMode.JSON:
            print(
                json.dumps(summary, sort_keys=True, separators=(",", ":")),
                file=self.stdout,
            )
        elif self.mode is OutputMode.HUMAN:
            status_value = str(summary.get("status", "passed"))
            status = {"passed": "PASS", "failed": "FAIL"}.get(
                status_value, status_value.upper()
            )
            suffix = (
                f" summary={_display_path(summary_path)}"
                if summary_path is not None
                else ""
            )
            print(f"{status} {self.profile}{suffix}", file=self.stdout)


NULL_REPORTER = RunnerReporter(profile="", mode=None)


def add_output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        type=OutputMode,
        choices=tuple(OutputMode),
        default=os.environ.get("FULL_COLOR_OUTPUT", OutputMode.HUMAN.value),
    )
