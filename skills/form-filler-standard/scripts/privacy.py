"""Shared privacy boundaries. No network or file writes at import time."""
from __future__ import annotations

import os
import re
import tempfile
import contextvars
import functools
import logging
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from edition import EDITION, DATA_NAMESPACE, POSIX_NAMESPACE


class PrivacyError(ValueError):
    """A safe-to-display error; never include user data in its message."""


_log_scope = contextvars.ContextVar("form_filler_private_diagnostics", default=False)
_log_lock = threading.RLock()


def scoped_log_guard(function):
    """Hide this call's SDK diagnostics even when OPENAI_LOG=debug is set.

    Scrub records before handlers see them, without changing logger levels,
    credentials, or unrelated callers' messages. Restore the previous factory.
    This covers standard logging, not arbitrary third-party print statements.
    """
    @functools.wraps(function)
    def guarded(*args, **kwargs):
        with _log_lock:
            previous = logging.getLogRecordFactory()
            token = _log_scope.set(True)
            def factory(*a, **kw):
                record = previous(*a, **kw)
                if _log_scope.get() and record.name.split(".")[0] in {"openai", "httpx", "httpcore"}:
                    record.msg, record.args = "[model diagnostics withheld]", ()
                    record.exc_info = record.exc_text = record.stack_info = None
                return record
            logging.setLogRecordFactory(factory)
            try:
                return function(*args, **kwargs)
            finally:
                if logging.getLogRecordFactory() is factory:
                    logging.setLogRecordFactory(previous)
                _log_scope.reset(token)
    return guarded


def local_data_dir() -> Path:
    # Outside the skill checkout; never default to Documents/OneDrive.
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / DATA_NAMESPACE
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / POSIX_NAMESPACE


def private_write(path, data: bytes) -> None:
    """Atomic replacement; POSIX 0600 files, 0700 newly created directories.

    Windows uses inherited ACLs; this function does NOT promise ACL isolation.
    Refuse symlink destinations to avoid accidental writes through user data links.
    """
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise PrivacyError("Refusing a symbolic-link output path.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=".ff-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def private_text(path, text: str) -> None:
    private_write(path, text.encode("utf-8"))


def protect_inputs(outputs, inputs) -> None:
    """Reject output/input aliases and collisions between different artifacts."""
    destinations = [Path(p).resolve() for p in outputs if p is not None]
    sources = {Path(p).resolve() for p in inputs if p is not None}
    if len(set(destinations)) != len(destinations) or any(p in sources for p in destinations):
        raise PrivacyError("Output paths must be distinct from inputs and other artifacts.")


def utf8_console() -> None:
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def endpoint_url(value: str | None, *, local: bool) -> str:
    """Strict endpoint parsing; local names pinned to numeric loopback, no DNS."""
    if not local and EDITION == "private":
        raise PrivacyError("External model calls are disabled in the private edition.")
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise PrivacyError("An explicit model endpoint is required.")
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise PrivacyError("Invalid model endpoint.") from None
    if (parts.scheme not in ("http", "https") or not host or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment
            or "\\" in value or "%" in parts.netloc):
        raise PrivacyError("Endpoint must have no credentials, query, or fragment.")
    if local:
        if host not in ("localhost", "127.0.0.1", "::1"):
            raise PrivacyError("Local model requires numeric loopback or localhost; cloud needs a separate reviewed request.")
        host = "127.0.0.1" if host == "localhost" else host
    elif parts.scheme != "https":
        raise PrivacyError("Cloud model requires HTTPS.")
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    if ".." in parts.path.split("/") or "%" in parts.path:
        raise PrivacyError("Endpoint path must be literal and must not contain traversal.")
    return urlunsplit((parts.scheme, authority, parts.path.rstrip("/"), "", ""))


# Names, addresses and narrative text cannot be reliably found with regexes.
# Omit ALL values and model-generated reflections from the diagnostic channel.
_LABELS = set("姓名 性别 学号 手机 电话 联系电话 邮箱 电子邮箱 身份证 身份证号 银行卡 银行卡号 开户行 籍贯 民族 出生日期 出生年月 政治面貌 学校 院系 学院 专业 学历 学位 所在单位 年级 申报类别 类别 单位 职务 地址 通讯地址 家庭住址 邮编 入团时间 入团日期 团内职务 评议等级 获奖情况 个人陈述 自荐信 自我评价 主要事迹".split())


def safe_label(value) -> str:
    label = str(value).strip().rstrip(":：* ")
    return label if label in _LABELS else "[字段]"


def safe_audit(audit: dict) -> dict:
    result = {k: audit.get(k, 0) if type(audit.get(k, 0)) is int and audit.get(k, 0) >= 0 else 0
              for k in ("filled", "missed", "inferred")}
    result["template_mode"] = audit.get("template_mode", "cell") if audit.get("template_mode") in ("cell", "jinja") else "cell"
    result["details"] = []
    for item in audit.get("details", []):
        mode = item.get("fill_mode")
        status = item.get("status")
        result["details"].append({
            "label": safe_label(item.get("label", "")),
            "value": "[已隐藏]" if item.get("value") else "",
            "source": "本地资料",
            "status": status if status in ("✅", "❌", "⚠️", "📝", "🔄", "📎") else "⚠️",
            "reflection": ("[skip-llm: literal]" if item.get("reflection") == "[skip-llm: literal]"
                           else "[需本地复核]" if item.get("reflection") else ""),
            "fill_mode": mode if mode in ("literal", "literal-mismatch", "schema", "regex", "llm", "unknown") else "unknown",
        })
    result["warnings"] = ["Local processing fallback; review locally."] * len(audit.get("warnings", []))
    # User-supplied titles, paths and source names can themselves contain PII.
    result.update(table_name="本地表格", info_source="本地资料", input_format="DOCX", attachments=0)
    date = str(audit.get("date", ""))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        result["date"] = date
    return result
