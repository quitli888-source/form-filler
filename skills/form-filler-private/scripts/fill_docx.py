#!/usr/bin/env python3
"""v7 local DOCX table filler.

Read local YAML or user-bound DPAPI profiles in-process, match existing fields,
write a result copy and a value-free audit. Optional model reflection is local
only; this private edition contains no cloud drafting flow.
The legacy write_profile_md API now writes counts only, never personal values.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable, List, Literal, Optional, Tuple, get_args, get_origin  # v6.2 R4-A2: Literal introspection

from docx import Document

# 让 scripts/ 子目录互相 import
sys.path.insert(0, str(Path(__file__).parent))
# 也让 evaluation/ (project root) 可被 import — 防止 CLI subprocess 找不到
sys.path.insert(0, str(Path(__file__).parent.parent))
from model_adapter import StubAdapter, get_adapter  # noqa: E402
from privacy import PrivacyError, local_data_dir, private_text, private_write, safe_audit, safe_label, protect_inputs, utf8_console
from profile_store import load_sections
from io import BytesIO

# v6.3 R5-A1: Jinja2-tag-aware scan — new authoring surface
try:
    from jinja_scan import scan_jinja_tags, is_jinja_template  # noqa: E402
except Exception:  # defensive — should not happen in normal env
    def scan_jinja_tags(docx_path):  # type: ignore
        return []
    def is_jinja_template(docx_path):  # type: ignore
        return False

# v6.4 (R6-A3): 确定性字段类型推断（纯标准库，introspect JSON 的 type/required/empty）
try:
    from field_types import (  # noqa: E402
        infer_field_type,
        is_required_label,
        is_empty_value,
    )
except Exception:  # defensive — field_types.py 是纯标准库，正常不会失败
    def infer_field_type(label, value):  # type: ignore
        return "text"
    def is_required_label(label):  # type: ignore
        return False
    def is_empty_value(value):  # type: ignore
        return not (value or "").strip()

# 可选依赖：pydantic + schemas（缺失则降级到 v5.0 行为）
try:
    from evaluation.schemas import (  # noqa: E402
        SCHEMAS,
        find_schema_for_label,
        find_field_in_schema,
        SCHEMA_SYNONYMS,  # v6.3 R5-A2: single source of truth
        build_match_rules_from_synonyms,  # v6.3 R5-A2: generates match_rules
    )
except Exception:  # ImportError or evaluation package missing
    SCHEMAS = {}
    find_schema_for_label = lambda label: None  # noqa: E731
    find_field_in_schema = lambda label, schema_cls=None: None  # noqa: E731
    SCHEMA_SYNONYMS = {}
    build_match_rules_from_synonyms = lambda: []  # noqa: E731


def load_profiles(profile_dir: str, *, allow_plain: bool = True) -> dict:
    """Read local profiles in-process; never echo filenames or values."""
    profiles = load_sections(profile_dir, allow_plain=allow_plain)
    print(f"📄 已加载 {len(profiles)} 类本地资料（内容隐藏）")
    return profiles


def scan_docx_tables(doc_path: str) -> list:
    """扫描 DOCX 文件中的表格结构，返回字段清单"""
    doc = Document(doc_path)
    fields = []

    for ti, table in enumerate(doc.tables):
        print(f"\n📊 表格 #{ti} ({len(table.rows)}行 x {len(table.columns)}列)")

        seen_cells = set()
        for ri, row in enumerate(table.rows):
            for ci, cell in enumerate(row.cells):
                cell_id = cell._tc
                if cell_id in seen_cells:
                    continue
                seen_cells.add(cell_id)

                text = cell.text.strip()
                if text:
                    fields.append({
                        "table": ti,
                        "row": ri,
                        "col": ci,
                        "text": safe_label(text) if _is_likely_label(text) else "[已隐藏]",
                        "is_label": _is_likely_label(text),
                    })
                    label = "标签" if _is_likely_label(text) else "值"
                    print(f"  [{ri},{ci}] {label}: {safe_label(text) if label == '标签' else '[已隐藏]'}")

    return fields


def scan_docx_introspect(doc_path: str) -> dict:
    """v6.0 (R2-A3, Pattern J): 把 scan_docx_tables 结果持久化为可序列化的 JSON 结构。

    用途：供下游 Schema 选择 / Round 3+ 自动化回归测试使用。
    不依赖任何运行时状态；纯静态扫描。

    v6.4 (R6-A3): 每个 cell dict 新增 `type` / `required` / `empty` 三键
    （additive，既有键 text/is_label/merged_dup 不动；merged_dup 分支同步补
    三键保持 schema 一致）。type 由 scripts/field_types.py 确定性推断，
    不经过 LLM，可复现、可 diff。
    """
    doc = Document(doc_path)
    tables_data = []
    for ti, table in enumerate(doc.tables):
        seen_cells = set()
        rows = []
        for ri, row in enumerate(table.rows):
            cells = []
            for ci, cell in enumerate(row.cells):
                cell_id = cell._tc
                if cell_id in seen_cells:
                    cells.append({
                        "row": ri, "col": ci, "text": "", "is_label": False,
                        "merged_dup": True,
                        # v6.4 (R6-A3): merged_dup 与普通 cell 保持同一 schema
                        "type": "text", "required": False, "empty": True,
                    })
                    continue
                seen_cells.add(cell_id)
                text = cell.text.strip()
                cells.append({
                    "row": ri, "col": ci, "text": safe_label(text) if _is_likely_label(text) else ("[已隐藏]" if text else ""),
                    "is_label": _is_likely_label(text),
                    "merged_dup": False,
                    # v6.4 (R6-A3): 确定性类型/必填/空值标注（additive）
                    "type": infer_field_type(text, text),
                    "required": is_required_label(text),
                    "empty": is_empty_value(text),
                })
            rows.append(cells)
        tables_data.append({
            "index": ti,
            "rows": len(table.rows),
            "cols": len(table.columns),
            "cells": rows,
        })
    from datetime import datetime
    return {
        "template": "local-template",
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "tables": tables_data,
        "labels": [
            {"table": f["table"], "row": f["row"], "col": f["col"], "text": f["text"]}
            for f in [
                {"table": ti, "row": ri, "col": ci, "text": safe_label(text) if _is_likely_label(text) else "[已隐藏]", "is_label": _is_likely_label(text)}
                for ti, table in enumerate(doc.tables)
                for ri, row in enumerate(table.rows)
                for ci, cell in enumerate({id(c._tc): c for c in row.cells}.values())
                for text in [cell.text.strip()]
                if text
            ]
            if f["is_label"]
        ],
    }


# ---------------------------------------------------------------------------
# v6.0 新增：PII 脱敏（手机/邮箱/身份证/银行卡），用于 audit 写入前
# ---------------------------------------------------------------------------

PHONE_PAT = re.compile(r"(?<![\d])(1\d{2})\d{4}(\d{4})(?![\d])")
EMAIL_PAT = re.compile(r"(?<![@\w])(\w[\w.+-]*[A-Za-z0-9])@(\w[\w.-]*\.[A-Za-z]{2,})(?![\w.])")
ID_NUMBER_PAT = re.compile(r"(?<![\d])(\d{6})\d{8}(\d{3}[\dXx])(?![\d])")
CARD_PAT = re.compile(r"(?<![\d])(\d{4})\d{6,11}(\d{4})(?![\d])")


def _redact(value: str) -> str:
    """Mask obvious PII patterns. Best-effort; never raises.

    Patterns (with negative lookarounds to avoid false matches):
      - 手机号: 11 位数字，1 开头，前后无其他数字
      - 邮箱: ASCII local-part + @ + domain，前无 @/word 字符，后无 word/dot 字符
      - 身份证: 18 位（6 位地区 + 8 位生日 + 3 位 + 校验位 Xx/digit），前后无其他数字
      - 银行卡: 13–19 位数字，前后无其他数字（避免误伤学号）
    """
    if not value:
        return value
    s = str(value)
    s = PHONE_PAT.sub(r"\1****\2", s)
    s = EMAIL_PAT.sub(r"***@\2", s)
    s = ID_NUMBER_PAT.sub(r"\1********\2", s)
    s = CARD_PAT.sub(r"\1******\2", s)
    return s


def _redact_label(label: str) -> bool:
    """这个 label 本身就是 PII（写入对照表的字段名行）。True 表示需要脱敏。"""
    return any(k in label for k in ("手机", "邮箱", "身份证", "银行卡"))


# v6.4 (R6-A3): _is_likely_label hardening — 数值/单位值（"6个月" "1万元" 类）
# 是待填写值而非标签；与 field_types._AMOUNT_UNIT_RE 同族但单位表更宽。
_LABEL_UNIT_VALUE_RE = re.compile(
    r"^\d+(?:\.\d+)?\s*(?:万元|亿元|元|块钱|个月|月|人|个|名|位|年|天|日|次|件|条|张|份|台|部|间|%|％)$"
)
# v6.4 (R6-A3): _is_likely_label hardening — 说明语句（"……请依次填写" "……如下" 类）
# 是模板提示语而非字段标签。
_LABEL_INSTRUCTION_TAIL_RE = re.compile(r"请依次填写|请填写|请按照|如下")


def _is_likely_label(text: str) -> bool:
    """判断单元格文本是否是字段标签（而非待填写值）

    v6.4 (R6-A3) hardening: 在关键词匹配前增加两条排除——
      1. 数值/单位值（"6个月" "1万元" 类）→ False；
      2. 说明语句（"……请依次填写" "……如下" 类）→ False。
    其余行为与 v6.3 逐字节一致（既有 label_patterns 不动）。
    """
    if len(text) > 20:
        return False
    # v6.4 (R6-A3): 排除 1——数值/单位值是待填写值
    if _LABEL_UNIT_VALUE_RE.match(text):
        return False
    # v6.4 (R6-A3): 排除 2——说明语句是模板提示语
    if _LABEL_INSTRUCTION_TAIL_RE.search(text):
        return False
    # 常见表格标签关键词
    label_patterns = [
        r"姓名", r"性别", r"年龄", r"民族", r"籍贯", r"出生",
        r"学历", r"学位", r"专业", r"学号", r"院系", r"学校",
        r"手机", r"电话", r"邮箱", r"地址", r"邮编",
        r"政治", r"团员", r"入党", r"职务",
        r"申报", r"申请", r"所在", r"单位",
        r"获奖", r"荣誉", r"简历", r"陈述", r"自荐",
        r"日期", r"签名", r"意见", r"盖章",
        r"培养", r"年级", r"类别",
    ]
    for pattern in label_patterns:
        if re.search(pattern, text):
            return True
    return False



_FILL_LABEL_DECORATIONS = re.compile(
    r"[（(](?:必填|选填|可选|中文|英文|拼音|正楷|真实姓名|11位|18位|YYYY[-/]MM(?:[-/]DD)?)[)）]",
    re.IGNORECASE,
)


def _fillable_label(text: str) -> Optional[str]:
    """Accept exact schema names/explicit aliases for writes, never substrings.

    Inspection may suggest more possible labels; actual writes deliberately
    require a known field after harmless spacing/required-marker normalization.
    """
    label = re.sub(r"\s+", "", text)
    label = _FILL_LABEL_DECORATIONS.sub("", label).strip(":：*＊※★")
    canonical = SCHEMA_SYNONYMS.get(label, label)
    canonical = {"学历": "最高学历", "年级": "学历年级"}.get(canonical, canonical)
    known = {name for schema in SCHEMAS.values() for name in schema.model_fields}
    known.update(("学历", "年级", "所在单位", "申报类别"))
    return canonical if canonical in known else None

def _get_nested_value(data: dict, path: str):
    """按点分路径获取嵌套字典值，如 entries.0.student_id"""
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, list):
            try:
                current = current[int(key)]
            except (IndexError, ValueError):
                return None
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def _compute_grade(profiles: dict) -> str:
    """Build a cohort label only from an explicit supported degree and valid date."""
    from datetime import date
    entries = (profiles.get("education", {}) or {}).get("entries", [])
    if not entries or not isinstance(entries[0], dict):
        return None
    entry = entries[0]
    degree = entry.get("degree")
    if degree not in ("本科", "硕士", "博士"):
        return None
    start_date = entry.get("start_date")
    if isinstance(start_date, date):
        year = start_date.year
    else:
        text = str(start_date or "").strip()
        try:
            if re.fullmatch(r"\d{4}", text):
                year = date(int(text), 1, 1).year
            elif re.fullmatch(r"\d{4}-\d{2}", text):
                year = date.fromisoformat(text + "-01").year
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                year = date.fromisoformat(text).year
            else:
                return None
        except ValueError:
            return None
    return f"{year % 100:02d}级{degree}生"


def _compute_workplace(profiles: dict) -> str:
    """从学校+院系拼接所在单位"""
    edu = profiles.get("education", {})
    entries = edu.get("entries", [])
    if not entries:
        return None
    entry = entries[0]
    school = entry.get("school", "")
    department = entry.get("department", "")
    if school and department:
        return f"{school}{department}"
    return school or department or None


def _compute_category(profiles: dict) -> str:
    """从学位推断申报类别"""
    edu = profiles.get("education", {})
    entries = edu.get("entries", [])
    if not entries:
        return None
    degree = entries[0].get("degree", "")
    if degree in ("本科", "硕士", "博士"):
        return "学生"
    return None


# 匹配规则表（模块级常量，供 validate_rules.py 等导入使用）
# 格式: (正则模式, 配置文件, 字段路径, 转换函数)
# 转换函数接收 profiles dict，返回字符串或 None
#
# v6.3 R5-A2: 从 SCHEMA_SYNONYMS (single source of truth in evaluation/schemas.py)
# 自动生成。transform-based rules (_compute_grade / _compute_workplace /
# _compute_category) 保留为显式条目 — 它们不是 synonym alias，而是派生计算。
try:
    _generated_rules = build_match_rules_from_synonyms() if SCHEMA_SYNONYMS else []
except Exception:
    _generated_rules = []
match_rules: List[Tuple[str, str, Optional[str], Optional[Callable]]] = [
    (r"学历|年级", "education", "entries.0.degree", _compute_grade),
    (r"所在单位", "education", None, _compute_workplace),
    (r"申报类别", "education", "entries.0.degree", _compute_category),
] + _generated_rules


def _is_literal_field(schema_cls, field_name: str) -> bool:
    """v6.2 R4-A2: detect whether a schema field has a `Literal[...]` annotation.

    Returns True iff the Pydantic field's annotation is `Literal["a","b",...]` or
    `Optional[Literal["a","b",...]]`. When True, the value space is closed and
    the lookup is fully deterministic — no LLM reflexion call should be made.

    Returns False on any introspection failure (defensive: fall through to the
    existing reflexion path on edge cases).
    """
    if schema_cls is None or not field_name:
        return False
    try:
        field = schema_cls.model_fields.get(field_name)
        if field is None:
            return False
        ann = field.annotation
        if ann is None:
            return False
        # Direct Literal[...] case
        if get_origin(ann) is Literal:
            return True
        # Optional[Literal[...]] → Union[None, Literal[...]]
        origin = get_origin(ann)
        if origin is not None and hasattr(origin, "__args__"):
            for arg in ann.__args__:
                if get_origin(arg) is Literal:
                    return True
        return False
    except Exception:
        return False


def _literal_values(schema_cls, field_name: str):
    """v6.2 R4-A2: extract the allowed values from a Literal-typed schema field.

    Returns a list of strings (the literals) or an empty list if the field is
    not Literal-typed or the introspection fails.
    """
    if not _is_literal_field(schema_cls, field_name):
        return []
    try:
        field = schema_cls.model_fields[field_name]
        ann = field.annotation
        if get_origin(ann) is Literal:
            return list(get_args(ann))
        # Optional[Literal[...]] case
        for arg in ann.__args__:
            if get_origin(arg) is Literal:
                return list(get_args(arg))
        return []
    except Exception:
        return []


def match_field(label: str, profiles: dict) -> dict:
    """语义匹配：将表格标签映射到配置文件字段。

    v6.1 (R3-A1, Pattern A3 schema-first routing):
      Pass 1: 如果 label 在 evaluation.schemas 的某 schema 字段名中能精确匹配，
              跳过正则列表，直接从 profile 中按字段名查找（绕开 first-match-wins）。
      Pass 2: 否则，回退到 v5.0 的 match_rules 正则列表。

    v6.2 (R4-A2, Pattern O1 — Literal-first deterministic routing):
      在 Pass 1 内部，当 schema 字段是 `Literal[...]` 时，对 profile 值做
      case/whitespace-tolerant 匹配。如果 profile 值在 Literal 集合内，
      直接返回 `{fill_mode: "literal"}`；否则记录一次警告（profile 数据 bug），
      仍走 schema-first 路径（不要让 LLM 选一个 LLM 不知道的闭集）。
    """
    # Pass 1 (R3-A1): schema-first routing — 精确匹配优先
    if SCHEMAS:
        schema_cls = find_schema_for_label(label)
        if schema_cls is not None:
            field_name = find_field_in_schema(label, schema_cls)
            if field_name:
                # v6.2 R4-A2 — Literal-first check (Pass 0 within Pass 1)
                literals = _literal_values(schema_cls, field_name)
                value = _lookup_profile_field(field_name, profiles)
                if literals:
                    # Literal-typed field: deterministic routing check
                    norm_value = str(value).strip() if value is not None else ""
                    norm_literals = {str(x).strip() for x in literals}
                    if norm_value and norm_value in norm_literals:
                        return {
                            "matched": True,
                            "config_file": "(schema-literal)",
                            "field_path": field_name,
                            "value": value,
                            "status": "✅",
                            "schema": schema_cls.__name__,
                            "fill_mode": "literal",
                            "literals": sorted(norm_literals),
                        }
                    if norm_value:
                        # Value not in the literal set — profile bug
                        print(
                            f"⚠️ profile value for schema field (value withheld) "
                            "not in the permitted Literal set; "
                            f"LLM reflexion skipped (closed enum cannot infer).",
                            file=sys.stderr,
                        )
                    # Value missing or mismatch — fall through to schema-first
                    # but mark fill_mode so audit shows the routing decision.
                    if value is not None:
                        return {
                            "matched": True,
                            "config_file": "(schema-literal-mismatch)",
                            "field_path": field_name,
                            "value": value,
                            "status": "⚠️",
                            "schema": schema_cls.__name__,
                            "fill_mode": "literal-mismatch",
                            "literals": sorted(norm_literals),
                        }
                # Standard schema-first path (Literal check skipped or no value)
                if value:
                    return {
                        "matched": True,
                        "config_file": "(schema)",
                        "field_path": field_name,
                        "value": value,
                        "status": "✅",
                        "schema": schema_cls.__name__,
                        "fill_mode": "schema",
                    }
                # value is None — try schema-first with no value (will be ❌)
                return {
                    "matched": True,
                    "config_file": "(schema)",
                    "field_path": field_name,
                    "value": None,
                    "status": "❌",
                    "schema": schema_cls.__name__,
                    "fill_mode": "schema",
                }

    # Pass 2 (v5.0 compat): regex match_rules
    for pattern, config_file, field_path, transform in match_rules:
        if re.search(pattern, label):
            value = _get_nested_value(profiles.get(config_file, {}), field_path) if field_path else None
            if transform:
                value = transform(profiles)
            return {
                "matched": True,
                "config_file": config_file,
                "field_path": field_path,
                "value": value,
                "status": "✅" if value else "❌",
                "fill_mode": "regex",
            }

    return {"matched": False, "value": None, "status": "❓", "fill_mode": "unmatched"}


def _lookup_profile_field(field_name: str, profiles: dict):
    """R3-A1 helper: 在 profiles dict 中按字段名查找值。

    Profile keys 通常是英文 (name / gender / phone / student_id)，
    schema field 是中文 (姓名 / 性别 / 手机 / 学号)。本函数做两步：

    1. 尝试直接匹配（如果 profile 也用中文键）
    2. 否则通过 `match_rules` 反查：找到 label 中能匹配 schema 字段名的
       规则，使用规则的 (config_file, field_path) 路径取值。

    这样 R3-A1 的 schema-first routing 不会因为中英 key 差异而拿不到值。
    """
    # 顶层直接匹配
    for cfg_name, cfg in profiles.items():
        if isinstance(cfg, dict) and field_name in cfg and cfg[field_name]:
            return cfg[field_name]
    # 嵌套 entries.0.field 直接匹配
    for cfg_name, cfg in profiles.items():
        if isinstance(cfg, dict) and "entries" in cfg:
            for entry in cfg["entries"]:
                if isinstance(entry, dict) and field_name in entry and entry[field_name]:
                    return entry[field_name]

    # Computed cohort labels must not degrade to the bare degree. Application
    # category is a distinct user fact: a degree never selects an honours category.
    if field_name == "学历年级":
        return _compute_grade(profiles)
    if field_name == "申报类别":
        for cfg in profiles.values():
            if not isinstance(cfg, dict):
                continue
            if cfg.get("application_category"):
                return cfg["application_category"]
            for entry in cfg.get("entries", []):
                if isinstance(entry, dict) and entry.get("application_category"):
                    return entry["application_category"]
        return None

    # 通过 match_rules 反查（label 形式 = schema 字段名）
    for pattern, config_file, field_path, transform in match_rules:
        if re.search(pattern, field_name) and field_path:
            value = _get_nested_value(profiles.get(config_file, {}), field_path)
            if value:
                return value
    # transform 形式（_compute_grade / _compute_workplace / _compute_category）
    for pattern, config_file, field_path, transform in match_rules:
        if re.search(pattern, field_name) and transform and not field_path:
            value = transform(profiles)
            if value:
                return value

    return None


# ---------------------------------------------------------------------------
# v5.0→v6.0 升级：Reflexion 走 Model Adapter
# ---------------------------------------------------------------------------

def _stub_reflect(field_label: str, field_value, all_filled_so_far: dict) -> str:
    """Back-compat alias for StubAdapter().reflect() — 保持 v5.0 行为。

    测试代码可通过 fill_docx(_reflect_impl=...) 注入自定义 reflect 函数。
    """
    return StubAdapter().reflect(field_label, field_value, {"filled_so_far": all_filled_so_far})


# 保留 reflect() 作为 _stub_reflect 的兼容别名（v5.0 文档中曾用此名）
def reflect(field_label: str, field_value, context: dict) -> str:
    """_stub_reflect 的兼容别名；context 是包含 filled_so_far 的 dict。"""
    return _stub_reflect(field_label, field_value, context.get("filled_so_far", {}))


# ---------------------------------------------------------------------------
# v5.0 新增：profile.md 中间产物生成（R1-A2 / Pattern D）
# ---------------------------------------------------------------------------

def write_profile_md(profiles: dict, out_dir: str, profiles_dir: str = None) -> str:
    """Deprecated v7: write counts only; never duplicate the full personal profile."""
    body = "# Local profile summary\n\nValues and filenames withheld.\n"
    body += f"Sections loaded: {len(profiles)}\n"
    private_text(Path(out_dir) / "profile.md", body)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# v5.0 新增：填写对照表渲染（R1-A3）
# ---------------------------------------------------------------------------

def render_audit_table(audit: dict, template_path: str, out_path: str) -> None:
    """
    读取 templates/audit_table.md，把 [占位符] 替换为 audit 数据，写到 out_path。
    复用的图标：✅ 🔄 ⚠️ 📝 ❌ 📎
    """
    audit = safe_audit(audit)
    tpl = Path(template_path).read_text(encoding="utf-8")

    # 字段详情行
    rows = []
    counts = {"✅": 0, "🔄": 0, "📝": 0, "⚠️": 0, "❌": 0, "📎": 0}
    missing_list = []
    ai_list = []
    for i, item in enumerate(audit.get("details", []), 1):
        status = item.get("status", "❓")
        counts[status] = counts.get(status, 0) + 1
        label = item.get("label", "")
        value = item.get("value", "")
        source = item.get("source", "")
        reflection = item.get("reflection", "") or "—"
        rows.append(
            f"| {i} | {label} | {value} | {source} | {status} | {reflection} |"
        )
        if status == "❌":
            missing_list.append(f"- {label}（{source}）")
        if status == "📝":
            ai_list.append(f"- {label}（约 {len(str(value))} 字）")

    total = sum(counts.values()) or 1
    pct = lambda n: f"{int(n / total * 100)}%"

    # 状态统计行
    stats_rows = [
        f"| ✅ 自动匹配 | {counts.get('✅', 0)} | {pct(counts.get('✅', 0))} |",
        f"| 🔄 推断填充 | {counts.get('🔄', 0)} | {pct(counts.get('🔄', 0))} |",
        f"| 📝 AI 生成 | {counts.get('📝', 0)} | {pct(counts.get('📝', 0))} |",
        f"| ⚠️ 模糊/反思警告 | {counts.get('⚠️', 0)} | {pct(counts.get('⚠️', 0))} |",
        f"| ❌ 缺失 | {counts.get('❌', 0)} | {pct(counts.get('❌', 0))} |",
    ]

    # 待补充字段
    missing_block = "\n".join(missing_list) if missing_list else "（无）"
    # AI 生成内容
    ai_block = "\n".join(ai_list) if ai_list else "（无）"

    today = audit.get("date") or "未知"
    table_name = audit.get("table_name") or "未指定"
    input_fmt = audit.get("input_format") or "DOCX"
    info_source = audit.get("info_source") or "（无）"
    attachments_n = audit.get("attachments", 0)

    replacements = {
        "[表格名称]": table_name,
        "[YYYY-MM-DD]": today,
        "[DOCX / Excel / PDF / 文字描述]": input_fmt,
        "[信息源文件名（如有）]": info_source,
        "[N] 个": f"{attachments_n} 个",
        "[逐条列出缺失字段，附推测值（如有）]": missing_block,
        "[逐条列出 AI 生成内容，附字数统计]": ai_block,
        "[文件名] | [附件类型] | [AI 生成 / 用户提供 / 待准备]": "（无附件） | — | —",
    }

    out = tpl
    for k, v in replacements.items():
        out = out.replace(k, str(v))

    # 替换示例行（`| 1 | [字段名] | ...`）为真实行
    out = re.sub(
        r"\|\s*1\s*\|\s*`?\[字段名\]`?\s*\|\s*`?\[填入值\]`?\s*\|\s*`?\[配置文件路径\]`?\s*\|\s*✅\s*\|\s*`?\[反思（≤2 句）或 — \]`?\s*\|",
        "\n".join(rows) if rows else "| 1 | — | — | — | — | — |",
        out,
        count=1,
    )
    # 替换 `...` 占位行（紧跟在字段行下面的省略行）
    out = re.sub(r"\|\s*\.\.\.\s*\|\s*\.\.\.\s*\|\s*\.\.\.\s*\|\s*\.\.\.\s*\|\s*\.\.\.\s*\|\s*\.\.\.\s*\|", "", out, count=1)

    # 替换状态统计的占位行
    out = re.sub(
        r"\|\s*✅\s*自动匹配\s*\|\s*`?\[N\]`?\s*\|\s*`?\[X%\]`?\s*\|",
        stats_rows[0], out, count=1
    )
    out = re.sub(
        r"\|\s*🔄\s*推断填充\s*\|\s*`?\[N\]`?\s*\|\s*`?\[X%\]`?\s*\|",
        stats_rows[1], out, count=1
    )
    out = re.sub(
        r"\|\s*📝\s*AI 生成\s*\|\s*`?\[N\]`?\s*\|\s*`?\[X%\]`?\s*\|",
        stats_rows[2], out, count=1
    )
    out = re.sub(
        r"\|\s*❌\s*缺失\s*\|\s*`?\[N\]`?\s*\|\s*`?\[X%\]`?\s*\|",
        stats_rows[4], out, count=1
    )

    private_text(out_path, out)


def count_chinese_chars(text: str) -> int:
    """统计中文字符数（不含标点和空格）"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def truncate_to_limit(content: str, max_chars: int) -> str:
    """按句子截断，保留完整句子"""
    if count_chinese_chars(content) <= max_chars:
        return content
    sentences = re.split(r'([。！？；])', content)
    result = ""
    for i in range(0, len(sentences) - 1, 2):
        trial = result + sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else "")
        if count_chinese_chars(trial) > max_chars:
            break
        result = trial
    return result


