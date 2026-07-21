from dataclasses import dataclass

from shiftcode.models.file_unit import FileUnit


@dataclass
class MigrationReport:
    files: list[FileUnit]
