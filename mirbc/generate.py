from __future__ import annotations

import os
from pathlib import Path

from .compare import sha256_file
from .types import CreateExpectationsInputs


def render_expectations(inputs: CreateExpectationsInputs) -> str:
    entries = collect_expectation_entries(inputs)
    lines = [f"{rel_path} = {digest}" for rel_path, digest in entries]
    return "\n".join(lines) + ("\n" if lines else "")


def collect_expectation_entries(
    inputs: CreateExpectationsInputs,
) -> list[tuple[str, str]]:
    collected: dict[str, str] = {}

    for path in inputs.selected_paths:
        if path.is_symlink():
            continue
        if path.is_file():
            rel_path = path.relative_to(inputs.root).as_posix()
            collected[rel_path] = sha256_file(path)
            continue
        if path.is_dir():
            for file_path in iter_files_under(path):
                if file_path.is_symlink():
                    continue
                rel_path = file_path.relative_to(inputs.root).as_posix()
                collected[rel_path] = sha256_file(file_path)

    return sorted(collected.items())


def iter_files_under(root: Path) -> list[Path]:
    results: list[Path] = []
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirnames[:] = sorted(dirnames)
        filenames.sort()
        for filename in filenames:
            file_path = current_path / filename
            if file_path.is_file():
                results.append(file_path)
    return results
