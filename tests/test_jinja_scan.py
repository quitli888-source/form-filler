#!/usr/bin/env python3
"""
tests/test_jinja_scan.py — form-filler v6.3 R5-A1: Jinja2-tag-aware DOCX scan tests.

Pattern T1 (deferred from R4, shipped in R5): opens a new authoring surface
where users can write `{{ 姓名 }}` tags in their DOCX templates instead of
relying on the brittle label-regex list.

Test surface:
  - striptags() handles Word's run-boundary splitting
  - find_jinja_tags() extracts bare identifiers from {{ var }}
  - scan_jinja_tags() walks all tables of a DOCX
  - is_jinja_template() returns a bool

Tests:
  1. test_jinja_tag_basic            — DOCX with `{{name}}` is detected
  2. test_jinja_tag_split_runs       — DOCX with tag split across <w:r> is detected
  3. test_jinja_tag_none             — DOCX without tags returns empty list
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from jinja_scan import (
    find_jinja_tags, is_jinja_template, scan_jinja_tags, striptags,
)


def _make_docx_with_tag(tag_text: str = "{{ 姓名 }}") -> str:
    """Build a minimal 1-table DOCX with `tag_text` as a cell's content."""
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "标签"  # column 0 = label
    table.cell(0, 1).text = tag_text  # column 1 = value (carries Jinja tag)
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    doc.save(path)
    return path


def _make_docx_with_split_runs(tag_text: str = "{{ 姓名 }}") -> str:
    """Build a DOCX where the {{ tag }} is split across multiple <w:r><w:t> runs.

    python-docx writes a single run by default. We have to manually craft
    the XML to simulate Word's run-splitting behaviour.
    """
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)

    # Clear default paragraph
    p = cell.paragraphs[0]
    for run in list(p.runs):
        run._element.getparent().remove(run._element)

    # Split the tag into three pieces: "{{ ", "姓名", " }}"
    pieces = tag_text.split(" ", 2) if tag_text.startswith("{{") else ["", "", tag_text]
    if len(pieces) < 3:
        pieces = ["{{", "姓名", "}}"]
    p1, p2, p3 = pieces

    # Build raw <w:r><w:t> elements manually
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    def make_run(text_content: str):
        r = etree.SubElement(p._p, qn("w:r"))
        t = etree.SubElement(r, qn("w:t"))
        t.text = text_content
        # Force xml:space="preserve" so leading/trailing whitespace survives
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        return r

    make_run(p1)
    make_run(p2)
    make_run(p3)

    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    doc.save(path)
    return path


def _make_docx_without_tag() -> str:
    """Build a plain DOCX with no Jinja tags anywhere."""
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "姓名"
    table.cell(0, 1).text = ""
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    doc.save(path)
    return path


class TestJinjaScanCore(unittest.TestCase):
    """Direct tests for striptags() + find_jinja_tags() helpers."""

    def test_striptags_collapses_run_boundaries(self):
        """Simulate Word's run-split: `</w:t>...<w:t>` boundaries collapse to ''."""
        xml = '<w:t>{{ </w:t></w:r><w:r><w:t>姓名</w:t></w:r><w:r><w:t> }}</w:t>'
        out = striptags(xml)
        # Boundary substring "></w:r>...<w:r><w:t" should be removed
        self.assertNotIn("</w:r>", out,
                         f"striptags should remove <w:r> boundaries: {out!r}")
        self.assertNotIn("<w:r>", out,
                         f"striptags should remove <w:r> boundaries: {out!r}")
        # The joined content should still contain the inner tag pieces
        self.assertIn("{{ ", out)
        self.assertIn("姓名", out)
        self.assertIn(" }}", out)

    def test_find_jinja_tags_single_variable(self):
        xml = "<w:t>{{ 姓名 }}</w:t>"
        tags = find_jinja_tags(xml)
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["tag"], "姓名")
        self.assertEqual(tags[0]["kind"], "variable")

    def test_find_jinja_tags_statement(self):
        xml = "<w:t>{%p for entry in entries %}</w:t>"
        tags = find_jinja_tags(xml)
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["kind"], "statement")
        self.assertIn("for entry", tags[0]["tag"])

    def test_find_jinja_tags_no_match(self):
        xml = "<w:t>普通文本，无标签</w:t>"
        tags = find_jinja_tags(xml)
        self.assertEqual(tags, [])


class TestScanJinjaTags(unittest.TestCase):
    """End-to-end tests on actual DOCX files."""

    def setUp(self):
        self.path_basic = _make_docx_with_tag("{{ 姓名 }}")
        self.path_split = _make_docx_with_split_runs("{{ 姓名 }}")
        self.path_none = _make_docx_without_tag()

    def tearDown(self):
        for p in (self.path_basic, self.path_split, self.path_none):
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_jinja_tag_basic(self):
        """DOCX with `{{name}}` is detected — R5-A1 test 1."""
        tags = scan_jinja_tags(self.path_basic)
        self.assertGreater(len(tags), 0,
                           f"Basic {{var}} should be detected: {tags}")
        # At least one tag with kind=variable and tag=姓名
        variable_tags = [t for t in tags if t["kind"] == "variable"]
        self.assertEqual(len(variable_tags), 1)
        self.assertEqual(variable_tags[0]["tag"], "姓名")
        # Position keys are present and valid
        self.assertIn("table_idx", variable_tags[0])
        self.assertIn("row", variable_tags[0])
        self.assertIn("col", variable_tags[0])
        self.assertEqual(variable_tags[0]["table_idx"], 0)

    def test_jinja_tag_split_runs(self):
        """DOCX with tag split across <w:r> is detected — R5-A1 test 2.

        Word's run-splitting behaviour breaks naive .text walks. striptags()
        is the solution; this test verifies it works through scan_jinja_tags().
        """
        tags = scan_jinja_tags(self.path_split)
        variable_tags = [t for t in tags if t["kind"] == "variable"]
        self.assertEqual(len(variable_tags), 1,
                         f"Split-run tag should be detected as ONE tag: {tags}")
        self.assertEqual(variable_tags[0]["tag"], "姓名",
                         f"Joined content should be '姓名': {tags}")

    def test_jinja_tag_none(self):
        """DOCX without tags returns empty list — R5-A1 test 3."""
        tags = scan_jinja_tags(self.path_none)
        self.assertEqual(tags, [],
                         f"No-tag DOCX should return []: {tags}")
        # And is_jinja_template should be False
        self.assertFalse(is_jinja_template(self.path_none))


if __name__ == "__main__":
    unittest.main(verbosity=2)