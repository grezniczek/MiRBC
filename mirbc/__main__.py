from __future__ import annotations

import sys

from .cli import parse_inputs, print_error
from .compare import compare_reference_zip_to_target
from .generate import render_expectations
from .report import render_report
from .types import CompareInputs, CreateExpectationsInputs


def main() -> int:
    try:
        inputs = parse_inputs(sys.argv[1:])
        if inputs is None:
            return 0
        if isinstance(inputs, CompareInputs):
            result = compare_reference_zip_to_target(
                reference_zip=inputs.reference_zip,
                target_root=inputs.target_root,
                ignored_subdirectories=inputs.ignored_subdirectories,
                expectations_files=inputs.expectations_files,
                skip_modules=inputs.skip_modules,
                skip_hooks=inputs.skip_hooks,
            )
        elif isinstance(inputs, CreateExpectationsInputs):
            print(render_expectations(inputs), end="")
            return 0
        else:
            raise ValueError("Unsupported input mode.")
    except (EOFError, KeyboardInterrupt):
        return print_error("Input cancelled.")
    except ValueError as exc:
        return print_error(str(exc))
    except OSError as exc:
        return print_error(str(exc))

    prefix = "\n\n" if inputs.interactive else ""
    print(f"{prefix}{render_report(result)}", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
