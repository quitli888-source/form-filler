#!/usr/bin/env python3
"""
tests/test_score_consistency.py — form-filler v6.0 R2-A6: 标准化 score_consistency 行为测试

可用 stdlib unittest 运行：
    python -m unittest tests/test_score_consistency.py -v
"""

from __future__ import annotations

import sys
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.score_consistency import (
    parse_audit_md, evaluate, score, evaluate, demo_profile, demo_filled, demo_details,
)


class TestRenameScoreEvaluate(unittest.TestCase):
    """R2-A5: score() 是规范名，evaluate() 是 deprecated alias."""

    def test_score_works(self):
        result = score(demo_profile(), demo_filled(), demo_details())
        self.assertIn("score", result)
        self.assertIn("blocking_errors", result)
        self.assertIn("warnings", result)
        self.assertIn("fill_rate_pct", result)
        self.assertIn("rule_results", result)

    def test_evaluate_deprecated_alias(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = evaluate(demo_profile(), demo_filled(), demo_details())
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0].category, DeprecationWarning)
        self.assertIn("score", result)

    def test_demo_score_100(self):
        # demo intentionally includes 1 MISS (团内职务) to demo status counts;
        # the demo profile passes all 9 rules → score still = 100.
        result = score(demo_profile(), demo_filled(), demo_details())
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["blocking_errors"], 0)
        self.assertEqual(result["warnings"], 0)
        # fill_rate_pct reflects 15/16 = 93.75% (1 MISS out of 16)
        self.assertEqual(result["fill_rate_pct"], 93.8)


class TestParseAuditMd(unittest.TestCase):
    """R2-A5: parse_audit_md 返回 (filled, details, status_counts) 三元组."""

    def test_demo_returns_three_tuple(self):
        # 用 demo_details 自己造一份合法 audit.md
        from pathlib import Path
        import tempfile
        sample_audit = """# 填写对照表 — Demo

## 字段详情
| 序号 | 字段名 | 填入值 | 来源 | 状态 | 自检反思 |
|---|---|---|---|---|---|
| 1 | 姓名 | 张三 | personal.yaml | ✅ | — |
| 2 | 性别 | 男 | personal.yaml | ✅ | — |
| 3 | 手机 | 138****5678 | contact.yaml | ✅ | — |

## 状态统计
| 状态类型 | 数量 | 占比 |
|---|---|---|
| ✅ 自动匹配 | 3 | 100% |
| ❌ 缺失 | 0 | 0% |
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(sample_audit)
            p = Path(f.name)
        try:
            filled, details, status_counts = parse_audit_md(p)
            self.assertIn("姓名", filled)
            self.assertEqual(filled["姓名"], "张三")
            self.assertEqual(len(details), 3)
            self.assertEqual(status_counts.get("✅ 自动匹配"), 3)
            self.assertEqual(status_counts.get("❌ 缺失"), 0)
        finally:
            p.unlink()

    def test_missing_file(self):
        filled, details, status_counts = parse_audit_md(Path("/nonexistent/path/audit.md"))
        self.assertEqual(filled, {})
        self.assertEqual(details, [])
        self.assertEqual(status_counts, {})


class TestRules(unittest.TestCase):
    """9 条规则基础 sanity check。"""

    PROFILE_OK = {
        "personal": {"political_status": "共青团员", "birth_date": "2006-03-15"},
        "education": {"entries": [{"degree": "本科", "start_date": "2024-09"}]},
    }

    def test_r7_political_block(self):
        # 申报优秀团员 + 政治面貌=共青团员 → pass
        filled = {"申报类别": "优秀团员"}
        details = []
        result = score(self.PROFILE_OK, filled, details)
        self.assertEqual(result["score"], 100)

        # 政治面貌=群众 + 申报优秀团员 → R7 fail → score 扣 20
        bad_profile = {**self.PROFILE_OK, "personal": {
            "political_status": "群众", "birth_date": "2006-03-15"}}
        result2 = score(bad_profile, filled, details)
        self.assertEqual(result2["blocking_errors"], 1)
        self.assertEqual(result2["score"], 80)


if __name__ == "__main__":
    unittest.main(verbosity=2)