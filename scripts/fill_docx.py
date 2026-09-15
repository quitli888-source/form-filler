#!/usr/bin/env python3
"""
DOCX 表格填写示例脚本 — form-filler 辅助工具 (v6.2)

功能：
  1. 读取 DOCX 表格模板，识别字段结构
  2. 从 YAML 配置文件加载用户信息
  3. 语义匹配字段 → 自动填写
  4. 处理合并单元格
  5. 生成填写对照表（audit.md 文件）
  6. (v5.0) 生成 profile.md 中间产物（Step 2.5）
  7. (v5.0→v6.0) Reflexion 自检反思走 Model Adapter（默认 Stub，可选 OpenAI 兼容）
  8. (v6.0) AI 生成字段走 Pydantic schema-as-prompt（可选；instructor 未装则降级）
  9. (v6.0) 审计表 PII 字段脱敏（手机/邮箱/身份证）
 10. (v6.0) `--introspect-out` 持久化 form-field 扫描结果为 JSON
 11. (v6.2 R4-A1) reflect() 失败时自动重试，默认 max_retries=2，CLI 标志 --max-retries N
 12. (v6.2 R4-A2) Literal-约束字段走 Pass 0 确定性路由，跳过 LLM 反射
 13. (v6.2 R4-A2) audit 行新增 `fill_mode` 字段（literal | schema | regex | llm）

用法：
  python fill_docx.py --template 优秀团员申报表.docx --profile-dir ./profiles --output 优秀团员申报表_已填写.docx
  python fill_docx.py --template T.docx --profile-dir ./profiles --output O.docx --reflexion-rounds 1
  python fill_docx.py --template T.docx --profile-dir ./profiles --output O.docx --write-profile
  python fill_docx.py --template T.docx --profile-dir ./profiles --output O.docx --audit-out ./audit.md
  # 启用真实 LLM（默认 stub）
  python fill_docx.py --template T.docx --profile-dir ./profiles --output O.docx \
      --provider openai-compatible --llm-model-name MiniMax-M3 \
      --llm-base-url https://api.minimax.chat/v1 --llm-api-key $LLM_API_KEY \
      --reflexion-rounds 1

依赖：
  pip install python-docx pyyaml
  可选（启用真实 LLM / schema-as-prompt）：pip install openai instructor pydantic
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Literal, get_args, get_origin  # v6.2 R4-A2: Literal introspection

import yaml
from docx import Document

# 让 scripts/ 子目录互相 import
sys.path.insert(0, str(Path(__file__).parent))
from model_adapter import StubAdapter, get_adapter  # noqa: E402

# 可选依赖：pydantic + schemas（缺失则降级到 v5.0 行为）
try:
    from evaluation.schemas import SCHEMAS, find_schema_for_label, find_field_in_schema  # noqa: E402
except Exception:  # ImportError or evaluation package missing
    SCHEMAS = {}
    find_schema_for_label = lambda label: None  # noqa: E731
    find_field_in_schema = lambda label, schema_cls=None: None  # noqa: E731


def load_profiles(profile_dir: str) -> dict:
    """加载 profiles/ 目录下所有 YAML 配置文件"""
    profiles = {}
    profile_path = Path(profile_dir)
    if not profile_path.exists():
        print(f"⚠️ 配置目录不存在: {profile_dir}")
        return profiles

    for yaml_file in profile_path.glob("*.yaml"):
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            profiles[yaml_file.stem] = data
            print(f"  📄 加载 {yaml_file.name}")

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
                cell_id = id(cell._tc)
                if cell_id in seen_cells:
                    continue
                seen_cells.add(cell_id)

                text = cell.text.strip()
                if text:
                    fields.append({
                        "table": ti,
                        "row": ri,
                        "col": ci,
                        "text": text,
                        "is_label": _is_likely_label(text),
                    })
                    label = "标签" if _is_likely_label(text) else "值"
                    print(f"  [{ri},{ci}] {label}: {text[:30]}")

    return fields


def scan_docx_introspect(doc_path: str) -> dict:
    """v6.0 (R2-A3, Pattern J): 把 scan_docx_tables 结果持久化为可序列化的 JSON 结构。

    用途：供下游 Schema 选择 / Round 3+ 自动化回归测试使用。
    不依赖任何运行时状态；纯静态扫描。
    """
    doc = Document(doc_path)
    tables_data = []
    for ti, table in enumerate(doc.tables):
        seen_cells = set()
        rows = []
        for ri, row in enumerate(table.rows):
            cells = []
            for ci, cell in enumerate(row.cells):
                cell_id = id(cell._tc)
                if cell_id in seen_cells:
                    cells.append({"row": ri, "col": ci, "text": "", "is_label": False, "merged_dup": True})
                    continue
                seen_cells.add(cell_id)
                text = cell.text.strip()
                cells.append({
                    "row": ri, "col": ci, "text": text,
                    "is_label": _is_likely_label(text),
                    "merged_dup": False,
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
        "template": str(Path(doc_path).name),
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "tables": tables_data,
        "labels": [
            {"table": ti, "row": f["row"], "col": f["col"], "text": f["text"]}
            for f in [
                {"table": ti, "row": ri, "col": ci, "text": text, "is_label": _is_likely_label(text)}
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


def _is_likely_label(text: str) -> bool:
    """判断单元格文本是否是字段标签（而非待填写值）"""
    if len(text) > 20:
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
    """从入学年份+学位推断年级"""
    edu = profiles.get("education", {})
    entries = edu.get("entries", [])
    if not entries:
        return None
    entry = entries[0]
    start_date = entry.get("start_date", "")
    degree = entry.get("degree", "")
    if start_date and degree:
        year = start_date.split("-")[0]
        return f"{year[2:]}级{degree}生"
    return None


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
match_rules = [
    (r"申报人姓名|申请人|姓名", "personal", "name", None),
    (r"性别", "personal", "gender", None),
    (r"民族", "personal", "ethnicity", None),
    (r"籍贯|出生地", "personal", "birthplace", None),
    (r"出生年月|出生日期", "personal", "birth_date", None),
    (r"政治面貌", "personal", "political_status", None),
    (r"手机|电话", "contact", "phone", None),
    (r"邮箱|电子邮件", "contact", "email", None),
    (r"学号|工号", "education", "entries.0.student_id", None),
    (r"专业", "education", "entries.0.major", None),
    (r"院系", "education", "entries.0.department", None),
    (r"学校", "education", "entries.0.school", None),
    (r"学历|年级", "education", "entries.0.degree", _compute_grade),
    (r"所在单位", "education", None, _compute_workplace),
    (r"申报类别", "education", "entries.0.degree", _compute_category),
    (r"团员评议|评议等级", "league", "league_evaluation", None),
    (r"入团日期", "league", "league_join_date", None),
    (r"党内职务|团内职务", "league", "league_position", None),
]


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
                            f"⚠️ profile value for '{field_name}' ({norm_value!r}) "
                            f"not in Literal set {sorted(norm_literals)}; "
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
    """
    将 profiles dict 扁平化为人类可读的 markdown spec，写到 out_dir 下：
      - profile_v{N}.md   （N 由 profiles_dir/.profile_counter 持久化，默认 N=1）
      - profile.md        （覆盖为最新版本的拷贝）

    profiles_dir 仅用于读取/递增版本计数器（profiles/.profile_counter），
    不会写入任何 profile.md 派生产物 —— 派生产物与输出 DOCX 同目录，
    避免污染 git-trackable 的 profiles/ 目录。

    返回正文（不含 frontmatter）的 8 字符 SHA-256 校验和，供 Step 2.5 / Step 5.5
    的 prompt 中引用。
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 决定下一个版本号：使用 profiles_dir/.profile_counter 文件持久化
    counter_dir = Path(profiles_dir) if profiles_dir else out_path
    counter_file = counter_dir / ".profile_counter"
    if counter_file.exists():
        try:
            next_n = int(counter_file.read_text(encoding="utf-8").strip()) + 1
        except (ValueError, OSError):
            next_n = 1
    else:
        # 默认 N=1（首次运行），并把计数器写到 counter_dir
        next_n = 1
    try:
        counter_dir.mkdir(parents=True, exist_ok=True)
        counter_file.write_text(str(next_n), encoding="utf-8")
    except OSError:
        # 若 counter 目录不可写，忽略（不阻塞主流程）
        pass

    versioned = out_path / f"profile_v{next_n}.md"
    stable = out_path / "profile.md"

    # 拼装 markdown 正文
    personal = profiles.get("personal", {}) or {}
    contact = profiles.get("contact", {}) or {}
    education_entries = (profiles.get("education", {}) or {}).get("entries", []) or []
    league = profiles.get("league", {}) or {}

    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# Profile Spec (v{0}) — generated {1}".format(next_n, ts),
        "> DO NOT CONTRADICT — 后续所有 Step 3–8 prompt 必须以本文档为事实源。",
        "",
        "## Identity",
        f"- 姓名 (zh): {personal.get('name') or '<未填>'}",
        f"- 姓名 (拼音占位): {personal.get('name_pinyin') or '<待填>'}",
        f"- 姓名 (English 占位): {personal.get('name_en') or '<待填>'}",
        f"- 性别: {personal.get('gender') or '<未填>'}",
        f"- 出生日期: {personal.get('birth_date') or '<未填>'}",
        f"- 籍贯: {personal.get('birthplace') or '<未填>'}",
        f"- 民族: {personal.get('ethnicity') or '<未填>'}",
        f"- 政治面貌: {personal.get('political_status') or '<未填>'}",
        "",
        "## Contact",
        f"- 手机: {contact.get('phone') or '<未填>'}",
        f"- 邮箱: {contact.get('email') or '<未填>'}",
        "",
        "## Education (entries[])",
        "| # | 学校 | 院系 | 专业 | 学位 | 入学 | 学号 |",
        "|---|------|------|------|------|------|------|",
    ]
    for i, e in enumerate(education_entries, 1):
        lines.append(
            f"| {i} | {e.get('school') or '<未填>'} | {e.get('department') or '<未填>'} | "
            f"{e.get('major') or '<未填>'} | {e.get('degree') or '<未填>'} | "
            f"{e.get('start_date') or '<未填>'} | {e.get('student_id') or '<未填>'} |"
        )
    lines += [
        "",
        "## League / Party",
        f"- 政治面貌 (personal): {personal.get('political_status') or '<未填>'}",
        f"- 团内职务: {league.get('league_position') or '<未填>'}",
        f"- 党员状态: {league.get('party_status') or '<未填>'}",
        f"- 评议等级: {league.get('league_evaluation') or '<未填>'}",
        f"- 入团日期: {league.get('league_join_date') or '<未填>'}",
        "",
        "## Checksum",
        "SHA-256(正文) = {0}",
        "",
    ]

    body = "\n".join(lines)
    # 用占位符写一次拿到 SHA，然后回填
    placeholder = "0" * 8
    body_for_hash = body.replace("{0}", placeholder, 1)
    digest = hashlib.sha256(body_for_hash.encode("utf-8")).hexdigest()[:8]
    final_body = body.replace("{0}", digest, 1)

    versioned.write_text(final_body, encoding="utf-8")
    stable.write_text(final_body, encoding="utf-8")
    return digest


