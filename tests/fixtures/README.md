# tests/fixtures/

合成 fixture 目录 — 给 `scripts/validate_rules.py --input` 用。

## JSON 格式

文件可以是一个 fixture dict，也可以是一个 fixture list：

```json
[
  {
    "name": "my_fixture_1",
    "description": "（可选）",
    "labels": ["姓名", "性别", "学号"],
    "profile": {
      "personal": {"name": "张三", "gender": "男"},
      "education": {"entries": [{"student_id": "2025000000"}]}
    }
  },
  ...
]
```

字段说明：

| 字段 | 必填 | 说明 |
|------|:---:|------|
| `name` | 是 | fixture 短名，用于输出 |
| `labels` | 是 | 表格中出现的标签列表 |
| `profile` | 是 | 合成的 YAML profile（嵌套 dict） |
| `description` | 否 | 一行描述（不参与校验） |
| `expected` | 否 | 期望结果列表（当前版本仅记录，不强制对比） |

## 使用

```bash
# 内置 3 个 mock fixture
python scripts/validate_rules.py --mock

# 自定义 JSON
python scripts/validate_rules.py --input tests/fixtures/my_fixtures.json
```

## 内置 mock 覆盖的 3 类场景

| fixture | 场景 | 期望 verdict |
|---------|------|:---:|
| `good_simple` | 标签一次命中、profile 有值 | OK |
| `missing_value` | 标签命中但 profile 缺字段 | FAIL（matched but no value） |
| `ambiguous_first_match` | 同一标签触发多条规则 | WARN（ambiguous） |

## 为什么不是真实 DOCX

生成 3 个真实 DOCX fixture 超出 Round 1 范围。validate_rules.py
直接对 `fill_docx.match_rules` 跑 `match_field()`，不依赖
python-docx 解析。这让 Tester 可以在 CI 里无需任何 DOCX 文件就跑。
