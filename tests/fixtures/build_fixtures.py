#!/usr/bin/env python3
"""
build_fixtures.py — 生成三份最小合成的 DOCX fixture（不含真实 PII）。
生成的 fixture 仅用作 match_field/match_rules 的端到端测试，
不包含任何真实姓名/手机/学号——值单元格留空或仅写 label 名本身。

用法：
  python tests/fixtures/build_fixtures.py
"""

from pathlib import Path

from docx import Document

HERE = Path(__file__).parent


def build_simple():
    """简单双列表：每行一个 [label][value]"""
    doc = Document()
    table = doc.add_table(rows=3, cols=2)
    pairs = [("姓名", ""), ("性别", ""), ("学号", "")]
    for (label, value), row in zip(pairs, table.rows):
        row.cells[0].text = label
        row.cells[1].text = value
    out = HERE / "simple.docx"
    doc.save(out)
    print(f"  ✓ {out.name}")


def build_merged_cell():
    """含合并单元格的 3x3 表格（label 跨两行右侧合并为 value）"""
    doc = Document()
    table = doc.add_table(rows=3, cols=3)
    table.cell(0, 0).text = "姓名"
    table.cell(0, 1).text = ""
    table.cell(0, 2).text = ""
    # 合并 (1,1) + (1,2) + (2,1) + (2,2) 为一个值单元
    merged = table.cell(1, 1).merge(table.cell(2, 2))
    merged.text = ""
    table.cell(1, 0).text = "专业"
    out = HERE / "merged_cell.docx"
    doc.save(out)
    print(f"  ✓ {out.name}")


def build_multi_match():
    """label 同时命中两条规则的 ambiguous case: '学历专业' 同时命中 学历 和 专业"""
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "学历专业"
    table.cell(0, 1).text = ""
    table.cell(1, 0).text = "学院"
    table.cell(1, 1).text = ""
    out = HERE / "multi_match.docx"
    doc.save(out)
    print(f"  ✓ {out.name}")


def main():
    print("🛠  生成 fixtures (synthetic, no real PII)...")
    build_simple()
    build_merged_cell()
    build_multi_match()
    print("✅ fixtures 生成完成")


if __name__ == "__main__":
    main()