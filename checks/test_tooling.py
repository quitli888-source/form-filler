"""Root-level checks deliberately import no edition modules or legacy tests."""
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import manage_packages as packages
import check_editions


def source_tree(tmp_path, edition="private"):
    root = tmp_path / "repo"
    skill = root / "skills" / packages.EDITIONS[edition]
    for name, content in {
        "SKILL.md": '---\nname: form-filler-private\nmetadata:\n  version: "8.0.1"\n---\n',
        "LICENSE": "Synthetic license\n", "scripts/edition.py": 'EDITION = "private"\n',
        "scripts/fill_docx.py": "# Synthetic test-only source\r\n",
        ".env.local.example": "# No real secret\n", "profiles/.gitkeep": "",
    }.items():
        target = skill / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode())
    return root, skill


def test_packaging_is_deterministic_and_excludes_runtime_data(tmp_path):
    root, skill = source_tree(tmp_path)
    for name in ("profiles/personal.yaml", ".env.local", "scripts/__pycache__/private.pyc",
                 "tests/_tmp_case/profile.py", "tests/fixtures/private.json", "outputs/person.docx"):
        path = skill / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SYNTHETIC_SECRET", encoding="utf-8")
    archive = packages.build_archive(root, "private")
    packages.write_checksums(root)
    initial = archive.read_bytes()
    os.utime(skill / "scripts/fill_docx.py", (1_900_000_000, 1_900_000_000))
    packages.build_archive(root, "private")
    assert archive.read_bytes() == initial
    assert packages.check_archive(root, "private") == 6
    with zipfile.ZipFile(archive) as package:
        assert not any(b"SYNTHETIC_SECRET" in package.read(name) for name in package.namelist())
        assert package.read("form-filler-private/scripts/fill_docx.py").endswith(b"\n")
        assert b"\r\n" not in package.read("form-filler-private/scripts/fill_docx.py")


@pytest.mark.parametrize("tamper", ["extra", "changed", "missing"])
def test_distribution_changes_are_detected(tmp_path, tamper):
    root, _ = source_tree(tmp_path)
    archive = packages.build_archive(root, "private")
    packages.write_checksums(root)
    with zipfile.ZipFile(archive) as package:
        entries = {name: package.read(name) for name in package.namelist()}
    if tamper == "extra":
        entries["form-filler-private/profiles/personal.yaml"] = b"SYNTHETIC_SECRET"
    elif tamper == "changed":
        entries["form-filler-private/scripts/fill_docx.py"] = b"modified source\n"
    else:
        del entries["form-filler-private/LICENSE"]
    with zipfile.ZipFile(archive, "w") as package:
        for name, content in entries.items():
            package.writestr(name, content)
    with pytest.raises(packages.PackageError):
        packages.check_archive(root, "private")


def test_private_package_refuses_cloud_sender(tmp_path):
    root, skill = source_tree(tmp_path)
    (skill / "scripts/cloud_draft.py").write_text("# Not allowed in private\n")
    with pytest.raises(packages.PackageError):
        packages.build_archive(root, "private")


def test_stale_source_is_detected(tmp_path):
    root, skill = source_tree(tmp_path)
    packages.build_archive(root, "private")
    packages.write_checksums(root)
    (skill / "scripts/fill_docx.py").write_text("# A new implementation\n")
    with pytest.raises(packages.PackageError):
        packages.check_archive(root, "private")


def test_edition_test_processes_use_separate_working_directories(tmp_path, monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(check_editions.subprocess, "run", run)
    for edition in packages.EDITIONS:
        assert check_editions.run_edition_tests(tmp_path, edition) == 0
    assert len(calls) == 2
    assert calls[0][1]["cwd"] != calls[1][1]["cwd"]
    assert all(call[0][:4] == [sys.executable, "-X", "utf8", "-m"] for call in calls)
    assert all(call[0][-3:] == ["pytest", "tests", "-q"] for call in calls)


def test_edition_failure_sets_nonzero_status(tmp_path, monkeypatch):
    monkeypatch.setattr(check_editions, "run_edition_tests", lambda root, edition: 1 if edition == "standard" else 0)
    assert check_editions.main(["--root", str(tmp_path), "--skip-packages"]) == 1
