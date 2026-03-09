from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

from .types import InputPaths

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
  python -m mirbc /path/to/redcap /path/to/redcap15.7.4.zip
  mirbc /path/to/redcap15.7.4.zip /path/to/redcap

This minimal version:
  - reads only from the REDCap installation
  - streams the reference ZIP without extracting it
  - performs no downloads, installs, or remote access
  - prints a text report to stdout
"""


def parse_inputs(argv: list[str]) -> InputPaths | None:
    if not argv:
        print(HELP_TEXT)
        return prompt_for_inputs()

    if len(argv) == 1 and argv[0] in {"-h", "--help"}:
        print(HELP_TEXT)
        return None

    ignored_subdirectories, positional = parse_cli_args(argv)
    if len(positional) != 2:
        raise ValueError(
            "Expected exactly two positional arguments plus optional -i/--ignore entries."
        )

    return normalize_inputs(
        positional[0],
        positional[1],
        ignored_subdirectories=ignored_subdirectories,
    )


def prompt_for_inputs() -> InputPaths:
    reference = input("Reference ZIP path: ").strip()
    target = input("Target REDCap root path: ").strip()
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
        interactive=True,
    )


def parse_cli_args(argv: list[str]) -> tuple[list[str], list[str]]:
    ignored_subdirectories: list[str] = []
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
        else:
            positional.append(token)
        idx += 1
    return dedupe_preserve_order(ignored_subdirectories), positional


def normalize_inputs(
    first: str,
    second: str,
    *,
    ignored_subdirectories: list[str] | None = None,
    interactive: bool = False,
) -> InputPaths:
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

    return InputPaths(
        reference_zip=reference_zip.resolve(),
        target_root=target_root.resolve(),
        ignored_subdirectories=dedupe_preserve_order(ignored_subdirectories or []),
        interactive=interactive,
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
