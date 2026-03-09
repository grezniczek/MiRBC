from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class CompareInputs:
    reference_zip: Path
    target_root: Path
    ignored_subdirectories: list[str] = field(default_factory=list)
    expectations_files: list[Path] = field(default_factory=list)
    skip_modules: bool = False
    skip_hooks: bool = False
    interactive: bool = False


@dataclass(slots=True)
class CreateExpectationsInputs:
    root: Path
    selected_paths: list[Path] = field(default_factory=list)
    recursive: bool = False


@dataclass(slots=True)
class SpecialDirectoryReport:
    name: str
    extra_entry_count: int = 0
    extra_module_dirs: list[str] = field(default_factory=list)
    extra_hook_entries: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ComparisonResult:
    reference_zip: Path
    reference_zip_sha256: str
    reference_root: str
    target_root: Path
    expectations_files: list[Path] = field(default_factory=list)
    skip_modules: bool = False
    skip_hooks: bool = False
    parsed_version: str = ""
    total_expectations: int = 0
    matching_count: int = 0
    matched_expectations: list[str] = field(default_factory=list)
    different_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    extra_files: list[str] = field(default_factory=list)
    special_dirs: dict[str, SpecialDirectoryReport] = field(default_factory=dict)
    extra_versioned_dirs: list[str] = field(default_factory=list)
    skipped_symlinks: list[str] = field(default_factory=list)
    unreadable_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ignored_subdirectories: list[str] = field(default_factory=list)
