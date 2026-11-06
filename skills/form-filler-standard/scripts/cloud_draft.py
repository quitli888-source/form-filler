"""Explicit, single-use cloud drafts. Never loads profiles or template documents.

prepare_request is offline. send_request requires approval of the exact prepared
endpoint/model/prompt and consumes that request before making one HTTP attempt.
The approval digest is a binding, NOT proof that a human actually consented.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

from privacy import PrivacyError, endpoint_url, private_text, utf8_console, scoped_log_guard

MAX_BYTES = 32_768
MAX_RESPONSE_BYTES = 1_048_576


def canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def request_digest(request: dict) -> str:
    return hashlib.sha256(canonical(request)).hexdigest()


def validate_request(request: dict, now: float) -> None:
    if set(request) != {"version", "endpoint", "body", "created_at", "expires_at", "nonce"}:
        raise PrivacyError("Invalid prepared request.")
    if request["version"] != 1 or not isinstance(request["nonce"], str):
        raise PrivacyError("Invalid prepared request version.")
    if endpoint_url(request["endpoint"], local=False) != request["endpoint"]:
        raise PrivacyError("Noncanonical cloud endpoint.")
    created, expires = request["created_at"], request["expires_at"]
    if (type(created) is not int or type(expires) is not int
            or not (created <= now < expires) or not 0 < expires - created <= 600):
        raise PrivacyError("Cloud request expired or has an invalid lifetime; prepare and review again.")
    body = request["body"]
    if not isinstance(body, dict) or set(body) != {"model", "messages"}:
        raise PrivacyError("Unexpected cloud request fields.")
    if not isinstance(body["model"], str) or not body["model"].strip() or len(body["model"]) > 200:
        raise PrivacyError("Invalid model name.")
    if (not isinstance(body["messages"], list) or len(body["messages"]) != 1
            or set(body["messages"][0]) != {"role", "content"}
            or body["messages"][0]["role"] != "user"
            or not isinstance(body["messages"][0]["content"], str)
            or not body["messages"][0]["content"].strip()
            or len(canonical(request)) > MAX_BYTES):
        raise PrivacyError("Invalid or oversized cloud prompt.")


def prepare_request(prompt: str, base_url: str, model: str, out_path, *, now=None) -> str:
    out_path = Path(out_path)
    if out_path.exists() or out_path.with_name(out_path.name + ".used").exists():
        raise PrivacyError("Use a fresh local request filename for every review.")
    now = int(time.time() if now is None else now)
    request = {"version": 1, "endpoint": endpoint_url(base_url, local=False),
               "body": {"model": model, "messages": [{"role": "user", "content": prompt}]},
               "created_at": now, "expires_at": now + 600, "nonce": os.urandom(16).hex()}
    validate_request(request, now)
    serialized = json.dumps(request, ensure_ascii=False, indent=2)
    if len(serialized.encode("utf-8")) > MAX_BYTES:
        raise PrivacyError("Prepared request exceeds its on-disk size limit.")
    private_text(out_path, serialized)
    return request_digest(request)


@scoped_log_guard
def send_request(request_path, approved_sha256: str, response_path, *, now=None) -> None:
    request_path = Path(request_path)
    used = request_path.with_name(request_path.name + ".used")
    if Path(response_path).resolve() in (request_path.resolve(), used.resolve()):
        raise PrivacyError("Response must not overwrite the prepared request.")
    if Path(response_path).exists():
        raise PrivacyError("Use a fresh local response filename.")
    with request_path.open("rb") as source:
        raw_request = source.read(MAX_BYTES + 1)
    if len(raw_request) > MAX_BYTES:
        raise PrivacyError("Prepared request is too large.")
    request = json.loads(raw_request.decode("utf-8"))
    validate_request(request, time.time() if now is None else now)
    digest = request_digest(request)
    if not hmac.compare_digest(digest, approved_sha256):
        raise PrivacyError("Approval does not match this exact request; nothing sent.")
    key = os.environ.get("FORM_FILLER_CLOUD_API_KEY", "")
    if not key or any(c in key for c in "\r\n"):
        raise PrivacyError("Set FORM_FILLER_CLOUD_API_KEY privately; no command-line keys.")
    # Exclusive marker prevents accidental replay/concurrent duplicate sends. No body in marker.
    # Import before consuming the request: a missing optional dependency sends nothing.
    import httpx
    try:
        fd = os.open(used, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise PrivacyError("Prepared request already consumed; prepare and review again.") from None
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(digest)
    try:
        # No implicit proxy, redirects, SDK retry, file uploads, or tools.
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=30.0) as client:
            with client.stream("POST", request["endpoint"] + "/chat/completions",
                               content=canonical(request["body"]),
                               headers={"Authorization": "Bearer " + key,
                                        "Content-Type": "application/json",
                                        "Accept-Encoding": "identity"}) as response:
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise PrivacyError("Compressed cloud responses are not accepted.")
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=16_384):
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise PrivacyError("Cloud response exceeds the local size limit.")
                    body.extend(chunk)
                payload = json.loads(body.decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise PrivacyError("Cloud response has no text draft.")
            private_text(response_path, content)
    except Exception:
        # Providers can echo prompts/keys in error bodies. Never print or retry them.
        raise PrivacyError("Cloud attempt failed; request consumed. Review locally before any new attempt.") from None


def main():
    parser = argparse.ArgumentParser(description="Review-bound cloud drafting (no automatic profile access)")
    sub = parser.add_subparsers(dest="command", required=True)
    # All CLI preparation goes through standard_workflow.py's local deidentifier.
    send = sub.add_parser("send")
    send.add_argument("--request", required=True)
    send.add_argument("--approved-sha256", required=True)
    send.add_argument("--response-out", required=True)
    args = parser.parse_args()
    try:
        send_request(args.request, args.approved_sha256, args.response_out)
        print("Cloud attempt completed; draft saved locally for review.")
    except Exception:
        print("Cloud operation blocked or failed; details withheld. Check local request and approval.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    utf8_console()
    sys.exit(main())
