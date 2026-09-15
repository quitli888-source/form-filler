#!/usr/bin/env python3
"""
scripts/validate_rules.py — form-filler 规则层离线校验器 (v5.0, Pattern E)

目的：在不依赖真实 DOCX / LLM 的前提下，对 fill_docx.py 的 match_field 规则层
做可重复的回归测试。

模式：
  --mock           用 3 个内置合成 fixture（good / missing / ambiguous）跑一遍
  --input PATH     从 JSON 文件加载 fixture 列表（格式见 tests/fixtures/README.md）

每个 fixture = 一个 dict，至少包含：
  {
    "name": "fixture label",
    "labels": ["姓名", "性别", ...],          # 表格中出现的标签
    "profile": {"personal": {...}, ...},     # 合成的 YAML profile
    "expected": [...]                        # （可选）每个标签的期望结果
  }

输出：每个 fixture 一行 OK / WARN: ... / FAIL: ...，结尾汇总。
退出码：FAIL 数 > 0 时返回 1，否则返回 0。

依赖：标准库 + PyYAML（项目已要求）。
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 让脚本作为模块被导入时，能找到同目录的 fill_docx
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fill_docx import match_field, match_rules  # noqa: E402


# ---------------------------------------------------------------------------
# 3 个内置 mock fixtures（无真实 PII）
# 覆盖 good / missing-value / multi-match-ambiguous 三类场景
# ---------------------------------------------------------------------------

MOCK_FIXTURES = [
    {
        "name": "good_simple",
        "description": "简单行：姓名/性别/手机/邮箱/学号 — 所有标签一次命中",
        "labels": ["申报人姓名", "性别", "手机", "邮箱", "学号"],
        "profile": {
            "personal": {"name": "<synth-name>", "gender": "<synth-gender>"},
            "contact": {"phone": "13800000000", "email": "synth@example.com"},
            "education": {"entries": [{"student_id": "2025000000", "degree": "本科"}]},
        },
    },
    {
        "name": "missing_value",
        "description": "规则命中但 profile 中无对应字段值（MISS 路径）",
        "labels": ["姓名", "民族", "籍贯"],
        "profile": {
            "personal": {"name": "<synth-name>"},  # gender/ethnicity/birthplace 缺失
        },
    },
    {
        "name": "ambiguous_first_match",
        "description": "同一标签触发多条规则（已知缺陷 #2：first-match-wins）",
        "labels": ["学历专业", "所在单位院系"],
        "profile": {
            "education": {
                "entries": [
                    {
                        "degree": "本科",
                        "major": "<synth-major>",
                        "department": "<synth-department>",
                        "school": "<synth-school>",
                        "start_date": "2025-09",
                    }
                ]
            }
        },
    },
]


def _all_matching_rules(label: str):
    """找出所有匹配该 label 的规则 pattern 列表（用于检测 ambiguous）。"""
    hits = []
    for pattern, *_ in match_rules:
        if re.search(pattern, label):
            hits.append(pattern)
    return hits


def run_fixture(fixture: dict) -> dict:
    """对单个 fixture 跑 match_field，返回 {verdict, ambiguous, unmatched, details}。"""
    name = fixture.get("name", "unnamed")
    labels = fixture.get("labels", [])
    profile = fixture.get("profile", {})

    ambiguous_labels = []
    unmatched_labels = []
    matched_no_value = []

    for label in labels:
        result = match_field(label, profile)
        all_hits = _all_matching_rules(label)
        if len(all_hits) > 1:
            ambiguous_labels.append((label, all_hits))
        if not result["matched"]:
            unmatched_labels.append(label)
            continue
        if result.get("value") in (None, ""):
            matched_no_value.append(label)

    # 优先级：unmatched > matched-no-value > ambiguous
    if unmatched_labels:
        verdict = "FAIL"
        note = f"no rule matched for {unmatched_labels}"
    elif matched_no_value:
        verdict = "FAIL"
        note = f"matched but no value for {matched_no_value}"
    elif ambiguous_labels:
        verdict = "WARN"
        first = ambiguous_labels[0]
        note = f"ambiguous match on \"{first[0]}\" → {first[1]}"
    else:
        verdict = "OK"
        note = "all labels matched with values"

    return {
        "name": name,
        "verdict": verdict,
        "note": note,
        "labels_tested": len(labels),
        "ambiguous": len(ambiguous_labels),
        "unmatched": len(unmatched_labels),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="form-filler v5.0 规则层离线校验器")
    parser.add_argument("--mock", action="store_true",
                        help="用内置 3 个合成 fixture (good / missing / ambiguous) 跑一遍")
    parser.add_argument("--input", default=None,
                        help="JSON fixture 文件路径（list 或单个 fixture dict）")
    args = parser.parse_args()

    if args.mock or not args.input:
        fixtures = MOCK_FIXTURES
        if not args.mock:
            print("ℹ️ 未指定 --input，使用 --mock（内置 3 个 fixture）", file=sys.stderr)
    else:
        with open(args.input, "r", encoding="utf-8") as f:
            fixtures = json.load(f)
        if isinstance(fixtures, dict):
            fixtures = [fixtures]

    print(f"🔧 validate_rules.py — 跑 {len(fixtures)} 个 fixture\n")
    summary = {"OK": 0, "WARN": 0, "FAIL": 0}
    for fx in fixtures:
        r = run_fixture(fx)
        summary[r["verdict"]] += 1
        print(f"  {r['verdict']:4}  {r['name']:24}  {r['note']}")
    print(f"\n📊 汇总: OK={summary['OK']}  WARN={summary['WARN']}  FAIL={summary['FAIL']}")
    return 0 if summary["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
