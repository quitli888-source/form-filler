#!/usr/bin/env python3
"""v7 adapters: offline rules, mocked tests, or explicitly selected loopback model.

This private edition ships no cloud sender; external endpoints are disabled.
Legacy provider names remain local-only. No ambient cloud API key is used.
Validation feedback and terminal diagnostics omit raw exception messages.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, TypeVar
from privacy import PrivacyError, endpoint_url, scoped_log_guard

T = TypeVar("T")


def _format_validation_feedback(exc: BaseException) -> str:
    """Return generic, input-free validation feedback for local retries.

    Custom exception messages, schema locations and validation messages can
    themselves contain private values; do not copy them into logs or prompts.
    """
    instruction = "Fix the errors and try again."
    try:
        import pydantic
    except ImportError:
        # pydantic 缺失（可选依赖）——退化为纯文本路径
        return f"Validation failed.\n\n{instruction}"
    if isinstance(exc, pydantic.ValidationError):
        try:
            errors = [
                {
                    "loc": ["field"],
                    "msg": "Value does not satisfy schema",
                    "type": "validation_error",
                }
                for err in exc.errors()
            ]
            body = json.dumps(errors, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001 — errors() 本身失败的极端情况
            return f"Validation failed.\n\n{instruction}"
        return (
            f"{len(errors)} validation error(s):\n"
            f"```json\n{body}\n```\n\n"
            f"{instruction}"
        )
    return f"Validation failed.\n\n{instruction}"


class ModelAdapter(ABC):
    """Provider-agnostic LLM adapter. Two operations:
      - `generate_struct(schema, prompt, **kw)`: Pydantic-validated generation
      - `reflect(field_label, field_value, ctx)`: per-field self-critique

    Either can be unimplemented (`returns None`) — callers must handle that.

    v6.2 (R4-A1) adds `max_retries: int` attribute so all subclasses share a
    uniform retry budget. `StubAdapter` always sets it to 0 (no retries,
    v5.0 behaviour); `MockLLMAdapter` uses 0 too (deterministic); only
    `OpenAICompatibleAdapter` exposes configurable retries.
    """

    name: str = "abstract"
    max_retries: int = 0  # uniform across providers; overridable in subclass

    @abstractmethod
    def generate_struct(self, schema: Type[T], prompt: str, **kw: Any) -> Optional[T]:
        """Generate a Pydantic instance matching `schema`. Returns None on failure or no-op."""
        raise NotImplementedError

    @abstractmethod
    def reflect(self, field_label: str, field_value: Any, ctx: dict,
                prior_reflections: Optional[list] = None) -> str:
        """Self-critique a single filled field. Returns "" when no objection.

        v6.4 (R6-A1): `prior_reflections` 携带之前轮次的反思原文（可选），
        供多轮反思闭环使用；None/空列表时行为同 v6.3。
        """
        raise NotImplementedError

    @abstractmethod
    def is_live(self) -> bool:
        """True iff this adapter actually calls an LLM (False for StubAdapter)."""
        raise NotImplementedError


class StubAdapter(ModelAdapter):
    """v5.0-compatible plumbing-only stub. No LLM calls, always available."""

    name = "stub"
    max_retries = 0  # v6.2 (R4-A1): stub never retries

    def generate_struct(self, schema: Type[T], prompt: str, **kw: Any) -> Optional[T]:
        return None  # caller falls back to free-form prompt

    def reflect(self, field_label: str, field_value: Any, ctx: dict,
                prior_reflections: Optional[list] = None) -> str:
        # v5.0 behaviour: stub returns "" = "no objection"
        # v6.4 (R6-A1): prior_reflections 对 stub 无意义（无 LLM 可回喂）
        return ""

    def is_live(self) -> bool:
        return False


class OpenAICompatibleAdapter(ModelAdapter):
    """OpenAI-compatible LOCAL service only; network destination pinned.

    Requires explicit base_url or LLM_BASE_URL. Accepted hosts: 127.0.0.1,
    ::1, localhost (pinned to 127.0.0.1). No environment proxy, redirect,
    SDK retry, automatic instructor wrapper, or cloud fallback.
    Model replies are validated locally. This cannot control whether the
    selected loopback service itself forwards to the internet or logs data.
    """

    name = "openai-compatible"

    @scoped_log_guard
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: Optional[int] = None,
    ) -> None:
        # v7: validate before imports/client construction, with no cloud default.
        self.base_url = endpoint_url(base_url or os.environ.get("LLM_BASE_URL"), local=True)
        # Lazy import — openai is optional
        try:
            import openai  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "OpenAICompatibleAdapter requires `openai>=1.0`. "
                "Install with: pip install openai"
            ) from exc

        # Never send an ambient cloud credential to a local service.
        self.api_key = api_key or os.environ.get("FORM_FILLER_LOCAL_TOKEN") or "local-only"
        self.model_name = (
            model_name
            or os.environ.get("LLM_MODEL_NAME")
            or "local-model"
        )
        self.timeout = timeout
        # v6.2 (R4-A1): max_retries override path: kwarg > env > default=2
        if max_retries is None:
            env_val = os.environ.get("LLM_REFLECT_RETRIES")
            try:
                max_retries = int(env_val) if env_val is not None else 2
            except (TypeError, ValueError):
                max_retries = 2
        self.max_retries = max(0, int(max_retries))

        # Lazy init of client; constructed here so errors surface at startup
        import openai
        import httpx
        self._openai = openai
        target = self.base_url + "/chat/completions"

        class LoopbackTransport(httpx.BaseTransport):
            def __init__(self):
                self.inner = httpx.HTTPTransport(trust_env=False, retries=0)

            def handle_request(self, request):
                # Pin the complete destination even if SDK client.base_url mutates.
                if request.method != "POST" or str(request.url) != target:
                    raise PrivacyError("Model destination changed; request blocked.")
                return self.inner.handle_request(request)

            def close(self):
                self.inner.close()

        self._client = openai.OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=0,
            http_client=httpx.Client(transport=LoopbackTransport(), trust_env=False,
                                     follow_redirects=False, timeout=self.timeout),
        )

        # Optional instructor wrapping
        self._instructor = None
        # Keep response validation local; avoid implicit wrappers and their logs/retries.
        self._instructor_client = None

        # v6.4 (R6-A2): optional json-repair — 缺失时 generate_struct 行为同 v6.3
        self._json_repair = None
        try:
            import json_repair
            self._json_repair = json_repair
        except ImportError:
            self._json_repair = None

    @scoped_log_guard
    def generate_struct(self, schema: Type[T], prompt: str, **kw: Any) -> Optional[T]:
        """Pydantic-validated generation via instructor; falls back to plain chat if unavailable.

        v6.2 (R4-A1): outer retry loop wraps the schema-validated path so a single
        validation failure doesn't immediately give up. Instructor internally also
        retries (max_retries=2), but the outer loop catches cases where instructor
        itself raises (timeout, BadRequestError, etc).

        v6.4 (R6-A2): 重试前把校验失败格式化为反馈块（`_format_validation_feedback`）
        追加进 prompt，让下一轮 attempt 的 messages 携带错误详情自修正。
        首次 attempt（无任何失败）发送的 prompt 与 v6.3 逐字节相同——反馈块只在
        失败后的重试追加。plain 分支在 `json_repair` 可用时先宽松修复再严格校验；
        `json_repair` 缺失时行为同 v6.3（原样 raise → 走外层重试）。
        """
        total_attempts = max(1, self.max_retries)
        for attempt in range(total_attempts):
            messages = [{"role": "user", "content": prompt}]
            if self._instructor_client is not None:
                try:
                    return self._instructor_client.chat.completions.create(
                        model=self.model_name,
                        messages=messages,
                        response_model=schema,
                        max_retries=2,
                        **kw,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"⚠️ LLM generate_struct attempt {attempt+1}/{total_attempts} failed (details withheld)",
                        file=sys.stderr,
                    )
                    # v6.4 (R6-A2): 若还有剩余 attempt，把校验错误回喂进 prompt 再重试
                    if attempt + 1 < total_attempts:
                        prompt = f"{prompt}\n\n{_format_validation_feedback(exc)}"
                    # Continue to next retry iteration
                    continue
            # Plain OpenAI fallback (no schema enforcement)
            try:
                resp = self._client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                    **kw,
                )
                raw = resp.choices[0].message.content
                try:
                    return schema.model_validate_json(raw)
                except Exception:
                    # v6.4 (R6-A2): 严格解析失败 → json_repair 可用则修复后再校验；
                    # 不可用（或修复后仍不合法）时原样抛给外层重试逻辑（v6.3 行为）
                    if self._json_repair is None:
                        raise
                    repaired = self._json_repair.loads(raw)
                    return schema.model_validate(repaired)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"⚠️ LLM generate_struct (plain) attempt {attempt+1}/{total_attempts} failed (details withheld)",
                    file=sys.stderr,
                )
                # v6.4 (R6-A2): 同 instructor 分支——剩余 attempt 时回喂错误反馈
                if attempt + 1 < total_attempts:
                    prompt = f"{prompt}\n\n{_format_validation_feedback(exc)}"
                continue
        # All retries exhausted
        print(
            f"⚠️ LLM generate_struct exhausted {total_attempts} attempts; returning None",
            file=sys.stderr,
        )
        return None

    @scoped_log_guard
    def reflect(self, field_label: str, field_value: Any, ctx: dict,
                prior_reflections: Optional[list] = None) -> str:
        """Single-field self-critique with retry-on-failure (v6.2 R4-A1).

        Up to `max_retries` attempts (default 2). On each failure (BadRequestError,
        BadResponseError, empty response, JSON decode error), append the error to
        the prompt for the next attempt: "上一次回答出错: {err}\n请重新回答。"
        Final failure returns "" and logs "reflect exhausted" to stderr.

        v6.4 (R6-A1): `prior_reflections` 反馈闭环——调用方（fill_docx.py 的多轮
        反思循环）把之前轮次的反思原文回喂进来。非空时（仅取最后 3 条）在
        base_prompt 末尾追加「之前轮次的反思记录」块，让模型在既有反思基础上
        重新审计，而不是从零重复同一个任务。`prior_reflections` 为 None/空列表时
        prompt 与 v6.3 逐字节相同（历史行为硬约束）。
        注意：SKILL.md 承诺的「重新调用 Step 5 用反思重生成」仍未实现（future
        work）——本参数只让多轮反思任务递进，不触发现值重生成。

        Back-compat: when `max_retries=0`, behaves identically to v6.0 (single call,
        log + return "" on failure). When `max_retries>=1`, adds retry semantics.
        """
        ctx_lines = "\n".join(f"  - {k}: {v}" for k, v in (ctx or {}).items())
        base_prompt = (
            "你正在审计一个已填写的表格字段。回答格式：单句陈述；若一切正常回 OK；\n"
            f"字段名: {field_label}\n"
            f"当前填入值: {field_value}\n"
            f"同表已填字段:\n{ctx_lines}\n"
            "请回答 (≤2 句):"
        )
        # v6.4 (R6-A1): 多轮反思闭环——把之前轮次的反思原文（最后 3 条）回喂 prompt
        if prior_reflections:
            prior_block = "\n".join(f"- {r}" for r in prior_reflections[-3:])
            base_prompt += (
                f"\n\n之前轮次的反思记录:\n{prior_block}\n"
                "请在上述反思基础上重新审计该字段。"
            )
        # max_retries=0 → single attempt (v6.0 behaviour)
        # max_retries=N → up to N+1 total attempts (1 initial + N retries)
        attempts = max(1, self.max_retries + 1)
        last_err: Optional[BaseException] = None
        last_prompt = base_prompt

        for attempt_idx in range(attempts):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": last_prompt}],
                    temperature=0.0,
                    max_tokens=120,
                )
                content = (resp.choices[0].message.content or "").strip()
                if not content:
                    # Empty response = soft failure; trigger retry
                    raise ValueError("empty response from LLM")
                if attempt_idx > 0:
                    print(
                        f"ℹ️ LLM reflect succeeded on retry attempt {attempt_idx+1}/{attempts}",
                        file=sys.stderr,
                    )
                return content
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                print(
                    f"⚠️ LLM reflect attempt {attempt_idx+1}/{attempts} failed (details withheld)",
                    file=sys.stderr,
                )
                # Append error to next prompt (if we have more attempts)
                if attempt_idx + 1 < attempts:
                    last_prompt = (
                        f"{base_prompt}\n\n"
                        "上一次回答未通过验证。请重新回答。"
                    )
                # else: final attempt exhausted → fall through to return ""

        # All retries exhausted; v6.0-compatible graceful degrade
        print(
            f"⚠️ LLM reflect exhausted {attempts} attempts (details withheld)",
            file=sys.stderr,
        )
        return ""

    def is_live(self) -> bool:
        return True


class MockLLMAdapter(ModelAdapter):
    """v6.2 (R4-A3, Pattern G2): deterministic offline test stub.

    Accepts `canned_responses: Dict[str, str]` mapping either:
      - LITERAL prompt substrings (label, prompt fragment, etc.)
      - SHA-256 of the prompt prefix (first 200 chars), prefixed with 'sha256:'

    On `reflect(label, value, ctx)`:
      - Looks up `label` first in `canned_responses`.
      - Then iterates keys looking for a substring match (e.g. "label=姓名" matches
        if any canned key is a substring of `label`).
      - On miss: returns "" (same degrade behaviour as StubAdapter).

    On `generate_struct(schema, prompt, **kw)`:
      - Computes SHA-256 of `prompt[:200]` and looks up `'sha256:' + hex` in
        `canned_responses`.
      - On miss: returns None (same degrade behaviour as StubAdapter).

    `is_live()` returns True — MockLLM is a *fake* LLM (deterministic responses),
    not a *stub* (which never produces output). Tests use this distinction.

    Does NOT require any external API key or network access. Use via:
        get_adapter("mock", canned_responses={"姓名": "OK", ...})

    Risk note: if `provider="mock"` slips into a production CLI invocation, the
    adapter will print a yellow warning to stderr at __init__ time so the
    operator notices. This is a defensive measure per R4-R3.
    """

    name = "mock"
    max_retries = 0  # deterministic — no retries needed

    def __init__(self, canned_responses: Optional[Dict[str, str]] = None) -> None:
        self.canned_responses: Dict[str, str] = dict(canned_responses or {})
        # Defensive warning so a mistyped --provider mock in production is loud.
        print(
            "🔶 MockLLM — not a real LLM (deterministic canned responses only)",
            file=sys.stderr,
        )

    def reflect(self, field_label: str, field_value: Any, ctx: dict,
                prior_reflections: Optional[list] = None) -> str:
        """Return canned response keyed by label (exact → substring → miss).

        v6.4 (R6-A1): prior_reflections 不影响 mock 查表（确定性替身）。
        """
        # Exact label match first
        if field_label in self.canned_responses:
            return self.canned_responses[field_label]
        # Substring match — useful for prompts like "label=姓名 ..."
        for key, val in self.canned_responses.items():
            if key and (key in field_label or field_label in key):
                return val
        # Miss → empty (graceful degrade)
        return ""

    def generate_struct(self, schema: Type[T], prompt: str, **kw: Any) -> Optional[T]:
        """Look up SHA-256 of `prompt[:200]`; on miss return None."""
        prefix = prompt[:200]
        digest = hashlib.sha256(prefix.encode("utf-8", errors="replace")).hexdigest()
        key = f"sha256:{digest}"
        raw = self.canned_responses.get(key)
        if raw is None:
            return None
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            print("⚠️ MockLLM generate_struct validation failed (details withheld)", file=sys.stderr)
            return None

    def is_live(self) -> bool:
        # MockLLM is a *fake* LLM — deterministic but not stub-zero-output.
        return True


def get_adapter(provider: str = "stub", **kw: Any) -> ModelAdapter:
    """Factory. `provider` ∈ {"stub", "openai-compatible", "mock"}.

    Default is `stub` (v5.0 behaviour preserved). Pass any other value via env
    var `LLM_PROVIDER` or CLI flag `--provider` to use a real LLM.

    v6.2 (R4-A3): `provider="mock"` returns a `MockLLMAdapter` — deterministic
    offline stub for tests. Pass `canned_responses` dict via kwargs.
    """
    provider = (provider or "stub").lower()
    if provider in ("stub", "none", "offline"):
        return StubAdapter()
    if provider in ("local-model", "openai", "openai-compatible", "openai_compatible"):
        return OpenAICompatibleAdapter(**kw)
    if provider in ("mock", "mock-llm", "mockllm"):
        canned = kw.pop("canned_responses", None) or {}
        return MockLLMAdapter(canned_responses=canned)
    raise ValueError(
        "Unknown provider. Supported: 'stub', 'local-model', 'openai-compatible' (local only), 'mock'."
    )


if __name__ == "__main__":
    # Self-test: print which adapter each env config yields
    import json
    provider = os.environ.get("LLM_PROVIDER", "stub")
    try:
        if provider in ("mock", "mock-llm", "mockllm"):
            # MockLLM requires canned_responses; provide a trivial example.
            adapter = get_adapter(provider, canned_responses={"姓名": "OK（mock）"})
        else:
            adapter = get_adapter(provider)
        print(json.dumps({
            "provider": provider,
            "adapter_name": adapter.name,
            "is_live": adapter.is_live(),
            "max_retries": getattr(adapter, "max_retries", 0),
            "reflexion_stub_returns": adapter.reflect("姓名", "张三", {}),
        }, ensure_ascii=False, indent=2))
    except Exception as exc:
        print("❌ Adapter init failed (details withheld)", file=sys.stderr)
        sys.exit(1)
