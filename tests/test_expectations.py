from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from mirbc.cli import parse_inputs
from mirbc.compare import compare_reference_zip_to_target, sha256_file
from mirbc.expectations import load_expectations_files, parse_expectations_file
from mirbc.report import render_report


MARKER_CONTENT = {
    "redcap_connect.php": "<?php echo 'connect';\n",
    "database.php": "<?php echo 'database';\n",
    "cron.php": "<?php echo 'cron';\n",
}


class ExpectationsParsingTests(unittest.TestCase):
    def test_parse_expectations_file_accepts_comments_and_normalizes_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            expectations_path = Path(tmpdir) / "expectations.txt"
            expectations_path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "",
                        r"modules\\custom\\config.php = " + ("A" * 64),
                        "hooks/test.php = " + ("b" * 64),
                    ]
                ),
                encoding="utf-8",
            )

            expectations, warnings = parse_expectations_file(expectations_path)

            self.assertEqual(
                expectations,
                {
                    "modules/custom/config.php": "a" * 64,
                    "hooks/test.php": "b" * 64,
                },
            )
            self.assertEqual(warnings, [])

    def test_parse_expectations_file_reports_invalid_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            expectations_path = Path(tmpdir) / "expectations.txt"
            expectations_path.write_text(
                "\n".join(
                    [
                        "bad line",
                        "/absolute/path.php = " + ("a" * 64),
                        "dup.php = " + ("b" * 64),
                        "dup.php = " + ("c" * 64),
                        "wrong-hash.php = xyz",
                    ]
                ),
                encoding="utf-8",
            )

            expectations, warnings = parse_expectations_file(expectations_path)

            self.assertEqual(expectations, {"dup.php": "b" * 64})
            self.assertEqual(len(warnings), 4)
            self.assertTrue(any("expected 'path = sha256hex'" in warning for warning in warnings))
            self.assertTrue(any("path must be relative" in warning for warning in warnings))
            self.assertTrue(any("duplicate path 'dup.php'" in warning for warning in warnings))
            self.assertTrue(any("64-character SHA-256" in warning for warning in warnings))

    def test_load_expectations_files_merges_unique_entries_and_ignores_same_hash_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "one.txt"
            second = root / "two.txt"
            first.write_text(
                "\n".join(
                    [
                        "database.php = " + ("a" * 64),
                        "cron.php = " + ("b" * 64),
                    ]
                ),
                encoding="utf-8",
            )
            second.write_text(
                "\n".join(
                    [
                        "database.php = " + ("a" * 64),
                        "hooks/test.php = " + ("c" * 64),
                    ]
                ),
                encoding="utf-8",
            )

            expectations, warnings, origins = load_expectations_files([first, second])

            self.assertEqual(
                expectations,
                {
                    "database.php": "a" * 64,
                    "cron.php": "b" * 64,
                    "hooks/test.php": "c" * 64,
                },
            )
            self.assertEqual(warnings, [])
            self.assertEqual(origins["database.php"], str(first))

    def test_load_expectations_files_rejects_conflicting_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "one.txt"
            second = root / "two.txt"
            first.write_text("database.php = " + ("a" * 64) + "\n", encoding="utf-8")
            second.write_text("database.php = " + ("b" * 64) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Conflicting expectation hashes for database.php"):
                load_expectations_files([first, second])


class ExpectationsComparisonTests(unittest.TestCase):
    def test_matching_expectation_suppresses_different_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_zip = build_reference_zip(root)
            target_root = build_target_root(root)

            modified_path = target_root / "database.php"
            modified_path.write_text("changed target\n", encoding="utf-8")
            expectations_path = root / "expectations.txt"
            expectations_path.write_text(
                f"database.php = {sha256_file(modified_path)}\n",
                encoding="utf-8",
            )

            result = compare_reference_zip_to_target(
                reference_zip=reference_zip,
                target_root=target_root,
                expectations_files=[expectations_path],
            )

            self.assertEqual(result.different_files, [])
            self.assertEqual(result.matched_expectations, ["database.php"])
            self.assertEqual(result.matching_count, len(MARKER_CONTENT))
            self.assertEqual(result.warnings, [])

    def test_matching_expectation_suppresses_special_extra_file_and_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_zip = build_reference_zip(root)
            target_root = build_target_root(root)

            extra_path = target_root / "modules" / "custom" / "override.php"
            extra_path.parent.mkdir(parents=True, exist_ok=True)
            extra_path.write_text("extra module\n", encoding="utf-8")
            expectations_path = root / "expectations.txt"
            expectations_path.write_text(
                f"modules/custom/override.php = {sha256_file(extra_path)}\n",
                encoding="utf-8",
            )

            result = compare_reference_zip_to_target(
                reference_zip=reference_zip,
                target_root=target_root,
                expectations_files=[expectations_path],
            )

            self.assertEqual(result.extra_files, [])
            self.assertEqual(result.matched_expectations, ["modules/custom/override.php"])
            self.assertEqual(result.special_dirs["modules"].extra_entry_count, 0)
            self.assertEqual(result.special_dirs["modules"].extra_module_dirs, [])

    def test_nonmatching_or_unused_expectations_warn_without_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_zip = build_reference_zip(root)
            target_root = build_target_root(root)

            changed_path = target_root / "database.php"
            changed_path.write_text("changed target\n", encoding="utf-8")
            expectations_path = root / "expectations.txt"
            expectations_path.write_text(
                "\n".join(
                    [
                        "database.php = " + ("0" * 64),
                        "missing.php = " + ("1" * 64),
                    ]
                ),
                encoding="utf-8",
            )

            result = compare_reference_zip_to_target(
                reference_zip=reference_zip,
                target_root=target_root,
                expectations_files=[expectations_path],
            )

            self.assertEqual(result.matched_expectations, [])
            self.assertEqual(result.different_files, ["database.php"])
            self.assertIn(
                "Expectation hash did not match target file: database.php",
                result.warnings,
            )
            self.assertIn(
                "Unused expectation for missing target file: missing.php",
                result.warnings,
            )

    def test_expectation_does_not_suppress_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_zip = build_reference_zip(root)
            target_root = build_target_root(root)

            missing_path = target_root / "cron.php"
            missing_path.unlink()
            expectations_path = root / "expectations.txt"
            expectations_path.write_text(
                "cron.php = " + ("f" * 64) + "\n",
                encoding="utf-8",
            )

            result = compare_reference_zip_to_target(
                reference_zip=reference_zip,
                target_root=target_root,
                expectations_files=[expectations_path],
            )

            self.assertEqual(result.missing_files, ["cron.php"])
            self.assertEqual(result.matched_expectations, [])
            self.assertIn(
                "Unused expectation for missing target file: cron.php",
                result.warnings,
            )

    def test_multiple_expectations_files_are_merged_in_cli_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_zip = build_reference_zip(root)
            target_root = build_target_root(root)

            modified_path = target_root / "database.php"
            modified_path.write_text("changed target\n", encoding="utf-8")
            extra_path = target_root / "modules" / "custom" / "override.php"
            extra_path.parent.mkdir(parents=True, exist_ok=True)
            extra_path.write_text("extra module\n", encoding="utf-8")

            first = root / "base.txt"
            second = root / "local.txt"
            first.write_text(
                f"database.php = {sha256_file(modified_path)}\n",
                encoding="utf-8",
            )
            second.write_text(
                f"modules/custom/override.php = {sha256_file(extra_path)}\n",
                encoding="utf-8",
            )

            result = compare_reference_zip_to_target(
                reference_zip=reference_zip,
                target_root=target_root,
                expectations_files=[first, second],
            )

            self.assertEqual(
                result.matched_expectations,
                ["database.php", "modules/custom/override.php"],
            )
            self.assertEqual(result.different_files, [])
            self.assertEqual(result.extra_files, [])
            self.assertEqual(result.special_dirs["modules"].extra_entry_count, 0)


class ExpectationsCliTests(unittest.TestCase):
    def test_parse_inputs_accepts_multiple_expectations_files_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_zip = build_reference_zip(root)
            target_root = build_target_root(root)
            first = root / "one.txt"
            second = root / "two.txt"
            first.write_text("", encoding="utf-8")
            second.write_text("", encoding="utf-8")

            inputs = parse_inputs(
                [
                    "-e",
                    str(first),
                    "-e",
                    str(second),
                    "-e",
                    str(first),
                    str(reference_zip),
                    str(target_root),
                ]
            )

            assert inputs is not None
            self.assertEqual(inputs.expectations_files, [first.resolve(), second.resolve()])

    def test_parse_inputs_rejects_missing_expectations_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_zip = build_reference_zip(root)
            target_root = build_target_root(root)

            with self.assertRaisesRegex(ValueError, "Expectations file not found"):
                parse_inputs(
                    [
                        "-e",
                        str(root / "missing.txt"),
                        str(reference_zip),
                        str(target_root),
                    ]
                )


class ExpectationsReportTests(unittest.TestCase):
    def test_render_report_lists_expectations_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference_zip = build_reference_zip(root)
            target_root = build_target_root(root)
            first = root / "one.txt"
            second = root / "two.txt"
            first.write_text("", encoding="utf-8")
            second.write_text("", encoding="utf-8")

            result = compare_reference_zip_to_target(
                reference_zip=reference_zip,
                target_root=target_root,
                expectations_files=[first, second],
            )

            report = render_report(result)

            self.assertIn("Expectations Files", report)
            self.assertIn(f"- {first.resolve()}", report)
            self.assertIn(f"- {second.resolve()}", report)


def build_reference_zip(root: Path) -> Path:
    reference_zip = root / "redcap15.7.4.zip"
    with zipfile.ZipFile(reference_zip, "w") as archive:
        archive.writestr("redcap/", "")
        for name, content in MARKER_CONTENT.items():
            archive.writestr(f"redcap/{name}", content)
    return reference_zip


def build_target_root(root: Path) -> Path:
    target_root = root / "target"
    target_root.mkdir()
    for name, content in MARKER_CONTENT.items():
        (target_root / name).write_text(content, encoding="utf-8")
    return target_root


if __name__ == "__main__":
    unittest.main()
