"""Behavioral privacy tests; all identities and model replies are synthetic."""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from privacy import PrivacyError, endpoint_url, safe_audit, private_text
from model_adapter import get_adapter, OpenAICompatibleAdapter, _format_validation_feedback
from fill_docx import fill_docx, scan_docx_tables, scan_docx_introspect, print_audit, render_audit_table, write_profile_md
from profile_store import save_section, read_section, load_sections


@pytest.mark.parametrize("url", [
    "https://provider.example/v1", "http://192.168.1.3/v1", "http://0.0.0.0/v1",
    "http://127.0.0.2/v1", "http://localhost.evil.example/v1", "http://2130706433/v1",
    "http://127.0.0.1@provider.example/v1", "file:///secret", "http://[::ffff:127.0.0.1]/v1",
    "http://127.0.0.1/v1?token=secret", "http://user:secret@localhost/v1",
    "http://localhost/v1#fragment", "http://localhost/%2e%2e", "http://localhost/../v1",
    "http://localhost:bad/v1", "http://localhost /v1",
])
def test_local_endpoint_rejected_before_client(url):
    with patch("openai.OpenAI") as constructor:
        with pytest.raises(PrivacyError):
            OpenAICompatibleAdapter(base_url=url)
        constructor.assert_not_called()


@pytest.mark.parametrize("url,normalized", [
    ("http://localhost:11434/v1", "http://127.0.0.1:11434/v1"),
    ("http://[::1]:11434/v1", "http://[::1]:11434/v1"),
    ("http://127.0.0.1:11434/v1/", "http://127.0.0.1:11434/v1"),
])
def test_loopback_normalization(url, normalized):
    assert endpoint_url(url, local=True) == normalized


def test_ambient_cloud_configuration_does_not_enable_network(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "SYNTHETIC_CLOUD_SECRET")
    assert get_adapter().is_live() is False
    with pytest.raises(PrivacyError):
        get_adapter("local-model")
    adapter = get_adapter("local-model", base_url="http://localhost:11434/v1")
    assert adapter.api_key == "local-only"
    adapter._client.close()


