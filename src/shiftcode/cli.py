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
    migrate.add_argument(
        "--capture-repair-history",
        action="store_true",
        default=None,
        help="append every diagnosed repair to repair_history_path, for later use by `suggest-fixer-rules`",
    )
    migrate.add_argument(
        "--recordings-dir",
        default=None,
        help="directory of *.jsonl recordings (see `shiftcode init-recorder`) for Mode R verification",
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

    suggest = sub.add_parser(
        "suggest-fixer-rules",
        help="draft candidate permanent fixer detectors from confirmed repairs (see --capture-repair-history)",
    )
    suggest.add_argument("--history", type=Path, default=None, help="defaults to config's repair_history_path")
    suggest.add_argument("--out", type=Path, default=Path("candidate_fixers"))
    suggest.add_argument("--model", default=None)
    suggest.add_argument("--base-url", default=None)

    init_recorder = sub.add_parser(
        "init-recorder",
        help="copy the standalone py2-compatible call recorder into your own project (see --recordings-dir)",
    )
    init_recorder.add_argument("--out", type=Path, default=Path("shiftcode_record.py"))

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
    it), VERIFIED_RECORDED (real captured usage data confirmed it), and
    VERIFIED_INFERRED (LLM-inferred/fuzzed characterization tests confirmed
    it - the weakest of the three real signals, see docs) all get written
    out; previously only VERIFIED did, silently dropping real, usable
    migrated code for anything that only reached a weaker tier. Neither
    VERIFIED_RECORDED nor VERIFIED_INFERRED ever overwrites the original
    file even under --in-place - neither tier is confirmed by a
    human-authored test, so silently replacing real source with either is a
    meaningfully bigger risk than doing so for a human-test-confirmed
    VERIFIED file."""
    written = []
    for f in report.files:
        if f.final_source is None:
            continue
        if f.status == Status.VERIFIED:
            target = f.path if in_place else (output_dir / f.path.name)
        elif f.status in (Status.VERIFIED_RECORDED, Status.VERIFIED_INFERRED):
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


def _write_draft_fixer(rule, entry, out_dir: Path) -> Path:
    """Never exec()'d - a candidate .py file for a human to read like a PR.
    A draft that doesn't even parse still gets written (never silently
    dropped - same "be honest about degraded output" posture as everywhere
    else in this pipeline), just flagged loudly in the header instead."""
    import ast

    parse_warning = ""
    try:
        ast.parse(rule.draft_detector_code)
    except SyntaxError as exc:
        parse_warning = f"\n# WARNING: draft did not parse, needs manual rewrite: {exc}"

    header = (
        "# Candidate fixer, drafted by FixerRuleAgent - REVIEW BEFORE USE.\n"
        "# Never wired into the pipeline automatically. See docs/bug-log.md for\n"
        "# the graduation process: review, test, then hand-add to analyze.py.\n"
        f"# source repair: {entry.file_path}\n"
        f"# trigger: {rule.trigger_description}\n"
        f"# fix: {rule.fix_description}\n"
        f"# safety_conditions: {rule.safety_conditions}\n"
        f"# confidence: {rule.confidence}"
        f"{parse_warning}\n\n"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{rule.pattern_name}.py"
    target.write_text(header + rule.draft_detector_code)
    return target


def _run_suggest_fixer_rules(args: argparse.Namespace) -> int:
    from shiftcode.agents.base import AgentOutputError
    from shiftcode.agents.fixer_rule import FixerRuleAgent
    from shiftcode.llm import get_provider
    from shiftcode.pipeline.repair_history import load_repair_history

    config = load_config(cli_base_url=args.base_url, cli_model=args.model)
    history_path = args.history or Path(config.repair_history_path)
    entries = load_repair_history(history_path)
    if not entries:
        print(f"no repair history found at {history_path} - nothing to suggest")
        return 0

    agent = FixerRuleAgent(get_provider(config.llm_for("fixer_rule"), name="fixer_rule"))
    written = []
    for entry in entries:
        try:
            rule = agent.propose_rule(entry=entry)
        except AgentOutputError as exc:
            print(f"{entry.file_path}: skipped, could not draft a rule ({exc})")
            continue
        target = _write_draft_fixer(rule, entry, args.out)
        written.append(target)
        print(f"{entry.file_path}: drafted {target}")

    print(f"\n{len(written)}/{len(entries)} candidate fixer(s) written to {args.out} - review before use.")
    return 0


def _run_init_recorder(args: argparse.Namespace) -> int:
    from importlib import resources

    source = resources.files("shiftcode.record").joinpath("recorder.py").read_text()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(source)
    print(f"wrote {args.out} - copy it into your Python 2 project and `from {args.out.stem} import record`.")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # loads .env from cwd (or nearest parent) into os.environ, if present

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "suggest-fixer-rules":
        return _run_suggest_fixer_rules(args)

    if args.command == "init-recorder":
        return _run_init_recorder(args)

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
        cli_capture_repair_history=args.capture_repair_history,
        cli_recordings_dir=args.recordings_dir,
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

    # VERIFIED_RECORDED/VERIFIED_INFERRED files always land here, even under --in-place
    output_dir.mkdir(parents=True, exist_ok=True)
    written = _write_migrated_files(report, output_dir, args.in_place)
    recorded_written = [f for f in report.files if f.status == Status.VERIFIED_RECORDED and f.final_source]
    if recorded_written:
        print(
            f"\n{len(recorded_written)} file(s) reached VERIFIED_RECORDED (matched real "
            f"captured usage data, not a human-authored test) - written to {output_dir}, "
            f"not overwritten in place, even with --in-place. Review before trusting these."
        )
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
