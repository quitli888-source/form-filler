#!/usr/bin/env python3
"""Local model adapter tests. All model replies are mocked; no live service."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from model_adapter import OpenAICompatibleAdapter, StubAdapter  # noqa: E402


class TestMinimaxStubComparison(unittest.TestCase):
    """对比 StubAdapter vs OpenAICompatibleAdapter 的行为差异 — 不调网络。"""

    def test_stub_is_not_live(self):
        s = StubAdapter()
        self.assertFalse(s.is_live())
        self.assertEqual(s.reflect("姓名", "张三", {}), "")

    def test_openai_compatible_is_live(self):
        a = OpenAICompatibleAdapter(
            base_url="http://127.0.0.1:11434/v1",
            api_key="dummy",  # 仅 init，不调网络
            model_name="MiniMax-M3",
        )
        self.assertTrue(a.is_live())
        # No live network tests: simulate a failing local model.
        from unittest.mock import patch
        with patch.object(a._client.chat.completions, "create", side_effect=RuntimeError("synthetic")):
            self.assertEqual(a.reflect("姓名", "张三", {}), "")



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
            base_url="http://127.0.0.1:11434/v1",
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
