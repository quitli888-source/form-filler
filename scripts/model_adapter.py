#!/usr/bin/env python3
"""
scripts/model_adapter.py — form-filler v6.0 provider-agnostic Model Adapter (R2-A1, Pattern F2)

目的：把 LLM 调用从 fill_docx.py 的 plumbing-only stub 抽到一个可插拔的 Adapter 层。
让同一份 fill_docx.py 代码既能离线跑（CI / 演示 / 敏感文档），也能调用任何
OpenAI 兼容 endpoint（OpenAI / DeepSeek / minimax m3 / Qwen / Moonshot / Zhipu...）。

设计要点（来源：jxnl/instructor + dottxt-ai/outlines + Round 1 §Pattern F）：
  1. `ModelAdapter` 是 ABC；有两个内建实现：`StubAdapter` 和 `OpenAICompatibleAdapter`。
  2. `StubAdapter` 保持 v5.0 的行为（reflexion 返回 ""、AI 生成走原始 prompt），
     即使没有 LLM key 也能端到端跑通。**这是默认**，所以现存用户零行为变化。
  3. `OpenAICompatibleAdapter` 用 `instructor` 库（基于 OpenAI SDK）包装任意
     OpenAI 兼容 endpoint。`instructor` 缺失时自动降级到裸 OpenAI SDK。
  4. 通过环境变量 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL_NAME` 提供默认值，
     CLI 标志 `--llm-base-url` / `--llm-api-key` / `--llm-model-name` 可覆盖。
     这意味着用户跑 `export LLM_API_KEY=sk-...` 即可启用真实 LLM，无需改代码。

依赖：
  - 必需：标准库
  - 可选：openai>=1.0；instructor>=1.0；pydantic>=2.0
    （都缺失则 OpenAICompatibleAdapter 在 __init__ 时抛 ImportError，明确告知用户）
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from typing import Any, Optional, Type, TypeVar

T = TypeVar("T")


class ModelAdapter(ABC):
    """Provider-agnostic LLM adapter. Two operations:
      - `generate_struct(schema, prompt, **kw)`: Pydantic-validated generation
      - `reflect(field_label, field_value, ctx)`: per-field self-critique

    Either can be unimplemented (`returns None`) — callers must handle that.
    """

    name: str = "abstract"

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

    Environment variables (read at __init__ time):
      - LLM_BASE_URL: e.g. https://api.openai.com/v1
      - LLM_API_KEY: e.g. sk-...
      - LLM_MODEL_NAME: e.g. gpt-4o-mini / MiniMax-M3 / deepseek-chat

    Explicit constructor args override env vars.
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 30.0,
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
        """Pydantic-validated generation via instructor; falls back to plain chat if unavailable."""
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
                # Don't crash fill_docx on LLM errors — return None so caller falls back
                print(f"⚠️ LLM generate_struct failed: {exc}", file=sys.stderr)
                return None
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
            print(f"⚠️ LLM generate_struct (plain) failed: {exc}", file=sys.stderr)
            return None

    def reflect(self, field_label: str, field_value: Any, ctx: dict) -> str:
        """Single-field self-critique. Plain chat completion (no schema)."""
        ctx_lines = "\n".join(f"  - {k}: {v}" for k, v in (ctx or {}).items())
        prompt = (
            "你正在审计一个已填写的表格字段。回答格式：单句陈述；若一切正常回 OK；\n"
            f"字段名: {field_label}\n"
            f"当前填入值: {field_value}\n"
            f"同表已填字段:\n{ctx_lines}\n"
            "请回答 (≤2 句):"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=120,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ LLM reflect failed: {exc}", file=sys.stderr)
            return ""

    def is_live(self) -> bool:
        return True


def get_adapter(provider: str = "stub", **kw: Any) -> ModelAdapter:
    """Factory. `provider` ∈ {"stub", "openai-compatible"}.

    Default is `stub` (v5.0 behaviour preserved). Pass any other value via env
    var `LLM_PROVIDER` or CLI flag `--provider` to use a real LLM.
    """
    provider = (provider or "stub").lower()
    if provider in ("stub", "none", "offline"):
        return StubAdapter()
    if provider in ("openai", "openai-compatible", "openai_compatible"):
        return OpenAICompatibleAdapter(**kw)
    raise ValueError(
        f"Unknown provider: {provider!r}. "
        "Supported: 'stub', 'openai-compatible'."
    )


if __name__ == "__main__":
    # Self-test: print which adapter each env config yields
    import json
    provider = os.environ.get("LLM_PROVIDER", "stub")
    try:
        adapter = get_adapter(provider)
        print(json.dumps({
            "provider": provider,
            "adapter_name": adapter.name,
            "is_live": adapter.is_live(),
            "reflexion_stub_returns": adapter.reflect("姓名", "张三", {}),
        }, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"❌ Adapter init failed: {exc}", file=sys.stderr)
        sys.exit(1)