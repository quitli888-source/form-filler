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


# ---- Schema 4: 入党申请书 (v6.1, R3-A4) ------------------------------------
class 入党申请书(BaseModel):
    """入党申请书 / 入党积极分子登记表 (示例：高校入党流程)"""
    姓名: str = Field(min_length=2, max_length=20)
    性别: Literal["男", "女"]
    出生年月: str = Field(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM")
    籍贯: str = Field(min_length=2, max_length=30)
    民族: str = Field(default="汉族", min_length=2, max_length=10)
    政治面貌: Literal["共青团员", "入党积极分子", "群众"]
    申请日期: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")
    入党动机: str = Field(
        min_length=200, max_length=800,
        description="AI 生成，200–800 中文字符",
    )


# ---- Schema 5: 学位论文申请表 (v6.1, R3-A4) -------------------------------
class 学位论文申请表(BaseModel):
    """硕士 / 博士学位论文答辩申请表"""
    姓名: str = Field(min_length=2, max_length=20)
    学号: str = Field(pattern=STUDENT_ID_RE)
    院系: str = Field(min_length=2, max_length=40)
    专业: str = Field(min_length=2, max_length=40)
    学位: Literal["硕士", "博士"]
    导师: str = Field(min_length=2, max_length=20, description="指导教师姓名")
    论文题目: str = Field(min_length=4, max_length=100, description="完整论文题目")
    答辩日期: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")
    创新点摘要: str = Field(
        min_length=300, max_length=1000,
        description="AI 生成，300–1000 字",
    )


# ---- Schema 6: 实习鉴定表 (v6.1, R3-A4) -----------------------------------
class 实习鉴定表(BaseModel):
    """毕业实习鉴定表 / 单位实习考核表"""
    姓名: str = Field(min_length=2, max_length=20)
    学号: str = Field(pattern=STUDENT_ID_RE)
    院系: str = Field(min_length=2, max_length=40)
    专业: str = Field(min_length=2, max_length=40)
    实习单位: str = Field(min_length=2, max_length=60)
    实习岗位: str = Field(min_length=2, max_length=30)
    实习起止: str = Field(pattern=r"^\d{4}-\d{2}\s*至\s*\d{4}-\d{2}$",
                         description="YYYY-MM 至 YYYY-MM")
    指导老师: str = Field(min_length=2, max_length=20, description="校内指导教师")
    鉴定意见: str = Field(
        min_length=200, max_length=800,
        description="AI 生成，200–800 字",
    )


# ---- Registry / 工具 -----------------------------------------------------
SCHEMAS = {
    "优秀团员申报表": 优秀团员申报表,
    "奖学金申请表": 奖学金申请表,
    "个人简历": 个人简历,
    "入党申请书": 入党申请书,
    "学位论文申请表": 学位论文申请表,
    "实习鉴定表": 实习鉴定表,
}


def find_schema_for_label(label: str):
    """Best-effort: pick a schema containing a field whose name matches `label`.

    Strategy (R3-A1, Pattern A3 schema-first routing):
      1. EXACT match — `label == field_name` (preferred; bypasses regex ambiguity)
      2. SUBSTRING match — `field_name in label` or `label in field_name`
      3. SYNONYM match — handle common aliases (e.g. "申请人" → "姓名", "E-mail" → "邮箱")
    Returns the schema class or None.
    """
    # Synonym table — short list of common DOCX label aliases
    SYNONYMS = {
        "申请人": "姓名",
        "申报人": "姓名",
        "申请人姓名": "姓名",
        "E-mail": "邮箱",
        "email": "邮箱",
        "电子邮件": "邮箱",
        "联系方式": "手机",
        "联系电话": "手机",
        "指导教师": "指导老师",
        "校内导师": "指导老师",
        "论文标题": "论文题目",
    }
    canonical = SYNONYMS.get(label, label)

    # Pass 1: exact match (highest priority — fixes first-match-wins)
    for schema_cls in SCHEMAS.values():
        if canonical in schema_cls.model_fields:
            return schema_cls
    # Pass 2: substring match (fallback)
    for schema_cls in SCHEMAS.values():
        for fname in schema_cls.model_fields:
            if fname in label or label in fname:
                return schema_cls
    return None


def find_field_in_schema(label: str, schema_cls=None):
    """Return the canonical field name in `schema_cls` (or any schema) that matches `label`.

    R3-A1 used by `fill_docx.match_field()` to bypass the regex first-match-wins.
    Returns the canonical field name (str) or None.
    """
    SYNONYMS = {
        "申请人": "姓名",
        "申报人": "姓名",
        "申请人姓名": "姓名",
        "E-mail": "邮箱",
        "email": "邮箱",
        "电子邮件": "邮箱",
        "联系方式": "手机",
        "联系电话": "手机",
        "指导教师": "指导老师",
        "校内导师": "指导老师",
        "论文标题": "论文题目",
    }
    canonical = SYNONYMS.get(label, label)
    candidates = [schema_cls] if schema_cls else list(SCHEMAS.values())
    for sc in candidates:
        if canonical in sc.model_fields:
            return canonical
    # Substring match
    for sc in candidates:
        for fname in sc.model_fields:
            if fname in label or label in fname:
                return fname
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
        # v6.1: R3-A4 new schemas
        ("入党申请书", {
            "姓名": "李华", "性别": "男", "出生年月": "2004-05", "籍贯": "江苏省南京市",
            "民族": "汉族", "政治面貌": "共青团员", "申请日期": "2025-06-01",
            "入党动机": "我志愿加入中国共产党，为共产主义事业奋斗终身，这是我从大学入学以来一直坚守的信念和追求。" * 5,
        }, True),
        ("入党申请书", {
            "姓名": "李华", "性别": "男", "出生年月": "2004年5月",  # bad: pattern mismatch
            "籍贯": "江苏", "民族": "汉族", "政治面貌": "共青团员",
            "申请日期": "2025-06-01", "入党动机": "我志愿加入中国共产党..." * 5,
        }, False),
        ("学位论文申请表", {
            "姓名": "王博士", "学号": "2023001234", "院系": "信息学院",
            "专业": "计算机科学与技术", "学位": "博士",
            "导师": "张教授", "论文题目": "基于深度学习的智能填表关键技术研究",
            "答辩日期": "2026-05-20",
            "创新点摘要": "本文提出..." * 50,
        }, True),
        ("学位论文申请表", {
            "姓名": "王博士", "学号": "2023001234", "院系": "信息学院",
            "专业": "CS", "学位": "本科",  # bad: not Literal 硕士/博士
            "导师": "张教授", "论文题目": "测试题目",
            "答辩日期": "2026-05-20", "创新点摘要": "本文提出..." * 50,
        }, False),
        ("实习鉴定表", {
            "姓名": "陈同学", "学号": "2021005678", "院系": "经济管理学院",
            "专业": "金融学", "实习单位": "中国工商银行北京分行",
            "实习岗位": "客户经理助理", "实习起止": "2024-07 至 2024-09",
            "指导老师": "刘老师", "鉴定意见": "该同学实习期间表现优异，工作认真负责，积极主动学习业务知识，团队协作能力强，圆满完成了实习任务，获得实习单位一致好评。" * 4,
        }, True),
        ("实习鉴定表", {
            "姓名": "陈同学", "学号": "2021005678", "院系": "经济管理学院",
            "专业": "金融学", "实习单位": "中国工商银行北京分行",
            "实习岗位": "客户经理助理", "实习起止": "2024年7月至9月",  # bad: pattern mismatch
            "指导老师": "刘老师", "鉴定意见": "该同学实习期间表现优异..." * 5,
        }, False),
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