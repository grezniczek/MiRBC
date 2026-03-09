from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

from .types import CompareInputs, CreateExpectationsInputs

HELP_TEXT = """MiRBC is the Minimal REDCap Baseline Comparator. It compares a deployed
REDCap installation against a matching reference REDCap ZIP using relative paths
and SHA-256 file hashes.

Required inputs:
  1. Path to a full REDCap ZIP for the exact deployed version.
  2. Path to the root of a deployed REDCap installation.

Ways to supply the target path without third-party Python dependencies:
  - a normal local filesystem path
  - a read-only bind mount
  - a mounted network share (for example NFS or SMB)
  - a mounted remote filesystem prepared outside this tool

Usage:
  python -m mirbc
  python -m mirbc /path/to/redcap15.7.4.zip /path/to/redcap
  python -m mirbc -i modules/custom -i temp/cache /path/to/redcap15.7.4.zip /path/to/redcap
  python -m mirbc -e /path/to/base.txt -e /path/to/local.txt /path/to/redcap15.7.4.zip /path/to/redcap
  python -m mirbc --skip-modules --skip-hooks /path/to/redcap15.7.4.zip /path/to/redcap
  python -m mirbc create-expectations --base /path/to/redcap some/file.php
  python -m mirbc create-expectations --base /path/to/redcap -r modules/custom
  python -m mirbc /path/to/redcap /path/to/redcap15.7.4.zip
  mirbc /path/to/redcap15.7.4.zip /path/to/redcap

This minimal version:
  - reads only from the REDCap installation
  - streams the reference ZIP without extracting it
  - performs no downloads, installs, or remote access
  - prints reports or generated expectations to stdout

Optional inputs:
  -i, --ignore         Ignore a subdirectory relative to the detected target root.
  -e, --expectations   Read expected file hashes from a text file; may be repeated.
  --skip-modules       Treat target-only modules/ content as a special skipped directory.
  --skip-hooks         Treat target-only hooks/ content as a special skipped directory.
"""


def parse_inputs(argv: list[str]) -> CompareInputs | CreateExpectationsInputs | None:
    if not argv:
        print(HELP_TEXT)
        return prompt_for_compare_inputs()

    if len(argv) == 1 and argv[0] in {"-h", "--help"}:
        print(HELP_TEXT)
        return None
    if argv[0] == "create-expectations":
        return parse_create_expectations_inputs(argv[1:])

    (
        ignored_subdirectories,
        expectations_files,
        skip_modules,
        skip_hooks,
        positional,
    ) = parse_cli_args(argv)
    if len(positional) != 2:
        raise ValueError(
            "Expected exactly two positional arguments plus optional -i/--ignore and -e/--expectations entries."
        )

    return normalize_inputs(
        positional[0],
        positional[1],
        ignored_subdirectories=ignored_subdirectories,
        expectations_files=expectations_files,
        skip_modules=skip_modules,
        skip_hooks=skip_hooks,
    )


def prompt_for_compare_inputs() -> CompareInputs:
    reference = input("Reference ZIP path: ").strip()
    target = input("Target REDCap root path: ").strip()
    expectations_files: list[str] = []
    while True:
        value = input("Expectations file path (empty to finish): ").strip()
        if not value:
            break
        expectations_files.append(value)
    ignored_subdirectories: list[str] = []
    while True:
        value = input(
            "Ignore subdirectory relative to target root (empty to finish): "
        ).strip()
        if not value:
            break
        ignored_subdirectories.append(normalize_ignore_entry(value))
    return normalize_inputs(
        reference,
        target,
        ignored_subdirectories=ignored_subdirectories,
        expectations_files=expectations_files,
        interactive=True,
    )


def parse_create_expectations_inputs(
    argv: list[str],
) -> CreateExpectationsInputs | None:
    if not argv or (len(argv) == 1 and argv[0] in {"-h", "--help"}):
        print(CREATE_EXPECTATIONS_HELP_TEXT)
        return None

    base_value: str | None = None
    recursive = False
    positional: list[str] = []
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token in {"-h", "--help"}:
            print(CREATE_EXPECTATIONS_HELP_TEXT)
            raise SystemExit(0)
        if token in {"-b", "--base"}:
            idx += 1
            if idx >= len(argv):
                raise ValueError("Missing value after -b/--base.")
            base_value = argv[idx]
        elif token in {"-r", "--recursive"}:
            recursive = True
        else:
            positional.append(token)
        idx += 1

    if not base_value:
        raise ValueError("create-expectations requires -b/--base /path/to/redcap.")
    if not positional:
        raise ValueError("create-expectations requires at least one file or directory path.")

    return normalize_create_expectations_inputs(
        base_value,
        positional,
        recursive=recursive,
    )


