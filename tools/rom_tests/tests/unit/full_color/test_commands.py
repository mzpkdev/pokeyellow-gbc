"""Stable Gate 0 command-surface checks."""

from pathlib import Path
import json
import os
import re
import subprocess


ROOT = Path(__file__).parents[5]


def _recipes() -> dict[str, str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    names = (
        "test-full-color-setup",
        "measure-full-color-phase1",
        "measure-full-color-source-transition",
        "measure-full-color-audit-evidence-identities",
        "measure-full-color-phase2-audit",
        "verify-full-color-phase2-audit",
        "test-full-color-gate0",
        "test-full-color-renderer-conformance",
        "test-full-color-renderer-runtime",
        "test-full-color-smoke",
        "test-full-color-fast",
        "test-full-color-certify",
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


def _dependencies() -> dict[str, tuple[str, ...]]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    return {
        name: tuple(dependencies.split())
        for name, dependencies in re.findall(
            r"^((?:test|verify)-full-color-[a-z0-9-]+):([^\n]*)$", text, re.MULTILINE
        )
    }


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
        "test-full-color-renderer-runtime test-full-color-handoffs "
        "test-full-color-soak"
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


def test_profiles_enter_the_runner_without_make_dependencies() -> None:
    recipes = _recipes()
    dependencies = _dependencies()
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert dependencies["test-full-color-fast"] == ()
    assert dependencies["test-full-color-certify"] == ()
    assert "--profile fast" in recipes["test-full-color-fast"]
    assert "--profile certify" in recipes["test-full-color-certify"]
    assert "full_color.harness_runner" in recipes["test-full-color-fast"]
    assert "full_color.harness_runner" in recipes["test-full-color-certify"]
    assert "FULL_COLOR_HARNESS_RESULTS ?= test-results/full-color-harness" in makefile
    for name in ("test-full-color-fast", "test-full-color-certify"):
        assert "$(PYTHON)" in recipes[name]
        assert recipes[name].startswith("\t@$(PYTHON)")
        assert recipes[name].count("$(FULL_COLOR_HARNESS_RESULTS)") == 1
        assert '--results "$(FULL_COLOR_HARNESS_RESULTS)"' in recipes[name]


def test_json_profile_make_entrypoints_emit_only_the_runner_document(
    tmp_path: Path,
) -> None:
    python = tmp_path / "json-python"
    python.write_text("#!/bin/sh\nprintf '%s\\n' '{\"status\":\"probe\"}'\n", encoding="utf-8")
    python.chmod(0o755)
    direct_make_env = os.environ.copy()
    for name in ("MAKELEVEL", "MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS"):
        direct_make_env.pop(name, None)
    direct_make_env["FULL_COLOR_OUTPUT"] = "json"
    for target in ("test-full-color-fast", "test-full-color-certify"):
        completed = subprocess.run(
            (
                "make",
                target,
                f"PYTHON={python}",
                f"FULL_COLOR_HARNESS_RESULTS={tmp_path / 'results with spaces'}",
            ),
            cwd=ROOT,
            env=direct_make_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0
        assert json.loads(completed.stdout) == {"status": "probe"}
        assert len(completed.stdout.splitlines()) == 2
        assert completed.stdout.splitlines()[0] == ""
        assert "harness_runner" not in completed.stdout
        assert completed.stderr == ""


def test_gate0_builds_every_phase1_product_rom() -> None:
    assert _dependencies()["test-full-color-gate0"] == (
        "pokeyellow.gbc",
        "pokeyellow_debug.gbc",
        "pokeyellow_vc.gbc",
    )


def test_phase2_audit_verification_is_a_separate_focused_gate() -> None:
    dependencies = _dependencies()
    assert dependencies["verify-full-color-phase2-audit"] == (
        "pokeyellow.gbc",
        "pokeyellow_debug.gbc",
        "pokeyellow_vc.gbc",
        "pokeyellow_phase2_audit.gbc",
    )
    assert "phase2_measurements" in _recipes()["verify-full-color-phase2-audit"]
    assert "--verify" in _recipes()["verify-full-color-phase2-audit"]


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
        '--output "$(FULL_COLOR_PROPOSALS)/phase1-ownership-placement.proposal.json"'
        in target
    )


def test_measurement_make_graph_emits_only_disposable_unreviewed_proposals(
    tmp_path: Path,
) -> None:
    proposal_root = tmp_path / "proposals with spaces"
    completed = subprocess.run(
        (
            "make",
            "-n",
            "-B",
            "measure-full-color-phase2-audit",
            "PYTHON=/proposal-python",
            f"FULL_COLOR_PROPOSALS={proposal_root}",
        ),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
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
    assert f'--proposal-output "{proposal_root}/phase1-source-transition.proposal.json"' in commands[0]
    assert f'--transition-proposal "{proposal_root}/phase1-source-transition.proposal.json"' in commands[1]
    assert f'--proposal-output "{proposal_root}/audit-evidence-identities.proposal.json"' in commands[1]
    assert f'--proposal-output "{proposal_root}/phase2-subjects.proposal.json"' in commands[2]
    assert all("specs/full-colors" not in line for line in commands)


def test_actual_measurement_make_graph_preserves_all_reviewed_files(
    tmp_path: Path,
) -> None:
    reviewed = (
        ROOT / "specs/full-colors/definitions/phase1-audit-source-transition.json",
        ROOT / "specs/full-colors/inventory/assignments.json",
        ROOT / "specs/full-colors/inventory/mutations.json",
        ROOT / "specs/full-colors/inventory/scenes.json",
        ROOT / "specs/full-colors/inventory/writers.json",
        ROOT / "specs/full-colors/evidence/phase1-ownership-placement.json",
        ROOT / "specs/full-colors/evidence/phase2-hostile-slice-representation.json",
    )
    before = {path: path.read_bytes() for path in reviewed}
    proposal_root = tmp_path / "proposal-root"
    log = tmp_path / "producer.log"
    producer = tmp_path / "proposal-python"
    producer.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "printf '%s\\n' \"$*\" >> \"$MEASURE_LOG\"\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    --output|--proposal-output)\n"
        "      shift\n"
        "      mkdir -p \"$(dirname \"$1\")\"\n"
        "      printf '{}\\n' > \"$1\"\n"
        "      ;;\n"
        "  esac\n"
        "  shift\n"
        "done\n",
        encoding="utf-8",
    )
    producer.chmod(0o755)
    environment = os.environ.copy()
    environment["MEASURE_LOG"] = str(log)
    completed = subprocess.run(
        (
            "make",
            "--old-file=pokeyellow.gbc",
            "--old-file=pokeyellow_debug.gbc",
            "--old-file=pokeyellow.patch",
            "--old-file=pokeyellow_phase2_audit.gbc",
            "measure-full-color-phase1",
            "measure-full-color-phase2-audit",
            f"PYTHON={producer}",
            f"FULL_COLOR_PROPOSALS={proposal_root}",
        ),
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert {path: path.read_bytes() for path in reviewed} == before
    expected = {
        "phase1-ownership-placement.proposal.json",
        "phase1-source-transition.proposal.json",
        "audit-evidence-identities.proposal.json",
        "phase2-subjects.proposal.json",
    }
    assert {path.name for path in proposal_root.iterdir()} == expected
    invoked = log.read_text(encoding="utf-8")
    assert invoked.index("phase1_measurements") < invoked.index("source_transition")
    assert invoked.index("source_transition") < invoked.index("audit_evidence_identities")
    assert invoked.index("audit_evidence_identities") < invoked.index("phase2_measurements")


def test_phase2_verify_make_graph_is_read_only() -> None:
    completed = subprocess.run(
        ("make", "-n", "-B", "verify-full-color-phase2-audit", "PYTHON=/verify-python"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    command = next(
        line
        for line in completed.stdout.splitlines()
        if "tools.rom_tests.full_color.phase2_measurements" in line
    )
    assert "--verify" in command
    assert "--proposal-output" not in command
    assert "--authority-reviewed" not in command
    assert "specs/full-colors/evidence/phase2-hostile-slice-representation.json" in command


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


def test_phase1_runtime_has_a_stable_separate_command() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipes = _recipes()
    dependencies = _dependencies()
    assert (
        "FULL_COLOR_RUNTIME_RESULTS ?= test-results/full-color-renderer-runtime"
        in makefile
    )
    assert dependencies["test-full-color-renderer-runtime"] == ("yellow_debug",)
    target = recipes["test-full-color-renderer-runtime"]
    assert (
        "$(PYTHON) -m tools.rom_tests.full_color.renderer_runtime_runner --root ."
        in target
    )
    assert target.count("$(FULL_COLOR_RUNTIME_RESULTS)") == 1
    assert '--results "$(FULL_COLOR_RUNTIME_RESULTS)"' in target

    for sibling in (
        "test-full-color-gate0",
        "test-full-color-renderer-conformance",
    ):
        assert "test-full-color-renderer-runtime" not in dependencies[sibling]
        assert "renderer_runtime_runner" not in recipes[sibling]
    assert "test-full-color-renderer-runtime" in dependencies["test-full-color-all"]
