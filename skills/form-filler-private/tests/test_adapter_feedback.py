#!/usr/bin/env python3
"""
tests/test_adapter_feedback.py — form-filler v6.4 R6-A2:
generate_struct 结构化校验错误回喂 + json_repair 可选修复层

复用 tests/test_minimax_smoke.py 的零网络模式：
    patch.object(adapter._client.chat.completions, "create", ...)
不发任何网络请求。为强制走 plain 分支（schema.model_validate_json 路径），
测试把 adapter._instructor_client 置 None——instructor 分支共享同一套
反馈回喂逻辑（_format_validation_feedback），由 test_adapter_self_test
级别的冒烟覆盖。

覆盖（R6-A2 reviewer 必需 3 项 + 1 补充）：
  - test_retry_prompt_contains_validation_errors（必需 1）
  - test_json_repair_fallback（必需 2）
  - test_no_json_repair_matches_v6_3（必需 3）
  - test_first_attempt_prompt_unchanged（补充：硬约束——首 attempt 与 v6.3 逐字节相同）
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pydantic import BaseModel  # noqa: E402

from model_adapter import OpenAICompatibleAdapter, _format_validation_feedback  # noqa: E402


class _DemoModel(BaseModel):
    """测试用最小 schema：姓名 必填 str，年龄 必填 int。"""
    姓名: str
    年龄: int


class TestAdapterFeedback(unittest.TestCase):
    """v6.4 R6-A2：generate_struct 反馈回喂 + json_repair 修复层。"""

    def _make_adapter(self, max_retries=2):
        """构造零网络 adapter 并强制 plain 分支（不走 instructor）。"""
        a = OpenAICompatibleAdapter(
            base_url="http://127.0.0.1:11434/v1",
            api_key="dummy",  # 仅 init，不调网络
            model_name="MiniMax-M3",
            max_retries=max_retries,
        )
        a._instructor_client = None  # 强制 plain JSON 分支
        return a

    @staticmethod
    def _resp(content: str):
        """伪造 chat.completions.create 的返回对象。"""
        choice = MagicMock()
        choice.message.content = content
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    def test_retry_prompt_contains_validation_errors(self):
        """必需 1：第 1 次返回违反 schema 的 JSON（缺 年龄），第 2 次返回合法 JSON。

        断言：第 2 次调用的 messages 含 "validation error" 与
        "Fix the errors and try again."，且最终返回合法 schema 实例。
        """
        adapter = self._make_adapter(max_retries=2)
        bad = '{"姓名": "张三"}'  # 缺必填字段 年龄 → ValidationError
        good = '{"姓名": "张三", "年龄": 18}'
        with patch.object(adapter._client.chat.completions, "create",
                          side_effect=[self._resp(bad), self._resp(good)]) as mc:
            buf = io.StringIO()
            with redirect_stderr(buf):
                result = adapter.generate_struct(_DemoModel, "填一下DemoModel")
        # 最终返回合法 schema 实例
        self.assertIsInstance(result, _DemoModel)
        self.assertEqual(result.姓名, "张三")
        self.assertEqual(result.年龄, 18)
        self.assertEqual(mc.call_count, 2, "1 次失败 + 1 次重试")
        # 第 2 次调用的 messages 携带结构化反馈块
        second_messages = mc.call_args_list[1].kwargs["messages"]
        second_prompt = second_messages[0]["content"]
        self.assertIn("validation error", second_prompt)
        self.assertIn("Fix the errors and try again.", second_prompt)
        self.assertIn("```json", second_prompt)
        # 反馈块是追加的：原始 prompt 仍在前半部分
        self.assertTrue(second_prompt.startswith("填一下DemoModel"))

    def test_json_repair_fallback(self):
        """必需 2：尾逗号 / ```json 围栏两种坏 JSON 在 json_repair 可用时
        均返回合法实例（修复层生效，无需重试）。

        注：尾逗号用例必须是语义完整的 payload（含必填字段 年龄）——
        spec 原文 `'{"姓名": "张三",}'` 缺 年龄，修复后仍无法通过 schema
        校验，无法区分"修复层未生效"与"payload 本身不完整"。
        """
        adapter = self._make_adapter(max_retries=2)
        if adapter._json_repair is None:
            self.skipTest("optional json-repair not installed")
        for canned in ('{"姓名": "张三", "年龄": 18,}',               # 尾逗号（完整）
                       '```json\n{"姓名": "张三", "年龄": 18}\n```'):  # markdown 围栏
            with patch.object(adapter._client.chat.completions, "create",
                              return_value=self._resp(canned)) as mc:
                result = adapter.generate_struct(_DemoModel, "填一下DemoModel")
            self.assertIsInstance(result, _DemoModel,
                                  f"json_repair 应修复: {canned!r}")
            self.assertEqual(result.姓名, "张三")
            self.assertEqual(result.年龄, 18)
            self.assertEqual(mc.call_count, 1, "修复成功不应触发重试")

    def test_no_json_repair_matches_v6_3(self):
        """必需 3：monkeypatch adapter._json_repair = None 后，坏 JSON 下
        行为与 v6.3 一致——重试耗尽 → None + stderr exhausted 警告。

        v6.3 循环语义：attempts = max(1, max_retries)，故 max_retries=2 → 2 次。
        """
        adapter = self._make_adapter(max_retries=2)
        adapter._json_repair = None  # 模拟未安装 json-repair 的环境
        with patch.object(adapter._client.chat.completions, "create",
                          return_value=self._resp('{"姓名": "张三",}')) as mc:
            buf = io.StringIO()
            with redirect_stderr(buf):
                result = adapter.generate_struct(_DemoModel, "填一下DemoModel")
        self.assertIsNone(result)
        self.assertEqual(mc.call_count, 2, "max_retries=2 → 2 次 attempt 后耗尽")
        self.assertIn("exhausted", buf.getvalue())

    def test_first_attempt_prompt_unchanged(self):
        """补充（硬约束）：无失败时（首次 attempt 即成功），发送的 prompt
        与 v6.3 逐字节相同——反馈块不得出现在 happy path。"""
        adapter = self._make_adapter(max_retries=2)
        prompt = "填一下 DemoModel"
        with patch.object(adapter._client.chat.completions, "create",
                          return_value=self._resp('{"姓名": "张三", "年龄": 18}')) as mc:
            result = adapter.generate_struct(_DemoModel, prompt)
        self.assertIsInstance(result, _DemoModel)
        self.assertEqual(mc.call_count, 1)
        sent = mc.call_args_list[0].kwargs["messages"][0]["content"]
        self.assertEqual(sent, prompt)
        self.assertNotIn("Fix the errors and try again.", sent)


class TestFormatValidationFeedback(unittest.TestCase):
    """_format_validation_feedback 的格式单测（pydantic-ai 风格，不引库）。"""

    def test_validation_error_json_block(self):
        """ValidationError → "N validation error(s):" + ```json 围栏 + 指令收尾；
        只含 loc/msg/type，不含 ctx/input/url。"""
        try:
            _DemoModel.model_validate({"姓名": 123})
        except Exception as exc:
            feedback = _format_validation_feedback(exc)
        else:
            self.fail("应触发 ValidationError")
        self.assertIn("validation error(s):", feedback)
        self.assertIn("```json", feedback)
        self.assertIn("Fix the errors and try again.", feedback)
        self.assertIn('"loc"', feedback)
        self.assertIn('"msg"', feedback)
        self.assertIn('"type"', feedback)
        self.assertNotIn('"ctx"', feedback)
        self.assertNotIn('"input"', feedback)
        self.assertNotIn('"url"', feedback)

    def test_plain_exception_message(self):
        """非 ValidationError → str(exc) + 同一指令式收尾。"""
        feedback = _format_validation_feedback(RuntimeError("boom"))
        self.assertNotIn("boom", feedback)
        self.assertTrue(feedback.endswith("Fix the errors and try again."))


if __name__ == "__main__":
    unittest.main(verbosity=2)