# ---------------------------------------------------------------------------
# v5.0 新增：填写对照表渲染（R1-A3）
# ---------------------------------------------------------------------------

def render_audit_table(audit: dict, template_path: str, out_path: str) -> None:
    """
    读取 templates/audit_table.md，把 [占位符] 替换为 audit 数据，写到 out_path。
    复用的图标：✅ 🔄 ⚠️ 📝 ❌ 📎
    """
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

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(out, encoding="utf-8")


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
              schema_ai_generate: bool = True) -> dict:
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
    9. 保存结果

    reflexion_rounds: 自检反思轮数（0 = 关闭，1 = 默认）。每轮会调用 adapter.reflect()，
                      反思非空则把反思写入 audit entry 并把状态降级为 ⚠️。
    profile_md_dir: 若提供，则调用 write_profile_md() 把 profile.md 写到该目录
                    （默认建议 = output DOCX 同目录，避免污染 profiles/）。
    profile_counter_dir: 计数器文件目录（默认 profiles/），仅持久化版本号 N。
    _reflect_impl: 可选，注入测试替身；缺省使用 adapter.reflect()。
    adapter: 可选，注入 ModelAdapter 实例；缺省 = StubAdapter()（v5.0 行为）。
    schema_ai_generate: 当 AI 生成字段（📝）匹配到一个 Pydantic schema 时，
                       是否尝试用 adapter.generate_struct() 生成受约束的内容；
                       失败或关闭时回退到原始 prompt。"""
    if profile_md_dir:
        try:
            sha = write_profile_md(
                profiles,
                profile_md_dir,
                profiles_dir=profile_counter_dir,
            )
            print(f"📝 已生成 profile.md (SHA {sha})")
        except Exception as exc:
            print(f"⚠️ profile.md 生成失败: {exc}")

    doc = Document(template_path)
    audit = {"filled": 0, "missed": 0, "inferred": 0, "details": []}
    if adapter is None:
        adapter = StubAdapter()
    reflect_fn = _reflect_impl if _reflect_impl is not None else (
        lambda lbl, val, ctx: adapter.reflect(lbl, val, {"filled_so_far": ctx})
    )

    for table in doc.tables:
        seen_cells = set()

        # v6.1 (R3-A2): iterate w:tc directly to avoid double-counting merged cells
        try:
            cell_iter = list(_iter_unique_cells(table))
        except Exception as exc:
            # Fallback to old behavior if XML iteration fails (defensive)
            print(f"⚠️ _iter_unique_cells failed, fallback: {exc}")
            cell_iter = []
            for ri, row in enumerate(table.rows):
                for ci, cell in enumerate(row.cells):
                    cell_iter.append((ri, ci, cell, id(cell._tc)))

        for ri, ci, cell, cell_id in cell_iter:
            if cell_id in seen_cells:
                continue
            seen_cells.add(cell_id)

            text = cell.text.strip()
            if not _is_likely_label(text):
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
            if value_cell and result["value"]:
                # 清空原有内容
                for p in value_cell.paragraphs:
                    for run in p.runs:
                        run.text = ""
                if value_cell.paragraphs:
                    value_cell.paragraphs[0].text = str(result["value"])
                filled_value = result["value"]
                status_icon = "✅"
            else:
                status_icon = "❌"

            # v6.2 R4-A2: Literal-约束字段跳过 LLM 反思（已校验过枚举值）
            # Reflection would be redundant for closed-enum fields.
            skip_llm = (fill_mode == "literal")

            # Step 5.5 自检反思（走 adapter；StubAdapter 返回 "" = 无意见）
            reflection_text = ""
            if reflexion_rounds > 0 and filled_value and not skip_llm:
                filled_so_far = {
                    d["label"]: d["value"] for d in audit["details"] if d.get("value")
                }
                for _ in range(reflexion_rounds):
                    r = reflect_fn(text, filled_value, filled_so_far)
                    if not r:
                        break  # stub: nothing to reflect on
                    reflection_text = r
                    status_icon = "⚠️"
                    filled_so_far[text] = filled_value
            elif skip_llm and reflexion_rounds > 0 and filled_value:
                # Record the deterministic skip in the audit
                reflection_text = "[skip-llm: literal]"

            if filled_value:
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
                    "status": "❌",
                    "reflection": "",
                    "fill_mode": fill_mode,  # v6.2 R4-A2: routing trace
                })

    # 保存
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    doc.save(output_path)
    print(f"\n✅ 已保存到: {output_path}")

    return audit


def _find_value_cell(table, label_row: int, label_col: int, seen_cells: set):
    """找到标签旁边的值单元格（优先右侧，其次下方）"""
    # 优先右侧
    if label_col + 1 < len(table.columns):
        cell = table.rows[label_row].cells[label_col + 1]
        if id(cell._tc) not in seen_cells or cell.text.strip() == "":
            return cell

    # 其次下方
    if label_row + 1 < len(table.rows):
        cell = table.rows[label_row + 1].cells[label_col]
        if id(cell._tc) not in seen_cells or cell.text.strip() == "":
            return cell

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
    parser = argparse.ArgumentParser(description="DOCX 表格填写工具 (form-filler v6.0)")
    parser.add_argument("--template", required=True, help="DOCX 模板文件路径")
    parser.add_argument("--profile-dir", default="./profiles", help="配置文件目录")
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument("--scan-only", action="store_true", help="仅扫描不填写")
    parser.add_argument("--reflexion-rounds", type=int, default=0,
                        help="v5.0+ Reflexion 自检反思轮数（默认 0 = 关闭，1 = 推荐）")
    parser.add_argument("--audit-out", default=None,
                        help="v5.0+ 填写对照表输出路径（默认 {output_basename}_audit.md）")
    parser.add_argument("--audit-template", default="templates/audit_table.md",
                        help="v5.0+ 对照表模板路径")
    parser.add_argument("--write-profile", action="store_true",
                        help="v5.0+ 先生成 profile.md 中间产物，再填写")
    parser.add_argument("--table-name", default=None,
                        help="v5.0+ 写入对照表的「表格名称」字段")
    # v6.0 新增
    parser.add_argument("--provider", default="stub",
                        choices=["stub", "openai-compatible", "mock"],
                        help="v6.0 Model Adapter provider (默认 stub = v5.0 行为；openai-compatible 启用真实 LLM；mock 启用离线测试桩 v6.2 R4-A3)")
    parser.add_argument("--llm-base-url", default=None,
                        help="v6.0 OpenAI 兼容 endpoint base URL (也可 LLM_BASE_URL 环境变量)")
    parser.add_argument("--llm-api-key", default=None,
                        help="v6.0 API key (也可 LLM_API_KEY 环境变量)")
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

    args = parser.parse_args()

    # 加载配置
    print("📂 加载配置文件...")
    profiles = load_profiles(args.profile_dir)
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
            print(f"⚠️ 加载 mock-canned JSON 失败: {exc}；使用空 canned dict",
                  file=sys.stderr)
            adapter_kwargs["canned_responses"] = {}
    adapter = get_adapter(**adapter_kwargs)
    print(f"🤖 Model Adapter: {adapter.name} (live={adapter.is_live()}, max_retries={getattr(adapter, 'max_retries', 0)})")

    # 扫描模板
    print(f"\n🔍 扫描模板: {args.template}")
    fields = scan_docx_tables(args.template)

    # v6.0: --introspect-out 持久化扫描结果（Pattern J）
    if args.introspect_out:
        try:
            intro = scan_docx_introspect(args.template)
            Path(args.introspect_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.introspect_out).write_text(
                json.dumps(intro, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"📥 introspect 已写入: {args.introspect_out}")
        except Exception as exc:
            print(f"⚠️ introspect 写入失败: {exc}")

    if args.scan_only:
        print(f"\n📊 共发现 {len(fields)} 个单元格")
        return

    # 填写
    output = args.output or args.template.replace(".docx", "_已填写.docx")
    print(f"\n✍️ 开始填写...")
    # profile.md 写到 output DOCX 同目录，计数器仍在 profiles/ 里
    profile_md_dir = str(Path(output).parent) if args.write_profile else None
    profile_counter_dir = args.profile_dir
    audit = fill_docx(args.template, profiles, output,
                      reflexion_rounds=args.reflexion_rounds,
                      profile_md_dir=profile_md_dir,
                      profile_counter_dir=profile_counter_dir,
                      adapter=adapter,
                      schema_ai_generate=not args.no_schema_ai)
    print_audit(audit)

    # v5.0+: 写入 audit.md 文件
    audit_path = args.audit_out or (str(Path(output).with_suffix("")) + "_audit.md")
    try:
        audit["table_name"] = args.table_name or Path(args.template).stem
        audit["date"] = __import__("datetime").date.today().isoformat()
        audit["input_format"] = "DOCX"
        audit["info_source"] = "（无）"
        audit["attachments"] = 0
        render_audit_table(audit, args.audit_template, audit_path)
        print(f"📋 已写入对照表: {audit_path}")
    except Exception as exc:
        print(f"⚠️ 对照表写入失败: {exc}")


if __name__ == "__main__":
    main()
