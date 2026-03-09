from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

EXPECTATION_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def parse_expectations_file(path: Path) -> tuple[dict[str, str], list[str]]:
    return parse_expectations_file_with_context(path)[:2]


def parse_expectations_file_with_context(
    path: Path,
) -> tuple[dict[str, str], list[str], dict[str, str]]:
    expectations: dict[str, str] = {}
    warnings: list[str] = []
    origins: dict[str, str] = {}
    path_label = str(path)

    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.count("=") != 1:
                warnings.append(
                    f"{path_label}: invalid expectation line {line_number}: expected 'path = sha256hex'."
                )
                continue

            raw_rel_path, raw_hash = (part.strip() for part in line.split("=", 1))
            try:
                rel_path = normalize_expectation_path(raw_rel_path)
            except ValueError as exc:
                warnings.append(
                    f"{path_label}: invalid expectation line {line_number}: {exc}"
                )
                continue

            if not raw_hash:
                warnings.append(
                    f"{path_label}: invalid expectation line {line_number}: hash cannot be empty."
                )
                continue
            if not EXPECTATION_HASH_RE.fullmatch(raw_hash):
                warnings.append(
                    f"{path_label}: invalid expectation line {line_number}: hash must be a 64-character SHA-256 hex digest."
                )
                continue
            if rel_path in expectations:
                warnings.append(
                    f"{path_label}: invalid expectation line {line_number}: duplicate path '{rel_path}'."
                )
                continue

            expectations[rel_path] = raw_hash.lower()
            origins[rel_path] = path_label

    return expectations, warnings, origins


def load_expectations_files(
    paths: list[Path],
) -> tuple[dict[str, str], list[str], dict[str, str]]:
    merged: dict[str, str] = {}
    warnings: list[str] = []
    origins: dict[str, str] = {}

    for path in paths:
        parsed, parsed_warnings, parsed_origins = parse_expectations_file_with_context(path)
        warnings.extend(parsed_warnings)
        for rel_path, expected_hash in parsed.items():
            if rel_path not in merged:
                merged[rel_path] = expected_hash
                origins[rel_path] = parsed_origins[rel_path]
                continue
            if merged[rel_path] == expected_hash:
                continue
            raise ValueError(
                "Conflicting expectation hashes for "
                f"{rel_path}: {origins[rel_path]} has {merged[rel_path]}, "
                f"but {parsed_origins[rel_path]} has {expected_hash}."
            )

    return merged, warnings, origins


def normalize_expectation_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        raise ValueError("path cannot be empty.")

    path = PurePosixPath(normalized)
    if path.is_absolute():
        raise ValueError(f"path must be relative: {value}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"path must be a clean relative path: {value}")

    return path.as_posix()
