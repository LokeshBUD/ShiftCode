import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from shiftcode.config import load_config
from shiftcode.models import Status
from shiftcode.pipeline.orchestrator import run_migration
from shiftcode.pipeline.report import to_json, to_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shiftcode")
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="Migrate a Python 2 file or project to Python 3")
    migrate.add_argument("path", type=Path)
    migrate.add_argument("--output-dir", type=Path, default=None)
    migrate.add_argument("--report-format", choices=["json", "text", "both"], default="both")
    migrate.add_argument("--model", default=None)
    migrate.add_argument("--base-url", default=None)
    migrate.add_argument("--py2-interpreter", default=None)
    migrate.add_argument("--max-repair-attempts", type=int, default=None)
    migrate.add_argument("--determinism-runs", type=int, default=None)
    migrate.add_argument("--dry-run", action="store_true")
    migrate.add_argument("--in-place", action="store_true")
    migrate.add_argument("--strict", action="store_true")
    return parser


def _default_output_dir(path: Path) -> Path:
    return Path.cwd() / f"{path.name}-migrated"


def _write_migrated_files(report, output_dir: Path, in_place: bool) -> None:
    for f in report.files:
        if f.status != Status.VERIFIED or f.final_source is None:
            continue
        target = f.path if in_place else (output_dir / f.path.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.final_source)


def _run_dry_run(path: Path) -> int:
    from shiftcode.pipeline.analyze import find_lib2to3_findings
    from shiftcode.pipeline.ingest import ingest

    for unit in ingest(path):
        findings = find_lib2to3_findings(unit.original_source)
        print(f"{unit.path}: {len(findings)} lib2to3-fixable construct(s) found")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # loads .env from cwd (or nearest parent) into os.environ, if present

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "migrate":
        parser.print_help()
        return 1

    if args.dry_run:
        return _run_dry_run(args.path)

    project_root = args.path if args.path.is_dir() else args.path.parent
    config = load_config(
        project_root=project_root,
        cli_base_url=args.base_url,
        cli_model=args.model,
        cli_py2_interpreter=args.py2_interpreter,
        cli_max_repair_attempts=args.max_repair_attempts,
        cli_determinism_runs=args.determinism_runs,
    )

    report = run_migration(args.path, config)

    if args.report_format in ("text", "both"):
        print(to_text(report))

    output_dir = args.output_dir or _default_output_dir(args.path)
    if args.report_format in ("json", "both"):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.json").write_text(to_json(report))
        print(f"\nJSON report written to {output_dir / 'report.json'}")

    if not args.in_place:
        output_dir.mkdir(parents=True, exist_ok=True)
    _write_migrated_files(report, output_dir, args.in_place)

    if args.strict and any(f.status != Status.VERIFIED for f in report.files):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
