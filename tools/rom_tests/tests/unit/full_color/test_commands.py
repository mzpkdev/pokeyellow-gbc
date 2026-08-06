"""Contracts for the public local full-color command surface."""

from pathlib import Path
import json
import os
import re
import subprocess


ROOT = Path(__file__).parents[5]
PUBLIC_COMMANDS = (
    "test-unit",
    "test-full-color-setup",
    "test-full-color-donor-contract",
    "test-full-color-harness-contracts",
    "test-full-color-evidence",
    "test-full-color-audit",
    "test-full-color-renderer-contracts",
    "test-full-color-renderer-runtime",
    "test-full-color-smoke",
    "test-full-color-e2e-core",
    "test-full-color-e2e-renderer",
    "test-full-color-e2e-journey",
    "test-full-color-fast",
    "test-full-color-certify",
    "test-full-color-handoffs",
    "test-full-color-soak",
)
RETIRED_STAGE = "gate" + "0"
RETIRED_COMMANDS = (
    f"test-full-color-{RETIRED_STAGE}",
    f"test-full-color-{RETIRED_STAGE}-ci-run",
    f"test-full-color-{RETIRED_STAGE}-ci-compare",
    "verify-full-color-phase2-audit",
    "test-full-color-renderer-conformance",
    "test-full-color-e2e",
    "test-full-color-all",
)
ALL_PRODUCTS = (
    "pokeyellow.gbc",
    "pokeyellow.map",
    "pokeyellow.sym",
    "pokeyellow_debug.gbc",
    "pokeyellow_debug.map",
    "pokeyellow_debug.sym",
    "pokeyellow_vc.gbc",
    "pokeyellow_vc.map",
    "pokeyellow_vc.sym",
    "pokeyellow_phase2_audit.gbc",
    "pokeyellow_phase2_audit.map",
    "pokeyellow_phase2_audit.sym",
)
E2E_MODULES = {
    "core": {"test_new_game.py", "test_viridian_city.py"},
    "renderer": {
        "test_full_color_connection_palette.py",
        "test_full_color_house_palette_visual.py",
        "test_full_color_oak_battle_handoff.py",
        "test_full_color_oaks_lab_save_confirmation.py",
        "test_full_color_start_menu_journey.py",
    },
    "journey": {
        "test_full_color_cold_boot_journey.py",
        "test_parcel_delivery.py",
    },
}


def _makefile() -> str:
    return (ROOT / "Makefile").read_text(encoding="utf-8")


def _recipe(name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}(?:\s*:[^\n]*)?\n"
        r"(?P<body>(?:\t[^\n]*\n|\n)*)",
        _makefile(),
        re.MULTILINE,
    )
    assert match is not None, f"Makefile is missing command {name}"
    return match.group("body")


def _dependencies(name: str) -> tuple[str, ...]:
    match = re.search(rf"^{re.escape(name)}:([^\n]*)$", _makefile(), re.MULTILINE)
    assert match is not None
    return tuple(match.group(1).split())


