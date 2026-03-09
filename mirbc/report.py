from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from .types import ComparisonResult


def render_report(result: ComparisonResult) -> str:
    lines: list[str] = []
    add = lines.append

    add("MiRBC Report")
    add("============")
    add(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    add("")
    add("Inputs")
    add("------")
    add(f"Reference ZIP: {result.reference_zip}")
    add(f"Reference ZIP SHA-256: {result.reference_zip_sha256}")
    add(f"Reference REDCap root: {result.reference_root}")
    add(f"Target REDCap root: {result.target_root}")
    add(f"Parsed REDCap version: {result.parsed_version or 'unavailable'}")
    if result.warnings:
        add(f"Warnings: {len(result.warnings)}")
    add("")
    add("Expectations Files")
    add("------------------")
    add_paths(add, [str(path) for path in result.expectations_files])
    add("")
    add("Ignored Subdirectories")
    add("----------------------")
    add_paths(add, result.ignored_subdirectories)
    add("")
    add("Special Skip Flags")
    add("------------------")
    add(f"modules/: {'enabled' if result.skip_modules else 'disabled'}")
    add(f"hooks/: {'enabled' if result.skip_hooks else 'disabled'}")
    add("")
    add("Summary")
    add("-------")
    add(f"Matching files: {result.matching_count}")
    add(
        "Matched expectations: "
        f"{len(result.matched_expectations)} / {result.total_expectations}"
    )
    add(f"Different files: {len(result.different_files)}")
    add(f"Missing files: {len(result.missing_files)}")
    add(f"Extra files: {len(result.extra_files)}")
    add("")
    add("Special Directories")
    add("-------------------")
    for name in result.special_dirs:
        report = result.special_dirs[name]
        add(f"{name}/: contains {report.extra_entry_count} extra files/folders")
        if name == "modules" and report.extra_module_dirs:
            add("Extra module folders:")
            for entry in report.extra_module_dirs:
                add(f"  - {entry}")
        if name == "hooks" and report.extra_hook_entries:
            add("Extra hooks tree:")
            for entry in report.extra_hook_entries:
                add(f"  - {entry}")
    add("")

    add("Extra Versioned REDCap Folders (not checked, removal recommended)")
    add("---------------------------------------------------------------")
    if result.extra_versioned_dirs:
        for entry in result.extra_versioned_dirs:
            add(f"- {entry}")
    else:
        add("None")
    add("")

    add("Different Files")
    add("---------------")
    add_paths(add, result.different_files)
    add("")

    add("Missing Files")
    add("-------------")
    add_paths(add, result.missing_files)
    add("")

    add("Extra Files")
    add("-----------")
    add_paths(add, result.extra_files)

    if result.warnings:
        add("")
        add("Warnings")
        add("--------")
        add_paths(add, result.warnings)

    if result.skipped_symlinks:
        add("")
        add("Skipped Symlinks")
        add("----------------")
        add_paths(add, result.skipped_symlinks)

    if result.unreadable_files:
        add("")
        add("Unreadable Files")
        add("----------------")
        add_paths(add, result.unreadable_files)

    lines.append("")
    return "\n".join(lines)


def add_paths(add: Callable[[str], None], paths: list[str]) -> None:
    if not paths:
        add("None")
        return
    for path in paths:
        add(f"- {path}")
