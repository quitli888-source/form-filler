#!/usr/bin/env python3
"""
scripts/model_adapter.py — form-filler v6.2 provider-agnostic Model Adapter

历史：
  v6.0 (R2-A1, Pattern F2): 抽出 `ModelAdapter` ABC + Stub/OpenAI 两个实现
  v6.1 (R3-A1): 把 OpenAICompatible 用 instructor 包了一层
  v6.2 (R4-A1, Pattern I1): reflect() 增加重试-on-validation-failure 循环
  v6.2 (R4-A3, Pattern G2): 新增 MockLLMAdapter 离线测试桩

目的：把 LLM 调用从 fill_docx.py 的 plumbing-only stub 抽到一个可插拔的 Adapter 层。
让同一份 fill_docx.py 代码既能离线跑（CI / 演示 / 敏感文档），也能调用任何
OpenAI 兼容 endpoint（OpenAI / DeepSeek / minimax m3 / Qwen / Moonshot / Zhipu...）。

设计要点（来源：jxnl/instructor + dottxt-ai/outlines + Round 1 §Pattern F）：
  1. `ModelAdapter` 是 ABC；三个内建实现：`StubAdapter` / `OpenAICompatibleAdapter` / `MockLLMAdapter`。
  2. `StubAdapter` 保持 v5.0 的行为（reflexion 返回 ""、AI 生成走原始 prompt），
     即使没有 LLM key 也能端到端跑通。**这是默认**，所以现存用户零行为变化。
  3. `OpenAICompatibleAdapter` 用 `instructor` 库（基于 OpenAI SDK）包装任意
     OpenAI 兼容 endpoint。`instructor` 缺失时自动降级到裸 OpenAI SDK。
     (v6.2) reflect() 内置 retry-on-failure 循环，默认 max_retries=2。
  4. (v6.2) `MockLLMAdapter` 接受 `canned_responses` dict 用于离线测试；
     `provider="mock"` 时注册，无需 API key。
  5. 通过环境变量 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL_NAME` 提供默认值，
     CLI 标志 `--llm-base-url` / `--llm-api-key` / `--llm-model-name` 可覆盖。

依赖：
  - 必需：标准库
  - 可选：openai>=1.0；instructor>=1.0；pydantic>=2.0
    （都缺失则 OpenAICompatibleAdapter 在 __init__ 时抛 ImportError，明确告知用户）
"""

from __future__ import annotations

import hashlib
import os
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, TypeVar

T = TypeVar("T")


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
    def reflect(self, field_label: str, field_value: Any, ctx: dict) -> str:
        """Self-critique a single filled field. Returns "" when no objection."""
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

    def reflect(self, field_label: str, field_value: Any, ctx: dict) -> str:
        # v5.0 behaviour: stub returns "" = "no objection"
        return ""

    def is_live(self) -> bool:
        return False


