"""Synthetic SDK logging regression, with no live model request."""
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from model_adapter import get_adapter
from privacy import scoped_log_guard


def test_sdk_debug_logging_cannot_echo_raw_profile_values(caplog, monkeypatch):
    monkeypatch.setenv("OPENAI_LOG", "debug")
    adapter = get_adapter("local-model", base_url="http://127.0.0.1:11434/v1", max_retries=0)
    previous = logging.getLogRecordFactory()
    secret = "SYNTHETIC_PRIVATE_PROMPT_VALUE"
    def reply(transport, request):
        return httpx.Response(200, json={"id": "local", "choices": [{"message": {"content": "OK"}}]})
    with caplog.at_level(logging.DEBUG, logger="openai"), patch.object(httpx.HTTPTransport, "handle_request", reply):
        assert adapter.reflect("姓名", secret, {}) == "OK"
    assert any(record.name.startswith("openai") for record in caplog.records)
    assert secret not in caplog.text
    assert all(secret not in repr(record.args) for record in caplog.records)
    assert logging.getLogRecordFactory() is previous
    adapter._client.close()


def test_diagnostic_scope_restores_factory_on_error_and_preserves_other_logs(caplog):
    previous = logging.getLogRecordFactory()
    @scoped_log_guard
    def call():
        logging.getLogger("openai.unusual_child").warning("SYNTHETIC_SECRET")
        logging.getLogger("application").warning("unrelated diagnostic")
        raise ValueError("synthetic")
    with pytest.raises(ValueError), caplog.at_level(logging.WARNING):
        call()
    assert "SYNTHETIC_SECRET" not in caplog.text
    assert "unrelated diagnostic" in caplog.text
    assert logging.getLogRecordFactory() is previous


def test_external_logging_reconfiguration_is_not_lost():
    previous = logging.getLogRecordFactory()
    def external(*args, **kwargs):
        return previous(*args, **kwargs)
    @scoped_log_guard
    def call():
        logging.setLogRecordFactory(external)
    try:
        call()
        assert logging.getLogRecordFactory() is external
    finally:
        logging.setLogRecordFactory(previous)
