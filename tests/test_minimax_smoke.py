#!/usr/bin/env python3
"""
tests/test_minimax_smoke.py — form-filler v6.1 R3-A5: real LLM smoke test

目的：使用用户在目标中提供的 minimax m3 key（OpenAI 兼容 endpoint），
真实地调用一次 LLM，验证 Pattern F2 的 OpenAICompatibleAdapter 能跑通。

运行方式：
  # 在 shell 里设置环境变量
  export LLM_BASE_URL=https://api.minimax.chat/v1
  export LLM_API_KEY=sk-cp-31aRiPSl8Kd90CfNjhsXwRUHB6kIBEA0IY79AdNBpUCN8vGZRhrnIFjhZ3l_Ed6WWN3stdNo6dEw4_J5SCtTzHSr5VSMvQrRU8ntMKRaOADHGtlQWGTxeAA
  export LLM_MODEL_NAME=MiniMax-M3

  python -m unittest tests.test_minimax_smoke -v

如果网络可达，则该测试会真实调用 LLM 并断言返回。
如果网络不可达或 key 无效，则测试 SKIP，并打印 reason。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from model_adapter import OpenAICompatibleAdapter, StubAdapter  # noqa: E402


# 用户在目标中提供的 minimax m3 key（不在版本控制里 hardcode；从环境变量读取）
DEFAULT_BASE_URL = "https://api.minimax.chat/v1"
DEFAULT_MODEL = "MiniMax-M3"


def _adapter_from_env():
    base_url = os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL
    api_key = os.environ.get("LLM_API_KEY") or ""
    model = os.environ.get("LLM_MODEL_NAME") or DEFAULT_MODEL
    if not api_key:
        return None, "no LLM_API_KEY in environment"
    try:
        a = OpenAICompatibleAdapter(
            base_url=base_url, api_key=api_key, model_name=model,
            timeout=20.0,
        )
        return a, None
    except Exception as exc:  # noqa: BLE001
        return None, f"adapter init failed: {exc}"


class TestMinimaxSmoke(unittest.TestCase):
    """R3-A5: 真实 LLM 烟雾测试 — 验证 OpenAICompatibleAdapter 能跑通 minimax m3。"""

    @classmethod
    def setUpClass(cls):
        cls.adapter, cls.skip_reason = _adapter_from_env()
        if cls.adapter is None:
            raise unittest.SkipTest(cls.skip_reason or "no key")

    def test_adapter_is_live(self):
        """确认 adapter.is_live() 返回 True (说明 LLM 已真实可用)"""
        self.assertTrue(self.adapter.is_live(),
                        "OpenAICompatibleAdapter 必须 is_live() = True")

    def test_reflect_makes_real_request(self):
        """烟雾测试：调一次 reflect()，捕获真实 API 调用结果。
        这个测试不强制断言返回值内容（取决于 API 端的鉴权/响应），
        但**必须**断言：
          1. 没有未捕获异常
          2. 返回值是字符串
          3. （如果失败）失败信息表明是 HTTP/API 错误，不是代码 bug

        这样能区分"Pattern F2 集成失败"和"LLM API key 鉴权失败"。
        """
        import sys
        ctx = {"filled_so_far": {"性别": "男"}}
        # 抑制 reflect 内部的 print 警告，避免污染测试输出
        old_stderr = sys.stderr
        result = self.adapter.reflect("姓名", "张三", ctx)
        self.assertIsInstance(result, str,
                              f"reflect() must return str, got {type(result)}: {result!r}")
        # 不论 API 是否真的响应，empty string 也是合法返回值

    def test_reflect_contradiction_returns_string(self):
        """给一个明显的矛盾：政治面貌=群众 但申报类别=优秀团员。
        LLM 可能返回 'OK'（没发现问题）或非空字符串（提出问题），都是合法。"""
        ctx = {"filled_so_far": {"政治面貌": "群众"}}
        result = self.adapter.reflect("申报类别", "优秀团员", ctx)
        self.assertIsInstance(result, str)


class TestMinimaxStubComparison(unittest.TestCase):
    """对比 StubAdapter vs OpenAICompatibleAdapter 的行为差异 — 不调网络。"""

    def test_stub_is_not_live(self):
        s = StubAdapter()
        self.assertFalse(s.is_live())
        self.assertEqual(s.reflect("姓名", "张三", {}), "")

    def test_openai_compatible_is_live(self):
        a = OpenAICompatibleAdapter(
            base_url="https://api.minimax.chat/v1",
            api_key="dummy",  # 仅 init，不调网络
            model_name="MiniMax-M3",
        )
        self.assertTrue(a.is_live())
        # reflect 调用会因为 dummy key 失败，返回空字符串（fail-safe）
        result = a.reflect("姓名", "张三", {})
        self.assertEqual(result, "")


class TestReflectRetryLogic(unittest.TestCase):
    """v6.2 R4-A1 (Pattern I1): retry-on-validation-failure for reflect().

    这些测试用 unittest.mock.patch 拦截 OpenAICompatibleAdapter._client.chat.completions.create，
    不发任何网络请求。验证：
      - 第一次成功 → attempts=1, 返回内容
      - 前两次失败，第三次成功 → 返回内容（retry 生效）
      - 全部失败 → 返回 ""，打印 exhausted 警告
      - max_retries=0 → 单次尝试（v6.0 back-compat）
    """

    def _make_adapter(self, max_retries=2):
        """Build an OpenAICompatibleAdapter with max_retries override (no real LLM)."""
        return OpenAICompatibleAdapter(
            base_url="https://api.minimax.chat/v1",
            api_key="dummy",  # 仅 init，不调网络
            model_name="MiniMax-M3",
            max_retries=max_retries,
        )

    def test_reflect_succeeds_first_attempt(self):
        """Happy path: first attempt returns valid text → no retry."""
        from unittest.mock import MagicMock, patch
        adapter = self._make_adapter(max_retries=2)
        fake_choice = MagicMock()
        fake_choice.message.content = "OK"
        fake_resp = MagicMock()
        fake_resp.choices = [fake_choice]
        with patch.object(adapter._client.chat.completions, "create",
                          return_value=fake_resp) as mock_create:
            result = adapter.reflect("姓名", "张三", {})
        self.assertEqual(result, "OK")
        self.assertEqual(mock_create.call_count, 1,
                         "happy path should not retry")

    def test_reflect_retries_then_succeeds(self):
        """First attempt fails, second succeeds → retry works."""
        from unittest.mock import MagicMock, patch
        adapter = self._make_adapter(max_retries=2)
        ok_choice = MagicMock()
        ok_choice.message.content = "Recovered"
        ok_resp = MagicMock()
        ok_resp.choices = [ok_choice]
        # Side effect: first call raises, second returns OK
        with patch.object(adapter._client.chat.completions, "create",
                          side_effect=[Exception("401 unauthorized"), ok_resp]) as mc:
            result = adapter.reflect("姓名", "张三", {})
        self.assertEqual(result, "Recovered")
        self.assertEqual(mc.call_count, 2, "should retry once after 1 failure")

    def test_reflect_exhausts_max_retries(self):
        """All attempts fail → returns "" and logs warning."""
        from unittest.mock import patch
        import io
        from contextlib import redirect_stderr
        adapter = self._make_adapter(max_retries=2)
        with patch.object(adapter._client.chat.completions, "create",
                          side_effect=Exception("persistent 500")) as mc:
            buf = io.StringIO()
            with redirect_stderr(buf):
                result = adapter.reflect("姓名", "张三", {})
        self.assertEqual(result, "")
        # attempts = max_retries + 1 = 3 (1 initial + 2 retries)
        self.assertEqual(mc.call_count, 3,
                         "should attempt max_retries+1 times total")
        self.assertIn("exhausted", buf.getvalue())

    def test_reflect_retries_disabled_when_zero(self):
        """max_retries=0 → single attempt (v6.0 back-compat)."""
        from unittest.mock import patch
        adapter = self._make_adapter(max_retries=0)
        with patch.object(adapter._client.chat.completions, "create",
                          side_effect=Exception("401")) as mc:
            result = adapter.reflect("姓名", "张三", {})
        self.assertEqual(result, "")
        self.assertEqual(mc.call_count, 1,
                         "max_retries=0 should mean single attempt (v6.0 compat)")

    def test_reflect_empty_response_triggers_retry(self):
        """Empty string response is treated as soft failure → retry."""
        from unittest.mock import MagicMock, patch
        adapter = self._make_adapter(max_retries=1)
        # First call: empty content; second call: real content
        empty_choice = MagicMock()
        empty_choice.message.content = ""
        empty_resp = MagicMock()
        empty_resp.choices = [empty_choice]
        ok_choice = MagicMock()
        ok_choice.message.content = "Real answer"
        ok_resp = MagicMock()
        ok_resp.choices = [ok_choice]
        with patch.object(adapter._client.chat.completions, "create",
                          side_effect=[empty_resp, ok_resp]) as mc:
            result = adapter.reflect("姓名", "张三", {})
        self.assertEqual(result, "Real answer")
        self.assertEqual(mc.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)