class OpenAICompatibleAdapter(ModelAdapter):
    """Calls any OpenAI-compatible chat-completions endpoint via the `openai` SDK.

    When `instructor` is installed, uses it for Pydantic-validated `generate_struct`.
    When not installed, falls back to plain `chat.completions.create()` (no schema
    enforcement — Pattern A2's protection is lost, but generation still works).

    v6.2 (R4-A1, Pattern I1): `reflect()` now retries up to `max_retries` times on
    any failure (BadRequestError, ValidationError, JSONDecodeError, empty response).
    Each retry appends the error message to the next prompt so the model can
    self-correct. Final failure returns "" and logs a warning — same as v6.0
    behaviour, just with attempt count visible.

    Environment variables (read at __init__ time):
      - LLM_BASE_URL: e.g. https://api.openai.com/v1
      - LLM_API_KEY: e.g. sk-...
      - LLM_MODEL_NAME: e.g. gpt-4o-mini / MiniMax-M3 / deepseek-chat
      - LLM_REFLECT_RETRIES: int override for `max_retries` (default 2)

    Explicit constructor args override env vars.
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: Optional[int] = None,
    ) -> None:
        # Lazy import — openai is optional
        try:
            import openai  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "OpenAICompatibleAdapter requires `openai>=1.0`. "
                "Install with: pip install openai"
            ) from exc

        self.base_url = (
            base_url
            or os.environ.get("LLM_BASE_URL")
            or "https://api.openai.com/v1"
        )
        self.api_key = api_key or os.environ.get("LLM_API_KEY") or ""
        self.model_name = (
            model_name
            or os.environ.get("LLM_MODEL_NAME")
            or "gpt-4o-mini"
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

        if not self.api_key:
            raise ValueError(
                "OpenAICompatibleAdapter requires an API key. "
                "Set LLM_API_KEY env var or pass api_key=..."
            )

        # Lazy init of client; constructed here so errors surface at startup
        import openai
        self._openai = openai
        self._client = openai.OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )

        # Optional instructor wrapping
        self._instructor = None
        try:
            import instructor
            self._instructor = instructor
            self._instructor_client = instructor.from_openai(self._client)
        except ImportError:
            # instructor missing — generate_struct() falls back to plain JSON mode
            self._instructor_client = None

    def generate_struct(self, schema: Type[T], prompt: str, **kw: Any) -> Optional[T]:
        """Pydantic-validated generation via instructor; falls back to plain chat if unavailable.

        v6.2 (R4-A1): outer retry loop wraps the schema-validated path so a single
        validation failure doesn't immediately give up. Instructor internally also
        retries (max_retries=2), but the outer loop catches cases where instructor
        itself raises (timeout, BadRequestError, etc).
        """
        for attempt in range(max(1, self.max_retries)):
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
                        f"⚠️ LLM generate_struct attempt {attempt+1}/{self.max_retries} failed: {exc}",
                        file=sys.stderr,
                    )
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
                return schema.model_validate_json(raw)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"⚠️ LLM generate_struct (plain) attempt {attempt+1}/{self.max_retries} failed: {exc}",
                    file=sys.stderr,
                )
                continue
        # All retries exhausted
        print(
            f"⚠️ LLM generate_struct exhausted {self.max_retries} attempts; returning None",
            file=sys.stderr,
        )
        return None

    def reflect(self, field_label: str, field_value: Any, ctx: dict) -> str:
        """Single-field self-critique with retry-on-failure (v6.2 R4-A1).

        Up to `max_retries` attempts (default 2). On each failure (BadRequestError,
        BadResponseError, empty response, JSON decode error), append the error to
        the prompt for the next attempt: "上一次回答出错: {err}\n请重新回答。"
        Final failure returns "" and logs "reflect exhausted" to stderr.

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
                    f"⚠️ LLM reflect attempt {attempt_idx+1}/{attempts} failed: {exc}",
                    file=sys.stderr,
                )
                # Append error to next prompt (if we have more attempts)
                if attempt_idx + 1 < attempts:
                    last_prompt = (
                        f"{base_prompt}\n\n"
                        f"上一次回答出错: {exc}\n请重新回答。"
                    )
                # else: final attempt exhausted → fall through to return ""

        # All retries exhausted; v6.0-compatible graceful degrade
        print(
            f"⚠️ LLM reflect exhausted {attempts} attempts; last error: {last_err}",
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

    def reflect(self, field_label: str, field_value: Any, ctx: dict) -> str:
        """Return canned response keyed by label (exact → substring → miss)."""
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
            print(f"⚠️ MockLLM generate_struct validation failed: {exc}", file=sys.stderr)
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
    if provider in ("openai", "openai-compatible", "openai_compatible"):
        return OpenAICompatibleAdapter(**kw)
    if provider in ("mock", "mock-llm", "mockllm"):
        canned = kw.pop("canned_responses", None) or {}
        return MockLLMAdapter(canned_responses=canned)
    raise ValueError(
        f"Unknown provider: {provider!r}. "
        "Supported: 'stub', 'openai-compatible', 'mock'."
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
        print(f"❌ Adapter init failed: {exc}", file=sys.stderr)
        sys.exit(1)