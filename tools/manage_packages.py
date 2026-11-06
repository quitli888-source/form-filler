"""Build/check deterministic distributable skills from an explicit source policy.

Runtime profiles, credentials, caches and temporary outputs are never selected.
This is a packaging allowlist, not a semantic proof that source text has no PII.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import tempfile
import zipfile

EDITIONS = {"private": "form-filler-private", "standard": "form-filler-standard"}
ROOT_FILES = {".env.local.example", ".gitignore", "LICENSE", "README.md", "SKILL.md",
              "requirements.txt", "requirements-model.txt", "requirements-dev.txt"}
EXACT_FILES = {"profiles/.gitkeep", "templates/audit_table.md", "tests/fixtures/README.md",
               "tests/fixtures/custom_fixtures.json", "tests/fixtures/simple.docx",
               "tests/fixtures/merged_cell.docx", "tests/fixtures/multi_match.docx"}
STANDARD_EXAMPLES = {"examples/case.json", "examples/template.docx"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".example"}


class PackageError(ValueError):
    pass


def selected_editions(selection="all"):
    return list(EDITIONS) if selection == "all" else [selection]


def _ignored(parts):
    return any(p in {"__pycache__", ".pytest_cache", ".git", ".venv"} or p.startswith("_tmp")
               for p in parts)


def _allowed(relative, edition):
    name = relative.as_posix()
    if name in ROOT_FILES or name in EXACT_FILES:
        return True
    if edition == "standard" and name in STANDARD_EXAMPLES:
        return True
    if relative.parts[0] in {"scripts", "evaluation", "tests"} and relative.suffix == ".py":
        return True
    return relative.parts[0] == "references" and relative.suffix == ".md"


def _safe_source(path, source):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise PackageError("Symbolic links are not distributable source.")
    if not path.resolve().is_relative_to(source.resolve()):
        raise PackageError("Source file escaped the selected edition directory.")


def source_entries(repo_root, edition):
    source = Path(repo_root) / "skills" / EDITIONS[edition]
    if not source.is_dir() or source.is_symlink():
        raise PackageError("Selected edition source directory is missing or linked.")
    if edition == "private" and any((source / "scripts" / name).exists()
                                     for name in ("cloud_draft.py", "standard_workflow.py")):
        raise PackageError("Private edition must not contain a cloud sender/workflow.")
    entries = {}
    for parent, directories, filenames in os.walk(source, followlinks=False):
        parent = Path(parent)
        directories[:] = [d for d in directories if not _ignored((d,))]
        for name in filenames:
            path = parent / name
            relative = path.relative_to(source)
            if _ignored(relative.parts) or not _allowed(relative, edition):
                continue
            _safe_source(path, source)
            data = path.read_bytes()
            if path.suffix in TEXT_SUFFIXES or path.name in {".gitignore", ".gitkeep", "LICENSE"}:
                # Git on Windows may check out CRLF. Normalize archive text so
                # source/ZIP checks do not change merely because of checkout OS.
                data = data.replace(b"\r\n", b"\n")
            entries[EDITIONS[edition] + "/" + relative.as_posix()] = data
    required = {EDITIONS[edition] + "/" + name for name in
                ("SKILL.md", "LICENSE", "scripts/edition.py", "scripts/fill_docx.py")}
    if not required <= set(entries):
        raise PackageError("Required skill source files are missing.")
    return dict(sorted(entries.items()))


def archive_path(repo_root, edition):
    skill = Path(repo_root) / "skills" / EDITIONS[edition] / "SKILL.md"
    match = re.search(r'^\s+version:\s*[\"\']?(\d+)(?:\.\d+)*[\"\']?\s*$',
                      skill.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise PackageError("Skill metadata must declare a numeric version.")
    return Path(repo_root) / "dist" / (EDITIONS[edition] + "-v" + match.group(1) + ".zip")


def _safe_output(path):
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise PackageError("Refusing a symbolic-link distribution destination.")


def build_archive(repo_root, edition):
    entries = source_entries(repo_root, edition)
    output = archive_path(repo_root, edition)
    _safe_output(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".package-", dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in entries.items():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data, compresslevel=9)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output


def write_checksums(repo_root):
    root = Path(repo_root)
    rows = []
    for edition in EDITIONS:
        if not (root / "skills" / EDITIONS[edition] / "SKILL.md").exists():
            continue
        archive = archive_path(root, edition)
        if archive.is_file():
            rows.append(hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name)
    target = root / "dist" / "SHA256SUMS.txt"
    _safe_output(target)
    target.write_text("\n".join(sorted(rows)) + "\n", encoding="utf-8")


def check_archive(repo_root, edition):
    expected = source_entries(repo_root, edition)
    archive = archive_path(repo_root, edition)
    if not archive.is_file():
        raise PackageError("Distribution archive is missing; run the build command.")
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise PackageError("ZIP inventory differs from controlled source selection.")
        if package.testzip() is not None:
            raise PackageError("Distribution ZIP failed its CRC check.")
        for name, data in expected.items():
            info = package.getinfo(name)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise PackageError("Distribution ZIP contains a symbolic link.")
            if package.read(name) != data:
                raise PackageError("ZIP content is stale or modified: " + name)
    checksum_file = Path(repo_root) / "dist" / "SHA256SUMS.txt"
    checksums = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+\.zip)", line)
        if not match or match.group(2) in checksums:
            raise PackageError("Invalid or duplicate distribution checksum entry.")
        checksums[match.group(2)] = match.group(1)
    if checksums.get(archive.name) != hashlib.sha256(archive.read_bytes()).hexdigest():
        raise PackageError("Distribution SHA-256 does not match its checksum entry.")
    return len(expected)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build/check deterministic, privacy-filtered skill ZIPs")
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--edition", choices=("all", *EDITIONS), default="all")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            for edition in selected_editions(args.edition):
                output = build_archive(args.root, edition)
                print("Built " + output.name)
            write_checksums(args.root)
        for edition in selected_editions(args.edition):
            count = check_archive(args.root, edition)
            print(f"Checked {EDITIONS[edition]}: {count} controlled source files")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print("Package check failed: " + str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
