"""Profile replacement is explicit; no real personal data."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from privacy import PrivacyError
from profile_store import save_section


def test_existing_section_is_not_silently_replaced(tmp_path):
    destination = tmp_path / "personal.yaml.dpapi"
    destination.write_bytes(b"existing-encrypted-profile")
    with patch("profile_store._dpapi") as encrypt:
        with pytest.raises(PrivacyError):
            save_section(tmp_path, "personal", {"name": "Synthetic"})
        encrypt.assert_not_called()
    assert destination.read_bytes() == b"existing-encrypted-profile"


def test_plaintext_conflict_is_rejected_before_encryption(tmp_path):
    original = tmp_path / "personal.yaml"
    original.write_text("name: Synthetic", encoding="utf-8")
    with patch("profile_store._dpapi") as encrypt:
        with pytest.raises(PrivacyError):
            save_section(tmp_path, "personal", {"name": "Synthetic"})
        encrypt.assert_not_called()
    assert not (tmp_path / "personal.yaml.dpapi").exists()


def test_explicit_section_replacement_is_possible(tmp_path):
    destination = tmp_path / "personal.yaml.dpapi"
    destination.write_bytes(b"old-ciphertext")
    with patch("profile_store._dpapi", return_value=b"new-ciphertext"):
        save_section(tmp_path, "personal", {"name": "Synthetic"}, replace=True)
    assert destination.read_bytes() == b"new-ciphertext"
