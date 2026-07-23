import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from shiftcode.config import load_config
from shiftcode.models import Status
from shiftcode.pipeline.orchestrator import run_migration
from shiftcode.pipeline.report import to_console, to_json, to_text


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
    migrate.add_argument(
        "--characterization-fuzz-cases",
        type=int,
        default=None,
        help="target number of auto-generated Mode C fuzz cases per function (0/unset = off, use LLM-picked examples)",
    )
    migrate.add_argument("--dry-run", action="store_true")
    migrate.add_argument("--in-place", action="store_true")
    migrate.add_argument("--strict", action="store_true")
    migrate.add_argument(
        "--no-install-deps",
        action="store_true",
        help="skip auto-installing the project's requirements.txt into the verification sandboxes",
    )
    migrate.add_argument(
        "--quiet", "-q", action="store_true", help="suppress live per-file progress output during the run"
    )
    return parser


def _make_progress_printer():
    """Live progress output during the run: each real API/Docker call this
    slow (network + sandboxed execution, easily 10+ minutes for a real
    project) previously showed nothing at all until the whole run finished -
    just a silent, unresponsive-looking wait. Prefixes each line with
    elapsed seconds so a stall (e.g. waiting on a slow LLM response) is
    visible as time passing, not just silence."""
    start = time.monotonic()

    def _print(msg: str) -> None:
        elapsed = time.monotonic() - start
        print(f"[{elapsed:6.1f}s] {msg}", flush=True)

    return _print


def _default_output_dir(path: Path) -> Path:
    return Path.cwd() / f"{path.name}-migrated"


def _write_migrated_files(report, output_dir: Path, in_place: bool) -> list[Path]:
    """VERIFIED (human-authored test suite or golden-output diff confirmed
    it) and VERIFIED_INFERRED (LLM-inferred characterization tests confirmed
    it - a real but lower-confidence signal, see docs) both get written out;
    previously only VERIFIED did, silently dropping real, usable migrated
    code for any file that only reached VERIFIED_INFERRED. VERIFIED_INFERRED
    never overwrites the original file even under --in-place - that tier is
    confirmed by an LLM-inferred spec, not a human-authored one, so silently
    replacing real source with it is a meaningfully bigger risk than doing so
    for a human-test-confirmed VERIFIED file."""
    written = []
    for f in report.files:
        if f.final_source is None:
            continue
        if f.status == Status.VERIFIED:
            target = f.path if in_place else (output_dir / f.path.name)
        elif f.status == Status.VERIFIED_INFERRED:
            target = output_dir / f.path.name
        else:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.final_source)
        written.append(target)
    return written


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
        cli_characterization_fuzz_cases=args.characterization_fuzz_cases,
    )
    if args.no_install_deps:
        config = replace(config, install_project_dependencies=False)

    on_progress = None if args.quiet else _make_progress_printer()
    report = run_migration(args.path, config, on_progress=on_progress)

    if args.report_format in ("text", "both"):
        # Colorized summary for an interactive terminal; plain to_text() when
        # output is piped/redirected (a log file, `| grep`, CI capture) so
        # nothing downstream has to deal with ANSI codes it didn't ask for.
        print(to_console(report) if sys.stdout.isatty() else to_text(report))

    output_dir = args.output_dir or _default_output_dir(args.path)
    if args.report_format in ("json", "both"):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.json").write_text(to_json(report))
        print(f"\nJSON report written to {output_dir / 'report.json'}")

    output_dir.mkdir(parents=True, exist_ok=True)  # VERIFIED_INFERRED files always land here, even under --in-place
    written = _write_migrated_files(report, output_dir, args.in_place)
    inferred_written = [f for f in report.files if f.status == Status.VERIFIED_INFERRED and f.final_source]
    if inferred_written:
        print(
            f"\n{len(inferred_written)} file(s) reached VERIFIED_INFERRED (LLM-inferred "
            f"tests, not human-authored ones) - written to {output_dir}, not overwritten "
            f"in place, even with --in-place. Review before trusting these."
        )
    print(f"{len(written)} migrated file(s) written.")

    if args.strict and any(f.status != Status.VERIFIED for f in report.files):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
