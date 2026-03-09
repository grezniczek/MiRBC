# MiRBC

MiRBC is the Minimal REDCap Baseline Comparator. It compares a deployed
REDCap installation against a matching reference REDCap ZIP by relative path
and SHA-256 hash.

Created jointly by Dr. Günther Rezniczek (design and prompting) and
Codex / GPT-5.4 (implementation).

This version is intentionally small:

- Python standard library only
- no downloads
- no dependency auto-installation
- no external scanners
- no writes into the scanned REDCap installation
- plain text CLI output only

## What It Needs

You must provide:

1. a full REDCap ZIP for the exact deployed version
2. a readable filesystem path to the deployed REDCap installation

The target path can be:

- a local path
- a read-only bind mount
- a mounted network share
- another mounted filesystem prepared outside the tool

## Usage

### Prerequisites

MiRBC uses only the Python standard library, so there are no runtime
dependencies beyond Python itself.

Required:

- Python 3.11 or newer

Check your Python version:

```bash
python3 --version
```

On some systems, `python` already points to Python 3.11+:

```bash
python --version
```

### Run Directly From the Repository

From the project root, run the tool as a Python module.

Show help and enter interactive prompts:

```bash
python3 -m mirbc
```

Run with both required inputs in either order:

```bash
python3 -m mirbc /path/to/redcap15.7.4.zip /path/to/redcap
python3 -m mirbc /path/to/redcap /path/to/redcap15.7.4.zip
python3 -m mirbc -i modules/custom -i temp/cache /path/to/redcap15.7.4.zip /path/to/redcap
```

What the arguments mean:

- the `.zip` path must point to the full REDCap reference ZIP for the exact
  deployed version
- the other path must point to the root of the deployed REDCap installation

MiRBC detects which argument is the ZIP by its `.zip` extension, so argument
order does not matter.

To ignore one or more subdirectories under the REDCap root, use `-i` or
`--ignore` multiple times. Ignore paths are relative to the detected target
root, not absolute filesystem paths.

Examples:

```bash
python3 -m mirbc -i modules/custom /path/to/redcap15.7.4.zip /path/to/redcap
python3 -m mirbc --ignore temp/cache --ignore hooks/archive /path/to/redcap15.7.4.zip /path/to/redcap
```

In interactive mode, MiRBC will repeatedly prompt for ignored subdirectories.
Press Enter on an empty prompt to finish the ignore list.

### Install as a Script Entrypoint

If you want a `mirbc` command on your shell path, install the project into a
virtual environment or user environment.

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the project:

```bash
python3 -m pip install .
```

Then run it as a script:

```bash
mirbc /path/to/redcap15.7.4.zip /path/to/redcap
```

To verify the entrypoint was installed:

```bash
mirbc --help
```

### Typical Workflow

1. Obtain the official REDCap ZIP for the exact deployed version.
2. Identify the deployed REDCap root on disk or on a read-only mount.
3. Run MiRBC with the ZIP path and the target root path.
4. Review the stdout report for:
   - different files
   - missing files
   - extra files
   - the `Ignored Subdirectories` section
   - summarized extras under `temp`, `modules`, `edocs`, and `hooks`
   - warnings about ignored unexpected ZIP root-level entries

## Report Contents

The report prints:

- reference ZIP path
- SHA-256 of the reference ZIP
- reference REDCap root as `ZIP:redcap/`
- detected target REDCap root
- parsed REDCap version when available
- ignored subdirectories requested by the user
- summary counts for matching, different, missing, and extra files
- detailed path lists for different, missing, and extra files
- warnings for ignored unexpected ZIP root-level entries

## Special Directory Handling

The comparator still checks reference-backed files under these top-level
directories:

- `temp`
- `modules`
- `edocs`
- `hooks`

Target-only extra content under those directories is summarized specially:

- `temp` and `edocs`: summary count only
- `modules`: summary count plus first-level extra subfolder names
- `hooks`: summary count plus full tree of extra entries

Those extras are excluded from the normal `Extra Files` section.

## Extra Versioned REDCap Folders

If the target root contains immediate child directories named like
`redcap_v15.7.4` and the version does not match the reference ZIP version,
they are:

- reported as `Extra versioned REDCap folders (not checked, removal recommended)`
- excluded from the comparison scan
- not counted as normal extras

## Notes

- The comparator streams file contents directly from the reference ZIP.
- The reference ZIP is expected to contain `redcap/` at its root.
- Root-level `Installation Instructions.txt` and `REDCap License.txt` are ignored.
- Any other unexpected root-level ZIP entries are ignored and reported as warnings.
- The target installation is read only.
- Symlinks are skipped and listed in the report if encountered.
