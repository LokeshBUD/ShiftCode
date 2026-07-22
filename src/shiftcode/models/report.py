from dataclasses import dataclass

from shiftcode.models.file_unit import FileUnit


@dataclass
class MigrationReport:
    files: list[FileUnit]
    # Run-level (not per-file) transparency: did ShiftCode find/install the
    # project's own requirements.txt before verification ran? A missing
    # dependency in the sandbox looks identical to a real migration bug from
    # inside the pipeline (see docs/bug-log.md #5) - surfacing this plainly
    # in the report lets a human tell those two cases apart at a glance.
    dependency_provisioning: str | None = None
