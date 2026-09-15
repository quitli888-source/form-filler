#!/usr/bin/env python3
"""
evaluation/score_consistency.py — v5.0 minimal evaluation harness

目的：把 SKILL.md Step 7.5 的 9 条一致性校验规则做成可机器执行的评分脚本，
输出 0-100 的 score + 每条规则的 verdict，供 Darwin 优化循环衡量每轮 Δ。

用法：
  # 默认：demo run（内置合成 profile + audit，无需任何文件）
  python evaluation/score_consistency.py
  # 指定 audit.md + profiles/
  python evaluation/score_consistency.py --audit <path/to/audit.md> --profiles ./profiles

依赖：pyyaml（项目已要求）、标准库。
"""

import argparse
import json
import re
import sys
from pathlib import Path

# ---- 9 条规则，从 SKILL.md Step 7.5 (lines 358-368) 映射而来 ----------------
# 每条规则返回 (verdict, detail) — verdict ∈ {"pass","warn","fail"}
# 规则标签用于 rule_results 输出，便于 reviewer 定位。

PHONE_RE = re.compile(r"^1\d{10}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STUDENT_ID_RE = re.compile(r"^\d{6,12}$")

POLITICAL_BLOCK = {
    "优秀团员": {"共青团员"},
    "优秀团干": {"共青团员", "中共党员", "预备党员", "入党积极分子"},
    "三好学生": {"共青团员", "中共党员", "群众", "预备党员", "入党积极分子"},
}


def rule_gender_name(profile, filled, details):
    """性别-姓名一致性（仅提示）。姓名含「先生/男」与性别=男矛盾时报警。"""
    name = filled.get("姓名") or filled.get("申报人姓名") or ""
    gender = filled.get("性别") or ""
    if not name or not gender:
        return "pass", "姓名或性别为空，跳过"
    if "先生" in name and gender not in ("男", "male", "M"):
        return "warn", f"姓名含「先生」但性别={gender}"
    if any(h in name for h in ("女士", "小姐")) and gender not in ("女", "female", "F"):
        return "warn", f"姓名含女性称谓但性别={gender}"
    return "pass", f"性别-姓名一致（{gender}）"


def rule_age_degree(profile, filled, details):
    """age < 15 或 age > 35 → 阻断"""
    age = _coerce_int(filled.get("年龄"))
    degree = filled.get("学历") or filled.get("学位") or ""
    if age is None:
        return "pass", "年龄未填，跳过"
    if age < 15 and degree in ("本科",):
        return "fail", f"年龄 {age} < 15，不应为本科"
    if age > 35 and degree == "本科":
        return "fail", f"年龄 {age} > 35，不应为本科生"
    return "pass", f"年龄 {age} 与学位 {degree} 一致"


def rule_year_grade(profile, filled, details):
    """入学年份与年级推算匹配"""
    edu = (profile.get("education") or {}).get("entries") or []
    if not edu:
        return "pass", "无教育经历，跳过"
    start = str(edu[0].get("start_date", ""))
    degree = edu[0].get("degree", "")
    if not start or not degree:
        return "pass", "入学/学位缺失，跳过"
    try:
        year = int(start.split("-")[0])
    except ValueError:
        return "pass", f"入学年份解析失败 ({start})"
    filled_grade = filled.get("年级") or filled.get("所在年级") or ""
    expected = f"{year % 100}级{degree}生"
    if filled_grade and filled_grade != expected:
        return "fail", f"年级 {filled_grade} 与推算 {expected} 不匹配"
    return "pass", f"年级 {filled_grade or expected} 与推算一致"


def rule_phone(profile, filled, details):
    """手机号 11 位数字，1 开头"""
    phone = filled.get("手机") or filled.get("电话") or filled.get("手机号") or ""
    if not phone:
        return "pass", "手机号未填"
    if not PHONE_RE.match(str(phone)):
        return "warn", f"手机号 {phone} 不是 11 位 1 开头"
    return "pass", "手机号格式合规"


def rule_email(profile, filled, details):
    """邮箱含 @ 和域名"""
    email = filled.get("邮箱") or filled.get("电子邮件") or ""
    if not email:
        return "pass", "邮箱未填"
    if not EMAIL_RE.match(str(email)):
        return "warn", f"邮箱 {email} 格式异常"
    return "pass", "邮箱格式合规"


def rule_student_id(profile, filled, details):
    """学号格式（6-12 位数字）"""
    sid = filled.get("学号") or filled.get("工号") or ""
    if not sid:
        return "pass", "学号未填"
    if not STUDENT_ID_RE.match(str(sid)):
        return "warn", f"学号 {sid} 与常见规则不匹配"
    return "pass", "学号格式合规"


def rule_political(profile, filled, details):
    """申报「优秀团员」→ 必须是共青团员"""
    declared_apply = filled.get("申报类别") or filled.get("申报项目") or ""
    if not declared_apply:
        return "pass", "申报类别未填，跳过"
    expected_set = POLITICAL_BLOCK.get(declared_apply)
    if expected_set is None:
        return "pass", f"申报类别 {declared_apply} 无政治面貌硬性要求"
    pol = (profile.get("personal") or {}).get("political_status", "")
    if pol not in expected_set:
        return "fail", f"申报 {declared_apply} 但政治面貌为 {pol}（应为 {sorted(expected_set)}）"
    return "pass", f"政治面貌 {pol} 与申报类别 {declared_apply} 一致"


def rule_word_limit(profile, filled, details):
    """AI 生成内容超出字数限制（启发：填入值 > 2000 字符）"""
    violations = [
        d for d in details
        if d.get("status") == "📝" and len(str(d.get("value", ""))) > 2000
    ]
    if violations:
        return "fail", f"{len(violations)} 个 AI 生成字段字数超限"
    return "pass", "无字数超限"


def rule_miss_count(profile, filled, details):
    """MISS 状态字段数量警告（>5 警告）"""
    miss = sum(1 for d in details if d.get("status") == "❌")
    if miss > 5:
        return "warn", f"缺失字段 {miss} 个，建议分批补充"
    return "pass", f"缺失字段 {miss} 个，可控"


# 9 条规则 (R1–R9)，与 SKILL.md Step 7.5 一一对应
RULES = [
    ("R1_gender_name", rule_gender_name, "warning"),
    ("R2_age_degree", rule_age_degree, "blocking"),
    ("R3_year_grade", rule_year_grade, "blocking"),
    ("R4_phone", rule_phone, "warning"),
    ("R5_email", rule_email, "warning"),
    ("R6_student_id", rule_student_id, "warning"),
    ("R7_political", rule_political, "blocking"),
    ("R8_word_limit", rule_word_limit, "blocking"),
    ("R9_miss_count", rule_miss_count, "warning"),
]


def _coerce_int(value):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# demo data：让脚本默认就能跑（无需 DOCX/audit 文件）
# ---------------------------------------------------------------------------

def demo_profile() -> dict:
    """内置合成 profile：本科二年级，男，共青团员，籍贯浙江。"""
    return {
        "personal": {
            "name": "张三",
            "gender": "男",
            "birth_date": "2006-03-15",
            "ethnicity": "汉族",
            "birthplace": "浙江省杭州市",
            "political_status": "共青团员",
        },
        "contact": {
            "phone": "13812345678",
            "email": "zhangsan@example.edu.cn",
        },
        "education": {
            "entries": [
                {
                    "school": "浙江大学",
                    "department": "计算机科学与技术学院",
                    "major": "计算机科学与技术",
                    "degree": "本科",
                    "student_id": "12345678",
                    "start_date": "2024-09",
                    "end_date": "2028-06",
                }
            ]
        },
        "league": {
            "league_evaluation": "优秀",
            "league_position": "组织委员",
            "league_join_date": "2019-05",
        },
    }


def demo_filled() -> dict:
    """demo run 的 filled dict（audit.md 中字段名 → 值）。"""
    return {
        "姓名": "张三",
        "性别": "男",
        "出生年月": "2006-03-15",
        "政治面貌": "共青团员",
        "手机": "13812345678",
        "邮箱": "zhangsan@example.edu.cn",
        "学号": "12345678",
        "专业": "计算机科学与技术",
        "院系": "计算机科学与技术学院",
        "学校": "浙江大学",
        "学历/年级": "24级本科生",
        "所在单位": "浙江大学计算机科学与技术学院",
        "申报类别": "优秀团员",
        "团员评议": "优秀",
        "入团日期": "2019-05",
    }


def demo_details() -> list:
    """demo run 的 details 列表（与 audit.md 字段详情表一致）。"""
    filled = demo_filled()
    return [
        {"label": k, "value": v, "source": "personal.yaml" if k in ("姓名","性别","出生年月","政治面貌") else "education.yaml",
         "status": "✅" if v else "❌", "reflection": ""}
        for k, v in filled.items()
    ] + [{"label": "团内职务", "value": "", "source": "league.yaml (缺失)", "status": "❌", "reflection": ""}]


def parse_audit_md(audit_path: Path):
    """
    解析 audit.md 文件：
      1. 抓取「字段填写详情」表 → label → value dict + details 列表
      2. 抓取「状态统计」表 → status_counts dict（v6.0, R2-A5）

    返回 (filled, details, status_counts)。
    status_counts: {"✅": N, "🔄": N, "📝": N, "⚠️": N, "❌": N, ...}
    """
    if not audit_path.exists():
        return {}, [], {}
    text = audit_path.read_text(encoding="utf-8")
    filled = {}
    details = []
    status_counts = {}
    in_details = False
    in_stats = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("| 序号"):
            in_details = True
            in_stats = False
            continue
        if line.startswith("| 状态") or line.startswith("| 状态类型") or "✅ 自动匹配" in line:
            in_details = False
            in_stats = True
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            in_details = False
            in_stats = False
            continue
        cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
        if in_details and len(cells) >= 5:
            try:
                int(cells[0])
            except ValueError:
                continue
            label, value, source, status = cells[1], cells[2], cells[3], cells[4]
            reflection = cells[5] if len(cells) >= 6 else ""
            if label in ("序号", "表格字段名", "...") or not label:
                continue
            filled[label] = value
            details.append({
                "label": label, "value": value, "source": source,
                "status": status, "reflection": reflection,
            })
        elif in_stats and len(cells) >= 3:
            # | 状态类型 | 数量 | 占比 |   — parse: cells[0]=状态类型, cells[1]=数量, cells[2]=占比
            status_label = cells[0]
            try:
                n = int(cells[1])
            except (ValueError, IndexError):
                continue
            status_counts[status_label] = n
    return filled, details, status_counts


def load_profile_yaml(profile_dir: Path) -> dict:
    """加载 profiles/ 下所有 YAML，扁平为单个 dict（key=name, value 内容）。"""
    try:
        import yaml
    except ImportError:
        return {}
    out = {}
    if not profile_dir.exists():
        return out
    for f in profile_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            out[f.stem] = data
        except Exception:
            continue
    return out


def evaluate(profile: dict, filled: dict, details: list) -> dict:
    """DEPRECATED alias of `score()` — 保留 v5.0 调用方兼容。新代码请用 `score`."""
    import warnings
    warnings.warn(
        "evaluation.score_consistency.evaluate is deprecated; use score() instead.",
        DeprecationWarning, stacklevel=2,
    )
    return score(profile, filled, details)


def score(profile: dict, filled: dict, details: list) -> dict:
    """v6.0 跑 9 条规则，返回结构化结果（v5.0 evaluate 的新规范名）。"""
    blocking_errors = 0
    warnings = 0
    rule_results = []
    for name, fn, kind in RULES:
        try:
            verdict, detail = fn(profile, filled, details)
        except Exception as exc:
            verdict, detail = "warn", f"规则执行异常: {exc}"
        rule_results.append({"rule": name, "level": kind, "verdict": verdict, "detail": detail})
        if verdict == "fail":
            blocking_errors += 1
        elif verdict == "warn":
            warnings += 1

    total = len(details) or 1
    miss = sum(1 for d in details if d.get("status") == "❌")
    fill_rate_pct = round((total - miss) / total * 100, 1)

    score_val = max(0, min(100, 100 - 20 * blocking_errors - 5 * warnings))

    return {
        "score": score_val,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "fill_rate_pct": fill_rate_pct,
        "rule_results": rule_results,
    }


def main():
    parser = argparse.ArgumentParser(description="form-filler v6.0 一致性评分脚本")
    parser.add_argument("--audit", default=None,
                        help="audit.md 路径（默认 demo run）")
    parser.add_argument("--profiles", default="./profiles",
                        help="profile YAML 目录路径")
    parser.add_argument("--demo", action="store_true",
                        help="强制使用内置合成数据 demo run")
    args = parser.parse_args()

    if args.demo or not args.audit:
        # 默认 demo run：内置合成 profile + audit，无需任何文件
        profile = demo_profile()
        filled = demo_filled()
        details = demo_details()
        if not args.demo:
            print("ℹ️ 未指定 --audit，使用 demo run（内置合成数据）", file=sys.stderr)
        status_counts = {}  # demo 模式没有 status_counts
    else:
        audit_path = Path(args.audit)
        profile_dir = Path(args.profiles)
        filled, details, status_counts = parse_audit_md(audit_path)
        profile = load_profile_yaml(profile_dir)

    result = score(profile, filled, details)
    if status_counts:
        result["status_counts"] = status_counts
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result["blocking_errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())