def test_local_redirect_not_followed_and_environment_proxy_ignored(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example:8080")
    seen = []
    def reply(transport, request):
        seen.append(request)
        return httpx.Response(307, headers={"location": "https://provider.example/steal"},
                              json={"error": "SYNTHETIC_PRIVATE_ECHO"})
    adapter = get_adapter("local-model", base_url="http://localhost:11434/v1", max_retries=0)
    err = io.StringIO()
    with patch.object(httpx.HTTPTransport, "handle_request", reply), contextlib.redirect_stderr(err):
        assert adapter.reflect("姓名", "SYNTHETIC_PERSON", {}) == ""
    assert len(seen) == 1
    assert str(seen[0].url) == "http://127.0.0.1:11434/v1/chat/completions"
    assert not adapter._client._client._mounts  # no proxy mounts from environment
    assert "SYNTHETIC_PRIVATE_ECHO" not in err.getvalue()
    adapter._client.close()


def test_local_transport_pins_destination_even_after_sdk_mutation():
    adapter = get_adapter("local-model", base_url="http://127.0.0.1:11434/v1", max_retries=0)
    adapter._client.base_url = "https://provider.example/v1"
    with patch.object(httpx.HTTPTransport, "handle_request") as transport:
        assert adapter.reflect("姓名", "SYNTHETIC_PERSON", {}) == ""
        transport.assert_not_called()
    adapter._client.close()


def test_raw_exception_never_enters_feedback_or_terminal():
    sentinel = "SYNTHETIC_SECRET_PATH_AND_KEY"
    assert sentinel not in _format_validation_feedback(RuntimeError(sentinel))
    adapter = get_adapter("local-model", base_url="http://localhost:11434/v1", max_retries=1)
    err = io.StringIO()
    with patch.object(adapter._client.chat.completions, "create", side_effect=ValueError(sentinel)) as call:
        with contextlib.redirect_stderr(err):
            adapter.reflect("姓名", "Test", {})
    assert sentinel not in err.getvalue()
    assert sentinel not in repr(call.call_args_list)
    adapter._client.close()


def make_template(path):
    doc = Document()
    table = doc.add_table(rows=4, cols=2)
    for row, label in zip(table.rows, ["姓名", "通讯地址", "学号", "性别"]):
        row.cells[0].text = label
    doc.save(path)


def test_values_stay_in_final_document_not_diagnostics(tmp_path):
    source = tmp_path / "SYNTHETIC_PRIVATE_FILENAME.docx"
    make_template(source)
    profile = {"personal": {"name": "SYNTHETIC_PERSON", "gender": "男"},
               "contact": {"address": "SYNTHETIC_PRIVATE_ADDRESS"},
               "education": {"entries": [{"student_id": "SYNTHETIC_STUDENT"}]}}
    original = source.read_bytes()
    out = tmp_path / "filled.docx"
    terminal = io.StringIO()
    def local_reflection(*args):
        return "SYNTHETIC_PRIVATE_REFLECTION"
    with contextlib.redirect_stdout(terminal):
        audit = fill_docx(str(source), profile, str(out), reflexion_rounds=1, _reflect_impl=local_reflection)
        print_audit(audit)
        scan = scan_docx_tables(str(out))
        intro = scan_docx_introspect(str(out))
        write_profile_md(profile, str(tmp_path))
    render_audit_table(audit, str(Path(__file__).resolve().parents[1] / "templates/audit_table.md"), str(tmp_path / "audit.md"))
    diagnostics = terminal.getvalue() + json.dumps([audit, scan, intro])
    diagnostics += (tmp_path / "audit.md").read_text(encoding="utf-8")
    diagnostics += (tmp_path / "profile.md").read_text(encoding="utf-8")
    for value in ["SYNTHETIC_PERSON", "SYNTHETIC_PRIVATE_ADDRESS", "SYNTHETIC_STUDENT",
                  "SYNTHETIC_PRIVATE_FILENAME", "SYNTHETIC_PRIVATE_REFLECTION"]:
        assert value not in diagnostics
    filled_text = " ".join(c.text for t in Document(out).tables for r in t.rows for c in r.cells)
    assert "SYNTHETIC_PERSON" in filled_text
    assert "SYNTHETIC_STUDENT" in filled_text
    assert source.read_bytes() == original
    assert not list(tmp_path.glob("profile_v*.md"))


def test_untrusted_audit_strings_are_not_echoed():
    data = {"filled": "SECRET", "details": [{"label": "SECRET", "value": "SECRET",
              "source": "SECRET", "reflection": "SECRET", "fill_mode": "SECRET", "status": "SECRET"}],
            "table_name": "SECRET", "warnings": ["SECRET"], "date": "SECRET"}
    assert "SECRET" not in json.dumps(safe_audit(data))


def test_original_cannot_be_overwritten(tmp_path):
    path = tmp_path / "source.docx"
    make_template(path)
    original = path.read_bytes()
    with pytest.raises(PrivacyError):
        fill_docx(str(path), {"personal": {"name": "SYNTHETIC"}}, str(path))
    assert path.read_bytes() == original


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_encrypted_profile_round_trip_without_plaintext_copy(tmp_path):
    profile = {"name": "SYNTHETIC_PRIVATE_PERSON", "nested": {"value": "SYNTHETIC_PRIVATE_ADDRESS"}}
    save_section(tmp_path, "personal", profile)
    encrypted = tmp_path / "personal.yaml.dpapi"
    assert b"SYNTHETIC_PRIVATE_PERSON" not in encrypted.read_bytes()
    assert not list(tmp_path.glob("*.yaml"))
    assert read_section(encrypted) == profile
    assert load_sections(tmp_path) == {"personal": profile}


def test_encryption_failure_has_no_plaintext_fallback(tmp_path):
    with patch("profile_store._dpapi", side_effect=PrivacyError("failed")):
        with pytest.raises(PrivacyError):
            save_section(tmp_path, "personal", {"name": "SYNTHETIC_PRIVATE_PERSON"})
    assert list(tmp_path.iterdir()) == []


def test_conflicting_plain_and_encrypted_profiles_fail(tmp_path):
    (tmp_path / "personal.yaml").write_text("name: Synthetic", encoding="utf-8")
    (tmp_path / "personal.yaml.dpapi").write_bytes(b"not-real")
    with pytest.raises(PrivacyError):
        load_sections(tmp_path)










def test_default_profile_store_will_not_silently_load_plaintext(tmp_path):
    (tmp_path / "personal.yaml").write_text("name: Synthetic", encoding="utf-8")
    with pytest.raises(PrivacyError):
        load_sections(tmp_path, allow_plain=False)
    assert load_sections(tmp_path, allow_plain=True) == {"personal": {"name": "Synthetic"}}


@pytest.mark.parametrize("flag", ["--output", "--audit-out", "--introspect-out"])
def test_cli_cannot_overwrite_template_via_auxiliary_output(tmp_path, monkeypatch, flag):
    from fill_docx import main
    path = tmp_path / "source.docx"
    make_template(path)
    before = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["fill_docx.py", "--template", str(path), flag, str(path)])
    with pytest.raises(PrivacyError):
        main()
    assert path.read_bytes() == before


