"""Blocking SameBoy core-cycle authority for the Phase 2 hostile slice."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from types import MethodType
from typing import Iterable, Mapping

from .snapshots import TimingRow
from .errors import SnapshotValidationError


LOCK_PATH = Path("tools/rom_tests/vendor/sameboy.lock")
INPUT_MANIFEST_PATH = Path("tools/rom_tests/results/full_color_phase2/sameboy-input.json")
BRIDGE_VERSION = "SameBoy Timing Bridge v1.0.3"
AUTHORITY = "SAMEBOY_CORE_CYCLES"
REPORT_SCHEMA = "full-color-phase2-sameboy-timing-v1"
INPUT_SCHEMA = "full-color-phase2-sameboy-input-v1"

EVENT_SAMPLE_START = 1
EVENT_SAMPLE_END = 2
EVENT_CALIBRATION_START = 3
EVENT_CALIBRATION_END = 4
EVENT_THRESHOLD_START = 5
EVENT_THRESHOLD_DEFER = 6
EVENT_THRESHOLD_COMMITTING = 7


class SameBoyTimingError(AssertionError):
    """A timing input cannot support the blocking Phase 2 verdict."""


@dataclass(frozen=True, slots=True)
class RowDefinition:
    row_id: int
    key: str
    operation: str
    mode: str
    deadline_cycle: int
    guard_cycles: int


# SameBoy reports 8 MHz core ticks. LCD rows own one 456-dot line, visible
# VBlank work owns the ten-line VBlank interval, and hidden reconstruction owns
# one complete frame. The guard is host-authored and never read from the ROM.
ROW_DEFINITIONS = (
    RowDefinition(1, "TIME-LCD-OVERRIDE-OFF", "LCD interrupt", "scanline overrides disabled", 912, 128),
    RowDefinition(2, "TIME-LCD-OVERRIDE-ON", "LCD interrupt", "scanline overrides enabled", 912, 128),
    RowDefinition(3, "TIME-VBLANK-YELLOW", "VBlank route", "RENDERER_YELLOW", 9120, 912),
    RowDefinition(4, "TIME-VBLANK-OVERWORLD", "VBlank route", "RENDERER_FULL_COLOR_OVERWORLD", 9120, 912),
    RowDefinition(5, "TIME-PALETTE-BG", "complete 64-byte BG palette upload", "owned VBlank", 9120, 912),
    RowDefinition(6, "TIME-PALETTE-OBJ", "complete 64-byte OBJ palette upload", "owned VBlank", 9120, 912),
    RowDefinition(7, "TIME-PALETTE-COMBINED", "serialized complete BG and OBJ palette uploads", "owned VBlank", 9120, 912),
    RowDefinition(8, "TIME-STREAM-HORIZONTAL", "paired horizontal row/column transfer", "owned VBlank", 9120, 912),
    RowDefinition(9, "TIME-STREAM-VERTICAL", "paired vertical row/column transfer", "owned VBlank", 9120, 912),
    RowDefinition(10, "TIME-STREAM-CONNECTION", "paired north connection transfer", "owned VBlank", 9120, 912),
    RowDefinition(11, "TIME-RECONSTRUCTION", "full map reconstruction and presentation barrier", "LCD off", 140448, 912),
    RowDefinition(12, "TIME-OAM-MAXIMUM", "maximum shadow OAM build and hardware DMA", "owned VBlank", 9120, 912),
)
ROW_BY_ID = {row.row_id: row for row in ROW_DEFINITIONS}
ROW_BY_KEY = {row.key: row for row in ROW_DEFINITIONS}


@dataclass(frozen=True, slots=True)
class SourceLock:
    schema: str
    version: str
    tag_object: str
    commit: str
    source_url: str
    archive_sha256: str

    @classmethod
    def load(cls, path: Path) -> "SourceLock":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SameBoyTimingError(f"cannot read SameBoy lock: {exc}") from exc
        required = set(cls.__dataclass_fields__)
        if not isinstance(raw, dict) or set(raw) != required:
            raise SameBoyTimingError("SameBoy lock has an open or incomplete schema")
        lock = cls(**raw)
        if lock.schema != "sameboy-source-lock-v1" or lock.version != "v1.0.3":
            raise SameBoyTimingError("SameBoy lock has the wrong version")
        if lock.source_url != "https://codeload.github.com/LIJI32/SameBoy/tar.gz/refs/tags/v1.0.3":
            raise SameBoyTimingError("SameBoy lock has the wrong source identity")
        expected = {
            "tag_object": "5104c0429df2a73cfccea8c5034d5cb72c13c5f2",
            "commit": "208ba4afabffab9edde416f2dbb8ae459e34adb8",
            "archive_sha256": "7da338458e19396cb43dfe1a4df4555882ebea92540565dc993c1c706c981dc3",
        }
        for name, value in expected.items():
            if getattr(lock, name) != value:
                raise SameBoyTimingError(f"SameBoy lock has the wrong {name}")
        return lock


@dataclass(frozen=True, slots=True)
class Observation:
    row: int
    event: int
    sequence: int
    core_cycles: int
    ly: int
    probe: int
    probe_cycles: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SameBoyTimingError(f"cannot hash identity {path}: {exc}") from exc
    return digest.hexdigest()


def _symbols(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SameBoyTimingError(f"cannot read symbol identity: {exc}") from exc
    for line in lines:
        match = re.fullmatch(r"[0-9a-fA-F]+:([0-9a-fA-F]{4}) (\S+)", line)
        if match:
            result[match.group(2)] = int(match.group(1), 16)
    required = {
        "wFullColorRuntimeTimingEvent",
        "wFullColorRuntimeTimingRow",
        "wFullColorRuntimeTimingSequence",
        "wFullColorRuntimeTimingProbeResult",
        "wFullColorRuntimeTimingProbeCycles",
    }
    missing = sorted(required - result.keys())
    if missing:
        raise SameBoyTimingError("debug ROM lacks timing marker ABI: " + ", ".join(missing))
    return result


def parse_bridge_output(path: Path) -> tuple[Observation, ...]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SameBoyTimingError(f"cannot read SameBoy bridge output: {exc}") from exc
    if not lines or lines[0] != "row\tevent\tsequence\tcore_cycles\tly\tprobe\tprobe_cycles":
        raise SameBoyTimingError("SameBoy bridge output has the wrong header")
    observations: list[Observation] = []
    for number, line in enumerate(lines[1:], 2):
        fields = line.split("\t")
        if len(fields) != 7 or any(not field.isdecimal() for field in fields):
            raise SameBoyTimingError(f"SameBoy bridge output line {number} is malformed")
        item = Observation(*(int(field) for field in fields))
        if item.row not in ROW_BY_ID or item.event not in range(1, 8):
            raise SameBoyTimingError(f"SameBoy bridge output line {number} has an unknown marker")
        if not 0 <= item.ly <= 153 or not 0 <= item.probe <= 2 or not 0 <= item.probe_cycles <= 0xFFFFFFFF:
            raise SameBoyTimingError(f"SameBoy bridge output line {number} has invalid ROM state")
        observations.append(item)
    if not observations:
        raise SameBoyTimingError("SameBoy bridge output contains no samples")
    if any(b.core_cycles < a.core_cycles for a, b in zip(observations, observations[1:])):
        raise SameBoyTimingError("SameBoy core cycles moved backwards")
    return tuple(observations)


def _pair(events: Mapping[int, Observation], start: int, end: int, label: str) -> int:
    if start not in events or end not in events:
        raise SameBoyTimingError(f"timing sequence lacks {label} markers")
    delta = events[end].core_cycles - events[start].core_cycles
    if delta <= 0:
        raise SameBoyTimingError(f"timing sequence has non-positive {label} cycles")
    return delta


def rows_from_observations(observations: Iterable[Observation], rom_name: str) -> tuple[dict[str, object], ...]:
    grouped: dict[tuple[int, int], dict[int, Observation]] = {}
    for item in observations:
        events = grouped.setdefault((item.row, item.sequence), {})
        if item.event in events:
            raise SameBoyTimingError("timing sequence repeats an event marker")
        events[item.event] = item
    durations: dict[int, list[int]] = {row.row_id: [] for row in ROW_DEFINITIONS}
    instrumentation: dict[int, list[int]] = {row.row_id: [] for row in ROW_DEFINITIONS}
    scanlines: dict[int, list[list[int]]] = {row.row_id: [] for row in ROW_DEFINITIONS}
    probes: dict[int, list[tuple[int, int]]] = {row.row_id: [] for row in ROW_DEFINITIONS}
    for (row_id, _), events in grouped.items():
        if EVENT_THRESHOLD_COMMITTING in events:
            raise SameBoyTimingError("threshold + 1 entered COMMITTING")
        if EVENT_THRESHOLD_START not in events or EVENT_THRESHOLD_DEFER not in events:
            raise SameBoyTimingError("timing sequence lacks threshold + 1 pre-COMMIT defer")
        ordered = [events[event].core_cycles for event in (
            EVENT_CALIBRATION_START, EVENT_CALIBRATION_END,
            EVENT_SAMPLE_START, EVENT_SAMPLE_END,
            EVENT_THRESHOLD_START, EVENT_THRESHOLD_DEFER,
        ) if event in events]
        if len(ordered) != 6 or ordered != sorted(ordered) or len(set(ordered)) != 6:
            raise SameBoyTimingError("timing sequence markers are out of order")
        if events[EVENT_THRESHOLD_DEFER].probe != 1:
            raise SameBoyTimingError("threshold probe lacks the ROM defer verdict")
        total = _pair(events, EVENT_SAMPLE_START, EVENT_SAMPLE_END, "sample")
        overhead = _pair(events, EVENT_CALIBRATION_START, EVENT_CALIBRATION_END, "calibration")
        if total <= overhead:
            raise SameBoyTimingError("sample does not exceed measured instrumentation")
        durations[row_id].append(total - overhead)
        instrumentation[row_id].append(overhead)
        scanlines[row_id].append([events[EVENT_SAMPLE_START].ly, events[EVENT_SAMPLE_END].ly])
        probes[row_id].append((overhead, events[EVENT_THRESHOLD_DEFER].probe_cycles))
    result: list[dict[str, object]] = []
    for definition in ROW_DEFINITIONS:
        samples = durations[definition.row_id]
        if not samples:
            raise SameBoyTimingError(f"missing canonical timing row {definition.key}")
        overheads = instrumentation[definition.row_id]
        if len(set(overheads)) != 1:
            raise SameBoyTimingError("timing marker instrumentation is not deterministic")
        worst, overhead = max(samples), max(overheads)
        usable = definition.deadline_cycle - definition.guard_cycles
        threshold = usable - overhead
        if any(probe_cycles != threshold + 1 for _, probe_cycles in probes[definition.row_id]):
            raise SameBoyTimingError("threshold probe is not exact cycle threshold + 1")
        margin = threshold - worst
        row = TimingRow.from_dict({
            "key": definition.key,
            "operation": definition.operation,
            "mode": definition.mode,
            "rom": rom_name,
            "tool_device": BRIDGE_VERSION,
            "samples": len(samples),
            "worst_cycles": worst,
            "instrumentation_cycles": overhead,
            "start_cycle": 0,
            "deadline_cycle": definition.deadline_cycle,
            "guard_cycles": definition.guard_cycles,
            "margin_cycles": margin,
            "margin_percent": margin * 100 / usable,
            "defer_threshold": threshold,
            "threshold_plus_one_result": "DEFER",
            "threshold_plus_one_entered_committing": False,
            "result": "PASS" if margin >= 0 else "DEFER",
            "evidence_kind": "RENDERER_RUNTIME",
            "activation_phase": 2,
        }).to_dict()
        row["sample_core_cycles"] = samples
        row["sample_scanlines"] = scanlines[definition.row_id]
        result.append(row)
    return tuple(result)


def validate_report(report: object, *, rom_sha256: str, bridge_sha256: str) -> None:
    if not isinstance(report, dict):
        raise SameBoyTimingError("timing report is not an object")
    required = {"schema", "authority", "sameboy", "bridge_sha256", "rom", "rows"}
    if set(report) != required:
        raise SameBoyTimingError("timing report has an open or incomplete schema")
    if report["schema"] != REPORT_SCHEMA or report["authority"] != AUTHORITY:
        raise SameBoyTimingError("PyBoy or unknown timing authority cannot produce the verdict")
    if report["bridge_sha256"] != bridge_sha256:
        raise SameBoyTimingError("timing report has the wrong tool identity")
    rom = report["rom"]
    if not isinstance(rom, dict) or set(rom) != {"name", "sha256"} or rom["sha256"] != rom_sha256:
        raise SameBoyTimingError("timing report has the wrong ROM identity")
    sameboy = report["sameboy"]
    expected_sameboy = {
        "schema": "sameboy-source-lock-v1",
        "version": "v1.0.3",
        "tag_object": "5104c0429df2a73cfccea8c5034d5cb72c13c5f2",
        "commit": "208ba4afabffab9edde416f2dbb8ae459e34adb8",
        "source_url": "https://codeload.github.com/LIJI32/SameBoy/tar.gz/refs/tags/v1.0.3",
        "archive_sha256": "7da338458e19396cb43dfe1a4df4555882ebea92540565dc993c1c706c981dc3",
    }
    if sameboy != expected_sameboy:
        raise SameBoyTimingError("timing report has the wrong SameBoy identity")
    rows = report["rows"]
    if not isinstance(rows, list) or {row.get("key") for row in rows if isinstance(row, dict)} != set(ROW_BY_KEY) or len(rows) != 12:
        raise SameBoyTimingError("timing report does not contain the exact 12 canonical rows")
    for raw in rows:
        if not isinstance(raw, dict) or set(raw) != set(TimingRow.__dataclass_fields__) | {"sample_core_cycles", "sample_scanlines"}:
            raise SameBoyTimingError("timing row has an open or incomplete schema")
        samples, scanlines = raw["sample_core_cycles"], raw["sample_scanlines"]
        if not isinstance(samples, list) or not samples or any(type(value) is not int or value <= 0 for value in samples):
            raise SameBoyTimingError("timing row lacks core-cycle samples")
        if not isinstance(scanlines, list) or len(scanlines) != len(samples):
            raise SameBoyTimingError("timing row lacks matching scanline samples")
        definition = ROW_BY_KEY[raw["key"]]
        if raw["deadline_cycle"] != definition.deadline_cycle or raw["guard_cycles"] != definition.guard_cycles:
            raise SameBoyTimingError("timing row relabels a non-cycle budget")
        if raw["result"] != "PASS":
            raise SameBoyTimingError("timing row does not satisfy the blocking cycle budget")
        try:
            TimingRow.from_dict({
                key: value for key, value in raw.items()
                if key in TimingRow.__dataclass_fields__
            })
        except SnapshotValidationError as exc:
            raise SameBoyTimingError(str(exc)) from exc


def _load_input_manifest(path: Path, root: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SameBoyTimingError(f"cannot read SameBoy input manifest: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema", "input_trace", "input_sha256", "max_cycles"} or raw["schema"] != INPUT_SCHEMA:
        raise SameBoyTimingError("SameBoy input manifest has the wrong schema")
    trace = root / str(raw["input_trace"])
    if _sha256(trace) != raw["input_sha256"]:
        raise SameBoyTimingError("SameBoy input trace has the wrong identity")
    if type(raw["max_cycles"]) is not int or not 1 <= raw["max_cycles"] <= 2_000_000_000:
        raise SameBoyTimingError("SameBoy input manifest has an invalid cycle bound")
    return {**raw, "input_trace": trace}


def _write_generated_input_replay(
    directory: Path,
    events: Iterable[tuple[int, int]],
    *,
    max_cycles: int,
) -> Path:
    """Write one strict, closed replay and its hash-bound manifest."""

    rows = tuple(events)
    if not rows or rows[0] != (0, 0):
        raise SameBoyTimingError("generated SameBoy replay lacks released frame zero")
    if any(
        type(frame) is not int or type(mask) is not int
        or frame < 0 or not 0 <= mask <= 0xFF
        for frame, mask in rows
    ):
        raise SameBoyTimingError("generated SameBoy replay contains an invalid event")
    frames = tuple(frame for frame, _ in rows)
    if any(after <= before for before, after in zip(frames, frames[1:])):
        raise SameBoyTimingError("generated SameBoy replay is not strictly ordered")
    if not 1 <= max_cycles <= 2_000_000_000:
        raise SameBoyTimingError("generated SameBoy replay exceeds its cycle bound")
    directory.mkdir(parents=True, exist_ok=True)
    trace = directory / "sameboy-input.tsv"
    trace.write_text(
        "frame\tkey_mask\n"
        + "".join(f"{frame}\t{mask}\n" for frame, mask in rows),
        encoding="ascii",
    )
    manifest = directory / "sameboy-input.json"
    manifest.write_text(
        json.dumps({
            "schema": INPUT_SCHEMA,
            "input_trace": trace.name,
            "input_sha256": _sha256(trace),
            "max_cycles": max_cycles,
        }, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return manifest


def _generate_default_input_manifest(root: Path, directory: Path) -> Path:
    """Record the real cold-boot path through Pallet's north boundary.

    PyBoy only records deterministic joypad frames here. SameBoy independently
    replays them and remains the sole source of blocking core-cycle samples.
    """

    from tools.rom_tests.emulator import Emulator
    from tools.rom_tests.scenarios.oaks_lab import PALLET_TOWN, REDS_HOUSE_1F

    emulator = Emulator(
        root / "pokeyellow_debug.gbc",
        root / "pokeyellow_debug.sym",
        directory / "replay-capture",
        cgb=True,
    )
    events: list[tuple[int, int]] = [(0, 0)]
    masks = {
        "right": 1, "left": 2, "up": 4, "down": 8,
        "a": 16, "b": 32, "select": 64, "start": 128,
    }
    original_press = emulator.press

    def append(frame: int, mask: int) -> None:
        if events[-1][0] == frame:
            events[-1] = (frame, mask)
        else:
            events.append((frame, mask))

    def recorded_press(self, button: str, wait_frames: int = 120) -> None:
        append(self.frame, masks[button])
        original_press(button, wait_frames)
        append(self.frame, 0)

    emulator.press = MethodType(recorded_press, emulator)
    try:
        boot_inputs = {
            650: "start", 700: "a", 750: "start", 800: "a",
            900: "start", 950: "a", 1050: "start", 1100: "a",
            1200: "start", 1250: "a",
        }
        for frame in range(1, 1321):
            button = boot_inputs.get(frame)
            if button is not None:
                emulator.pyboy.button(button, delay=2)
                append(frame, masks[button])
                append(frame + 2, 0)
            emulator.tick()
        emulator.advance_until(
            emulator.is_in_bedroom_overworld,
            button="a", max_presses=100, description="timing replay bedroom",
        )

        def advance(symbol: str, value: int, button: str, description: str) -> None:
            emulator.advance_until(
                lambda: emulator.read(symbol) == value,
                button=button, max_presses=140, description=description,
            )

        advance("wXCoord", 5, "right", "timing replay bedroom aisle")
        advance("wYCoord", 1, "up", "timing replay bedroom stairs")
        advance("wCurMap", REDS_HOUSE_1F, "right", "timing replay first floor")
        advance("wYCoord", 6, "down", "timing replay house exit row")
        advance("wXCoord", 3, "left", "timing replay house exit")
        advance("wCurMap", PALLET_TOWN, "down", "timing replay Pallet Town")
        # Exercise both movement axes and Pallet's real north connection
        # producer. Oak may intercept afterward; the connection work has
        # already crossed the measured production path.
        advance("wXCoord", 10, "right", "timing replay north exit column")
        advance("wYCoord", 0, "up", "timing replay north boundary")
        emulator.tick(120)
        max_cycles = (emulator.frame + 120) * 140_448
        return _write_generated_input_replay(
            directory, events, max_cycles=max_cycles,
        )
    finally:
        emulator.close()


def generate(root: Path, sameboy: Path, output: Path, input_manifest: Path | None = None) -> dict[str, object]:
    root, sameboy, output = root.resolve(), sameboy.resolve(), output.resolve()
    lock = SourceLock.load(root / LOCK_PATH)
    version = subprocess.run([sameboy, "--version"], text=True, capture_output=True, check=True).stdout.strip()
    if version != BRIDGE_VERSION:
        raise SameBoyTimingError(f"wrong SameBoy bridge version: {version!r}")
    rom, sym = root / "pokeyellow_debug.gbc", root / "pokeyellow_debug.sym"
    symbols = _symbols(sym)
    boot = sameboy.parent / "cgb_boot.bin"
    if not boot.is_file():
        raise SameBoyTimingError("SameBoy bridge lacks its pinned CGB boot ROM")
    observations: list[Observation] = []
    with tempfile.TemporaryDirectory(prefix="phase2-sameboy-") as temporary:
        temporary_root = Path(temporary)
        selected_manifest = input_manifest or root / INPUT_MANIFEST_PATH
        manifest_root = root
        if input_manifest is None and not selected_manifest.is_file():
            selected_manifest = _generate_default_input_manifest(root, temporary_root / "input")
            manifest_root = selected_manifest.parent
        manifest = _load_input_manifest(selected_manifest, manifest_root)
        capture = temporary_root / "capture.tsv"
        budgets = temporary_root / "budgets.tsv"
        budgets.write_text(
            "row\tusable_cycles\n" + "".join(
                f"{row.row_id}\t{row.deadline_cycle - row.guard_cycles}\n"
                for row in ROW_DEFINITIONS
            ),
            encoding="ascii",
        )
        command = [
                str(sameboy), "--rom", str(rom), "--boot-rom", str(boot),
                "--input-script", str(manifest["input_trace"]), "--output", str(capture),
                "--event-address", f"{symbols['wFullColorRuntimeTimingEvent']:04x}",
                "--row-address", f"{symbols['wFullColorRuntimeTimingRow']:04x}",
                "--sequence-address", f"{symbols['wFullColorRuntimeTimingSequence']:04x}",
                "--probe-address", f"{symbols['wFullColorRuntimeTimingProbeResult']:04x}",
                "--probe-cycles-address", f"{symbols['wFullColorRuntimeTimingProbeCycles']:04x}",
                "--budgets", str(budgets),
                "--max-cycles", str(manifest["max_cycles"]),
            ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise SameBoyTimingError(f"SameBoy bridge failed: {exc.stderr.strip()}") from exc
        observations.extend(parse_bridge_output(capture))
    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "authority": AUTHORITY,
        "sameboy": asdict(lock),
        "bridge_sha256": _sha256(sameboy),
        "rom": {"name": rom.name, "sha256": _sha256(rom)},
        "rows": list(rows_from_observations(observations, rom.name)),
    }
    validate_report(report, rom_sha256=_sha256(rom), bridge_sha256=_sha256(sameboy))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sameboy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        generate(args.root, args.sameboy, args.output, args.input_manifest)
    except (SameBoyTimingError, OSError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
