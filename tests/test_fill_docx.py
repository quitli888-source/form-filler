#!/usr/bin/env python3
"""
tests/test_fill_docx.py — form-filler v6.0 R2-A6: 标准化 fill_docx.py 行为测试

可用 stdlib unittest 运行（无需 pytest 依赖）：
    python -m unittest tests/test_fill_docx.py -v
或 pytest：
    pytest tests/ -v

覆盖：
  - match_field 路由（已有 fixture 数据）
  - _stub_reflect 保持 v5.0 行为（返回 ""）
  - _redact PII 脱敏（手机/邮箱/身份证/银行卡）
  - scan_docx_introspect 输出 JSON 结构
  - fill_docx 主流程（stub adapter + fixtures）
  - model_adapter factory (get_adapter)
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# 让 tests/ 能 import scripts/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from fill_docx import (
    _redact, _stub_reflect, match_field, scan_docx_introspect,
    write_profile_md, fill_docx,
)
from model_adapter import StubAdapter, OpenAICompatibleAdapter, get_adapter


class TestMatchField(unittest.TestCase):
    """match_field 路由：覆盖 v5.0 已通过的 case。"""

    PROFILE = {
        "personal": {"name": "张三", "gender": "男", "birthplace": "浙江省杭州市",
                     "ethnicity": "汉族", "birth_date": "2006-03-15",
                     "political_status": "共青团员"},
        "contact": {"phone": "13812345678", "email": "zhangsan@example.edu.cn"},
        "education": {"entries": [{
            "school": "浙江大学", "department": "计算机科学与技术学院",
            "major": "计算机科学与技术", "degree": "本科",
            "student_id": "12345678", "start_date": "2024-09",
        }]},
        "league": {"league_evaluation": "优秀", "league_join_date": "2019-05",
                   "league_position": "组织委员"},
    }

    def test_name(self):
        r = match_field("申报人姓名", self.PROFILE)
        self.assertTrue(r["matched"])
        self.assertEqual(r["value"], "张三")

    def test_gender(self):
        r = match_field("性别", self.PROFILE)
        self.assertEqual(r["value"], "男")

    def test_phone(self):
        r = match_field("手机", self.PROFILE)
        self.assertEqual(r["value"], "13812345678")

    def test_school(self):
        r = match_field("学校", self.PROFILE)
        self.assertEqual(r["value"], "浙江大学")

    def test_unmatched(self):
        r = match_field("非标字段名XYZ", self.PROFILE)
        self.assertFalse(r["matched"])


class TestStubReflect(unittest.TestCase):
    """v5.0 back-compat: _stub_reflect must return empty string."""

    def test_empty(self):
        self.assertEqual(_stub_reflect("姓名", "张三", {}), "")
        self.assertEqual(_stub_reflect("任意字段", "任意值", {"已填": "X"}), "")


class TestPIIRedact(unittest.TestCase):
    """v6.0 R2-A4: PII 脱敏单元测试。"""

    def test_phone(self):
        self.assertEqual(_redact("我的手机是13812345678"), "我的手机是138****5678")

    def test_email(self):
        self.assertEqual(_redact("邮箱：zhangsan@example.edu.cn"),
                         "邮箱：***@example.edu.cn")

    def test_id_number(self):
        self.assertEqual(_redact("身份证110101200603151234"),
                         "身份证110101********1234")

    def test_no_pii(self):
        # 普通文本不应被改
        self.assertEqual(_redact("张三"), "张三")
        self.assertEqual(_redact(""), "")

    def test_keeps_partial_digits(self):
        # 学号 8 位不应被误判
        self.assertEqual(_redact("学号 12345678"), "学号 12345678")


class TestScanIntrospect(unittest.TestCase):
    """v6.0 R2-A3 (Pattern J): introspect JSON 结构。"""

    FIXTURE = ROOT / "tests" / "fixtures" / "simple.docx"

    def setUp(self):
        if not self.FIXTURE.exists():
            self.skipTest(f"fixture missing: {self.FIXTURE}")

    def test_returns_dict(self):
        d = scan_docx_introspect(str(self.FIXTURE))
        self.assertIn("template", d)
        self.assertIn("scanned_at", d)
        self.assertIn("tables", d)
        self.assertIsInstance(d["tables"], list)
        self.assertGreater(len(d["tables"]), 0)

    def test_first_table_has_rows(self):
        d = scan_docx_introspect(str(self.FIXTURE))
        t0 = d["tables"][0]
        self.assertIn("rows", t0)
        self.assertIn("cols", t0)
        self.assertIn("cells", t0)
        self.assertGreater(t0["rows"], 0)
        self.assertGreater(t0["cols"], 0)

    def test_labels_extracted(self):
        d = scan_docx_introspect(str(self.FIXTURE))
        self.assertIn("labels", d)
        # fixture 中至少有 1 个 label
        self.assertGreater(len(d["labels"]), 0)


class TestModelAdapter(unittest.TestCase):
    """v6.0 R2-A1: ModelAdapter factory."""

    def test_stub_default(self):
        a = get_adapter("stub")
        self.assertIsInstance(a, StubAdapter)
        self.assertFalse(a.is_live())
        self.assertEqual(a.reflect("姓名", "张三", {}), "")

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            get_adapter("bogus")

    def test_openai_compatible_requires_key(self):
        # 没 key 就 ValueError
        os.environ.pop("LLM_API_KEY", None)
        with self.assertRaises(ValueError):
            OpenAICompatibleAdapter(api_key="")

    def test_openai_compatible_requires_openai(self):
        # openai 缺失会 ImportError（在我们环境里装了，所以跳过）
        try:
            import openai  # noqa
            self.skipTest("openai installed; cannot test ImportError path")
        except ImportError:
            with self.assertRaises(ImportError):
                OpenAICompatibleAdapter(api_key="dummy")


class TestFillDocxEnd2End(unittest.TestCase):
    """v6.0 R2-A1+A2: 端到端跑一次 fill_docx。"""

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
        # 清理临时输出
        import shutil
        if self.out_dir.exists():
            shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_end_to_end(self):
        out = self.out_dir / "filled.docx"
        audit = fill_docx(
            str(self.FIXTURE), self.PROFILE, str(out),
            adapter=StubAdapter(),
        )
        self.assertGreater(audit["filled"], 0,
                           "应至少填一个字段（姓名/性别/学号等）")
        # v6.0: PII 脱敏生效
        for d in audit["details"]:
            v = str(d.get("value", ""))
            self.assertNotIn("13812345678", v,
                             f"audit details 应不含明文手机号: {d}")
            self.assertNotIn("z@example.com", v,
                             f"audit details 应不含明文邮箱: {d}")

    def test_reflexion_stub_no_warning(self):
        """reflexion_rounds=1 + StubAdapter → audit 里不应出现 ⚠️（stub 返回 ""）"""
        out = self.out_dir / "filled.docx"
        audit = fill_docx(
            str(self.FIXTURE), self.PROFILE, str(out),
            reflexion_rounds=1,
            adapter=StubAdapter(),
        )
        warn_count = sum(1 for d in audit["details"] if d["status"] == "⚠️")
        self.assertEqual(warn_count, 0,
                         f"StubAdapter 反射空字符串，不应触发 ⚠️: {audit}")


if __name__ == "__main__":
    unittest.main(verbosity=2)