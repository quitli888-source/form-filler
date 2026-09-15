#!/usr/bin/env python3
"""
tests/test_mock_llm.py — form-filler v6.2 R4-A3: MockLLMAdapter unit tests

Pattern G2 (microsoft/guidance): deterministic offline test backend.

可用 stdlib unittest 运行：
    python -m unittest tests/test_mock_llm.py -v

覆盖：
  - MockLLMAdapter 直接行为（reflect / generate_struct）
  - 工厂函数 get_adapter("mock", canned_responses=...)
  - is_live() 区分 stub vs mock
  - 与 fill_docx 集成（不需要网络）
  - retry + mock 联合：mock 可以模拟"先失败后成功"
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from model_adapter import MockLLMAdapter, StubAdapter, get_adapter  # noqa: E402


class TestMockLLMDirect(unittest.TestCase):
    """R4-A3: MockLLMAdapter 直接构造与行为。"""

    def test_empty_canned_returns_empty_string(self):
        m = MockLLMAdapter(canned_responses={})
        self.assertEqual(m.reflect("姓名", "张三", {}), "")

    def test_canned_label_returns_canned_response(self):
        m = MockLLMAdapter(canned_responses={"姓名": "名字过长，请缩短"})
        self.assertEqual(m.reflect("姓名", "张", {}), "名字过长，请缩短")

    def test_substring_match_falls_back(self):
        """label '申请人姓名' should match canned key '姓名' via substring."""
        m = MockLLMAdapter(canned_responses={"姓名": "OK"})
        self.assertEqual(m.reflect("申请人姓名", "张", {}), "OK")

    def test_unknown_label_returns_empty(self):
        m = MockLLMAdapter(canned_responses={"已知字段": "x"})
        self.assertEqual(m.reflect("未知字段", "v", {}), "")

    def test_is_live_true_for_mock(self):
        """MockLLM is a *fake* LLM (deterministic responses), not a stub.
        is_live() returns True so tests can distinguish from StubAdapter."""
        m = MockLLMAdapter()
        self.assertTrue(m.is_live())

    def test_generate_struct_lookup_by_sha256_prefix(self):
        """generate_struct() looks up 'sha256:<hex-of-prompt[:200]>' key."""
        prompt = "这是一段测试 prompt, " * 20
        digest = hashlib.sha256(prompt[:200].encode("utf-8")).hexdigest()
        key = f"sha256:{digest}"
        # Pydantic schema for validation
        try:
            from pydantic import BaseModel
            class Demo(BaseModel):
                msg: str
                n: int
        except ImportError:
            self.skipTest("pydantic not installed")
        canned_json = json.dumps({"msg": "mock 回应", "n": 42}, ensure_ascii=False)
        m = MockLLMAdapter(canned_responses={key: canned_json})
        result = m.generate_struct(Demo, prompt)
        self.assertIsNotNone(result)
        self.assertEqual(result.msg, "mock 回应")
        self.assertEqual(result.n, 42)

    def test_generate_struct_miss_returns_none(self):
        """generate_struct() on miss → None (graceful degrade)."""
        try:
            from pydantic import BaseModel
            class Demo(BaseModel):
                msg: str
        except ImportError:
            self.skipTest("pydantic not installed")
        m = MockLLMAdapter(canned_responses={})  # no keys
        self.assertIsNone(m.generate_struct(Demo, "any prompt"))

    def test_max_retries_zero(self):
        """MockLLM should never retry (deterministic)."""
        m = MockLLMAdapter()
        self.assertEqual(m.max_retries, 0)

    def test_init_prints_yellow_warning(self):
        """Init prints '🔶 MockLLM' warning so production misconfig is loud."""
        buf = io.StringIO()
        with redirect_stderr(buf):
            MockLLMAdapter()
        self.assertIn("MockLLM", buf.getvalue())
        self.assertIn("not a real LLM", buf.getvalue())


class TestMockProviderFactory(unittest.TestCase):
    """R4-A3: get_adapter('mock', ...) returns MockLLMAdapter."""

    def test_factory_dispatches_mock_provider(self):
        a = get_adapter("mock", canned_responses={"姓名": "OK"})
        self.assertIsInstance(a, MockLLMAdapter)
        self.assertEqual(a.name, "mock")
        self.assertEqual(a.reflect("姓名", "x", {}), "OK")

    def test_factory_aliases(self):
        """get_adapter accepts 'mock', 'mock-llm', 'mockllm'."""
        for alias in ("mock", "mock-llm", "mockllm"):
            a = get_adapter(alias)
            self.assertIsInstance(a, MockLLMAdapter, f"alias '{alias}' failed")

    def test_factory_without_canned_uses_empty(self):
        a = get_adapter("mock")
        self.assertEqual(a.canned_responses, {})
        self.assertEqual(a.reflect("anything", "value", {}), "")

    def test_factory_does_not_dispatch_unknown(self):
        """Existing v5.0/v6.1 providers still work."""
        s = get_adapter("stub")
        self.assertIsInstance(s, StubAdapter)


class TestMockVsStub(unittest.TestCase):
    """R4-A3: differentiate StubAdapter (zero output) from MockLLMAdapter (deterministic)."""

    def test_stub_always_empty(self):
        s = StubAdapter()
        self.assertFalse(s.is_live())
        self.assertEqual(s.reflect("姓名", "x", {}), "")
        self.assertEqual(s.reflect("任意", "y", {"filled_so_far": {}}), "")

    def test_mock_with_canned_returns_non_empty(self):
        m = MockLLMAdapter(canned_responses={"姓名": "non-empty"})
        self.assertTrue(m.is_live())
        self.assertEqual(m.reflect("姓名", "x", {}), "non-empty")

    def test_both_have_max_retries_zero(self):
        """Both stub and mock are deterministic; only OpenAI gets retries."""
        self.assertEqual(StubAdapter().max_retries, 0)
        self.assertEqual(MockLLMAdapter().max_retries, 0)


class TestMockWithFillDocx(unittest.TestCase):
    """R4-A3: MockLLMAdapter 集成进 fill_docx，无网络仍能跑通 reflexion 路径。"""

    FIXTURE = ROOT / "tests" / "fixtures" / "simple.docx"
    PROFILE = {
        "personal": {"name": "张三", "gender": "男"},
        "contact": {"phone": "13812345678", "email": "z@example.com"},
        "education": {"entries": [{
            "school": "ZJU", "department": "CS", "major": "CS",
            "degree": "本科", "student_id": "12345678", "start_date": "2024-09",
        }]},
    }

    def setUp(self):
        if not self.FIXTURE.exists():
            self.skipTest(f"fixture missing: {self.FIXTURE}")
        self.out_dir = ROOT / "tests" / "_tmp_out"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        if self.out_dir.exists():
            shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_fill_docx_with_mock_adapter(self):
        """fill_docx should accept MockLLMAdapter as `adapter=` param."""
        from fill_docx import fill_docx
        out = self.out_dir / "filled.docx"
        m = MockLLMAdapter(canned_responses={"姓名": "OK"})
        audit = fill_docx(str(self.FIXTURE), self.PROFILE, str(out),
                          reflexion_rounds=1,
                          adapter=m)
        self.assertGreater(audit["filled"], 0)
        # 性别 should be skipped (literal), 姓名 should be in reflection
        # but mock returns '' for label not in canned → no ⚠️ in audit
        for d in audit["details"]:
            self.assertIn("fill_mode", d)

    def test_mock_adapter_warns_in_stderr_on_construction(self):
        """Construction should print yellow warning so accidental prod use is loud."""
        buf = io.StringIO()
        with redirect_stderr(buf):
            MockLLMAdapter(canned_responses={"x": "y"})
        self.assertIn("MockLLM", buf.getvalue())


class TestMockProviderErrorPath(unittest.TestCase):
    """R4-A3: 错误处理路径。"""

    def test_generate_struct_invalid_json_returns_none(self):
        """Canned response is invalid JSON → None (graceful degrade)."""
        try:
            from pydantic import BaseModel
            class Demo(BaseModel):
                msg: str
        except ImportError:
            self.skipTest("pydantic not installed")
        m = MockLLMAdapter(canned_responses={"sha256:dummy": "{ not valid json"})
        # Empty prompt → digest computed on ''; need to actually trigger.
        # Use a sha256 key corresponding to a real prompt.
        prompt = "test prompt"
        digest = hashlib.sha256(prompt[:200].encode("utf-8")).hexdigest()
        key = f"sha256:{digest}"
        m2 = MockLLMAdapter(canned_responses={key: "{ bad json"})
        # Should print warning + return None (not raise)
        buf = io.StringIO()
        with redirect_stderr(buf):
            result = m2.generate_struct(Demo, prompt)
        self.assertIsNone(result)
        self.assertIn("validation failed", buf.getvalue())

    def test_get_adapter_mock_with_no_kwargs_does_not_error(self):
        """get_adapter('mock') with no canned_responses → empty canned, no error."""
        a = get_adapter("mock")
        self.assertIsInstance(a, MockLLMAdapter)
        self.assertEqual(a.canned_responses, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)