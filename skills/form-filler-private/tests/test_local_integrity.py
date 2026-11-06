"""Regression checks for local fill integrity, formatting and profile-free inspection."""
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import date
import pytest

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.shared import Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fill_docx import fill_docx, scan_docx_introspect

PROFILE = {"personal": {"name": "合成姓名", "gender": "男"}}


def template(tmp_path, cells):
    doc = Document()
    table = doc.add_table(rows=len(cells), cols=len(cells[0]))
    for r, row in enumerate(cells):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    path = tmp_path / "template.docx"
    doc.save(path)
    return path


def test_existing_values_and_adjacent_labels_are_preserved(tmp_path):
    source = template(tmp_path, [["姓名", "原有姓名"], ["姓名", "性别"]])
    before = source.read_bytes()
    output = tmp_path / "filled.docx"
    audit = fill_docx(str(source), PROFILE, str(output))
    doc = Document(output)
    assert [[c.text for c in row.cells] for row in doc.tables[0].rows] == [["姓名", "原有姓名"], ["姓名", "性别"]]
    assert audit["filled"] == 0
    assert source.read_bytes() == before


def test_occupied_right_cell_does_not_redirect_value_to_blank_below(tmp_path):
    source = template(tmp_path, [["姓名", "已填写"], ["", ""]])
    output = tmp_path / "filled.docx"
    fill_docx(str(source), PROFILE, str(output))
    doc = Document(output)
    assert doc.tables[0].cell(1, 0).text == ""
    assert doc.tables[0].cell(0, 1).text == "已填写"


def test_newly_filled_value_is_not_processed_as_another_label(tmp_path):
    source = template(tmp_path, [["姓名", ""]])
    audit = fill_docx(str(source), PROFILE, str(tmp_path / "filled.docx"))
    assert audit["filled"] == 1
    assert audit["missed"] == 0
    assert len(audit["details"]) == 1


def test_horizontal_merged_label_fills_first_distinct_right_cell(tmp_path):
    doc = Document()
    table = doc.add_table(rows=1, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "姓名"
    source = tmp_path / "merged.docx"
    doc.save(source)
    output = tmp_path / "filled.docx"
    audit = fill_docx(str(source), PROFILE, str(output))
    result = Document(output).tables[0]
    assert result.cell(0, 0).text == "姓名"
    assert result.cell(0, 2).text == "合成姓名"
    assert audit["filled"] == 1


def test_empty_value_retains_paragraph_and_run_formatting(tmp_path):
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "姓名"
    paragraph = table.cell(0, 1).paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("")
    run.bold = True
    run.font.name = "Arial"
    run.font.size = Pt(16)
    run.font.color.rgb = RGBColor(0x12, 0x34, 0x56)
    source = tmp_path / "styled.docx"
    doc.save(source)
    output = tmp_path / "filled.docx"
    fill_docx(str(source), PROFILE, str(output))
    p = Document(output).tables[0].cell(0, 1).paragraphs[0]
    assert p.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert p.runs[0].bold
    assert p.runs[0].font.name == "Arial"
    assert p.runs[0].font.size == Pt(16)
    assert p.runs[0].font.color.rgb == RGBColor(0x12, 0x34, 0x56)


def test_text_empty_drawing_cell_is_not_overwritten(tmp_path):
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "姓名"
    table.cell(0, 1).paragraphs[0].add_run()._r.append(OxmlElement("w:drawing"))
    source = tmp_path / "drawing.docx"
    doc.save(source)
    output = tmp_path / "filled.docx"
    audit = fill_docx(str(source), PROFILE, str(output))
    cell = Document(output).tables[0].cell(0, 1)
    assert cell.text == ""
    assert len(cell._tc.xpath(".//w:drawing")) == 1
    assert audit["filled"] == 0


def test_ok_reflection_does_not_mark_valid_value_as_warning(tmp_path):
    source = template(tmp_path, [["姓名", ""]])
    audit = fill_docx(str(source), PROFILE, str(tmp_path / "filled.docx"),
                      reflexion_rounds=2, _reflect_impl=lambda *args: " OK。 ")
    assert audit["details"][0]["status"] == "✅"
    assert not audit["details"][0]["reflection"]


def test_multitable_scan_retains_actual_table_indices(tmp_path):
    doc = Document()
    for label in ("姓名", "性别"):
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = label
    source = tmp_path / "tables.docx"
    doc.save(source)
    assert [(x["table"], x["text"]) for x in scan_docx_introspect(str(source))["labels"]] == [(0, "姓名"), (1, "性别")]


def test_scan_only_needs_neither_profiles_nor_model(tmp_path):
    source = template(tmp_path, [["姓名", ""]])
    scan = tmp_path / "scan.json"
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts/fill_docx.py"),
         "--template", str(source), "--scan-only", "--profile-dir", str(tmp_path / "not-present"),
         "--provider", "local-model", "--llm-base-url", "https://provider.example/v1",
         "--introspect-out", str(scan)],
        cwd=tmp_path, text=True, encoding="utf-8", capture_output=True,
    )
    assert proc.returncode == 0
    assert scan.exists()
    assert "姓名" in scan.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*_audit.md"))