def fill_docx(template_path: str, profiles: dict, output_path: str,
              reflexion_rounds: int = 0,
              profile_md_dir: str = None,
              profile_counter_dir: str = None,
              _reflect_impl=None,
              adapter=None,
              schema_ai_generate: bool = True,
              scan_mode: str = "auto") -> dict:
    """
    填写 DOCX 表格：
    1. 遍历所有表格的标签单元格
    2. 语义匹配 → 找到配置值
    3. 填入相邻的值单元格
    4. 处理合并单元格
    5. 可选：对每个填入字段调用 adapter.reflect() 做自检反思
    6. (v6.0) PII 字段在写入 audit 前脱敏
    7. (v6.2 R4-A2) 跳过 Literal-约束字段的 LLM 反思（确定性匹配）
    8. (v6.2 R4-A2) audit 行新增 `fill_mode` 字段
    9. (v6.3 R5-A1) 若模板含 `{{ var }}` Jinja2 标签，则切换 jinja 模式，按标签直接取值
    10. (v6.3 R5-A3) XML 迭代失败时在 audit["warnings"] 写入结构化警告
    11. 保存结果
    12. (v6.4 R6-A1) reflexion_rounds≥2 时，后续轮次的反思 prompt 携带之前轮次的
        反思原文（prior_reflections 回喂），使多轮反思任务递进而非重复

    reflexion_rounds: 自检反思轮数（0 = 关闭，1 = 推荐）。每轮会调用 adapter.reflect()，
                      反思非空则把反思写入 audit entry 并把状态降级为 ⚠️。
                      v6.4 (R6-A1): N≥2 时第 k 轮（k≥2）的反思 prompt 会附带前 k-1 轮
                      的反思原文（adapter 侧仅取最后 3 条）。
    profile_md_dir: 若提供，则调用 write_profile_md() 把 profile.md 写到该目录
                    （默认建议 = output DOCX 同目录，避免污染 profiles/）。
    profile_counter_dir: 计数器文件目录（默认 profiles/），仅持久化版本号 N。
    _reflect_impl: 可选，注入测试替身；缺省使用 adapter.reflect()。
                   v6.4 (R6-A1) 起契约为 4 参：
                   reflect_fn(label, value, ctx, prior_reflections)，
                   其中 prior_reflections 为之前轮次反思原文列表（首轮为 []）；
                   旧 3 参替身会因缺参 TypeError——测试替身需同步加 `prior_reflections=None`。
    adapter: 可选，注入 ModelAdapter 实例；缺省 = StubAdapter()（v5.0 行为）。
    schema_ai_generate: 当 AI 生成字段（📝）匹配到一个 Pydantic schema 时，
                       是否尝试用 adapter.generate_struct() 生成受约束的内容；
                       失败或关闭时回退到原始 prompt。"""
    protect_inputs([output_path, Path(profile_md_dir) / "profile.md" if profile_md_dir else None], [template_path])
    if profile_md_dir:
        try:
            sha = write_profile_md(
                profiles,
                profile_md_dir,
                profiles_dir=profile_counter_dir,
            )
            print(f"📝 已生成 profile.md (SHA {sha})")
        except Exception as exc:
            print("⚠️ 本地摘要生成失败（详情隐藏）")

    doc = Document(template_path)
    audit = {"filled": 0, "missed": 0, "inferred": 0, "details": [], "warnings": []}
    if adapter is None:
        adapter = StubAdapter()
    reflect_fn = _reflect_impl if _reflect_impl is not None else (
        # v6.4 (R6-A1): 4 参契约——prior 回喂之前轮次的反思原文（首轮为 []）
        lambda lbl, val, ctx, prior=None: adapter.reflect(
            lbl, val, {"filled_so_far": ctx}, prior_reflections=prior
        )
    )

    # v6.3 R5-A1: detect Jinja2 tags and switch mode
    template_mode = "cell"  # default = v6.2 cell-walk behaviour
    if scan_mode == "jinja":
        template_mode = "jinja"
    elif scan_mode == "auto":
        try:
            jinja_tags = scan_jinja_tags(template_path)
            if jinja_tags:
                template_mode = "jinja"
                print(f"🔖 Detected {len(jinja_tags)} Jinja2 tag(s); switching to jinja mode")
        except Exception as exc:
            audit.setdefault("warnings", []).append(
                "jinja_scan failed; falling back to cell-walk"
            )
    audit["template_mode"] = template_mode  # v6.3 R5-A1: record mode in audit

    filled_context = {}
    for ti, table in enumerate(doc.tables):
        seen_cells = set()

        # v6.1 (R3-A2): iterate w:tc directly to avoid double-counting merged cells
        try:
            cell_iter = list(_iter_unique_cells(table))
        except Exception as exc:
            # v6.3 R5-A3: surface the fallback in the audit, not just stderr
            audit.setdefault("warnings", []).append(
                f"_iter_unique_cells failed on table {ti}; "
                "falling back to legacy cell-walk (known to double-count merged cells)"
            )
            cell_iter = []
            for ri, row in enumerate(table.rows):
                for ci, cell in enumerate(row.cells):
                    cell_iter.append((ri, ci, cell, id(cell._tc)))

        # Keep the original text snapshot: a newly filled value is never a label.
        original_text = {cell_id: cell.text.strip() for _, _, cell, cell_id in cell_iter}
        for ri, ci, cell, cell_id in cell_iter:
            if cell_id in seen_cells:
                continue
            seen_cells.add(cell_id)

            text = _fillable_label(original_text[cell_id])
            if text is None:
                continue

            # 找到标签，尝试匹配
            result = match_field(text, profiles)
            if not result["matched"]:
                continue

            # v6.2 R4-A2: track fill_mode for audit transparency
            fill_mode = result.get("fill_mode", "unknown")

            # 找相邻单元格填入值
            value_cell = _find_value_cell(table, ri, ci, seen_cells)
            filled_value = None
            if value_cell is not None and result["value"] and fill_mode != "literal-mismatch":
                # Preserve paragraph/run formatting in the existing empty value cell.
                paragraph = value_cell.paragraphs[0]
                run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
                run.text = str(result["value"])
                filled_value = result["value"]
                seen_cells.add(id(value_cell._tc))
                status_icon = "✅"
            else:
                status_icon = "❌"

            # v6.2 R4-A2: Literal-约束字段跳过 LLM 反思（已校验过枚举值）
            # Reflection would be redundant for closed-enum fields.
            skip_llm = (fill_mode == "literal")

            # Step 5.5 自检反思（走 adapter；StubAdapter 返回 "" = 无意见）
            reflection_text = ""
            if reflexion_rounds > 0 and filled_value and not skip_llm:
                filled_so_far = dict(filled_context)
                # v6.4 (R6-A1): 多轮反思闭环——prior_reflections 收集已产出的反思原文，
                # 回喂给下一轮 reflect 调用（修复"反思原文从不回喂"的 near-no-op 缺陷）
                prior_reflections: list = []
                for _ in range(reflexion_rounds):
                    r = reflect_fn(text, filled_value, filled_so_far, prior_reflections)
                    if not r or str(r).strip().upper().rstrip(".。!！") == "OK":
                        break  # no objection; OK is the model's explicit success token
                    reflection_text = r
                    status_icon = "⚠️"
                    filled_so_far[text] = filled_value
                    prior_reflections.append(r)
            elif skip_llm and reflexion_rounds > 0 and filled_value:
                # Record the deterministic skip in the audit
                reflection_text = "[skip-llm: literal]"

            if filled_value:
                filled_context[text] = filled_value
                audit["filled"] += 1
                # v6.0: PII 脱敏后再写入 audit（手机/邮箱/身份证/银行卡）
                audit_value = _redact(filled_value) if _redact_label(text) else filled_value
                audit["details"].append({
                    "label": text,
                    "value": audit_value,
                    "source": f"{result['config_file']}.yaml",
                    "status": status_icon,
                    "reflection": reflection_text,
                    "fill_mode": fill_mode,  # v6.2 R4-A2: routing trace
                })
            else:
                audit["missed"] += 1
                audit["details"].append({
                    "label": text,
                    "value": "",
                    "source": f"{result['config_file']}.yaml (缺失)",
                    "status": "⚠️" if fill_mode == "literal-mismatch" else "❌",
                    "reflection": "",
                    "fill_mode": fill_mode,  # v6.2 R4-A2: routing trace
                })

    # 保存
    if Path(template_path).resolve() == Path(output_path).resolve():
        raise PrivacyError("Output must not overwrite the original template.")
    buffer = BytesIO()
    doc.save(buffer)
    private_write(output_path, buffer.getvalue())
    print("\n✅ 已保存填写结果（路径和内容隐藏）")

    # v6.3 R5-A3: surface any fallback warnings from the XML iter path
    if audit.get("warnings"):
        print(f"⚠️ {len(audit['warnings'])} cell(s) used fallback path; "
              "see audit.md for details")

    return safe_audit(audit)


