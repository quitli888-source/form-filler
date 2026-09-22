#!/usr/bin/env python3
"""
tests/test_reflexion.py — form-filler v6.4 R6-A1: 反思反馈闭环

背景（已确认缺陷）：v6.3 及以前，fill_docx.py 的多轮反思循环从不把反思原文
回喂给下一轮 reflect 调用；temperature=0.0 下多轮反思任务实质相同
（near-no-op）。R6-A1 在 model_adapter.reflect() 增加 prior_reflections
参数，fill_docx.py 维护 prior_reflections 列表逐轮回喂。

零网络模式：patch.object(adapter._client.chat.completions, "create", ...)
（复用 tests/test_minimax_smoke.py 的手法），不发任何网络请求。

覆盖（R6-A1 reviewer 必需 4 项）：
  - test_round2_prompt_contains_round1_reflection（必需 1）
  - test_single_round_prompt_identical_to_v6_3（必需 2）
  - test_prior_reflections_empty_no_block（必需 3）
  - test_rounds_zero_no_reflect_calls（必需 4）
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fill_docx import fill_docx  # noqa: E402
from model_adapter import OpenAICompatibleAdapter, StubAdapter  # noqa: E402

# v6.3 基线 prompt 模板（逐字节复刻，用于单轮 identical 断言）
_V6_3_BASE_TEMPLATE = (
    "你正在审计一个已填写的表格字段。回答格式：单句陈述；若一切正常回 OK；\n"
    "字段名: {label}\n"
    "当前填入值: {value}\n"
    "同表已填字段:\n"
    "  - filled_so_far: {filled_so_far}\n"
    "请回答 (≤2 句):"
)


class TestReflexionFeedbackLoop(unittest.TestCase):
    """v6.4 R6-A1：多轮反思的 prior_reflections 回喂闭环。

    simple.docx fixture 含 3 个 label（姓名/性别/学号，按此序）：
    性别 是 Literal 字段 → 跳过 LLM 反思；姓名/学号 各触发 reflexion_rounds 轮。
    """

    FIXTURE = ROOT / "tests" / "fixtures" / "simple.docx"
    PROFILE = {
        "personal": {"name": "张三", "gender": "男"},
        "contact": {"phone": "13812345678", "email": "z@example.com"},
        "education": {"entries": [{"student_id": "12345678", "degree": "本科",
                                    "school": "ZJU", "department": "CS",
                                    "major": "CS", "start_date": "2024-09"}]},
    }

    def setUp(self):
        if not self.FIXTURE.exists():
            self.skipTest(f"fixture missing: {self.FIXTURE}")
        self.out_dir = ROOT / "tests" / "_tmp_out"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.out_dir.exists():
            shutil.rmtree(self.out_dir, ignore_errors=True)

    def _make_adapter(self, max_retries=0):
        """零网络 adapter；max_retries=0 → 每轮反思恰好 1 次 create 调用。"""
        return OpenAICompatibleAdapter(
            base_url="https://api.minimax.chat/v1",
            api_key="dummy",  # 仅 init，不调网络
            model_name="MiniMax-M3",
            max_retries=max_retries,
        )

    @staticmethod
    def _fake_create_factory(calls, contents=None):
        """记录调用的 create 替身；contents 为 None 时按调用序号生成"发现问题N"。"""
        def fake_create(**kwargs):
            calls.append(kwargs)
            n = len(calls)
            content = (contents[n - 1] if contents else f"发现问题{n}")
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content=content))]
            return resp
        return fake_create

    def test_round2_prompt_contains_round1_reflection(self):
        """必需 1：reflexion_rounds=2 时，第 2 轮反思 prompt 含第 1 轮反思原文。"""
        adapter = self._make_adapter(max_retries=0)
        calls: list = []
        out = self.out_dir / "reflexion_r2.docx"
        with patch.object(adapter._client.chat.completions, "create",
                          side_effect=self._fake_create_factory(calls)):
            audit = fill_docx(
                str(self.FIXTURE), self.PROFILE, str(out),
                reflexion_rounds=2, adapter=adapter,
            )
        # 姓名 + 学号（性别是 literal 跳过）× 2 轮 = 4 次 reflect 调用
        self.assertEqual(len(calls), 4,
                         f"应有 4 次 reflect 调用，实际 {len(calls)}: {calls}")
        round2_prompt = calls[1]["messages"][0]["content"]
        self.assertIn("之前轮次的反思记录", round2_prompt)
        self.assertIn("发现问题1", round2_prompt,  # 第 1 轮反思原文必须回喂
                      "第 2 轮 prompt 必须携带第 1 轮反思原文")
        self.assertIn("请在上述反思基础上重新审计该字段。", round2_prompt)
        # audit 的反思列取最后一轮非空反思
        name_rows = [d for d in audit["details"] if d["label"] == "姓名"]
        self.assertEqual(len(name_rows), 1)
        self.assertEqual(name_rows[0]["reflection"], "发现问题2")
        self.assertEqual(name_rows[0]["status"], "⚠️")

    def test_single_round_prompt_identical_to_v6_3(self):
        """必需 2：reflexion_rounds=1 时 prompt 与 v6.3 基线逐字节相同
        （无"之前轮次的反思记录"块，无反馈追加）。"""
        adapter = self._make_adapter(max_retries=0)
        calls: list = []
        out = self.out_dir / "reflexion_r1.docx"
        with patch.object(adapter._client.chat.completions, "create",
                          side_effect=self._fake_create_factory(calls, ["OK", "OK"])):
            fill_docx(
                str(self.FIXTURE), self.PROFILE, str(out),
                reflexion_rounds=1, adapter=adapter,
            )
        self.assertEqual(len(calls), 2, "单轮 × 2 个非 literal 字段 = 2 次调用")
        first_prompt = calls[0]["messages"][0]["content"]
        expected = _V6_3_BASE_TEMPLATE.format(
            label="姓名", value="张三", filled_so_far={},
        )
        self.assertEqual(first_prompt, expected,
                         "单轮反思 prompt 必须与 v6.3 基线逐字节相同")
        self.assertNotIn("之前轮次的反思记录", first_prompt)
        self.assertNotIn("Fix the errors", first_prompt)

    def test_prior_reflections_empty_no_block(self):
        """必需 3：adapter.reflect(..., prior_reflections=[]) 与 None 产出相同 prompt
        （空列表不触发反思记录块）。"""
        adapter = self._make_adapter(max_retries=0)
        prompts: list = []
        with patch.object(adapter._client.chat.completions, "create",
                          side_effect=self._fake_create_factory(prompts, ["OK", "OK"])):
            adapter.reflect("姓名", "张三", {"filled_so_far": {}},
                            prior_reflections=None)
            adapter.reflect("姓名", "张三", {"filled_so_far": {}},
                            prior_reflections=[])
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[0], prompts[1],
                         "prior_reflections=None 与 [] 必须产出相同 prompt")
        self.assertNotIn("之前轮次的反思记录", prompts[0])

    def test_rounds_zero_no_reflect_calls(self):
        """必需 4：默认 reflexion_rounds=0 时 reflect 零调用（v5.0 行为）。"""
        reflect_calls: list = []

        def tracking_reflect(label, value, ctx, prior_reflections=None):
            reflect_calls.append(label)
            return ""

        out = self.out_dir / "reflexion_r0.docx"
        audit = fill_docx(
            str(self.FIXTURE), self.PROFILE, str(out),
            adapter=StubAdapter(),
            _reflect_impl=tracking_reflect,
        )
        self.assertEqual(reflect_calls, [],
                         f"reflexion_rounds=0 时不得调用 reflect: {reflect_calls}")
        self.assertEqual(audit["filled"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