def test_audit_default_template_is_relative_to_installation(tmp_path):
    source = template(tmp_path, [["姓名", ""]])
    profile = tmp_path / "profiles"
    profile.mkdir()
    (profile / "personal.yaml").write_text("name: 合成姓名", encoding="utf-8")
    output = tmp_path / "filled.docx"
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts/fill_docx.py"),
         "--template", str(source), "--profile-dir", str(profile), "--output", str(output)],
        cwd=tmp_path, text=True, encoding="utf-8", capture_output=True,
    )
    assert proc.returncode == 0
    assert output.exists()
    audit = tmp_path / "filled_audit.md"
    assert audit.exists()
    assert "合成姓名" not in audit.read_text(encoding="utf-8")


def test_existing_value_containing_school_keyword_is_never_a_write_label(tmp_path):
    source = template(tmp_path, [["学校", "某某高等专科学校", ""]])
    output = tmp_path / "filled.docx"
    profile = {"education": {"entries": [{"school": "合成大学"}]}}
    audit = fill_docx(str(source), profile, str(output))
    assert [c.text for c in Document(output).tables[0].rows[0].cells] == ["学校", "某某高等专科学校", ""]
    assert audit["filled"] == 0


def test_explicit_labels_accept_required_markers_spaces_and_aliases(tmp_path):
    source = template(tmp_path, [["姓名（必填）*", "", "性 别：", ""], ["E-mail", "", "", ""]])
    output = tmp_path / "filled.docx"
    profile = {**PROFILE, "contact": {"email": "synthetic@example.edu"}}
    audit = fill_docx(str(source), profile, str(output))
    doc = Document(output)
    assert doc.tables[0].cell(0, 1).text == "合成姓名"
    assert doc.tables[0].cell(0, 3).text == "男"
    assert doc.tables[0].cell(1, 1).text == "synthetic@example.edu"
    assert audit["filled"] == 3


def test_cohort_uses_known_date_but_degree_does_not_choose_application_category(tmp_path):
    source = template(tmp_path, [["学历年级", ""], ["申报类别", ""], ["学历", ""]])
    output = tmp_path / "filled.docx"
    profile = {"education": {"entries": [{"degree": "本科", "start_date": date(2024, 9, 1)}]}}
    audit = fill_docx(str(source), profile, str(output))
    result = Document(output).tables[0]
    assert result.cell(0, 1).text == "24级本科生"
    assert result.cell(1, 1).text == ""
    assert result.cell(2, 1).text == "本科"
    assert audit["filled"] == 2


@pytest.mark.parametrize("entry", [
    {"degree": "未知学历", "start_date": "2024-09"},
    {"start_date": "2024-09"},
    {"degree": "本科"},
    {"degree": "本科", "start_date": "2024-02-31"},
])
def test_cohort_does_not_guess_missing_unknown_or_invalid_education(tmp_path, entry):
    source = template(tmp_path, [["学历年级", ""], ["申报类别", ""]])
    output = tmp_path / "filled.docx"
    audit = fill_docx(str(source), {"education": {"entries": [entry]}}, str(output))
    assert Document(output).tables[0].cell(0, 1).text == ""
    assert Document(output).tables[0].cell(1, 1).text == ""
    assert audit["filled"] == 0


@pytest.mark.parametrize("profile", [
    {"personal": {"申报类别": "优秀团员"}, "education": {"entries": [{"degree": "本科"}]}},
    {"education": {"entries": [{"degree": "本科", "application_category": "优秀团员"}]}},
])
def test_explicit_legal_application_category_has_priority(tmp_path, profile):
    source = template(tmp_path, [["申报类别", ""]])
    output = tmp_path / "filled.docx"
    audit = fill_docx(str(source), profile, str(output))
    assert Document(output).tables[0].cell(0, 1).text == "优秀团员"
    assert audit["details"][0]["status"] == "✅"


def test_invalid_literal_is_not_written_or_sent_for_reflection(tmp_path):
    source = template(tmp_path, [["政治面貌", ""]])
    output = tmp_path / "filled.docx"
    def unexpected_reflection(*args):
        raise AssertionError("Invalid enum must not be reflected")
    audit = fill_docx(str(source), {"personal": {"political_status": "合成无效枚举"}},
                      str(output), reflexion_rounds=1, _reflect_impl=unexpected_reflection)
    assert Document(output).tables[0].cell(0, 1).text == ""
    assert audit["filled"] == 0
    assert audit["details"][0]["status"] == "⚠️"
    assert audit["details"][0]["fill_mode"] == "literal-mismatch"


def test_text_empty_nested_table_cell_is_preserved(tmp_path):
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "姓名"
    nested = table.cell(0, 1).add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "已有嵌套内容"
    source = tmp_path / "nested.docx"
    doc.save(source)
    output = tmp_path / "filled.docx"
    audit = fill_docx(str(source), PROFILE, str(output))
    result = Document(output).tables[0].cell(0, 1)
    assert result.text.strip() == ""
    assert result.tables[0].cell(0, 0).text == "已有嵌套内容"
    assert audit["filled"] == 0