def _cell_is_empty_for_fill(cell) -> bool:
    """A text-empty cell can still contain a picture, field or content control."""
    if cell.text.strip():
        return False
    return not bool(cell._tc.xpath(
        ".//w:drawing | .//w:pict | .//w:object | .//w:fldChar | .//w:instrText | .//w:sdt | .//w:tbl"
    ))


def _find_value_cell(table, label_row: int, label_col: int, seen_cells: set):
    """Select the first distinct adjacent empty cell; never overwrite values/labels.

    Merged aliases of the label itself are skipped. An occupied right-hand cell
    stops this field rather than sending its value to an unrelated cell below.
    """
    label_tc = table.rows[label_row].cells[label_col]._tc
    for col in range(label_col + 1, len(table.columns)):
        cell = table.rows[label_row].cells[col]
        if cell._tc is label_tc:
            continue
        return cell if id(cell._tc) not in seen_cells and _cell_is_empty_for_fill(cell) else None

    for row in range(label_row + 1, len(table.rows)):
        cell = table.rows[row].cells[label_col]
        if cell._tc is label_tc:
            continue
        return cell if id(cell._tc) not in seen_cells and _cell_is_empty_for_fill(cell) else None
    return None


def _iter_unique_cells(table):
    """v6.1 (R3-A2, Pattern D2): iterate `w:tc` elements directly to avoid
    double-counting merged cells.

    python-docx's `table.rows[ri].cells[ci]` returns the SAME `w:tc` element
    multiple times when a cell is horizontally/vertically merged. By walking
    the underlying XML tree, each `w:tc` is visited exactly once.

    Yields (row_index, col_index, cell_object, tc_id) tuples with positions
    reconstructed from the table grid.
    """
    tbl = table._tbl
    rows_seen = 0
    for tr in tbl.iterchildren("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"):
        cells_in_row = []
        col_idx = 0
        for tc in tr.iterchildren("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc"):
            # gridSpan: how many columns this tc occupies
            gridSpan_el = tc.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcPr/{http://schemas.openxmlformats.org/wordprocessingml/2006/main}gridSpan")
            grid_span = int(gridSpan_el.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "1")) if gridSpan_el is not None else 1
            cells_in_row.append((tc, col_idx, grid_span))
            col_idx += grid_span
        # Yield each cell once, with its starting column index
        for tc, start_col, span in cells_in_row:
            # Build a Cell wrapper from tc (python-docx style)
            from docx.table import _Cell
            cell = _Cell(tc, table)
            yield rows_seen, start_col, cell, id(tc)
        rows_seen += 1


