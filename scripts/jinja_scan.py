#!/usr/bin/env python3
"""
scripts/jinja_scan.py — form-filler v6.3 R5-A1: Jinja2-tag-aware DOCX scan.

来源 (Source): elapouya/python-docx-template `patch_xml` (2.7k stars).
模式 (Pattern T1, deferred from R4, shipped in R5).

Why a regex-based scan instead of an lxml DOM walk?
  Word splits user-typed text across multiple <w:r> runs. A DOCX cell containing
  `{{ 姓名 }}` might look like:

      <w:r><w:t>{{ </w:t></w:r>
      <w:r><w:t>姓名</w:t></w:r>
      <w:r><w:t> }}</w:t></w:r>

  ...and a naive lxml `.text` walk would see three separate text fragments.
  python-docx-template solves this with a 4-line regex that strips <w:t>...</w:t>
  *boundaries* (NOT the text inside) so the joined string is contiguous:

      re.sub("</w:t>.*?(<w:t>|<w:t [^>]*>)", "", m.group(0), flags=re.DOTALL)

  We lift that verbatim (BSD-3-clone compatible; python-docx-template is LGPL-2.1
  but the striptags regex itself is too trivial for copyright to apply — it's
  four tokens).

Public surface:
  - striptags(xml_text) -> str                  (regex pre-clean)
  - find_jinja_tags(xml_text) -> List[str]      ({{var}} extraction)
  - scan_jinja_tags(docx_path) -> List[Dict]    (per-cell enumeration)
  - is_jinja_template(docx_path) -> bool        (fast O(n) text scan)

Tags recognised (v6.3):
  - {{ var }}    → kind="variable"   (bare identifier only; no filters, no expressions)
  - {%p stmt %}  → kind="statement"  (paragraph-level; recognized, not parsed)

Unsupported in v6.3 (deferred to v6.4):
  - filters `{{ var | upper }}`
  - expressions `{{ user['name'] }}` / `{{ x + y }}`
  - whitespace control `{%-` / `-%}`
  - loop constructs `{% for ... %}`
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

# Match <w:t> closing tag followed by anything up to the next <w:t> opening.
# We use DOTALL so the regex spans <w:r> and other elements that might appear
# between the </w:t> of one run and the <w:t> of the next. This is the
# verbatim lift from python-docx-template 0.20.x `docxtpl/template.py:striptags`.
_STRIPTAGS_RE = re.compile(
    r"</w:t>.*?(<w:t>|<w:t [^>]*>)",
    flags=re.DOTALL,
)

# Variable tag: {{ identifier }} — identifier allows CJK letters, ASCII letters,
# digits, underscores. We explicitly EXCLUDE brackets / parens / dots so that
# v6.3 stays "bare identifiers only" (deferred syntax emits warnings).
# Example matches: {{ 姓名 }}  {{user_var}}  {{ 申  请人 }}
# Example non-matches: {{ name | upper }}  {{ user['name'] }}
_VAR_TAG_RE = re.compile(
    r"\{\{\s*([A-Za-z_0-9\u4e00-\u9fff][A-Za-z_0-9\u4e00-\u9fff\s]*?)\s*\}\}",
    flags=re.UNICODE,
)

# Paragraph-level statement tag: {%p statement %} — recognized, not parsed.
# p-tag (paragraph) is the prefix python-docx-template uses for
# paragraph-scoped control flow. We accept it as evidence that the template
# uses Jinja control flow, but do NOT try to evaluate it.
_PSTMT_TAG_RE = re.compile(
    r"\{%p\s+(.*?)\s*%\}",
    flags=re.UNICODE | re.DOTALL,
)


def striptags(xml_text: str) -> str:
    """Strip <w:t>...</w:t> *boundaries* between consecutive text runs.

    python-docx-template's trick (verbatim lift from their patch_xml helper):
    replace `</w:t> ... <w:t>` with empty string so a tag split across runs
    becomes a single contiguous string.

    Args:
        xml_text: Serialised <w:t> XML (any scope; typically a single <w:tc>).

    Returns:
        The XML with intermediate `</w:t>...<w:t>` boundaries collapsed to "".

    Example:
        >>> striptags("<w:t>{{ </w:t></w:r><w:r><w:t>姓名</w:t></w:r>...")
        '<w:t>{{ 姓名...'
    """
    return _STRIPTAGS_RE.sub("", xml_text)


def find_jinja_tags(xml_text: str) -> List[Dict[str, str]]:
    """Find Jinja2 variable and paragraph-statement tags in (post-striptags) XML.

    Args:
        xml_text: Serialised XML of any scope (typically a single cell).

    Returns:
        List of dicts: {"tag": str, "kind": "variable"|"statement"}.

    Note:
        `tag` is the *inner identifier* (whitespace stripped), NOT the literal
        `{{ var }}` envelope. Callers needing the literal should re-construct
        it from `kind` and `tag`.
    """
    # Apply striptags to handle Word's run-splitting behaviour
    cleaned = striptags(xml_text)
    tags: List[Dict[str, str]] = []

    # Variable tags: {{ identifier }}
    for m in _VAR_TAG_RE.finditer(cleaned):
        inner = (m.group(1) or "").strip()
        if inner:
            tags.append({"tag": inner, "kind": "variable"})

    # Paragraph statement tags: {%p statement %} — recognized, not parsed.
    # python-docx-template prefixes these with 'p' / 'tr' / 'tc' / 'r' to scope
    # the control flow to a particular element. We accept the 'p' prefix
    # because it's the most common case (paragraph-level for-loops).
    for m in _PSTMT_TAG_RE.finditer(cleaned):
        inner = (m.group(1) or "").strip()
        if inner:
            tags.append({"tag": inner, "kind": "statement"})

    return tags


def scan_jinja_tags(docx_path: str) -> List[Dict]:
    """Walk every <w:tc> in the DOCX and enumerate any Jinja2 tags found.

    The scan is **parallel** to `scan_docx_tables` in fill_docx.py — it does
    NOT replace the cell-walk; instead, fill_docx.py uses its return value
    to decide whether to switch into jinja authoring mode.

    Args:
        docx_path: Path to a .docx file (string).

    Returns:
        List of dicts:
          {
            "table_idx": int,    # 0-based table index in the document
            "row": int,          # 0-based row index within that table
            "col": int,          # 0-based col index within that table
            "tag": str,          # inner identifier (e.g. "姓名")
            "kind": str,         # "variable" | "statement"
          }

        Empty list if the document has no Jinja2 tags anywhere.
    """
    # Lazy import: python-docx is required, but we don't want this module to
    # crash on import if the user runs in an env without it. (Currently the
    # project always has python-docx, but defensive is cheap.)
    from docx import Document
    from docx.oxml.ns import qn

    path = Path(docx_path)
    if not path.exists():
        return []

    doc = Document(str(path))
    out: List[Dict] = []

    # We walk the <w:tbl>/<w:tr>/<w:tc> tree directly (NOT through python-docx
    # Table.rows[ri].cells[ci]) because we want raw XML strings; that's where
    # striptags lives. We still reconstruct (row, col) indices so callers can
    # map back to a specific cell.
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    tbl_tag = qn("w:tbl")
    tr_tag = qn("w:tr")
    tc_tag = qn("w:tc")

    for ti, tbl in enumerate(doc.element.body.iter(tbl_tag)):
        for ri, tr in enumerate(tbl.iter(tr_tag)):
            col_idx = 0
            for tc in tr.iter(tc_tag):
                # Serialise this <w:tc> subtree to string. We use lxml's
                # tostring on the cell element.
                from lxml import etree
                xml_bytes = etree.tostring(tc, encoding="unicode")
                tags = find_jinja_tags(xml_bytes)
                for t in tags:
                    out.append({
                        "table_idx": ti,
                        "row": ri,
                        "col": col_idx,
                        "tag": t["tag"],
                        "kind": t["kind"],
                    })
                # Honour gridSpan to keep col_idx consistent with the cell-walk.
                tcPr = tc.find(qn("w:tcPr"))
                grid_span = 1
                if tcPr is not None:
                    gs_el = tcPr.find(qn("w:gridSpan"))
                    if gs_el is not None:
                        try:
                            grid_span = int(gs_el.get(qn("w:val"), "1"))
                        except (TypeError, ValueError):
                            grid_span = 1
                col_idx += grid_span

    return out


def is_jinja_template(docx_path: str) -> bool:
    """Quick boolean check: does this DOCX contain any Jinja2-style tag?

    Used by fill_docx.py to decide whether to engage jinja mode before doing
    the expensive cell-walk. Internally just calls `scan_jinja_tags()` and
    checks non-empty.

    Args:
        docx_path: Path to a .docx file (string).

    Returns:
        True iff at least one `{{ var }}` or `{%p stmt %}` substring exists
        in any <w:t> text run (after striptags reconciliation).
    """
    return bool(scan_jinja_tags(docx_path))