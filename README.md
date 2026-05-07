# 📝 Form Filler — 智能填表助手

> WorkBuddy Skill | Auto-fill DOCX/Excel/PDF/image forms from user profile

## ✨ 核心能力

- **多格式支持** — DOCX表格/模板、Excel、PDF表单、扫描PDF/图片、文字描述
- **信息源深度挖掘** — 从OCR文本提取隐含信息（校名→籍贯、决赛→国家级、高考→出生年）
- **语义字段映射** — 7级匹配优先级（完全→同义→上下文→计算推断→拼音→时间→级别）
- **AI内容生成** — 自荐信/个人陈述/理解类内容，字数精准控制
- **一致性校验** — 9条规则阻断明显错误（如"群众"申报"优秀团员"）
- **配置自动丰富** — 用户确认的推断值自动保存，越用越聪明
- **预览确认模式** — 生成前展示预填方案+校验结果

## 🚀 快速开始

1. 安装 [WorkBuddy](https://www.codebuddy.cn)
2. 将此skill安装到 `~/.workbuddy/skills/form-filler/`
3. 对WorkBuddy说："帮我填一个XX表"

## 📁 目录结构

```
form-filler/
├── SKILL.md              ← 核心定义（工作流+配置模板）
├── .gitignore            ← 隐私保护（profiles/*.yaml）
├── profiles/             ← 用户配置（自动生成，纯本地）
│   ├── personal.yaml
│   ├── contact.yaml
│   ├── education.yaml
│   └── ...
└── templates/
    └── audit_table.md    ← 填写对照表模板
```

## 🔒 隐私

- 所有用户配置 **仅存储在本机** `profiles/` 目录
- `.gitignore` 已配置排除个人数据
- 首次使用只收集当前场景必需字段

## 📊 版本历史

| 版本 | 分数 | 关键改进 |
|------|------|---------|
| v1.0 | 42 | 基线版本 |
| v2.0 | 62 | OCR/AI生成/工具集成/计算推断 |
| v3.0 | 72 | DOCX实操/信息源合并/字数控制 |
| v3.1 | 76 | 触发增强/对照表升级/审查分区 |
| **v4.0** | **82** | 深度挖掘/智能建议/一致性校验/配置丰富 |

## License

MIT
