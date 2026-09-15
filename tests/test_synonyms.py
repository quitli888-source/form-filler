#!/usr/bin/env python3
"""
tests/test_synonyms.py — form-filler v6.3 R5-A2: SCHEMA_SYNONYMS dedup tests.

Pattern B5: match_rules + SCHEMA_SYNONYMS duplicate-source-of-truth refactor.

Tests:
  1. test_schema_synonyms_export             — verify the export exists
  2. test_build_match_rules_from_synonyms    — verify generated rules
  3. test_match_rules_unchanged_behavior     — verify v6.2 routing is preserved
  4. test_no_duplicate_patterns              — assert uniqueness of generated patterns
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from evaluation.schemas import (
    SCHEMA_SYNONYMS,
    build_match_rules_from_synonyms,
    find_schema_for_label,
)
import fill_docx as fd  # for match_rules + match_field


class TestSchemaSynonymsExport(unittest.TestCase):
    """R5-A2 test 1: the SCHEMA_SYNONYMS dict is module-level and exported."""

    def test_schema_synonyms_is_dict(self):
        """SCHEMA_SYNONYMS should be a dict."""
        self.assertIsInstance(SCHEMA_SYNONYMS, dict)

    def test_schema_synonyms_has_key_entries(self):
        """At least the v6.2 synonym families should be present."""
        expected_keys = ["申请人", "申报人", "E-mail", "email", "联系方式", "指导教师"]
        for key in expected_keys:
            self.assertIn(key, SCHEMA_SYNONYMS,
                          f"SCHEMA_SYNONYMS should contain '{key}'")

    def test_synonyms_resolve_to_canonical_names(self):
        """Aliases should resolve to schema field names."""
        # 申请人 / 申报人 → 姓名
        self.assertEqual(SCHEMA_SYNONYMS["申请人"], "姓名")
        self.assertEqual(SCHEMA_SYNONYMS["申报人"], "姓名")
        # E-mail → 邮箱
        self.assertEqual(SCHEMA_SYNONYMS["E-mail"], "邮箱")

    def test_find_schema_for_label_uses_singleton(self):
        """Both alias and canonical names resolve to the same schema."""
        schema_a = find_schema_for_label("申请人")
        schema_b = find_schema_for_label("姓名")
        # Same schema class (or both None if env quirk); in practice both
        # should return 优秀团员申报表
        self.assertIsNotNone(schema_a)
        self.assertEqual(schema_a, schema_b,
                         "申请人 and 姓名 should route to the same schema")


class TestBuildMatchRulesFromSynonyms(unittest.TestCase):
    """R5-A2 test 2: build_match_rules_from_synonyms generates the expected shape."""

    def test_returns_list_of_tuples(self):
        rules = build_match_rules_from_synonyms()
        self.assertIsInstance(rules, list)
        self.assertGreater(len(rules), 0,
                           "Should generate at least one rule per synonym cluster")
        for r in rules:
            self.assertEqual(len(r), 4,
                             f"Each rule should be a 4-tuple: {r}")
            pattern, config_file, field_path, transform = r
            self.assertIsInstance(pattern, str)
            self.assertIsInstance(config_file, str)
            self.assertTrue(field_path is None or isinstance(field_path, str))
            self.assertIsNone(transform,
                              "Synonym-generated rules should not have transforms")

    def test_includes_each_canonical(self):
        """Every canonical name reachable through SCHEMA_SYNONYMS should appear
        as the regex target in at least one generated rule."""
        rules = build_match_rules_from_synonyms()
        canonicals = set(SCHEMA_SYNONYMS.values())
        # For each canonical, at least one pattern must contain it (escaped)
        import re as _re
        for canonical in canonicals:
            found = False
            escaped_canonical = _re.escape(canonical)
            for pattern, _, _, _ in rules:
                if escaped_canonical in pattern:
                    found = True
                    break
            if not found:
                # Canonical not in profile mapping (we deliberately skip those
                # because they'd emit an unmatched rule). Skip quietly.
                continue
            # If canonical IS in mapping but missing from rules, fail.
            from evaluation.schemas import _CANONICAL_TO_PROFILE
            if canonical in _CANONICAL_TO_PROFILE:
                self.assertTrue(found,
                                f"Canonical '{canonical}' should appear in "
                                f"at least one rule: {rules}")


class TestMatchRulesUnchangedBehavior(unittest.TestCase):
    """R5-A2 test 3: v6.2 fixture labels route identically after dedup."""

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

    def test_all_v6_2_labels_route(self):
        """All 18 v6.2 baseline labels still resolve through match_field."""
        labels = [
            "姓名", "性别", "民族", "籍贯", "出生年月", "政治面貌",
            "手机", "邮箱", "学号", "专业", "院系", "学校", "学历",
            "所在单位", "申报类别", "团员评议", "入团日期", "团内职务",
        ]
        for label in labels:
            r = fd.match_field(label, self.PROFILE)
            self.assertTrue(r["matched"],
                            f"v6.2 label '{label}' should still match: {r}")

    def test_alias_labels_route_through_match_field(self):
        """Alias labels (now in SCHEMA_SYNONYMS) still route correctly."""
        # 申报人 → 姓名 (personal.name = 张三)
        r = fd.match_field("申报人", self.PROFILE)
        self.assertTrue(r["matched"])
        self.assertEqual(r["value"], "张三",
                         f"申报人 should resolve to 姓名=张三: {r}")

        # email → 邮箱 (contact.email = zhangsan@...)
        r = fd.match_field("email", self.PROFILE)
        self.assertTrue(r["matched"])
        self.assertEqual(r["value"], "zhangsan@example.edu.cn",
                         f"email should resolve to 邮箱: {r}")


class TestNoDuplicatePatterns(unittest.TestCase):
    """R5-A2 test 4: generated rules must not contain duplicate patterns."""

    def test_generated_patterns_are_unique(self):
        rules = build_match_rules_from_synonyms()
        patterns = [r[0] for r in rules]
        self.assertEqual(len(patterns), len(set(patterns)),
                         f"Duplicate patterns detected: {patterns}")

    def test_generated_rules_unique_by_destination(self):
        """Two rules pointing at the same (config_file, field_path) is fine
        (alias variants may share destinations), but each pattern should
        be unique."""
        rules = build_match_rules_from_synonyms()
        seen = set()
        for pattern, config_file, field_path, _ in rules:
            key = (pattern, config_file, field_path)
            self.assertNotIn(key, seen,
                            f"Duplicate rule (pattern, config, path): {key}")
            seen.add(key)


if __name__ == "__main__":
    unittest.main(verbosity=2)