"""Stable Gate 0 command-surface checks."""

from pathlib import Path
import re


ROOT = Path(__file__).parents[5]


def _recipes() -> dict[str, str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    names = (
        "test-full-color-setup",
        "test-full-color-gate0",
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
    assert "test-full-color-gate0 test-full-color-handoffs test-full-color-soak" in (
        ROOT / "Makefile"
    ).read_text(encoding="utf-8")


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
