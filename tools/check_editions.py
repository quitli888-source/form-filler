"""Run each edition's suite in an isolated interpreter, then check shipped ZIPs."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import zipfile

from manage_packages import EDITIONS, selected_editions, check_archive


def run_edition_tests(repo_root, edition):
    # Do not import either edition here. Same-named modules in two installed
    # skills must never share sys.modules or a pytest collection session.
    directory = Path(repo_root) / "skills" / EDITIONS[edition]
    result = subprocess.run([sys.executable, "-X", "utf8", "-m", "pytest", "tests", "-q"],
                            cwd=directory, check=False)
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description="Isolated edition tests and source/ZIP verification")
    parser.add_argument("--edition", choices=("all", *EDITIONS), default="all")
    parser.add_argument("--skip-packages", action="store_true", help="Run tests before rebuilding updated ZIPs")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    failures = []
    for edition in selected_editions(args.edition):
        print("Testing " + EDITIONS[edition], flush=True)
        if run_edition_tests(args.root, edition):
            failures.append(edition + " tests")
        if not args.skip_packages:
            try:
                count = check_archive(args.root, edition)
                print(f"Package matches source: {EDITIONS[edition]} ({count} files)", flush=True)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                print("Package verification failed: " + str(exc), flush=True)
                failures.append(edition + " package")
    if failures:
        print("Failed: " + ", ".join(failures), flush=True)
        return 1
    print("Selected edition checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
