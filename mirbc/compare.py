from __future__ import annotations

import hashlib
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .expectations import load_expectations_files
from .types import ComparisonResult, SpecialDirectoryReport

MARKER_FILES = ("redcap_connect.php", "database.php", "cron.php")
SPECIAL_DIRS = ("temp", "modules", "edocs", "hooks")
EXPECTED_ZIP_ROOT_FILES = {
    "Installation Instructions.txt",
    "REDCap License.txt",
}
ZIP_VERSION_RE = re.compile(
    r"^redcap(?:_|-)?v?(?P<version>\d+\.\d+\.\d+)\.zip$",
    re.IGNORECASE,
)
VERSIONED_DIR_RE = re.compile(r"^redcap_v(?P<version>\d+\.\d+\.\d+)$", re.IGNORECASE)


@dataclass(slots=True)
class TreeSnapshot:
    file_hashes: dict[str, str]
    file_paths: set[str]
    dir_paths: set[str]
    symlinks: list[str]
    unreadable_files: list[str]

    @property
    def all_paths(self) -> set[str]:
        return self.file_paths | self.dir_paths


def compare_reference_zip_to_target(
    reference_zip: Path,
    target_root: Path,
    ignored_subdirectories: list[str] | None = None,
    expectations_files: list[Path] | None = None,
) -> ComparisonResult:
    reference_zip = reference_zip.resolve()
    target_root = detect_redcap_root(target_root.resolve())
    ignored_subdirectories = sorted(set(ignored_subdirectories or []))
    parsed_version = parse_zip_version(reference_zip.name)
    reference_zip_sha256 = sha256_file(reference_zip)
    ignored_version_dirs = find_ignored_version_dirs(target_root, parsed_version)
    reference, warnings = snapshot_reference_zip(reference_zip, ignored_subdirectories)
    target = snapshot_tree(
        target_root,
        ignored_top_level_dirs=ignored_version_dirs,
        ignored_subdirectories=ignored_subdirectories,
    )
    expectations: dict[str, str] = {}
    if expectations_files:
        expectations, expectation_warnings, _ = load_expectations_files(
            expectations_files
        )
        warnings.extend(expectation_warnings)

    all_reference_files = reference.file_paths
    all_target_files = target.file_paths

    different_files = {
        path
        for path in (all_reference_files & all_target_files)
        if reference.file_hashes[path] != target.file_hashes[path]
    }
    missing_files = sorted(all_reference_files - all_target_files)
    raw_extra_files = set(all_target_files - all_reference_files)
    matched_expectations: list[str] = []

    for rel_path, expected_hash in expectations.items():
        if rel_path not in all_target_files:
            warnings.append(
                f"Unused expectation for missing target file: {rel_path}"
            )
            continue

        actual_hash = target.file_hashes[rel_path]
        if actual_hash != expected_hash:
            warnings.append(
                f"Expectation hash did not match target file: {rel_path}"
            )
            continue

        matched_expectations.append(rel_path)
        different_files.discard(rel_path)
        raw_extra_files.discard(rel_path)

    special_dirs = summarize_special_extras(
        reference,
        target,
        suppressed_files=set(matched_expectations),
    )
    special_extra_files = {
        path for path in raw_extra_files if top_level_component(path) in SPECIAL_DIRS
    }
    extra_files = sorted(raw_extra_files - special_extra_files)

    return ComparisonResult(
        reference_zip=reference_zip,
        reference_zip_sha256=reference_zip_sha256,
        reference_root="ZIP:redcap/",
        target_root=target_root,
        expectations_files=[path.resolve() for path in (expectations_files or [])],
        parsed_version=parsed_version,
        matching_count=len(all_reference_files & all_target_files) - len(different_files),
        matched_expectations=sorted(matched_expectations),
        different_files=sorted(different_files),
        missing_files=missing_files,
        extra_files=extra_files,
        special_dirs=special_dirs,
        extra_versioned_dirs=sorted(ignored_version_dirs),
        skipped_symlinks=sorted(set(reference.symlinks + target.symlinks)),
        unreadable_files=sorted(set(reference.unreadable_files + target.unreadable_files)),
        warnings=sorted(set(warnings)),
        ignored_subdirectories=ignored_subdirectories,
    )


