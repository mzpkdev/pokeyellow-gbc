"""Fail-closed authority checks for closure-before-activation."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

import tools.rom_tests.full_color.baseline_inventory as authority
from tools.rom_tests.full_color.baseline_discovery import discover_baseline_sources
from tools.rom_tests.full_color.baseline_discovery import writer_roots
from tools.rom_tests.full_color.rom_discovery import load_sym
from tools.rom_tests.full_color.inventory import InventoryReconciliationError
from tools.rom_tests.full_color.phase2_measurements import (
    _project_activation_audit_source,
    discover_phase2_sources,
)


ROOT = Path(__file__).resolve().parents[5]

AUTHORIZED_INACTIVE_AND_FROZEN_AUDIT_PRODUCTS = {
    "pokeyellow.gbc": "0ad345564d9ad11fc80b65ccfb786ffe592d1d6eca706caa8fc37b20a2b4ee75",
    "pokeyellow.sym": "f688d5799c295a6f9dd4fb8a5837061e31447f9577e8bdb2141c57c45d7001b2",
    "pokeyellow_vc.gbc": "6523f666706195dd6427163570bff99f7d09c85ad68dcba1e0ec9a2b67a775e2",
    "pokeyellow_vc.sym": "5dd6a0ccf29bd8f48c307d9b2eedcb00b35f4d3d11ad04cfdac832798292c3b4",
    "pokeyellow_phase2_audit.gbc": "536c747d855e6b381850d96d0dc45d3679d6a18034026e0add0ba4bb4eaa26ad",
    "pokeyellow_phase2_audit.sym": "ce8111cd4f86fd6185181bdccbd63e515360c47e90f88168951a73417afe8e02",
}


@pytest.fixture(scope="module")
def activation_inputs():
    report = discover_baseline_sources(ROOT)
    manifest = authority._source_path_manifest(
        ROOT, (relative for relative, _ in report.include_graph)
    )
    return report, manifest


def _mutated_transition(tmp_path: Path, monkeypatch, mutate) -> None:
    source = ROOT / authority.ACTIVATION_TRANSITION_PATH
    raw = json.loads(source.read_text(encoding="utf-8"))
    mutate(raw)
    target = tmp_path / "activation-transition.json"
    target.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(authority, "ACTIVATION_TRANSITION_PATH", target)


def _validate(activation_inputs) -> None:
    report, manifest = activation_inputs
    authority._validate_activation_transition(
        ROOT,
        report,
        "c4d94b9ac6433681be894192f6e71f2f7216e7f670412d5eeb673cbec111f50e",
        manifest,
    )


@pytest.mark.parametrize(
    ("product", "expected_sha256"),
    AUTHORIZED_INACTIVE_AND_FROZEN_AUDIT_PRODUCTS.items(),
)
def test_activation_keeps_inactive_and_audit_products_byte_exact(
    product: str, expected_sha256: str,
) -> None:
    assert hashlib.sha256((ROOT / product).read_bytes()).hexdigest() == expected_sha256


def test_real_activation_transition_binds_guarded_checkpoint_and_products(
    activation_inputs,
) -> None:
    _validate(activation_inputs)


def test_hostile_source_projection_retains_all_frozen_audit_subjects(
    activation_inputs,
) -> None:
    report, _ = activation_inputs
    assignments = authority.DiscoveryAssignmentAuthority.load(
        ROOT / "specs/full-colors/inventory/assignments.json"
    )
    normal = assignments.for_product()
    _, transition = authority._reviewed_source_view(normal, report, ROOT)
    projected = _project_activation_audit_source(
        discover_phase2_sources(ROOT),
        transition,
        assignments.for_product("pokeyellow_phase2_audit"),
    )
    assert projected.source_sha256 == (
        "c4d94b9ac6433681be894192f6e71f2f7216e7f670412d5eeb673cbec111f50e"
    )
    subjects = {
        authority.source_finding_subject(finding).sha256
        for finding in projected.findings
    }
    assert set(transition["_activation_transition"][
        "audit_source_subject_rebindings"
    ]) <= subjects


def test_activation_transition_rejects_arbitrary_source_drift(
    activation_inputs,
) -> None:
    report, manifest = activation_inputs
    changed = dict(manifest)
    changed["audio.asm"] = "0" * 64
    with pytest.raises(
        InventoryReconciliationError,
        match="outside the exact reviewed path delta",
    ):
        # Exercise the whole chain so unlisted changes must survive neither
        # the activation projection nor the pre-existing audit projection.
        assignments = authority.DiscoveryAssignmentAuthority.load(
            ROOT / "specs/full-colors/inventory/assignments.json"
        ).for_product()
        original = authority._source_path_manifest
        authority._source_path_manifest = lambda repository, paths: changed
        try:
            authority._reviewed_source_view(assignments, report, ROOT)
        finally:
            authority._source_path_manifest = original


def test_activation_transition_rejects_stale_guarded_parent(
    activation_inputs, tmp_path, monkeypatch
) -> None:
    _mutated_transition(
        tmp_path, monkeypatch, lambda raw: raw.__setitem__("guarded_commit", "0" * 40)
    )
    with pytest.raises(
        InventoryReconciliationError, match="wrong baseline or guarded parent"
    ):
        _validate(activation_inputs)


def test_activation_transition_rejects_wrong_baseline_parent(
    activation_inputs, tmp_path, monkeypatch
) -> None:
    _mutated_transition(
        tmp_path, monkeypatch, lambda raw: raw.__setitem__("baseline_commit", "0" * 40)
    )
    with pytest.raises(
        InventoryReconciliationError, match="wrong baseline or guarded parent"
    ):
        _validate(activation_inputs)


def test_activation_transition_rejects_wrong_reviewed_path(
    activation_inputs, tmp_path, monkeypatch
) -> None:
    def mutate(raw) -> None:
        binding = raw["activation_paths"].pop("home/lcdc.asm")
        raw["activation_paths"]["home/lcd.asm"] = binding

    _mutated_transition(tmp_path, monkeypatch, mutate)
    with pytest.raises(InventoryReconciliationError, match="activation path changed"):
        _validate(activation_inputs)


def test_activation_transition_rejects_wrong_reviewed_source_hash(
    activation_inputs, tmp_path, monkeypatch
) -> None:
    _mutated_transition(
        tmp_path,
        monkeypatch,
        lambda raw: raw.__setitem__("activated_source_sha256", "0" * 64),
    )
    with pytest.raises(
        InventoryReconciliationError, match="current source identity"
    ):
        _validate(activation_inputs)


def test_activation_transition_rejects_stale_debug_source_rebinding(
    activation_inputs, tmp_path, monkeypatch
) -> None:
    def mutate(raw) -> None:
        key = next(iter(raw["debug_source_subject_rebindings"]))
        raw["debug_source_subject_rebindings"][key] = "0" * 64

    _mutated_transition(tmp_path, monkeypatch, mutate)
    with pytest.raises(
        InventoryReconciliationError,
        match="malformed activation debug source subject bindings",
    ):
        _validate(activation_inputs)


def test_activation_transition_rejects_stale_audit_source_diagnostic(
    activation_inputs, tmp_path, monkeypatch
) -> None:
    def mutate(raw) -> None:
        binding = next(iter(raw["audit_source_error_rebindings"].values()))
        binding["activated_sha256"] = "0" * 64

    _mutated_transition(tmp_path, monkeypatch, mutate)
    with pytest.raises(
        InventoryReconciliationError,
        match="malformed activation audit source diagnostic bindings",
    ):
        _validate(activation_inputs)


@pytest.mark.parametrize("product", ("pokeyellow.gbc", "pokeyellow_vc.sym"))
def test_activation_transition_rejects_changed_product_projection(
    activation_inputs, tmp_path, monkeypatch, product
) -> None:
    def mutate(raw) -> None:
        raw["activated_product_input_sha256"][product] = "0" * 64

    _mutated_transition(tmp_path, monkeypatch, mutate)
    with pytest.raises(
        InventoryReconciliationError, match="activation product input changed"
    ):
        _validate(activation_inputs)


@pytest.mark.parametrize("mutation", ("extra", "moved", "off-by-one"))
def test_activation_transition_rejects_non_exact_placement(
    activation_inputs, tmp_path, monkeypatch, mutation
) -> None:
    def mutate(raw) -> None:
        if mutation == "extra":
            raw["activated_placement_sections"].append(
                {
                    "kind": "ROMX", "bank": 1, "start": 0x4000, "end": 0x4000,
                    "name": "Unreviewed", "products": ["debug"],
                }
            )
        elif mutation == "moved":
            raw["activated_placement_sections"][0]["bank"] = 58
        else:
            raw["activated_placement_sections"][0]["end"] += 1

    _mutated_transition(tmp_path, monkeypatch, mutate)
    with pytest.raises(
        InventoryReconciliationError, match="malformed activated placement authority"
    ):
        _validate(activation_inputs)


@pytest.mark.parametrize("field", ("audit_rom_sha256", "audit_sym_sha256"))
def test_activation_transition_rejects_changed_guarded_artifacts(
    activation_inputs, tmp_path, monkeypatch, field
) -> None:
    _mutated_transition(
        tmp_path, monkeypatch, lambda raw: raw.__setitem__(field, "0" * 64)
    )
    with pytest.raises(
        InventoryReconciliationError, match="guarded audit artifact identity changed"
    ):
        _validate(activation_inputs)


@pytest.mark.parametrize("field", ("rom_sha256", "sym_sha256", "map_sha256"))
def test_activation_transition_rejects_changed_debug_semantic_identity(
    activation_inputs, tmp_path, monkeypatch, field
) -> None:
    def mutate(raw) -> None:
        raw["activated_debug_identity"][field] = "0" * 64

    _mutated_transition(tmp_path, monkeypatch, mutate)
    report, _ = activation_inputs
    assignments = authority.DiscoveryAssignmentAuthority.load(
        ROOT / "specs/full-colors/inventory/assignments.json"
    ).for_product()
    _, transition = authority._reviewed_source_view(assignments, report, ROOT)
    linked_symbols = load_sym(ROOT / "pokeyellow_debug.sym").by_name.keys()
    missing_writers = set(writer_roots(report)) - linked_symbols
    linked_report = replace(
        report,
        findings=tuple(
            finding
            for finding in report.findings
            if finding.category != "writer" or finding.symbol not in missing_writers
        ),
    )
    rom_report = authority.discover_baseline_rom(ROOT, source_report=linked_report)
    with pytest.raises(
        InventoryReconciliationError, match="current debug product identity",
    ):
        authority._reviewed_rom_view(assignments, rom_report, transition)


@pytest.mark.parametrize("product", ("pokeyellow.sym", "pokeyellow_vc.sym"))
def test_activation_transition_rejects_widened_non_debug_reachability(
    activation_inputs, monkeypatch, product
) -> None:
    real_symbols = authority._symbol_names

    def widened(path: Path) -> frozenset[str]:
        names = real_symbols(path)
        if path.name == product:
            return names | {"BeginFullColorMapEntry"}
        return names

    monkeypatch.setattr(authority, "_symbol_names", widened)
    with pytest.raises(
        InventoryReconciliationError, match="widened into inactive product"
    ):
        _validate(activation_inputs)
