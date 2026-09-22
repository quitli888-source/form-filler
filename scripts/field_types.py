#!/usr/bin/env python3
r"""
scripts/field_types.py — form-filler v6.4 (R6-A3): 确定性字段类型推断

纯标准库实现（无第三方依赖）。为 `scan_docx_introspect()` 的 JSON 输出提供
确定性的 `type` / `required` / `empty` 标注——同一输入永远得到同一输出，
不经过 LLM，因此可复现、可测试、可diff。

推断策略（优先级从高到低）：
  1. 值模式（value pattern）：日期 / 电话 / 邮箱 / 金额（含单位数量）/ 复选框。
     值比标签更难伪造，优先按值形态判断。
  2. 标签关键词（label keyword）：中文表格标签的常规用词（出生|日期|年月|时间 …）。
  3. 默认 `text`。

设计细节（kordoc 注释级）：
  - **裸数字不让位 amount**："310000"（邮编）/ "2024001"（编号）与金额在纯数字
    形态下歧义；只有带千分位（1,234）或带单位数量（5万元 / 6个月）时才判 amount。
  - 日期同时接受 `2024-09-15` 三组件与 `2024-09` 年月两组件形态（profiles 里
    start_date / league_join_date 用的是后者）。

self-test: `python scripts/field_types.py` 打印真值表。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 值模式（值形态优先）
# ---------------------------------------------------------------------------

# 日期：2024-09-15 / 2024.9.15 / 2024年9月15日 / 2024/09/15（分隔符可混带空格）
_DATE_RE = re.compile(
    r"^\d{4}\s*[-./年]\s*\d{1,2}\s*[-./月]\s*\d{1,2}\s*日?$"
)
# 日期（年月两组件）：2024-09 / 2024年9月 —— profiles 的 start_date 常用形态
_DATE_YM_RE = re.compile(
    r"^\d{4}\s*[-./年]\s*\d{1,2}\s*月?$"
)
# 电话/手机：13812345678 / 010-1234-5678 / 021 6688 1234（区号可选 0 前缀）
_PHONE_RE = re.compile(
    r"^0?\d{3}[-.\s]?\d{4}[-.\s]?\d{4}$"
)
# 邮箱：ASCII local-part + @ + 多级域名
_EMAIL_RE = re.compile(
    r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$"
)
# 金额（千分位）：1,234 / 12,345,678 —— 千分位是强金额信号
_AMOUNT_THOUSANDS_RE = re.compile(
    r"^\d{1,3}(,\d{3})+$"
)
# 金额/数量（带单位）：5万元 / 8000元 / 6个月 / 3人 / 2个
_AMOUNT_UNIT_RE = re.compile(
    r"^\d+(?:\.\d+)?\s*(?:万元|亿元|元|块钱|个月|月|人|个|名|位|年|天|日|次|件|条|张|份|台|部|间|%|％)$"
)
# 复选框符号（出现即判定，不要求全文等于符号）
_CHECKBOX_CHARS = "□☑✓✔"

# ---------------------------------------------------------------------------
# 标签关键词（回退路径——值形态不明确时按标签惯例判断）
# ---------------------------------------------------------------------------

_LABEL_DATE_KEYWORDS = ("出生", "日期", "年月", "时间")
_LABEL_PHONE_KEYWORDS = ("手机", "电话", "联系", "号码")
_LABEL_EMAIL_KEYWORDS = ("邮箱", "邮件")
_LABEL_AMOUNT_KEYWORDS = ("金额", "数量", "合计", "总额")

# 必填标记：* ※ ★ / （必填） / (必填)
_REQUIRED_RE = re.compile(r"[*※★]|（\s*必填\s*）|\(\s*必填\s*\)")

# 空值/占位符：空串，或仅由空白与占位字符（_()（）-—–~.·,）组成
_EMPTY_RE = re.compile(r"^[\s_()（）\-—–~.·,]*$")


def infer_field_type(label: str, value: str) -> str:
    r"""推断字段类型，返回 "date" | "phone" | "email" | "amount" | "checkbox" | "text"。

    值模式优先（date/phone/email/amount/checkbox 按值形态判定），
    标签关键词回退（中文表格标签惯例），都够不着默认 "text"。

    注意：裸数字（无千分位、无单位）不判 amount——邮编/编号歧义，
    只有 `^\d{1,3}(,\d{3})+$` 或带单位数量才判 amount。

    >>> infer_field_type("出生日期", "2006-03-15")
    'date'
    >>> infer_field_type("手机", "13812345678")
    'phone'
    >>> infer_field_type("姓名", "张三")
    'text'
    """
    v = (value or "").strip()

    # --- 1. 值模式 ---
    if any(ch in v for ch in _CHECKBOX_CHARS):
        return "checkbox"
    if _DATE_RE.match(v) or _DATE_YM_RE.match(v):
        return "date"
    if _PHONE_RE.match(v):
        return "phone"
    if _EMAIL_RE.match(v):
        return "email"
    if _AMOUNT_THOUSANDS_RE.match(v) or _AMOUNT_UNIT_RE.match(v):
        return "amount"

    # --- 2. 标签关键词回退 ---
    lbl = label or ""
    if any(k in lbl for k in _LABEL_DATE_KEYWORDS):
        return "date"
    if any(k in lbl for k in _LABEL_PHONE_KEYWORDS):
        return "phone"
    if any(k in lbl for k in _LABEL_EMAIL_KEYWORDS):
        return "email"
    if any(k in lbl for k in _LABEL_AMOUNT_KEYWORDS):
        return "amount"

    # --- 3. 默认 ---
    return "text"


def is_required_label(label: str) -> bool:
    """标签是否带必填标记：`*` / `※` / `★` / `（必填）` / `(必填)`。

    >>> is_required_label("姓名*")
    True
    >>> is_required_label("（必填）邮箱")
    True
    >>> is_required_label("姓名")
    False
    """
    return bool(_REQUIRED_RE.search(label or ""))


def is_empty_value(value: str) -> bool:
    """值是否为空或占位符：空串，或仅由空白与占位字符
    （_ ( ) （ ） - — – ~ . · ,）组成。

    >>> is_empty_value("")
    True
    >>> is_empty_value("  ___  ")
    True
    >>> is_empty_value("张三")
    False
    """
    return bool(_EMPTY_RE.match(value or ""))


if __name__ == "__main__":
    # Self-test: 真值表打印（确定性输出，无网络无 key）
    print("=" * 64)
    print("field_types.py self-test (v6.4 R6-A3)")
    print("=" * 64)

    type_cases = [
        # (label, value, expected) — 值模式段
        ("出生日期", "2006-03-15", "date"),
        ("入职时间", "2024年9月1日", "date"),
        ("开始日期", "2024/09/01", "date"),
        ("起始年月", "2024-09", "date"),
        ("手机", "13812345678", "phone"),
        ("联系电话", "010-6688-1234", "phone"),
        ("邮箱", "zhangsan@example.edu.cn", "email"),
        ("奖学金金额", "12,000", "amount"),
        ("实习时长", "6个月", "amount"),
        ("月收入", "1万元", "amount"),
        ("参与人数", "3人", "amount"),
        ("健康状况", "□ 良好 ☑ 一般", "checkbox"),
        # 裸数字/编号 → text（不让位 amount）
        ("邮编", "310000", "text"),
        ("学号", "2024001", "text"),
        # 标签回退段
        ("出生年月", "", "date"),
        ("联系电话", "", "phone"),
        ("电子邮件", "", "email"),
        ("合计金额", "", "amount"),
        ("姓名", "张三", "text"),
        ("个人陈述", "本人品行端正……", "text"),
    ]
    failures = 0
    for label, value, expected in type_cases:
        got = infer_field_type(label, value)
        ok = got == expected
        failures += (not ok)
        mark = "✅" if ok else "❌"
        print(f"  {mark} infer({label!r}, {value!r}) = {got!r} (expect {expected!r})")

    print("-" * 64)
    required_cases = [
        ("姓名*", True), ("※ 邮箱", True), ("（必填）电话", True),
        ("(必填)金额", True), ("★政治面貌", True), ("姓名", False), ("邮箱", False),
    ]
    for label, expected in required_cases:
        got = is_required_label(label)
        ok = got == expected
        failures += (not ok)
        mark = "✅" if ok else "❌"
        print(f"  {mark} is_required({label!r}) = {got} (expect {expected})")

    print("-" * 64)
    empty_cases = [
        ("", True), ("   ", True), ("___", True), ("（ ）", True),
        ("-.~,", True), ("张三", False), ("□", False),
    ]
    for value, expected in empty_cases:
        got = is_empty_value(value)
        ok = got == expected
        failures += (not ok)
        mark = "✅" if ok else "❌"
        print(f"  {mark} is_empty({value!r}) = {got} (expect {expected})")

    print("=" * 64)
    if failures:
        print(f"❌ {failures} case(s) FAILED")
        raise SystemExit(1)
    print(f"✅ all {len(type_cases) + len(required_cases) + len(empty_cases)} cases passed")