def print_audit(audit: dict):
    """打印填写对照表（含自检反思列）"""
    audit = safe_audit(audit)
    print("\n" + "=" * 60)
    print("📋 填写对照表")
    print("=" * 60)
    print(f"✅ 已填充: {audit['filled']}  ❌ 缺失: {audit['missed']}")
    print("-" * 60)

    for item in audit["details"]:
        refl = item.get("reflection", "")
        suffix = f"  ↪ {refl}" if refl else ""
        print(f"  {item['status']} {item['label']}: {item['value']} ({item['source']}){suffix}")

    total = audit["filled"] + audit["missed"]
    if total > 0:
        rate = audit["filled"] / total * 100
        print(f"\n📊 自动填充率: {rate:.0f}%")


def main():
    parser = argparse.ArgumentParser(description="DOCX 本地填表工具 (form-filler v7)")
    parser.add_argument("--template", required=True, help="DOCX 模板文件路径")
    parser.add_argument("--profile-dir", default=None, help="显式选择旧资料目录；省略时仅从仓库外的本地数据目录读取加密档案")
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument("--scan-only", action="store_true", help="仅扫描不填写")
    parser.add_argument("--reflexion-rounds", type=int, default=0,
                        help="v5.0+ Reflexion 自检反思轮数（默认 0 = 关闭，1 = 推荐）")
    parser.add_argument("--audit-out", default=None,
                        help="v5.0+ 填写对照表输出路径（默认 {output_basename}_audit.md）")
    parser.add_argument("--audit-template", default=str(Path(__file__).resolve().parent.parent / "templates/audit_table.md"),
                        help="v5.0+ 对照表模板路径")
    parser.add_argument("--write-profile", action="store_true",
                        help="只生成不含值的本地摘要，旧版明文 profile 副本已停用")
    parser.add_argument("--table-name", default=None,
                        help="v5.0+ 写入对照表的「表格名称」字段")
    # v6.0 新增
    parser.add_argument("--provider", default="stub",
                        choices=["stub", "local-model", "openai-compatible", "mock"],
                        help="stub=离线规则；local-model=显式本机模型；旧 openai-compatible 名称也仅允许本机")
    parser.add_argument("--llm-base-url", default=None,
                        help="v6.0 OpenAI 兼容 endpoint base URL (也可 LLM_BASE_URL 环境变量)")
    parser.add_argument("--llm-api-key", default=None,
                        help="已禁用：不得通过命令行传递密钥；本机鉴权用 FORM_FILLER_LOCAL_TOKEN")
    parser.add_argument("--llm-model-name", default=None,
                        help="v6.0 模型名 (也可 LLM_MODEL_NAME 环境变量)")
    parser.add_argument("--introspect-out", default=None,
                        help="v6.0 持久化表格扫描结果为 JSON (Pattern J)")
    parser.add_argument("--no-schema-ai", action="store_true",
                        help="v6.0 关闭 Pydantic schema-as-prompt，强制走原始 prompt 路径")
    # v6.2 R4-A1 新增
    parser.add_argument("--max-retries", type=int, default=None,
                        help="v6.2 R4-A1 LLM reflect() 失败重试次数 (默认 2；设 0 关闭 = v6.0 行为；也可 LLM_REFLECT_RETRIES 环境变量)")
    # v6.2 R4-A3 新增
    parser.add_argument("--mock-canned", default=None,
                        help="v6.2 R4-A3 MockLLM 的 canned_responses JSON 路径 (需 --provider mock)")
    # v6.3 R5-A1 新增
    parser.add_argument("--scan-mode", default="auto",
                        choices=["auto", "jinja", "cell"],
                        help="v6.3 R5-A1 扫描模式: auto (default) 检测到 {{var}} 则切换 jinja; "
                             "jinja 强制 jinja 模式; cell 强制走原有 cell-walk (v6.2 行为)")

    args = parser.parse_args()
    if args.llm_api_key:
        parser.error("Command-line API keys are disabled. Use the local token environment variable.")
    explicit_profile_dir = args.profile_dir is not None
    args.profile_dir = args.profile_dir or str(local_data_dir() / "profiles")

    output = args.output or str(local_data_dir() / "outputs" / (__import__("uuid").uuid4().hex + ".docx"))
    audit_path = args.audit_out or (str(Path(output).with_suffix("")) + "_audit.md")
    inputs = [args.template]
    if not args.scan_only:
        inputs.extend([args.audit_template, args.mock_canned])
        inputs.extend(p for p in Path(args.profile_dir).glob("*") if p.is_file())
    outputs = [args.introspect_out]
    if not args.scan_only:
        outputs.extend([output, audit_path])
        if args.write_profile:
            outputs.append(Path(output).parent / "profile.md")
    protect_inputs(outputs, inputs)

    # Structural inspection must work on first use, without profiles or model init.
    if args.scan_only:
        fields = scan_docx_tables(args.template)
        if args.introspect_out:
            intro = scan_docx_introspect(args.template)
            private_text(args.introspect_out, json.dumps(intro, ensure_ascii=False, indent=2))
            print("📥 结构摘要已保存本地")
        print(f"\n📊 共发现 {len(fields)} 个单元格")
        return

    # 加载配置
    print("📂 加载配置文件...")
    profiles = load_profiles(args.profile_dir, allow_plain=explicit_profile_dir)
    if not profiles:
        print("❌ 未找到配置文件，请先创建 profiles/ 目录并添加 YAML 文件")
        sys.exit(1)

    # v6.0: 初始化 Model Adapter（默认 stub 保持 v5.0 行为）
    # v6.2 R4-A1: max_retries 透传到 OpenAICompatibleAdapter；v6.2 R4-A3: mock 接收 canned_responses
    adapter_kwargs = dict(
        provider=args.provider,
        base_url=args.llm_base_url,
        api_key=args.llm_api_key,
        model_name=args.llm_model_name,
    )
    if args.max_retries is not None:
        adapter_kwargs["max_retries"] = args.max_retries
    if args.provider == "mock" and args.mock_canned:
        try:
            with open(args.mock_canned, "r", encoding="utf-8") as f:
                adapter_kwargs["canned_responses"] = json.load(f)
        except Exception as exc:
            print("⚠️ 加载 mock-canned JSON 失败（详情隐藏）；使用空 canned dict",
                  file=sys.stderr)
            adapter_kwargs["canned_responses"] = {}
    adapter = get_adapter(**adapter_kwargs)
    print(f"🤖 Model Adapter: {adapter.name} (live={adapter.is_live()}, max_retries={getattr(adapter, 'max_retries', 0)})")

    # 扫描模板
    print("\n🔍 本地扫描模板（路径和原值隐藏）")
    fields = scan_docx_tables(args.template)

    # v6.0: --introspect-out 持久化扫描结果（Pattern J）
    if args.introspect_out:
        try:
            intro = scan_docx_introspect(args.template)
            private_text(args.introspect_out, json.dumps(intro, ensure_ascii=False, indent=2))
            print("📥 结构摘要已保存本地")
        except Exception as exc:
            print("⚠️ 结构摘要写入失败（详情隐藏）")

    # 填写
    print(f"\n✍️ 开始填写...")
    # Optional value-free summary lives beside the explicitly chosen output.
    profile_md_dir = str(Path(output).parent) if args.write_profile else None
    profile_counter_dir = args.profile_dir
    audit = fill_docx(args.template, profiles, output,
                      reflexion_rounds=args.reflexion_rounds,
                      profile_md_dir=profile_md_dir,
                      profile_counter_dir=profile_counter_dir,
                      adapter=adapter,
                      schema_ai_generate=not args.no_schema_ai,
                      scan_mode=args.scan_mode)
    print_audit(audit)

    # v5.0+: 写入 audit.md 文件
    try:
        audit["table_name"] = args.table_name or Path(args.template).stem
        audit["date"] = __import__("datetime").date.today().isoformat()
        audit["input_format"] = "DOCX"
        audit["info_source"] = "（无）"
        audit["attachments"] = 0
        render_audit_table(audit, args.audit_template, audit_path)
        print("📋 已保存不含填写值的本地对照表")
    except Exception as exc:
        print("⚠️ 对照表写入失败（详情隐藏）")


if __name__ == "__main__":
    utf8_console()
    try:
        main()
    except Exception:
        print("本地操作失败（详情隐藏）；请在本机检查输入、存储目录或模型地址。", file=sys.stderr)
        sys.exit(1)

