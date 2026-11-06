"""Private package boundaries; no live networking."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from edition import EDITION
from privacy import PrivacyError, endpoint_url, local_data_dir
from model_adapter import get_adapter

@pytest.mark.parametrize("url", ["https://provider.example/v1", "https://127.0.0.1/v1"])
def test_no_cloud_switch_exists(url, monkeypatch):
    monkeypatch.setenv("FORM_FILLER_CLOUD_API_KEY", "SYNTHETIC_KEY")
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    assert EDITION == "private"
    assert get_adapter().is_live() is False
    with patch("openai.OpenAI") as client:
        with pytest.raises(PrivacyError):
            endpoint_url(url, local=False)
        client.assert_not_called()

def test_cloud_senders_are_not_shipped():
    root=Path(__file__).resolve().parents[1]
    assert not (root/"scripts/cloud_draft.py").exists()
    assert not (root/"scripts/standard_workflow.py").exists()
    assert "FormFillerPrivate" in str(local_data_dir()) or "form-filler-private" in str(local_data_dir())
