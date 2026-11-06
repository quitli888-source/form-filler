"""Windows user-bound encrypted profiles; no plaintext persistence fallback."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from pathlib import Path

import yaml
from privacy import PrivacyError, local_data_dir, private_write, protect_inputs, utf8_console

SECTIONS = {"personal", "contact", "education", "awards", "work_experience",
            "publications", "skills", "league", "bank"}


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise PrivacyError("Encrypted persistence requires Windows DPAPI; use an OS-encrypted local store on other systems.")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(data, max(1, len(data)))
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        # No LOCAL_MACHINE flag: only this Windows user's context can decrypt normally.
        args = (ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    fn.restype = wintypes.BOOL
    try:
        if not fn(*args):
            raise PrivacyError("Windows profile encryption/decryption failed; no plaintext fallback.")
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.memset(buf, 0, len(buf))
        if target.pbData:
            ctypes.memset(target.pbData, 0, target.cbData)
            kernel.LocalFree(target.pbData)


def save_section(directory, section: str, data: dict, *, replace: bool = False) -> None:
    if section not in SECTIONS or not isinstance(data, dict):
        raise PrivacyError("Unknown profile section or invalid mapping.")
    directory = Path(directory)
    destination = directory / (section + ".yaml.dpapi")
    if destination.exists() and not replace:
        raise PrivacyError("Section already exists; replacement requires an explicit choice.")
    if any((directory / (section + suffix)).exists() for suffix in (".yaml", ".yml")):
        raise PrivacyError("Plaintext section already exists here; choose a separate encrypted directory.")
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    encrypted = _dpapi(raw, decrypt=False)
    private_write(destination, encrypted)


def read_section(path) -> dict:
    data = json.loads(_dpapi(Path(path).read_bytes(), decrypt=True).decode("utf-8"))
    if not isinstance(data, dict):
        raise PrivacyError("Profile section must be a mapping.")
    return data


def load_sections(directory, *, allow_plain: bool = True) -> dict:
    directory = Path(directory)
    profiles = {}
    # Explicit legacy directory remains readable, but is never silently migrated.
    for section in sorted(SECTIONS):
        encrypted = directory / (section + ".yaml.dpapi")
        plain_files = [p for p in (directory / (section + ".yaml"), directory / (section + ".yml")) if p.exists()]
        if plain_files and not allow_plain:
            raise PrivacyError("Plaintext profiles require an explicitly selected legacy directory.")
        if len(plain_files) + int(encrypted.exists()) > 1:
            raise PrivacyError("Conflicting profile formats; select one local copy explicitly.")
        if encrypted.exists():
            profiles[section] = read_section(encrypted)
        elif plain_files:
            data = yaml.safe_load(plain_files[0].read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                raise PrivacyError("Profile section must be a mapping.")
            profiles[section] = data
    return profiles


def main():
    parser = argparse.ArgumentParser(description="Import explicitly retained profile data into Windows DPAPI storage")
    parser.add_argument("--source", required=True, help="Local YAML mapping containing ONLY the section to retain")
    parser.add_argument("--section", required=True, choices=sorted(SECTIONS))
    parser.add_argument("--profile-dir", default=str(local_data_dir() / "profiles"))
    parser.add_argument("--replace-section", action="store_true", help="Explicitly replace this entire stored section; no automatic merge")
    args = parser.parse_args()
    try:
        destination = Path(args.profile_dir) / (args.section + ".yaml.dpapi")
        protect_inputs([destination], [args.source])
        data = yaml.safe_load(Path(args.source).read_text(encoding="utf-8"))
        save_section(args.profile_dir, args.section, data, replace=args.replace_section)
        print("Section encrypted locally. Source file was preserved; review and remove it yourself if appropriate.")
    except Exception:
        print("Profile import failed; details withheld. No plaintext fallback.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    utf8_console()
    sys.exit(main())
