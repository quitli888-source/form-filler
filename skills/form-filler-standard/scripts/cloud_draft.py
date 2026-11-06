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

from privacy import PrivacyError, endpoint_url, private_text, utf8_console

MAX_BYTES = 32_768


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
    private_text(out_path, json.dumps(request, ensure_ascii=False, indent=2))
    return request_digest(request)


def send_request(request_path, approved_sha256: str, response_path, *, now=None) -> None:
    request_path = Path(request_path)
    if request_path.resolve() == Path(response_path).resolve():
        raise PrivacyError("Response must not overwrite the prepared request.")
    if Path(response_path).exists():
        raise PrivacyError("Use a fresh local response filename.")
    if request_path.stat().st_size > MAX_BYTES:
        raise PrivacyError("Prepared request is too large.")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    validate_request(request, time.time() if now is None else now)
    digest = request_digest(request)
    if not hmac.compare_digest(digest, approved_sha256):
        raise PrivacyError("Approval does not match this exact request; nothing sent.")
    key = os.environ.get("FORM_FILLER_CLOUD_API_KEY", "")
    if not key or any(c in key for c in "\r\n"):
        raise PrivacyError("Set FORM_FILLER_CLOUD_API_KEY privately; no command-line keys.")
    # Exclusive marker prevents accidental replay/concurrent duplicate sends. No body in marker.
    used = request_path.with_name(request_path.name + ".used")
    try:
        fd = os.open(used, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise PrivacyError("Prepared request already consumed; prepare and review again.") from None
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(digest)
    import httpx
    try:
        # No implicit proxy, redirects, SDK retry, file uploads, or tools.
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=30.0) as client:
            response = client.post(request["endpoint"] + "/chat/completions",
                                   content=canonical(request["body"]),
                                   headers={"Authorization": "Bearer " + key,
                                            "Content-Type": "application/json"})
            response.raise_for_status()
            payload = response.json()
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
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--prompt-file", required=True)
    prepare.add_argument("--base-url", required=True)
    prepare.add_argument("--model", required=True)
    prepare.add_argument("--out", required=True)
    send = sub.add_parser("send")
    send.add_argument("--request", required=True)
    send.add_argument("--approved-sha256", required=True)
    send.add_argument("--response-out", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if Path(args.prompt_file).stat().st_size > MAX_BYTES:
                raise PrivacyError("Prompt file is too large.")
            digest = prepare_request(Path(args.prompt_file).read_text(encoding="utf-8"),
                                     args.base_url, args.model, args.out)
            print("Prepared offline. Review exact endpoint, model and prompt in the local request.")
            print("Approval SHA-256: " + digest)
        else:
            send_request(args.request, args.approved_sha256, args.response_out)
            print("Cloud attempt completed; draft saved locally for review.")
    except Exception:
        print("Cloud operation blocked or failed; details withheld. Check local request and approval.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    utf8_console()
    sys.exit(main())
