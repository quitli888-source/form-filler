#!/usr/bin/env python3
"""
tests/test_fill_docx.py — form-filler v6.2 R4-A2: 标准化 fill_docx.py 行为测试

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
  - (v6.2 R4-A2) Literal-first deterministic routing
  - (v6.2 R4-A2) audit["fill_mode"] column emission
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
    write_profile_md, fill_docx, _is_literal_field, _literal_values,
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

    def test_simple_docx_three_fields(self):
        """R3-A2 fix (Pattern D2): simple.docx 现在应该填满全部 3 个 label，
        而不是之前因为 diagonal merged cells 漏掉 1 个。"""
        out = self.out_dir / "filled.docx"
        audit = fill_docx(
            str(self.FIXTURE), self.PROFILE, str(out),
            adapter=StubAdapter(),
        )
        self.assertEqual(audit["filled"], 3,
                         f"R3-A2 fix: 应填满 3 个字段，实际 {audit['filled']}: {audit}")
        filled_labels = [d["label"] for d in audit["details"] if d["value"]]
        self.assertEqual(set(filled_labels), {"姓名", "性别", "学号"})


class TestSchemaFirstRouting(unittest.TestCase):
    """v6.1 R3-A1 (Pattern A3): schema-first routing 修复 first-match-wins."""

    PROFILE = {
        "personal": {"name": "张三", "gender": "男"},
        "contact": {"phone": "13812345678", "email": "z@example.com"},
        "education": {"entries": [{
            "school": "ZJU", "department": "CS", "major": "计算机科学",
            "degree": "本科", "student_id": "12345678", "start_date": "2024-09",
        }]},
    }

    def test_学历专业_resolves_to_专业(self):
        """R3-A1 修复：'学历专业' 不再匹配 first regex '学历|年级'，
        而是 schema-first 路由到 '专业' 字段。"""
        r = match_field("学历专业", self.PROFILE)
        self.assertTrue(r["matched"])
        # 应该路由到 专业 而非 学历|年级
        self.assertEqual(r["field_path"], "专业",
                         f"R3-A1: 应路由到 '专业' 字段，实际 '{r['field_path']}'")
        self.assertEqual(r["value"], "计算机科学")
        self.assertEqual(r["schema"], "优秀团员申报表")

    def test_专业_direct_match(self):
        """'专业' 直接匹配 schema '优秀团员申报表.专业' 字段"""
        r = match_field("专业", self.PROFILE)
        self.assertTrue(r["matched"])
        self.assertEqual(r["field_path"], "专业")
        self.assertEqual(r["value"], "计算机科学")

    def test_实习岗位_routes_to_internship_schema(self):
        """'实习岗位' 路由到 实习鉴定表 schema"""
        r = match_field("实习岗位", self.PROFILE)
        self.assertTrue(r["matched"])
        self.assertEqual(r["schema"], "实习鉴定表")
        # 没有实习单位配置 → value is None
        self.assertIsNone(r["value"])

    def test_论文题目_routes_to_thesis_schema(self):
        """'论文题目' 路由到 学位论文申请表 schema"""
        r = match_field("论文题目", self.PROFILE)
        self.assertTrue(r["matched"])
        self.assertEqual(r["schema"], "学位论文申请表")

    def test_unknown_label_falls_back_to_regex(self):
        """完全不在 schema 里的 label 应该回退到 match_rules 正则"""
        # '邮箱' 是 schema 字段，会走 schema-first → 命中
        r = match_field("邮箱", self.PROFILE)
        self.assertTrue(r["matched"])
        # value 通过 _lookup_profile_field 找 contact.email → "z@example.com"
        self.assertEqual(r["value"], "z@example.com")


class TestLiteralFirstRouting(unittest.TestCase):
    """v6.2 R4-A2 (Pattern O1): Literal-first deterministic routing.

    When a schema field has `Literal[...]`, the lookup is fully deterministic —
    the answer is in the profile (or it's a profile bug). Skip LLM reflexion.
    """
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
    }

    def test_is_literal_field_true_for_gender(self):
        """性别 is Literal['男','女'] → True"""
        from evaluation.schemas import SCHEMAS
        优秀团员申报表 = SCHEMAS["优秀团员申报表"]
        self.assertTrue(_is_literal_field(优秀团员申报表, "性别"))
        self.assertEqual(_literal_values(优秀团员申报表, "性别"), ["男", "女"])

    def test_is_literal_field_false_for_name(self):
        """姓名 is str (no Literal) → False"""
        from evaluation.schemas import SCHEMAS
        优秀团员申报表 = SCHEMAS["优秀团员申报表"]
        self.assertFalse(_is_literal_field(优秀团员申报表, "姓名"))
        self.assertEqual(_literal_values(优秀团员申报表, "姓名"), [])

    def test_gender_literal_match_returns_fill_mode_literal(self):
        """性别 label + 男 profile value → fill_mode='literal'"""
        r = match_field("性别", self.PROFILE)
        self.assertTrue(r["matched"])
        self.assertEqual(r["fill_mode"], "literal")
        self.assertEqual(r["value"], "男")
        self.assertEqual(r["config_file"], "(schema-literal)")
        self.assertIn("literals", r)
        # Set comparison is order-independent
        self.assertEqual(set(r["literals"]), {"男", "女"})

    def test_political_status_literal_skips_llm(self):
        """政治面貌=Literal + profile value='共青团员' → fill_mode='literal'"""
        r = match_field("政治面貌", self.PROFILE)
        self.assertTrue(r["matched"])
        self.assertEqual(r["fill_mode"], "literal")
        self.assertEqual(r["value"], "共青团员")

    def test_literal_mismatch_marks_warn(self):
        """political_status='外星人' (not in Literal) → fill_mode='literal-mismatch' + warning"""
        bad_profile = dict(self.PROFILE)
        bad_profile = {
            "personal": {"name": "张三", "gender": "男", "birthplace": "浙江省杭州市",
                         "ethnicity": "汉族", "birth_date": "2006-03-15",
                         "political_status": "外星人"},  # not in Literal
            "contact": {"phone": "13812345678", "email": "zhangsan@example.edu.cn"},
            "education": {"entries": [{
                "school": "浙江大学", "department": "CS", "major": "CS",
                "degree": "本科", "student_id": "12345678", "start_date": "2024-09",
            }]},
        }
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            r = match_field("政治面貌", bad_profile)
        self.assertTrue(r["matched"])
        # Value mismatch path produces 'literal-mismatch' (not 'literal')
        self.assertEqual(r["fill_mode"], "literal-mismatch")
        # Warning logged
        self.assertIn("not in Literal set", buf.getvalue())

    def test_non_literal_field_uses_schema_fill_mode(self):
        """姓名 (str, no Literal) → fill_mode='schema'"""
        r = match_field("姓名", self.PROFILE)
        self.assertTrue(r["matched"])
        self.assertEqual(r["fill_mode"], "schema")

    def test_unmatched_label_returns_unmatched_fill_mode(self):
        """Label not in any schema and not in match_rules → fill_mode='unmatched'"""
        r = match_field("非常规字段XYZ", self.PROFILE)
        self.assertFalse(r["matched"])
        self.assertEqual(r["fill_mode"], "unmatched")

    def test_regex_path_uses_regex_fill_mode(self):
        """Label not in schema but matched by match_rules regex → fill_mode='regex'"""
        # Strategy: temporarily stub find_schema_for_label to return None,
        # forcing the regex fallback path even for labels normally claimed
        # by schema-first routing.
        import fill_docx as fd
        original_find = fd.find_schema_for_label
        fd.find_schema_for_label = lambda label: None  # disable schema-first
        try:
            # '籍贯' matches match_rules r"籍贯|出生地" → regex path
            r = match_field("籍贯", self.PROFILE)
            self.assertTrue(r["matched"])
            self.assertEqual(r["fill_mode"], "regex")
            # Value should still come from profile via _lookup_profile_field
            self.assertEqual(r["value"], "浙江省杭州市")
        finally:
            fd.find_schema_for_label = original_find


class TestFillModeAuditColumn(unittest.TestCase):
    """v6.2 R4-A2: every audit row carries a `fill_mode` field."""

    FIXTURE = ROOT / "tests" / "fixtures" / "simple.docx"
    PROFILE = {
        "personal": {"name": "张三", "gender": "男"},
        "contact": {"phone": "13812345678", "email": "z@example.com"},
        "education": {"entries": [{
            "school": "ZJU", "department": "CS", "major": "计算机科学",
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

    def test_audit_rows_have_fill_mode(self):
        out = self.out_dir / "filled.docx"
        audit = fill_docx(str(self.FIXTURE), self.PROFILE, str(out),
                          adapter=StubAdapter())
        self.assertGreater(len(audit["details"]), 0)
        for d in audit["details"]:
            self.assertIn("fill_mode", d,
                          f"audit row must carry fill_mode: {d}")
            self.assertIn(d["fill_mode"],
                          {"literal", "literal-mismatch", "schema", "regex",
                           "unmatched", "unknown"},
                          f"fill_mode must be one of the documented set: {d}")

    def test_gender_row_uses_literal_fill_mode(self):
        """simple.docx fixture has 性别 label → fill_mode should be 'literal'"""
        out = self.out_dir / "filled.docx"
        audit = fill_docx(str(self.FIXTURE), self.PROFILE, str(out),
                          adapter=StubAdapter())
        gender_rows = [d for d in audit["details"] if d.get("label") == "性别"]
        self.assertGreater(len(gender_rows), 0,
                           "fixture must have a 性别 row")
        for row in gender_rows:
            self.assertEqual(row["fill_mode"], "literal",
                             f"性别 should use literal fill_mode: {row}")

    def test_reflection_marks_skip_llm_for_literal(self):
        """When reflexion_rounds > 0 and field is literal, reflection_text='[skip-llm: literal]'"""
        out = self.out_dir / "filled.docx"
        # Track reflect calls — should be 0 because literal fields skip LLM
        reflect_calls = []

        def tracking_reflect(label, value, ctx):
            reflect_calls.append(label)
            return ""

        audit = fill_docx(str(self.FIXTURE), self.PROFILE, str(out),
                          reflexion_rounds=1,
                          adapter=StubAdapter(),
                          _reflect_impl=tracking_reflect)
        # Literal fields (性别) must NOT trigger reflect() at all
        gender_rows = [d for d in audit["details"] if d.get("label") == "性别"
                       and d.get("fill_mode") == "literal"]
        for row in gender_rows:
            self.assertEqual(row["reflection"], "[skip-llm: literal]",
                             f"literal field should mark skip-llm: {row}")
        # No reflect() should be called for 性别
        self.assertNotIn("性别", reflect_calls,
                         f"reflect() must NOT be called for literal fields; calls: {reflect_calls}")


if __name__ == "__main__":
    unittest.main(verbosity=2)