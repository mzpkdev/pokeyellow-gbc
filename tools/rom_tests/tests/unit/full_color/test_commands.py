"""Stable Gate 0 command-surface checks."""

from pathlib import Path
import re


ROOT = Path(__file__).parents[5]


def _recipes() -> dict[str, str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    names = (
        "test-full-color-setup",
        "measure-full-color-phase1",
        "test-full-color-gate0",
        "test-full-color-renderer-conformance",
        "test-full-color-smoke",
        "test-full-color-handoffs",
        "test-full-color-soak",
        "test-full-color-all",
    )
    recipes: dict[str, str] = {}
    for name in names:
        match = re.search(
            rf"^{re.escape(name)}(?:\s*:[^\n]*)?\n"
            r"(?P<body>(?:\t[^\n]*\n|\n)*)",
            text,
            re.MULTILINE,
        )
        assert match is not None, f"Makefile is missing stable command {name}"
        recipes[name] = match.group("body")
    return recipes


def test_required_full_color_commands_are_concrete() -> None:
    recipes = _recipes()
    assert "python3 -m venv .venv" in recipes["test-full-color-setup"]
    assert "tools/rom_tests/requirements.txt" in recipes["test-full-color-setup"]
    assert "full_color.gate0_runner" in recipes["test-full-color-gate0"]
    assert "runtime_observability" in recipes["test-full-color-smoke"]
    assert "test_model.py" in recipes["test-full-color-handoffs"]
    assert "test_model.py" in recipes["test-full-color-soak"]
    assert (
        "test-full-color-gate0 test-full-color-renderer-conformance "
        "test-full-color-handoffs test-full-color-soak"
    ) in (ROOT / "Makefile").read_text(encoding="utf-8")


def test_gate0_artifacts_use_one_overridable_results_root() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "FULL_COLOR_RESULTS ?= test-results/full-color-gate0" in makefile
    gate0 = _recipes()["test-full-color-gate0"]
    assert gate0.count("$(FULL_COLOR_RESULTS)") == 1
    assert '--results "$(FULL_COLOR_RESULTS)"' in gate0
    assert '--results "$(FULL_COLOR_RESULTS)/smoke"' in _recipes()[
        "test-full-color-smoke"
    ]


def test_python_prefers_the_repo_virtualenv_when_present() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "$(wildcard .venv/bin/python)" in makefile


def test_phase1_measurement_has_a_stable_build_dependent_command() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    header = re.search(
        r"^measure-full-color-phase1:(?P<dependencies>[^\n]*)$",
        makefile,
        re.MULTILINE,
    )
    assert header is not None
    assert "yellow_debug" in header.group("dependencies").split()
    target = _recipes()["measure-full-color-phase1"]
    assert (
        "$(PYTHON) -m tools.rom_tests.full_color.phase1_measurements --root ."
        in target
    )
    assert (
        "--output specs/full-colors/evidence/phase1-ownership-placement.json"
        in target
    )


def test_cgb_only_link_allows_measured_switchable_wram_bank() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "RGBLINKFLAGS += -d" not in makefile
    assert "RGBLINKFLAGS += -w" not in makefile


def test_renderer_conformance_has_a_stable_separate_command() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    target = _recipes()["test-full-color-renderer-conformance"]
    assert (
        "$(PYTHON) -m tools.rom_tests.full_color.renderer_conformance_runner" in target
    )
    assert '--results "$(FULL_COLOR_CONFORMANCE_RESULTS)"' in target
    assert (
        "FULL_COLOR_CONFORMANCE_RESULTS ?= "
        "test-results/full-color-renderer-conformance"
    ) in makefile
    gate0_header = re.search(
        r"^test-full-color-gate0:[^\n]*$", makefile, re.MULTILINE
    )
    aggregate_header = re.search(
        r"^test-full-color-all:[^\n]*$", makefile, re.MULTILINE
    )
    assert gate0_header is not None
    assert aggregate_header is not None
    assert "test-full-color-renderer-conformance" not in gate0_header.group(0)
    assert "test-full-color-renderer-conformance" in aggregate_header.group(0)