def _run_make(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in ("MAKELEVEL", "MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS"):
        environment.pop(name, None)
    return subprocess.run(
        ("make", *arguments),
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_public_commands_are_concrete_and_phony() -> None:
    makefile = _makefile()
    phony = re.search(
        r"^\.PHONY:\s*\\\n(?P<body>(?:\t[^\n]+\n)+)", makefile, re.MULTILINE
    )
    assert phony is not None
    phony_names = set(re.findall(r"[a-z_][a-z0-9_-]+", phony.group("body")))
    for name in PUBLIC_COMMANDS:
        assert re.search(rf"^{re.escape(name)}\s*:", makefile, re.MULTILINE)
        assert name in phony_names


def test_required_commands_delegate_to_their_named_producers() -> None:
    assert "python3 -m venv .venv" in _recipe("test-full-color-setup")
    assert "test_overworld_color_data_donor.py" in _recipe(
        "test-full-color-donor-contract"
    )
    assert "baseline_discovery" in _recipe("test-full-color-harness-contracts")
    assert "baseline_inventory" in _recipe("test-full-color-harness-contracts")
    assert "bank_torture" in _recipe("test-full-color-harness-contracts")
    assert "full_color.evidence_runner" in _recipe("test-full-color-evidence")
    assert "phase2_measurements" in _recipe("test-full-color-audit")
    assert "--verify" in _recipe("test-full-color-audit")
    assert "renderer_conformance_runner" in _recipe(
        "test-full-color-renderer-contracts"
    )
    assert "renderer_runtime_runner" in _recipe("test-full-color-renderer-runtime")
    assert "runtime_observability" in _recipe("test-full-color-smoke")
    assert "tests/e2e/core" in _recipe("test-full-color-e2e-core")
    assert "tests/e2e/renderer" in _recipe("test-full-color-e2e-renderer")
    assert "tests/e2e/journey" in _recipe("test-full-color-e2e-journey")
    assert "test_model.py" in _recipe("test-full-color-handoffs")
    assert "test_model.py" in _recipe("test-full-color-soak")


def test_unit_tree_runs_once_and_excludes_only_the_donor_contract() -> None:
    recipe = _recipe("test-unit")
    assert recipe.count("tools/rom_tests/tests/unit") == 2
    assert (
        "--ignore=tools/rom_tests/tests/unit/full_color/test_overworld_color_data_donor.py"
        in recipe
    )
    assert _dependencies("test-unit") == ("_rom-test-all-products",)


def test_public_commands_use_the_smallest_product_prerequisite() -> None:
    assert _dependencies("test-full-color-harness-contracts") == (
        "_rom-test-debug-products",
    )
    assert _dependencies("test-full-color-evidence") == ("_rom-test-debug-products",)
    assert _dependencies("test-full-color-audit") == ("_rom-test-all-products",)
    assert _dependencies("test-full-color-renderer-contracts") == ()
    assert _dependencies("test-full-color-renderer-runtime") == (
        "_rom-test-debug-products",
    )
    assert _dependencies("test-full-color-smoke") == ("_rom-test-debug-products",)
    for name in (
        "test-full-color-e2e-core",
        "test-full-color-e2e-renderer",
        "test-full-color-e2e-journey",
    ):
        assert _dependencies(name) == ("_rom-test-gameplay-products",)


def test_each_e2e_module_belongs_to_exactly_one_suite() -> None:
    e2e = ROOT / "tools/rom_tests/tests/e2e"
    assert not tuple(e2e.glob("test_*.py"))
    actual = {
        suite: {path.name for path in (e2e / suite).glob("test_*.py")}
        for suite in E2E_MODULES
    }
    assert actual == E2E_MODULES
    all_modules = [name for modules in actual.values() for name in modules]
    assert len(all_modules) == 9
    assert len(all_modules) == len(set(all_modules))


def test_retired_commands_are_not_targets_or_aliases() -> None:
    makefile = _makefile()
    for name in RETIRED_COMMANDS:
        assert re.search(rf"^{re.escape(name)}\s*:", makefile, re.MULTILINE) is None


def test_prebuilt_mode_accepts_all_twelve_products(tmp_path: Path) -> None:
    products = tuple(tmp_path / name for name in ALL_PRODUCTS)
    for path in products:
        path.touch()
    completed = _run_make(
        "_rom-test-all-products",
        "ROM_TEST_PREBUILT_PRODUCTS=1",
        f"ROM_TEST_ALL_PRODUCTS={' '.join(str(path) for path in products)}",
    )
    assert completed.returncode == 0, completed.stderr
    assert "Missing required ROM test artifact" not in completed.stderr


def test_prebuilt_mode_fails_closed_with_the_missing_product(tmp_path: Path) -> None:
    present = tmp_path / "present.gbc"
    missing = tmp_path / "missing.sym"
    present.touch()
    completed = _run_make(
        "_rom-test-all-products",
        "ROM_TEST_PREBUILT_PRODUCTS=1",
        f"ROM_TEST_ALL_PRODUCTS={present} {missing}",
    )
    assert completed.returncode != 0
    assert completed.stderr.count(f"Missing required ROM test artifact: {missing}") == 1


def test_default_mode_builds_products_while_prebuilt_mode_only_checks_them() -> None:
    default = _run_make(
        "-n", "-B", "_rom-test-all-products", "ROM_TEST_PREBUILT_PRODUCTS=0"
    )
    assert default.returncode == 0, default.stderr
    assert "rgbasm" in default.stdout
    prebuilt = _run_make("-n", "_rom-test-all-products", "ROM_TEST_PREBUILT_PRODUCTS=1")
    assert prebuilt.returncode == 0, prebuilt.stderr
    assert "Missing required ROM test artifact" in prebuilt.stdout
    assert "rgbasm" not in prebuilt.stdout


def test_profiles_enter_the_runner_without_make_dependencies() -> None:
    for profile in ("fast", "certify"):
        name = f"test-full-color-{profile}"
        recipe = _recipe(name)
        assert _dependencies(name) == ()
        assert recipe.startswith("\t@$(PYTHON)")
        assert f"--profile {profile}" in recipe
        assert '--results "$(FULL_COLOR_HARNESS_RESULTS)"' in recipe


def test_json_profile_make_entrypoints_emit_only_the_runner_document(
    tmp_path: Path,
) -> None:
    python = tmp_path / "json-python"
    python.write_text(
        "#!/bin/sh\nprintf '%s\\n' '{\"status\":\"probe\"}'\n", encoding="utf-8"
    )
    python.chmod(0o755)
    environment = os.environ.copy()
    for name in ("MAKELEVEL", "MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS"):
        environment.pop(name, None)
    environment["FULL_COLOR_OUTPUT"] = "json"
    for target in ("test-full-color-fast", "test-full-color-certify"):
        completed = subprocess.run(
            (
                "make",
                target,
                f"PYTHON={python}",
                f"FULL_COLOR_HARNESS_RESULTS={tmp_path / 'results with spaces'}",
            ),
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0
        assert json.loads(completed.stdout) == {"status": "probe"}
        assert completed.stderr == ""


def test_measurement_commands_only_write_disposable_proposals() -> None:
    completed = _run_make(
        "-n",
        "-B",
        "measure-full-color-phase2-audit",
        "PYTHON=/proposal-python",
        "FULL_COLOR_PROPOSALS=/tmp/proposal-root",
    )
    assert completed.returncode == 0, completed.stderr
    commands = [
        line
        for line in completed.stdout.splitlines()
        if "tools.rom_tests.full_color" in line
        and any(
            module in line
            for module in (
                "source_transition",
                "audit_evidence_identities",
                "phase2_measurements",
            )
        )
    ]
    assert [line.split(" -m ", 1)[1].split()[0] for line in commands] == [
        "tools.rom_tests.full_color.source_transition",
        "tools.rom_tests.full_color.audit_evidence_identities",
        "tools.rom_tests.full_color.phase2_measurements",
    ]
    assert all("--proposal-output" in line for line in commands)
    assert all("specs/full-colors" not in line for line in commands)


def test_python_prefers_the_repo_virtualenv_and_link_keeps_cgb_banks() -> None:
    makefile = _makefile()
    assert "$(wildcard .venv/bin/python)" in makefile
    assert "RGBLINKFLAGS += -d" not in makefile
    assert "RGBLINKFLAGS += -w" not in makefile


def test_workflow_coupled_local_runner_is_removed() -> None:
    assert not (ROOT / "tools/run_ci.py").exists()
