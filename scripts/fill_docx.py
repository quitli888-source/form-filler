#!/usr/bin/env python3
"""
DOCX 表格填写示例脚本 — form-filler 辅助工具

功能：
  1. 读取 DOCX 表格模板，识别字段结构
  2. 从 YAML 配置文件加载用户信息
  3. 语义匹配字段 → 自动填写
  4. 处理合并单元格
  5. 生成填写对照表

用法：
  python fill_docx.py --template 优秀团员申报表.docx --profile-dir ./profiles --output 优秀团员申报表_已填写.docx

依赖：
  pip install python-docx pyyaml
"""

import argparse
import os
import re
import sys
from pathlib import Path

import yaml
from docx import Document


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


def match_field(label: str, profiles: dict) -> dict:
    """语义匹配：将表格标签映射到配置文件字段"""
    # 匹配规则表（标签关键词 → 配置路径）
    match_rules = [
        # (正则模式, 配置文件, 字段路径, 转换函数)
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
            }

    return {"matched": False, "value": None, "status": "❓"}


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


def count_chinese_chars(text: str) -> int:
    """统计中文字符数（不含标点和空格）"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def truncate_to_limit(content: str, max_chars: int) -> str:
    """按字数限制截断，保留完整句子"""
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


def fill_docx(template_path: str, profiles: dict, output_path: str) -> dict:
    """
    填写 DOCX 表格：
    1. 遍历所有表格的标签单元格
    2. 语义匹配 → 找到配置值
    3. 填入相邻的值单元格
    4. 处理合并单元格
    5. 保存结果
    """
    doc = Document(template_path)
    audit = {"filled": 0, "missed": 0, "inferred": 0, "details": []}

    for table in doc.tables:
        seen_cells = set()
        rows = list(table.rows)

        for ri, row in enumerate(rows):
            cells = list(row.cells)
            for ci, cell in enumerate(cells):
                cell_id = id(cell._tc)
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

                # 找相邻单元格填入值
                value_cell = _find_value_cell(table, ri, ci, seen_cells)
                if value_cell and result["value"]:
                    # 清空原有内容
                    for p in value_cell.paragraphs:
                        for run in p.runs:
                            run.text = ""
                    if value_cell.paragraphs:
                        value_cell.paragraphs[0].text = str(result["value"])

                    audit["filled"] += 1
                    audit["details"].append({
                        "label": text,
                        "value": result["value"],
                        "source": f"{result['config_file']}.yaml",
                        "status": result["status"],
                    })
                elif not result["value"]:
                    audit["missed"] += 1
                    audit["details"].append({
                        "label": text,
                        "value": "",
                        "source": f"{result['config_file']}.yaml (缺失)",
                        "status": "❌",
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


def print_audit(audit: dict):
    """打印填写对照表"""
    print("\n" + "=" * 60)
    print("📋 填写对照表")
    print("=" * 60)
    print(f"✅ 已填充: {audit['filled']}  ❌ 缺失: {audit['missed']}")
    print("-" * 60)

    for item in audit["details"]:
        print(f"  {item['status']} {item['label']}: {item['value']} ({item['source']})")

    total = audit["filled"] + audit["missed"]
    if total > 0:
        rate = audit["filled"] / total * 100
        print(f"\n📊 自动填充率: {rate:.0f}%")


def main():
    parser = argparse.ArgumentParser(description="DOCX 表格填写工具")
    parser.add_argument("--template", required=True, help="DOCX 模板文件路径")
    parser.add_argument("--profile-dir", default="./profiles", help="配置文件目录")
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument("--scan-only", action="store_true", help="仅扫描不填写")

    args = parser.parse_args()

    # 加载配置
    print("📂 加载配置文件...")
    profiles = load_profiles(args.profile_dir)
    if not profiles:
        print("❌ 未找到配置文件，请先创建 profiles/ 目录并添加 YAML 文件")
        sys.exit(1)

    # 扫描模板
    print(f"\n🔍 扫描模板: {args.template}")
    fields = scan_docx_tables(args.template)

    if args.scan_only:
        print(f"\n📊 共发现 {len(fields)} 个单元格")
        return

    # 填写
    output = args.output or args.template.replace(".docx", "_已填写.docx")
    print(f"\n✍️ 开始填写...")
    audit = fill_docx(args.template, profiles, output)
    print_audit(audit)


if __name__ == "__main__":
    main()
