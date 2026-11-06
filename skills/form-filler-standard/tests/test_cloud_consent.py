"""Cloud consent tests: synthetic content, no live requests."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from privacy import PrivacyError, private_text
from cloud_draft import prepare_request, send_request


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv("FORM_FILLER_CLOUD_API_KEY", "SYNTHETIC_KEY")
    request = tmp_path / "request.json"
    digest = prepare_request("Describe applicant A in general terms.", "https://provider.example/v1",
                             "synthetic-model", request, now=1000)
    return request, digest, tmp_path / "draft.txt"


@pytest.mark.parametrize("case", ["missing_approval", "wrong_approval", "expired", "future", "prompt", "endpoint", "model"])
def test_cloud_approval_is_bound_to_exact_unexpired_request(prepared, case):
    request, digest, output = prepared
    now = 1001
    if case == "missing_approval":
        digest = ""
    elif case == "wrong_approval":
        digest = "0" * 64
    elif case == "expired":
        now = 1600
    elif case == "future":
        now = 999
    else:
        body = json.loads(request.read_text(encoding="utf-8"))
        if case == "prompt":
            body["body"]["messages"][0]["content"] += " Added identity."
        elif case == "endpoint":
            body["endpoint"] = "https://another.example/v1"
        else:
            body["body"]["model"] = "another-model"
        private_text(request, json.dumps(body))
    with patch.object(httpx.Client, "post") as network:
        with pytest.raises(PrivacyError):
            send_request(request, digest, output, now=now)
        network.assert_not_called()
    assert not output.exists()


def test_cloud_sends_exact_body_once_and_does_not_log_draft(prepared):
    request, digest, output = prepared
    seen = []
    real_client = httpx.Client
    def reply(req):
        seen.append(req)
        return httpx.Response(200, json={"choices": [{"message": {"content": "SYNTHETIC_PRIVATE_DRAFT"}}]})
    settings = []
    def client(**kwargs):
        settings.append(kwargs)
        return real_client(transport=httpx.MockTransport(reply), **kwargs)
    with patch.object(httpx, "Client", client):
        send_request(request, digest, output, now=1001)
        with pytest.raises(PrivacyError):
            send_request(request, digest, output.with_name("another.txt"), now=1002)
    assert len(seen) == 1
    assert json.loads(seen[0].content) == json.loads(request.read_text(encoding="utf-8"))["body"]
    assert seen[0].headers["authorization"] == "Bearer SYNTHETIC_KEY"
    assert output.read_text(encoding="utf-8") == "SYNTHETIC_PRIVATE_DRAFT"
    assert settings == [{"trust_env": False, "follow_redirects": False, "timeout": 30.0}]


@pytest.mark.parametrize("status", [307, 401, 500])
def test_cloud_errors_are_not_logged_or_retried(prepared, status):
    request, digest, output = prepared
    seen = []
    real_client = httpx.Client
    def reply(req):
        seen.append(req)
        return httpx.Response(status, headers={"location": "https://another.example/steal"},
                              text="SYNTHETIC_ECHOED_SECRET")
    with patch.object(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw)):
        with pytest.raises(PrivacyError) as exc:
            send_request(request, digest, output, now=1001)
    assert "SYNTHETIC_ECHOED_SECRET" not in str(exc.value)
    assert len(seen) == 1
    assert not output.exists()
    assert request.with_name(request.name + ".used").exists()


def test_cloud_prepare_preserves_existing_local_files(prepared):
    path, _, _ = prepared
    before = path.read_bytes()
    with pytest.raises(PrivacyError):
        prepare_request("A different request", "https://provider.example/v1", "model", path, now=1001)
    assert path.read_bytes() == before

