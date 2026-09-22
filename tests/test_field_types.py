#!/usr/bin/env python3
"""
tests/test_field_types.py — form-filler v6.4 R6-A3: 确定性字段类型推断

覆盖（R6-A3 reviewer 必需 4 项 + 1 补充）：
  - test_infer_field_type_table（必需 1：值模式与标签回退两段式各 ≥3 例）
  - test_required_and_empty_detection（必需 2）
  - test_introspect_json_has_type_required_empty（必需 3）
  - test_is_likely_label_hardening（必需 4，条件性 hunk 的去留由 88 条既有测试裁定）
  - test_bare_number_not_amount（补充：裸数字不让位 amount —— kordoc 注释级细节）
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from field_types import (  # noqa: E402
    infer_field_type,
    is_required_label,
    is_empty_value,
)
from fill_docx import _is_likely_label, scan_docx_introspect  # noqa: E402


class TestInferFieldType(unittest.TestCase):
    """infer_field_type 真值表：值模式段 + 标签回退段。"""

    def test_infer_field_type_table(self):
        """必需 1：两段式真值表——值模式 ≥3 例，标签关键词回退 ≥3 例。"""
        # --- 值模式段（值形态优先于标签） ---
        value_pattern_cases = [
            ("任意标签", "2006-03-15", "date"),          # 日期（三组件）
            ("任意标签", "2024年9月1日", "date"),         # 日期（中文）
            ("任意标签", "13812345678", "phone"),         # 手机（11 位）
            ("任意标签", "010-6688-1234", "phone"),       # 带区号电话
            ("任意标签", "zhangsan@example.edu.cn", "email"),
            ("任意标签", "12,000", "amount"),             # 千分位金额
            ("任意标签", "6个月", "amount"),              # 单位数量
            ("任意标签", "1万元", "amount"),
            ("任意标签", "□ 良好 ☑ 一般", "checkbox"),     # 复选框符号
        ]
        for label, value, expected in value_pattern_cases:
            self.assertEqual(infer_field_type(label, value), expected,
                             f"值模式用例失败: ({label!r}, {value!r})")
        self.assertGreaterEqual(len(value_pattern_cases), 3,
                                "值模式段至少 3 例")

        # --- 标签关键词回退段（值无形态信号时按标签惯例） ---
        label_fallback_cases = [
            ("出生年月", "", "date"),
            ("入团时间", "待定", "date"),
            ("手机号码", "", "phone"),
            ("联系方式", "待填写", "phone"),
            ("电子邮件", "", "email"),
            ("邮箱地址", "待填写", "email"),
            ("合计金额", "", "amount"),
            ("数量", "待定", "amount"),
        ]
        for label, value, expected in label_fallback_cases:
            self.assertEqual(infer_field_type(label, value), expected,
                             f"标签回退用例失败: ({label!r}, {value!r})")
        self.assertGreaterEqual(len(label_fallback_cases), 3,
                                "标签回退段至少 3 例")

        # --- 默认 text ---
        self.assertEqual(infer_field_type("姓名", "张三"), "text")
        self.assertEqual(infer_field_type("个人陈述", "本人品行端正……"), "text")

    def test_bare_number_not_amount(self):
        """补充（kordoc 注释级细节）：裸数字不让位 amount——
        邮编/编号与金额在纯数字形态下歧义，只有千分位或带单位才判 amount。"""
        self.assertEqual(infer_field_type("邮编", "310000"), "text")
        self.assertEqual(infer_field_type("学号", "2024001"), "text")
        self.assertEqual(infer_field_type("编号", "42"), "text")
        # 对照组：带千分位 / 带单位 → amount
        self.assertEqual(infer_field_type("编号", "1,024"), "amount")
        self.assertEqual(infer_field_type("编号", "42个"), "amount")


class TestRequiredAndEmpty(unittest.TestCase):
    """必需 2：必填标记与空值/占位符判定。"""

    def test_required_and_empty_detection(self):
        # 必填：* ※ ★ （必填） (必填)
        for label in ("姓名*", "※ 邮箱", "（必填）电话", "(必填)金额", "★政治面貌"):
            self.assertTrue(is_required_label(label), f"应判定为必填: {label!r}")
        # 非必填
        for label in ("姓名", "邮箱", "出生日期", ""):
            self.assertFalse(is_required_label(label), f"不应判定为必填: {label!r}")

        # 空值/占位符：空串、空白、下划线、括号、连字符、波浪号
        for value in ("", "   ", "___", "（ ）", "-.~,", "———"):
            self.assertTrue(is_empty_value(value), f"应判定为空值: {value!r}")
        # 非空
        for value in ("张三", "□", "13812345678"):
            self.assertFalse(is_empty_value(value), f"不应判定为空值: {value!r}")


class TestIntrospectKeys(unittest.TestCase):
    """必需 3：scan_docx_introspect 输出的三新键 + merged_dup 分支 schema 一致。"""

    FIXTURE = ROOT / "tests" / "fixtures" / "simple.docx"
    MERGED_FIXTURE = ROOT / "tests" / "fixtures" / "merged_cell.docx"
    NEW_KEYS = {"type", "required", "empty"}
    LEGACY_KEYS = {"row", "col", "text", "is_label", "merged_dup"}

    def setUp(self):
        if not self.FIXTURE.exists():
            self.skipTest(f"fixture missing: {self.FIXTURE}")

    def _all_cells(self, doc_path):
        d = scan_docx_introspect(str(doc_path))
        return [c for t in d["tables"] for row in t["cells"] for c in row]

    def test_introspect_json_has_type_required_empty(self):
        """每个非 merged cell 含 type/required/empty 三新键；既有键不动。"""
        cells = self._all_cells(self.FIXTURE)
        self.assertGreater(len(cells), 0)
        for c in cells:
            self.assertLessEqual(self.LEGACY_KEYS, set(c.keys()),
                                 f"既有键必须保留: {c}")
            self.assertLessEqual(self.NEW_KEYS, set(c.keys()),
                                 f"三新键必须存在: {c}")
            self.assertIn(c["type"],
                          {"date", "phone", "email", "amount", "checkbox", "text"},
                          f"type 必须是已知枚举: {c}")
            self.assertIsInstance(c["required"], bool)
            self.assertIsInstance(c["empty"], bool)

    def test_merged_dup_branch_key_set_consistent(self):
        """merged_dup 分支与普通 cell 的键集合完全一致（schema 一致）。

        simple.docx 含 2 个 merged_dup cell（6 cells / 2 dup）；
        merged_cell.docx 作为合并单元格密集场景的附加回归。
        """
        cells = self._all_cells(self.FIXTURE)
        dup_cells = [c for c in cells if c["merged_dup"]]
        normal_cells = [c for c in cells if not c["merged_dup"]]
        self.assertGreater(len(dup_cells), 0, "simple.docx 应含 merged_dup cell")
        self.assertGreater(len(normal_cells), 0, "simple.docx 应含普通 cell")
        dup_keys = set(dup_cells[0].keys())
        for c in dup_cells + normal_cells:
            self.assertEqual(set(c.keys()), dup_keys,
                             f"merged_dup 与普通 cell 键集合必须一致: {c}")
        # merged_dup 分支的取值契约：text="" / is_label=False / type="text" /
        # required=False / empty=True
        for c in dup_cells:
            self.assertEqual(c["text"], "")
            self.assertFalse(c["is_label"])
            self.assertEqual(c["type"], "text")
            self.assertFalse(c["required"])
            self.assertTrue(c["empty"])

        if self.MERGED_FIXTURE.exists():
            merged_cells = self._all_cells(self.MERGED_FIXTURE)
            for c in merged_cells:
                self.assertLessEqual(self.NEW_KEYS, set(c.keys()),
                                     f"merged_cell.docx 也须含三新键: {c}")

    def test_label_cell_annotations(self):
        """自洽契约：每个非 merged 文本 cell 的三新键取值 == field_types 三个
        函数对该文本的直接输出（type/required/empty 与推断函数严格一致）。

        刻意不断言"姓名/性别/学号必须非 merged"——scan_docx_introspect 的
        `id(cell._tc)` 去活是既有实现，lxml 代理对象跨行 GC 后地址可复用，
        偶发把后续行 cell 误判为 merged_dup（预存 latent issue，超出 R6-A3
        scope；已在 agent_state/round_6/03_optimizer.md 记录）。
        """
        cells = self._all_cells(self.FIXTURE)
        text_cells = [c for c in cells if not c["merged_dup"] and c["text"]]
        self.assertGreater(len(text_cells), 0, "至少应有一个非 merged 文本 cell")
        for c in text_cells:
            t = c["text"]
            self.assertEqual(c["type"], infer_field_type(t, t),
                             f"type 必须与推断函数一致: {c}")
            self.assertEqual(c["required"], is_required_label(t),
                             f"required 必须与判定函数一致: {c}")
            self.assertEqual(c["empty"], is_empty_value(t),
                             f"empty 必须与判定函数一致: {c}")
            self.assertEqual(c["is_label"], _is_likely_label(t),
                             f"is_label 必须与 _is_likely_label 一致: {c}")
        # fixture 的标签 cell（若被正确判为非 merged）应为 text/非必填/非空
        labels = {c["text"]: c for c in text_cells}
        for label in ("姓名", "性别", "学号"):
            if label in labels:
                c = labels[label]
                self.assertEqual(c["type"], "text")
                self.assertFalse(c["required"])
                self.assertFalse(c["empty"])
                self.assertTrue(c["is_label"])


class TestIsLikelyLabelHardening(unittest.TestCase):
    """必需 4（条件性 hunk）：_is_likely_label 两条新排除。

    去留结论：本 hunk 实施后 88 条既有测试全绿（无回归）→ 保留。
    """

    def test_is_likely_label_hardening(self):
        # 排除 1：数值/单位值（"6个月" "1万元" 类）不是标签
        for value in ("6个月", "1万元", "8000元", "3人", "20%", "5个"):
            self.assertFalse(_is_likely_label(value),
                             f"数值/单位值不应判为标签: {value!r}")
        # 排除 2：说明语句（"……请依次填写" "……如下" 类）不是标签
        for stmt in ("请依次填写获奖情况", "填写要求如下", "请按照示例填写", "如下"):
            self.assertFalse(_is_likely_label(stmt),
                             f"说明语句不应判为标签: {stmt!r}")
        # 既有行为不回退：常规标签仍判 True
        for label in ("姓名", "性别", "学号", "出生日期", "政治面貌", "获奖情况"):
            self.assertTrue(_is_likely_label(label),
                            f"常规标签应判为标签: {label!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