def parse_zip_version(filename: str) -> str:
    match = ZIP_VERSION_RE.match(filename)
    return match.group("version") if match else ""


def detect_redcap_root(base_path: Path) -> Path:
    if contains_markers(base_path):
        return base_path

    for depth in (1, 2):
        for candidate in iter_dirs_to_depth(base_path, depth):
            if contains_markers(candidate):
                return candidate

    raise ValueError(
        f"Could not detect a REDCap root under {base_path}. "
        f"Expected one of: {', '.join(MARKER_FILES)}"
    )


def contains_markers(path: Path) -> bool:
    return path.is_dir() and any((path / marker).is_file() for marker in MARKER_FILES)


def iter_dirs_to_depth(root: Path, max_depth: int) -> list[Path]:
    results: list[Path] = []
    root_parts = len(root.parts)
    for current, dirnames, _ in os.walk(root):
        current_path = Path(current)
        depth = len(current_path.parts) - root_parts
        if depth > max_depth:
            dirnames[:] = []
            continue
        if depth > 0:
            results.append(current_path)
    return results


def snapshot_reference_zip(
    zip_path: Path,
    ignored_subdirectories: list[str] | None = None,
) -> tuple[TreeSnapshot, list[str]]:
    file_hashes: dict[str, str] = {}
    file_paths: set[str] = set()
    dir_paths: set[str] = set()
    unreadable_files: list[str] = []
    warnings: list[str] = []
    root_entries: set[str] = set()
    ignored = ignored_subdirectories or []

    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            filename = member.filename.rstrip("/")
            if not filename:
                continue

            root_entry = filename.split("/", 1)[0]
            root_entries.add(root_entry)

            if filename == "redcap":
                continue
            if filename in EXPECTED_ZIP_ROOT_FILES:
                continue
            if not filename.startswith("redcap/"):
                warnings.append(
                    f"Ignored unexpected root-level ZIP entry: {filename}"
                )
                continue
            if member.is_dir():
                rel_dir = filename.removeprefix("redcap/").rstrip("/")
                if rel_dir:
                    if is_ignored_relpath(rel_dir, ignored):
                        continue
                    register_parent_dirs(rel_dir, dir_paths)
                    dir_paths.add(rel_dir)
                continue

            rel_path = filename.removeprefix("redcap/")
            if not rel_path:
                continue
            if is_ignored_relpath(rel_path, ignored):
                continue
            register_parent_dirs(rel_path, dir_paths)
            try:
                file_hashes[rel_path] = sha256_zip_member(archive, member)
                file_paths.add(rel_path)
            except OSError:
                unreadable_files.append(rel_path)

    if "redcap" not in root_entries:
        raise ValueError("Reference ZIP does not contain the required redcap/ root folder.")

    for marker in MARKER_FILES:
        if marker not in file_paths:
            raise ValueError(
                f"Reference ZIP is missing required REDCap marker under redcap/: {marker}"
            )

    return (
        TreeSnapshot(
            file_hashes=file_hashes,
            file_paths=file_paths,
            dir_paths=dir_paths,
            symlinks=[],
            unreadable_files=unreadable_files,
        ),
        sorted(set(warnings)),
    )


def find_ignored_version_dirs(target_root: Path, parsed_version: str) -> set[str]:
    if not parsed_version:
        return set()

    ignored: set[str] = set()
    for child in target_root.iterdir():
        if not child.is_dir():
            continue
        match = VERSIONED_DIR_RE.match(child.name)
        if match and match.group("version") != parsed_version:
            ignored.add(child.name)
    return ignored