def parse_cli_args(argv: list[str]) -> tuple[list[str], list[str], bool, bool, list[str]]:
    ignored_subdirectories: list[str] = []
    expectations_files: list[str] = []
    skip_modules = False
    skip_hooks = False
    positional: list[str] = []
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token in {"-h", "--help"}:
            print(HELP_TEXT)
            raise SystemExit(0)
        if token in {"-i", "--ignore"}:
            idx += 1
            if idx >= len(argv):
                raise ValueError("Missing value after -i/--ignore.")
            ignored_subdirectories.append(normalize_ignore_entry(argv[idx]))
        elif token in {"-e", "--expectations"}:
            idx += 1
            if idx >= len(argv):
                raise ValueError("Missing value after -e/--expectations.")
            expectations_files.append(argv[idx])
        elif token == "--skip-modules":
            skip_modules = True
        elif token == "--skip-hooks":
            skip_hooks = True
        else:
            positional.append(token)
        idx += 1
    return (
        dedupe_preserve_order(ignored_subdirectories),
        dedupe_preserve_order(expectations_files),
        skip_modules,
        skip_hooks,
        positional,
    )


def normalize_inputs(
    first: str,
    second: str,
    *,
    ignored_subdirectories: list[str] | None = None,
    expectations_files: list[str] | None = None,
    skip_modules: bool = False,
    skip_hooks: bool = False,
    interactive: bool = False,
) -> CompareInputs:
    first_path = Path(first).expanduser()
    second_path = Path(second).expanduser()

    zip_candidates = [
        path for path in (first_path, second_path) if path.suffix.lower() == ".zip"
    ]
    if len(zip_candidates) != 1:
        raise ValueError("Exactly one argument must be a .zip file.")

    reference_zip = zip_candidates[0]
    target_root = second_path if reference_zip == first_path else first_path

    if not reference_zip.is_file():
        raise ValueError(f"Reference ZIP not found or not a file: {reference_zip}")
    if not target_root.is_dir():
        raise ValueError(f"Target path not found or not a directory: {target_root}")
    resolved_expectations: list[Path] = []
    for expectations_file in dedupe_preserve_order(expectations_files or []):
        resolved_expectation = Path(expectations_file).expanduser()
        if not resolved_expectation.is_file():
            raise ValueError(
                f"Expectations file not found or not a file: {resolved_expectation}"
            )
        try:
            with resolved_expectation.open("r", encoding="utf-8"):
                pass
        except OSError as exc:
            raise ValueError(
                f"Could not read expectations file {resolved_expectation}: {exc}"
            ) from exc
        resolved_expectations.append(resolved_expectation.resolve())

    return CompareInputs(
        reference_zip=reference_zip.resolve(),
        target_root=target_root.resolve(),
        ignored_subdirectories=dedupe_preserve_order(ignored_subdirectories or []),
        expectations_files=resolved_expectations,
        skip_modules=skip_modules,
        skip_hooks=skip_hooks,
        interactive=interactive,
    )


def normalize_create_expectations_inputs(
    base_value: str,
    selected_values: list[str],
    *,
    recursive: bool,
) -> CreateExpectationsInputs:
    base = Path(base_value).expanduser()
    if not base.is_dir():
        raise ValueError(f"Base path not found or not a directory: {base}")

    resolved_root = base.resolve()
    selected_paths: list[Path] = []
    for raw_path in dedupe_preserve_order(selected_values):
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = resolved_root / candidate
        if not candidate.exists():
            raise ValueError(f"Selected path not found: {candidate}")
        resolved_candidate = candidate.resolve()
        ensure_within_root(resolved_candidate, resolved_root)
        if resolved_candidate.is_dir() and not recursive:
            raise ValueError(
                f"Directory input requires -r/--recursive: {resolved_candidate}"
            )
        selected_paths.append(resolved_candidate)

    return CreateExpectationsInputs(
        root=resolved_root,
        selected_paths=selected_paths,
        recursive=recursive,
    )


def normalize_ignore_entry(value: str) -> str:
    normalized = value.strip().replace("\\", "/").strip("/")
    if not normalized:
        raise ValueError("Ignored subdirectory value cannot be empty.")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        raise ValueError(f"Ignored subdirectory must be relative: {value}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(
            f"Ignored subdirectory must be a clean relative path: {value}"
        )
    return path.as_posix()


def ensure_within_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Selected path is outside -b/--base: {path}") from exc


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def print_error(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


CREATE_EXPECTATIONS_HELP_TEXT = """Generate expectation file entries for selected files.

Usage:
  python -m mirbc create-expectations --base /path/to/redcap PATH...
  python -m mirbc create-expectations -b /path/to/redcap -r PATH...
  mirbc create-expectations --base /path/to/redcap PATH...

Behavior:
  - -b/--base is required and defines the relative path base for emitted entries
  - PATH arguments may be files or directories
  - directories require -r/--recursive
  - output is written to stdout as 'relative/path = sha256hex'
"""
