"""Repository contract for the retired migration-stage vocabulary."""

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).parents[5]
LEGITIMATE_GAME_GATE_COUNTS = {
    Path("constants/event_constants.asm"): 1,
    Path("engine/events/hidden_events/cinnabar_gym_quiz.asm"): 4,
    Path("scripts/CinnabarGym.asm"): 2,
}
RETIRED_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])" + "gate" + r"(?:[ _-]?(?:0|" + "zero" + r"))"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def test_retired_stage_vocabulary_is_absent_from_tracked_files() -> None:
    tracked = subprocess.run(
        ("git", "ls-files", "-z"),
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    findings: list[str] = []
    legitimate_counts: dict[Path, int] = {}
    for raw_path in tracked:
        if not raw_path:
            continue
        relative = Path(raw_path.decode("utf-8"))
        try:
            text = (ROOT / relative).read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeDecodeError):
            continue
        matches = RETIRED_PATTERN.findall(text)
        if relative in LEGITIMATE_GAME_GATE_COUNTS:
            legitimate_counts[relative] = len(matches)
        elif matches:
            findings.append(relative.as_posix())
    assert findings == []
    assert legitimate_counts == LEGITIMATE_GAME_GATE_COUNTS


def test_retired_stage_detector_covers_supported_spellings() -> None:
    spellings = (
        "Gate" + " 0",
        "gate" + "-0",
        "gate" + "_0",
        "gate" + "0",
        "Gate" + " Zero",
        "gate" + "-zero",
        "gate" + "_zero",
    )
    assert all(RETIRED_PATTERN.search(value) for value in spellings)
    detector_source = Path(__file__).read_text(encoding="utf-8")
    assert RETIRED_PATTERN.search(detector_source) is None


def test_retired_stage_detector_rejects_substrings_and_partial_numbers() -> None:
    false_positives = (
        "navi" + "gate" + " 0",
        "investi" + "gate" + "-zero",
        "aggre" + "gate" + "0",
        "gate" + " 01",
        "gate" + "zeroed",
    )
    assert all(RETIRED_PATTERN.search(value) is None for value in false_positives)
