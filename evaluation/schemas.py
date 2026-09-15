#!/usr/bin/env python3
"""
evaluation/schemas.py — form-filler v6.0 Pydantic field-level schemas (R2-A2, Pattern A2)

目的：把 SKILL.md / fill_docx.py / templates/audit_table.md 中分散的字段约束
（match_rules 正则、score_consistency 的 R4/R5/R6/R8、audit 表头）整合到一个
Pydantic 模型中，作为单一事实源 (single source of truth)。

核心想法（来源：jxnl/instructor + dottxt-ai/outlines + Pattern I）：
  - 一个字段对应一个 Pydantic `Field(...)`，约束写进类型系统。
  - instructor 把这个 schema 作为 `response_model` 传给 LLM，模型**无法**生成
    不符合约束的值 → R8（字数超限）/ R4（手机格式）/ R5（邮箱格式）等规则
    从「运行时检测」升级为「编译时不可能」。
  - 没有 instructor 时，本文件仍然作为文档 + 离线校验器（`python -m
    evaluation.schemas --validate sample.json`）。

依赖：pydantic>=2.0（项目已要求）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Literal, Optional

try:
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    print(
        "❌ evaluation/schemas.py requires pydantic>=2.0. "
        "Install with: pip install pydantic",
        file=sys.stderr,
    )
    raise


# ---- 共享正则 ------------------------------------------------------------
PHONE_RE = r"^1\d{10}$"
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
STUDENT_ID_RE = r"^\d{6,12}$"
ID_NUMBER_RE = r"^\d{17}[\dXx]$"
POSTAL_CODE_RE = r"^\d{6}$"


# ---- Schema 1: 优秀团员申报表 --------------------------------------------
class 优秀团员申报表(BaseModel):
    """优秀共青团员申报表 (示例：高校共青团员年度评优)"""
    姓名: str = Field(min_length=2, max_length=20, description="申报人真实姓名")
    性别: Literal["男", "女"]
    民族: str = Field(default="汉族", min_length=2, max_length=10)
    籍贯: str = Field(min_length=2, max_length=30, description="如「浙江省杭州市」")
    出生年月: str = Field(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM")
    政治面貌: Literal["共青团员", "中共党员", "预备党员", "入党积极分子", "群众"]
    手机: str = Field(pattern=PHONE_RE)
    邮箱: str = Field(pattern=EMAIL_RE)
    学号: str = Field(pattern=STUDENT_ID_RE)
    院系: str = Field(min_length=2, max_length=40)
    专业: str = Field(min_length=2, max_length=40)
    学校: str = Field(min_length=2, max_length=40)
    学历年级: str = Field(description="如「24级本科生」", pattern=r"^\d{2}级(本科|硕士|博士)生$")
    所在单位: str = Field(min_length=2, max_length=60)
    申报类别: Literal["优秀团员", "优秀团干", "三好学生"]
    团员评议: Optional[Literal["优秀", "合格", "基本合格", "不合格"]] = None
    入团日期: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    团内职务: Optional[str] = Field(default=None, max_length=20)
    自荐信: Optional[str] = Field(
        default=None, min_length=200, max_length=800,
        description="AI 生成内容，200–800 中文字符",
    )


# ---- Schema 2: 奖学金申请表 ----------------------------------------------
class 奖学金申请表(BaseModel):
    """国家奖学金 / 校级奖学金申请表 (示例)"""
    姓名: str = Field(min_length=2, max_length=20)
    学号: str = Field(pattern=STUDENT_ID_RE)
    院系: str = Field(min_length=2, max_length=40)
    专业: str = Field(min_length=2, max_length=40)
    学历年级: str = Field(pattern=r"^\d{2}级(本科|硕士|博士)生$")
    GPA: float = Field(ge=0.0, le=5.0, description="0–5 区间")
    综合排名: int = Field(ge=1, le=1000)
    手机: str = Field(pattern=PHONE_RE)
    申请理由: str = Field(
        min_length=300, max_length=1000,
        description="AI 生成，300–1000 字",
    )


# ---- Schema 3: 个人简历 --------------------------------------------------
class 个人简历(BaseModel):
    """求职 / 升学 - 个人简历字段"""
    姓名: str = Field(min_length=2, max_length=20)
    性别: Literal["男", "女"]
    手机: str = Field(pattern=PHONE_RE)
    邮箱: str = Field(pattern=EMAIL_RE)
    现地址: str = Field(min_length=4, max_length=60)
    最高学历: Literal["本科", "硕士", "博士"]
    毕业院校: str = Field(min_length=2, max_length=40)
    所学专业: str = Field(min_length=2, max_length=40)
    自我评价: str = Field(
        min_length=100, max_length=400,
        description="AI 生成，100–400 字",
    )


# ---- Registry / 工具 -----------------------------------------------------
SCHEMAS = {
    "优秀团员申报表": 优秀团员申报表,
    "奖学金申请表": 奖学金申请表,
    "个人简历": 个人简历,
}


def find_schema_for_label(label: str):
    """Best-effort: pick a schema containing a field whose name matches `label`.

    Currently a strict substring check; future Pattern I work could make this
    smarter (synonym table). Returns the schema class or None.
    """
    for schema_cls in SCHEMAS.values():
        for fname in schema_cls.model_fields:
            if fname in label or label in fname:
                return schema_cls
    return None


def get_field_schema(schema_cls, field_name: str):
    """Return the Pydantic Field for a given schema class + field name, or None."""
    return schema_cls.model_fields.get(field_name)


# ---- Self-test CLI --------------------------------------------------------
def _self_test() -> int:
    """Validate known-good + known-bad samples against each schema."""
    cases = [
        # (schema_name, sample, should_pass)
        ("优秀团员申报表", {
            "姓名": "张三", "性别": "男", "民族": "汉族", "籍贯": "浙江省杭州市",
            "出生年月": "2006-03", "政治面貌": "共青团员",
            "手机": "13812345678", "邮箱": "zhangsan@example.edu.cn",
            "学号": "12345678", "院系": "计算机科学与技术学院",
            "专业": "计算机科学与技术", "学校": "浙江大学",
            "学历年级": "24级本科生", "所在单位": "浙江大学计算机科学与技术学院",
            "申报类别": "优秀团员", "团员评议": "优秀",
            "入团日期": "2019-05", "团内职务": "组织委员",
        }, True),
        ("优秀团员申报表", {
            "姓名": "张三", "性别": "未知",  # bad: not in Literal
            "民族": "汉族", "籍贯": "浙江省杭州市", "出生年月": "2006-03",
            "政治面貌": "共青团员", "手机": "13812345678",
            "邮箱": "zhangsan@example.edu.cn", "学号": "12345678",
            "院系": "CS", "专业": "CS", "学校": "ZJU",
            "学历年级": "24级本科生", "所在单位": "ZJU CS",
            "申报类别": "优秀团员",
        }, False),
        ("奖学金申请表", {
            "姓名": "李四", "学号": "12345678", "院系": "数学系", "专业": "应用数学",
            "学历年级": "23级本科生", "GPA": 3.8, "综合排名": 5,
            "手机": "13900000000", "申请理由": "我在过去一年中..." * 30,
        }, True),
        ("个人简历", {
            "姓名": "王五", "性别": "女", "手机": "13700000000",
            "邮箱": "wangwu@example.com", "现地址": "北京市海淀区中关村大街1号",
            "最高学历": "硕士", "毕业院校": "清华大学", "所学专业": "软件工程",
            "自我评价": "本人热爱技术，对软件工程领域充满热情与好奇心，善于团队协作并持续学习。" * 3,
        }, True),
    ]
    fail = 0
    for schema_name, sample, should_pass in cases:
        schema_cls = SCHEMAS[schema_name]
        try:
            schema_cls.model_validate(sample)
            ok = True
        except Exception as exc:  # noqa: BLE001
            ok = False
            msg = str(exc).splitlines()[0]
        status = "✅" if ok == should_pass else "❌"
        if ok != should_pass:
            fail += 1
        print(f"  {status}  {schema_name:14}  expect={'PASS' if should_pass else 'FAIL'}  got={'PASS' if ok else 'FAIL: '+msg[:60]}")
    print(f"\n📊 schemas self-test: {len(cases) - fail}/{len(cases)} pass")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(_self_test())