def snapshot_tree(
    root: Path,
    ignored_top_level_dirs: set[str] | None = None,
    ignored_subdirectories: list[str] | None = None,
) -> TreeSnapshot:
    ignored = ignored_top_level_dirs or set()
    ignored_subdirs = ignored_subdirectories or []
    file_hashes: dict[str, str] = {}
    file_paths: set[str] = set()
    dir_paths: set[str] = set()
    symlinks: list[str] = []
    unreadable_files: list[str] = []

    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        rel_current = current_path.relative_to(root)
        if rel_current.parts:
            dir_path = rel_current.as_posix()
            if is_ignored_relpath(dir_path, ignored_subdirs):
                dirnames[:] = []
                filenames[:] = []
                continue
            dir_paths.add(dir_path)
            if rel_current.parts[0] in ignored:
                dirnames[:] = []
                filenames[:] = []
                continue

        dirnames[:] = sorted(
            d
            for d in dirnames
            if not should_ignore_top_level(rel_current, d, ignored)
            and not should_ignore_subdirectory(rel_current, d, ignored_subdirs)
        )
        filenames.sort()

        for dirname in dirnames:
            candidate = current_path / dirname
            if candidate.is_symlink():
                symlinks.append((rel_current / dirname).as_posix())

        for filename in filenames:
            file_path = current_path / filename
            rel_path = (rel_current / filename).as_posix() if rel_current.parts else filename

            if file_path.is_symlink():
                symlinks.append(rel_path)
                continue
            if is_ignored_relpath(rel_path, ignored_subdirs):
                continue
            if not file_path.is_file():
                continue
            try:
                file_hashes[rel_path] = sha256_file(file_path)
                file_paths.add(rel_path)
            except OSError:
                unreadable_files.append(rel_path)

    return TreeSnapshot(
        file_hashes=file_hashes,
        file_paths=file_paths,
        dir_paths=dir_paths,
        symlinks=symlinks,
        unreadable_files=unreadable_files,
    )


def should_ignore_top_level(rel_current: Path, dirname: str, ignored: set[str]) -> bool:
    return not rel_current.parts and dirname in ignored


def should_ignore_subdirectory(
    rel_current: Path,
    dirname: str,
    ignored_subdirectories: list[str],
) -> bool:
    if not ignored_subdirectories:
        return False
    candidate = (rel_current / dirname).as_posix() if rel_current.parts else dirname
    return is_ignored_relpath(candidate, ignored_subdirectories)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_zip_member(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(member, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register_parent_dirs(path: str, dir_paths: set[str]) -> None:
    parent = Path(path).parent
    while str(parent) not in {"", "."}:
        dir_paths.add(parent.as_posix())
        parent = parent.parent


def is_ignored_relpath(path: str, ignored_subdirectories: list[str]) -> bool:
    for ignored in ignored_subdirectories:
        if path == ignored or path.startswith(f"{ignored}/"):
            return True
    return False


def summarize_special_extras(
    reference: TreeSnapshot,
    target: TreeSnapshot,
    suppressed_files: set[str] | None = None,
) -> dict[str, SpecialDirectoryReport]:
    reports: dict[str, SpecialDirectoryReport] = {
        name: SpecialDirectoryReport(name=name)
        for name in SPECIAL_DIRS
    }

    extra_entries = set(target.all_paths - reference.all_paths)
    if suppressed_files:
        extra_entries -= suppressed_files
        extra_entries = prune_empty_extra_dirs(extra_entries, target.dir_paths)

    extra_entries = sorted(extra_entries)

    for entry in extra_entries:
        top_level = top_level_component(entry)
        if top_level not in reports:
            continue
        report = reports[top_level]
        report.extra_entry_count += 1

        if top_level == "modules":
            module_dir = first_child_under(entry, "modules")
            if module_dir and "/" not in module_dir and module_dir not in report.extra_module_dirs:
                report.extra_module_dirs.append(module_dir)
        elif top_level == "hooks":
            report.extra_hook_entries.append(entry)

    for report in reports.values():
        report.extra_module_dirs.sort()
        report.extra_hook_entries.sort()

    return reports


def prune_empty_extra_dirs(extra_entries: set[str], target_dirs: set[str]) -> set[str]:
    pruned = set(extra_entries)

    changed = True
    while changed:
        changed = False
        for entry in sorted(pruned, key=lambda value: value.count("/"), reverse=True):
            if entry not in target_dirs:
                continue
            prefix = f"{entry}/"
            if any(candidate.startswith(prefix) for candidate in pruned):
                continue
            pruned.remove(entry)
            changed = True

    return pruned


def top_level_component(path: str) -> str:
    return path.split("/", 1)[0]


def first_child_under(path: str, root_name: str) -> str:
    if not path.startswith(f"{root_name}/"):
        return ""
    parts = path.split("/")
    return parts[1] if len(parts) > 1 else ""
