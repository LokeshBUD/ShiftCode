import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from shiftcode.models import FileUnit, Status


@dataclass
class RepairHistoryEntry:
    file_path: str
    before_source: str
    after_source: str
    hints: list[str] = field(default_factory=list)
    failure_summaries: list[str] = field(default_factory=list)


def qualifying_repair(file_unit: FileUnit) -> RepairHistoryEntry | None:
    """Only files with a real, diagnosed root cause behind their fix are
    worth feeding to the fixer-rule agent - a file that reached
    VERIFIED/VERIFIED_INFERRED with zero repair attempts (Planner got it
    right first try) or with attempts that never got an Auditor hint (a
    syntax retry, not a diagnosed semantic bug) has no articulable "pattern"
    to generalize from, unlike the real historical cases (bug-log.md #1, #7,
    #8) this whole feature is modeled on - all three involved a real
    Auditor-diagnosed root cause."""
    if file_unit.status not in (Status.VERIFIED, Status.VERIFIED_INFERRED):
        return None
    hints = [a.hint for a in file_unit.repair_attempts if a.hint]
    if not hints:
        return None
    if file_unit.final_source is None:
        return None
    return RepairHistoryEntry(
        file_path=str(file_unit.path),
        before_source=file_unit.original_source,
        after_source=file_unit.final_source,
        hints=hints,
        failure_summaries=[a.failure_summary for a in file_unit.repair_attempts],
    )


def append_repair_history(entries: list[RepairHistoryEntry], path: Path) -> None:
    """JSONL append - one real repair per line, never truncates prior runs'
    history. Creates the parent directory and file on first write."""
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for entry in entries:
            f.write(json.dumps(asdict(entry)) + "\n")


def load_repair_history(path: Path) -> list[RepairHistoryEntry]:
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(RepairHistoryEntry(**json.loads(line)))
    return entries
