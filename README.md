# 📝 Form Filler — 智能填表助手

> 通用 Agent Skill | 从用户配置文件自动填写 DOCX/Excel/PDF 表格，支持 OCR、AI 内容生成、信息源深度挖掘、一致性校验

[![Agent Skills Standard](https://img.shields.io/badge/Agent%20Skills-OpenClaw-blue)](https://agentskills.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## ✨ 核心能力

| 能力 | 说明 |
|------|------|
| 🔄 **多格式支持** | DOCX 表格/模板、Excel、PDF 表单、扫描 PDF/图片、文字描述 |
| 🔍 **信息源深度挖掘** | 从 OCR 文本提取隐含信息（校名→籍贯、决赛→国家级、高考→出生年份） |
| 🎯 **语义字段映射** | 7 级匹配优先级（完全→同义→上下文→计算推断→拼音→时间→级别） |
| 🤖 **AI 内容生成** | 自荐信/个人陈述/理解类内容，字数精准控制 90-100% |
| ✅ **一致性校验** | 9 条规则阻断明显错误（如"群众"申报"优秀团员" ❌） |
| 📈 **配置自动丰富** | 用户确认的推断值自动保存到 profiles，越用越聪明 |
| 👁️ **预览确认模式** | 生成文件前展示预填方案 + 校验结果 |
| 🔒 **隐私优先** | 所有配置纯本地存储，永不外传 |

---

## 🚀 快速开始

### 1. 安装

```bash
# 克隆仓库
git clone https://github.com/quitli888-source/form-filler.git

# 复制到对应平台的 skills 目录
# Claude Code
cp -r form-filler ~/.claude/skills/

# WorkBuddy / CodeBuddy
cp -r form-filler ~/.workbuddy/skills/

# Cursor
cp -r form-filler .cursor/skills/

# Cline
cp -r form-filler .cline/skills/

# OpenClaw
cp -r form-filler skills/
```

### 2. 安装 Python 依赖

```bash
pip install rapidocr-onnxruntime pdf2image python-docx openpyxl PyMuPDF pyyaml

# 可选：文档转换工具（用于 DOCX/PDF → Markdown）
pip install markitdown
# 或使用 pandoc
```

### 3. 使用

对 AI 助手说：

> "帮我填一个优秀团员申报表" + 上传 DOCX 模板

或：

> "用这份奖学金申请表的信息，帮我填团员申报表" + 上传两个文件

---

## 📐 完整工作流

```
┌─────────────────────────────────────────────────────────────────┐
│                    Form Filler 工作流                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 0: 启动检查                                                │
│    profiles/ 存在？ ──否──→ 按场景最小收集 → 保存                  │
│         │是                                                     │
│         ↓                                                       │
│  Step 1: 检测输入类型                                            │
│    DOCX模板 / DOCX表格 / Excel / PDF表单 / 扫描PDF / 文字描述    │
│         ↓                                                       │
│  Step 2A: 语义字段映射（表格类）                                   │
│    7级匹配：完全→同义→上下文→计算→拼音→时间→级别                    │
│         ↓                                                       │
│  Step 3: 多条目选择                                              │
│    获奖/经历/论文 → 智能筛选+格式化                                │
│         ↓                                                       │
│  Step 4: 缺失信息处理                                            │
│    迭代询问 + 智能建议（深度挖掘推断值）                            │
│         ↓                                                       │
│  Step 5: AI 内容生成                                             │
│    自荐信/个人陈述/理解类 → 字数精准控制                           │
│         ↓                                                       │
│  Step 6: 附件处理                                                │
│         ↓                                                       │
│  Step 7: 生成填写结果（DOCX/Excel/PDF + 对照表）                  │
│         ↓                                                       │
│  Step 7.5: 预览确认 + 一致性校验 ←←← 阻断级错误必须修正           │
│         ↓                                                       │
│  Step 8: 用户审查确认 → 交付                                     │
│         ↓                                                       │
│  Step 8.5: 配置自动丰富（保存确认的推断值）                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 目录结构

```
form-filler/
├── SKILL.md              ← 核心定义（OpenClaw 标准格式，~800行）
├── README.md             ← 本文件
├── LICENSE               ← MIT
├── .gitignore            ← 隐私保护（profiles/*.yaml）
├── profiles/             ← 用户配置文件（自动生成，不入版本控制）
│   ├── personal.yaml     ← 姓名/性别/籍贯/政治面貌
│   ├── contact.yaml      ← 手机/邮箱/地址
│   ├── education.yaml    ← 学校/院系/专业/学号（支持多条）
│   ├── awards.yaml       ← 获奖（支持多条）
│   ├── work_experience.yaml
│   ├── publications.yaml
│   ├── skills.yaml       ← 技能证书
│   ├── league.yaml       ← 团组织/党建
│   └── bank.yaml         ← 金融信息
├── scripts/
│   └── fill_docx.py      ← DOCX 填写示例脚本
└── templates/
    └── audit_table.md    ← 填写对照表模板
```

---

## 📋 配置文件说明

首次使用时，模块会根据填表场景自动创建所需配置文件（最小收集原则）。每次填表都是配置的补充机会——**越用越聪明**。

### 配置文件一览

| 文件 | 内容 | 自动填充示例 |
|------|------|------------|
| `personal.yaml` | 姓名、性别、籍贯、政治面貌 | "张三", "男", "浙江省杭州市" |
| `contact.yaml` | 手机、邮箱、地址 | "138xxxx5678", "xxx@example.edu.cn" |
| `education.yaml` | 学校、院系、专业、学号 | "XX大学", "计算机科学系" |
| `awards.yaml` | 奖项名称、级别、日期 | "全国数学竞赛 国家级" |
| `work_experience.yaml` | 公司、职位、时间 | — |
| `league.yaml` | 入团日期、评议等级 | "2019-05", "优秀" |
| `bank.yaml` | 银行、卡号 | — |

### 配置自动丰富机制

```
填写过程中发现新信息 → 标记推断来源 → 用户确认 → 自动保存到 profiles/

示例：
  "浙江省杭州中学" → 推断籍贯="浙江省杭州市"
  → 用户确认 → 保存到 personal.yaml: birthplace=浙江省杭州市
```

---

## 🔍 信息源深度挖掘

这是 v4.0 的核心能力：从信息源文件中不仅提取显式键值对，还能挖掘隐含信息。

| 信息源线索 | 推断字段 | 示例 |
|-----------|---------|------|
| 高中校名含省份/城市 | 籍贯 | "浙江省杭州中学" → "浙江省杭州市" |
| "赛区XX" | 籍贯辅助验证 | "赛区浙江" → 印证浙江籍贯 |
| 高考年份 | 出生年份 | 2025高考 → 约出生于2007年 |
| 竞赛含"决赛" | 获奖级别 | "全国物理竞赛决赛" → 国家级 |
| 学校名称 | 学校类型 | "XX大学" → 985/双一流 |
| 本科+入学年份 | 所在年级 | 2025入学+本科 → 大二 |

---

## 📊 端到端使用示例

### 场景：奖学金申请PDF → 优秀团员申报表DOCX

```
输入：
  - 信息源：奖学金申请表（10页扫描PDF）
  - 目标表：优秀共青团员申报表（DOCX）

执行：
  Step 0: 检查profiles/ → 已有5个配置文件
  Step 1: 扫描PDF → RapidOCR → 深度挖掘隐含信息
  Step 2: 18个字段映射 → 11自动匹配 + 3推断 + 4缺失
  Step 4: 批量询问缺失字段（附智能建议）
  Step 5: AI生成申报材料(~800字) + 团员理解(~200字)
  Step 7.5: 一致性校验通过 → 用户确认预填方案
  Step 8: 输出已填写DOCX + 填写对照表

结果：自动填充率 78%（含推断确认后达89%）
```

---

## 🛠 平台兼容性

本模块遵循 [Agent Skills Open Standard](https://agentskills.io/specification)，兼容 25+ AI 编程工具：

| 平台 | 安装路径 | 状态 |
|------|---------|------|
| Claude Code | `~/.claude/skills/form-filler/` | ✅ 兼容 |
| WorkBuddy / CodeBuddy | `~/.workbuddy/skills/form-filler/` | ✅ 兼容 |
| Cursor | `.cursor/skills/form-filler/` | ✅ 兼容 |
| Cline | `.cline/skills/form-filler/` | ✅ 兼容 |
| OpenClaw | `skills/form-filler/` | ✅ 兼容 |
| Codex CLI | `.codex/skills/form-filler/` | ✅ 兼容 |

### 跨平台适配原理

SKILL.md 中描述的流程基于「能力」而非具体工具名：

| 本文档描述 | Claude Code | WorkBuddy | Cursor |
|-----------|-------------|-----------|--------|
| 文档转换工具 | markitdown CLI | markitdown skill | pandoc |
| 文件读取功能 | Read tool | Read tool | 内置 |
| 文件写入功能 | Write tool | Write tool | 内置 |
| 文件编辑功能 | Edit tool | Edit tool | 内置 |

---

## 🔒 隐私保护

- **纯本地存储** — 所有配置文件仅存储在本机 `profiles/` 目录
- **不入版本控制** — `.gitignore` 已配置排除 `profiles/*.yaml`
- **最小收集** — 首次使用只收集当前场景必需字段
- **用户可控** — YAML 明文保存，可随时查看/编辑/删除

---

## 📈 Darwin 优化历程

本模块经过 4 轮 Darwin 自动优化，每轮严格遵循棘轮机制（必须提升）：

| 轮次 | 版本 | 评分 | Δ | 关键改进 |
|------|------|------|---|---------|
| 基线 | v1.0 | 42 | — | 初始版本 |
| R1 | v2.0 | 62 | +20 | OCR / AI 生成 / 工具集成 / 计算推断 |
| R2 | v3.0 | 72 | +10 | DOCX 实操 / 信息源合并 / 字数控制 |
| R3 | v3.1 | 76 | +4 | 触发增强 / 对照表升级 / 审查分区 |
| **R4** | **v4.0** | **82** | **+6** | 深度挖掘 / 智能建议 / 一致性校验 / 配置丰富 |

实测指标：MISS 字段 5→3，INFER 2→4，自动填充率 61%→83%

---

## 🤝 贡献

欢迎贡献！可以：

1. **Fork & PR** — 修复 bug、添加新功能
2. **提交 Issue** — 报告问题、建议新特性
3. **分享配置模板** — 提交新行业的 profiles 模板
4. **测试场景** — 添加更多端到端测试用例

### 开发

```bash
git clone https://github.com/quitli888-source/form-filler.git
cd form-filler
# 编辑 SKILL.md — 这是唯一的逻辑定义文件
# 编辑 scripts/ — 辅助脚本
# 编辑 templates/ — 对照表模板
```

---

## 📄 License

[MIT](LICENSE) — 自由使用、修改、分发。

⚠️ 请注意：`profiles/` 目录下的用户配置文件包含个人隐私，**切勿分享或提交到版本控制**。
