---
name: form-filler
version: "4.0"
description: "通用智能填表助手。Auto-fill DOCX/Excel/PDF/image forms with OCR, AI generation, deep mining, consistency check. 触发：填表/申报表/奖学金/简历/报销/自荐信/申请表"
metadata:
  openclaw:
    always: false
  i18n:
    zh: "通用智能填表助手。支持 DOCX/Excel/PDF 等格式表格自动填写，含 OCR、AI 内容生成、信息源深度挖掘、一致性校验、缺失字段迭代收集"
    en: "General-purpose smart form filler. Auto-fill DOCX/Excel/PDF/image forms from user profile, with OCR, AI content generation, deep source mining, consistency validation, and progressive info collection."
---

# 智能填表助手（Form Filler）

> 上传表格模板或填写要求 → 自动匹配本地用户信息 → 智能填写 → AI 生成缺失内容 → 用户审核 → 输出成品

---

## When to Use

- 用户说"帮我填一个XX表"并上传模板/要求
- 用户说"帮我填表"、"填一下这个表"、"申请表怎么填" 等填表相关表述
- 用户需要反复填写同类表格（奖学金、申报、报销、简历等）
- 用户上传了含 `{{占位符}}` 或 `${变量}` 的模板文件
- 用户想基于已有个人信息快速生成填好的表格
- 用户上传了扫描 PDF / 图片表格，需要提取信息或填写
- 用户需要从一份文档中提取信息填入另一份表格（如：从奖学金申请表提取信息填入优秀团员申报表）
- 用户需要 AI 生成申请材料、自荐信、个人陈述等文本内容
- 用户提供了多个文件并说"用A的信息填B"

## When NOT to Use

- 用户只是查看/阅读表格内容（不涉及填写）
- 用户需要创建全新表格设计（不是填写现有表格）
- 用户需要填写的信息完全不在本地配置中且无法推断

---

## Core Principles

### 隐私优先
- 用户配置文件存储在 `profiles/` 目录，纯本地，**永不发送到外部**
- 首次使用时只收集当前场景必需的字段，非全量收集
- 配置文件以 YAML 明文保存，用户可随时查看/编辑/删除
- `.gitignore` 已配置，确保配置文件不会被提交

### 渐进式收集
- 用户首次回答的缺失字段自动保存到配置文件
- 每次填表都是配置文件的补充机会
- 配置越用越全，越用越省力

### 审核兜底
- 所有填写结果必须生成「填写对照表」供用户审核
- AI 生成的内容必须在对照表中明确标注「AI 生成」
- 用户确认后才输出最终文件

### 源文件优先
- 当同时有信息源文件和目标表格时，优先从信息源提取字段值
- 从信息源提取到的信息自动与本地配置文件合并（配置文件为准）
- 信息源中的新信息（配置中不存在的字段）在用户确认后追加到配置文件

### 信息源自动合并规则

当用户提供信息源文件（如扫描PDF、另一份表格）时，系统自动执行以下流程：

```
1. 提取信息源中的所有键值对
2. 与本地配置文件逐字段对比：
   a. 配置已有值 → 以配置为准（不覆盖）
   b. 配置为空 → 用信息源的值填充（自动保存）
   c. 配置与信息源冲突 → 标记冲突，提示用户确认
3. 信息源中有但配置模板中没有的字段 → 新增到最相关的配置文件
4. 合并结果写入配置文件，同时记录合并日志
```

**合并映射表**（信息源常见字段 → 配置文件）：

| 信息源常见字段 | 配置文件 | 字段路径 |
|--------------|---------|---------|
| 姓名/申请人 | personal.yaml | name |
| 学号 | education.yaml | entries[0].student_id |
| 专业 | education.yaml | entries[0].major |
| 院系/所在单位 | education.yaml | entries[0].department |
| 学校 | education.yaml | entries[0].school |
| 手机/电话 | contact.yaml | phone |
| 邮箱/电子邮件 | contact.yaml | email |
| 性别 | personal.yaml | gender |
| 政治面貌 | personal.yaml 或 league.yaml | political_status / party_status |
| 获奖/荣誉 | awards.yaml | entries[] |
| 培养类别/学位 | education.yaml | entries[0].degree |
| 入学成绩/高考分 | education.yaml | entries[0].gaokao_score |

### 缺省值推断

当配置字段为空且信息源也未提供时，可从已有信息推断：

| 目标字段 | 推断规则 | 可信度 |
|---------|---------|:------:|
| 籍贯 | 从高中学校所在地推断（如"云南省安宁中学"→"云南省安宁市"） | 低，需确认 |
| 申报类别 | 从 degree 推断（"本科"/"硕士"→"学生"） | 高 |
| 学历/年级 | 从 start_date 年份 + degree 推断 | 高 |
| 所在单位 | school + department 拼接 | 高 |
| 民族 | 中国汉族概率约91%，但不应默认推断 | 不推断 |

### 信息源深度挖掘

当信息源文件（如扫描PDF、另一份表格）被提取后，不仅提取显式键值对，还要挖掘隐含信息：

**挖掘规则表**：

| 信息源线索 | 可推断字段 | 推断逻辑 | 可信度 |
|-----------|-----------|---------|:------:|
| 高中学校名含省份/城市 | birthplace（籍贯） | 优先匹配"学校名称：XX省XX中学"，提取省份+城市名（如"云南省安宁中学"→"云南省安宁市"） | 中，需确认 |
| "赛区XX" | birthplace 辅助验证 | "赛区云南"→印证云南籍贯 | 中 |
| 高考成绩单含年份 | birth_date | 从高考年份-18推断出生年份 | 低，仅参考 |
| 竞赛证书含颁发日期 | awards.entries[].date | 补全缺失日期 | 高 |
| 学校含"985/211/双一流"标签 | education.school_type | "复旦大学"→"985/双一流" | 高 |
| 培养类别=本科 + 入学年份 | 所在年级 | 2025入学+本科→大二(2026年) | 高 |
| 竞赛全称含"决赛" | awards.entries[].level | "全国中学生物理竞赛决赛"→"国家级" | 高 |
| 奖项含"省级三好学生" | awards.category=综合荣誉 | 非学科竞赛类归类 | 高 |

**深度挖掘流程**（在信息源提取后自动执行）：

```
1. 完成显式键值对提取（Step 1 常规流程）
2. 扫描全文文本，按上表规则逐一匹配线索
3. 对每个挖掘到的隐含信息：
   a. 配置已有该字段且非空 → 跳过（配置为准）
   b. 配置该字段为空 → 填入推断值，标记来源为"[推断-信息源]"
   c. 多条线索推断同一字段 → 取可信度最高的，冲突则标注
4. 将挖掘结果加入匹配结果集，进入 Step 2 映射
```

**示例**：从奖学金申请扫描件中深度挖掘：
- "云南省安宁中学" → birthplace="云南省安宁市"（中可信度）
- "赛区云南" → 印证 birthplace 推断
- "全国中学生物理竞赛决赛" → awards level="国家级"
- "复旦大学" → school_type="985/双一流"
- "本科" + 入学2025 → 所在年级="大二"

---

## 目录结构

```
form-filler/
├── SKILL.md                    ← 本文件（核心定义）
├── README.md                   ← 详细文档
├── LICENSE                     ← MIT
├── .gitignore                  ← 配置隐私保护
├── profiles/                   ← 用户配置文件目录（自动生成，不入版本控制）
│   ├── personal.yaml           ← 基础个人信息
│   ├── contact.yaml            ← 联系方式
│   ├── education.yaml          ← 教育经历（支持多条）
│   ├── work_experience.yaml    ← 工作经历（支持多条）
│   ├── awards.yaml             ← 获奖情况（支持多条）
│   ├── publications.yaml       ← 论文/专利（支持多条）
│   ├── skills.yaml             ← 技能证书
│   ├── league.yaml             ← 团组织/党建信息
│   └── bank.yaml               ← 金融信息
├── scripts/                    ← 辅助脚本
│   └── fill_docx.py            ← DOCX 填写示例脚本
└── templates/
    └── audit_table.md          ← 填写对照表模板
```

---

## 完整工作流

### Step 0: 启动检查

检查 `profiles/` 目录是否存在及里面是否有配置文件。

- **无配置文件**（首次使用）：
  - 询问用户当前填表场景，只收集该场景所需的字段
  - 保存后进入 Step 1
- **有配置文件**：直接进入 Step 1

### Step 1: 检测输入类型

用户可能提供以下输入，需先识别类型：

| 输入形式 | 检测方法 | 处理方式 |
|----------|----------|----------|
| DOCX 文件（含 `{{字段名}}` 或 `${字段名}`） | 用文档转换工具（如 markitdown CLI）转换后扫描模板标记 | 模板替换填充（Step 2B） |
| DOCX/PDF 表格（含表格结构，无模板标记） | 文档转换后识别表格行列和表头 | 逐字段语义映射填充（Step 2A） |
| Excel 申报表（.xlsx） | 检测文件扩展名 + 表头行 | 逐单元格填充 |
| PDF 表单（含 AcroForm） | PyMuPDF 检测表单字段 | 字段级别填充 |
| 扫描 PDF / 图片表格 | 文档转换工具无文字输出 → 判定为扫描件 | OCR 提取后按上述流程处理 |
| 文字描述（如"帮我填一个奖学金申请"） | 无文件上传 | LLM 提取字段清单 |
| 信息源文件（非目标表格） | 用户指定"从XX文件提取信息" | 先提取信息 → 更新配置 → 再填目标表 |

#### 扫描 PDF / 图片处理流程

```
1. 先尝试用文档转换工具提取文字
2. 若输出为空或极少文字（< 50字），判定为扫描件
3. 用 pdf2image 或 PyMuPDF 将 PDF 转为 PNG（200 DPI）
4. 用 RapidOCR (rapidocr-onnxruntime) 进行 OCR
5. OCR 结果拼接为完整文本，进入后续流程
6. 若 OCR 质量差（大量乱码/空行），提示用户：
   a. 提供更清晰的扫描件
   b. 提供电子版/文字版
   c. 手动输入关键信息
```

**工具选择优先级**：文档转换 → OCR → 提示用户

**输出**：`字段清单 + 填写要求` 的结构化数据

### Step 2A: 语义字段映射（表格类输入）

将表格/要求中的字段名与本地配置文件中的字段进行匹配。

**匹配优先级**：
1. **完全匹配** — "姓名" ↔ `personal.name`
2. **同义词匹配** — "申请人姓名" / "申报人" / "Name" → `personal.name`
3. **上下文推断** — 字段位于"教育经历"区域 → 优先匹配 `education.*`
4. **计算推断** — "学历/年级" → 从 `education.start_date` 推断入学年份 + `education.degree` → "25级本科生"
5. **拼音/缩写** — "xb" → 性别, "sjh" → 手机号
6. **时间范围匹配** — "近三年获奖" → 按 `date` 筛选 `awards.entries[]`
7. **级别匹配** — "国家级奖项" → 筛选 `awards.entries[].level == "国家级"`

**常见计算推断规则**：

| 表格字段 | 推断逻辑 | 示例 |
|---------|---------|------|
| 学历/年级 | `start_date` 年份后两位 + "级" + `degree` | 2025-09入学 + 本科 → "25级本科生" |
| 所在单位 | `school` + `department`（如有） | "复旦大学高分子科学系" |
| 年龄 | 当前年份 - `birth_date` 年份 | 2026 - 2007 = 19岁 |
| 所在年级 | 当前年份 - `start_date` 年份 + 1 | 2026 - 2025 + 1 = 大二 |

**输出**：`匹配结果`（匹配 / 缺失 / 模糊 / 需生成）

### Step 2B: 模板替换填充（模板类输入）

当输入为含 `{{字段名}}` 或 `${变量}` 的模板文件时：

```
1. 用正则提取所有模板标记：\{\{(.+?)\}\} 或 \$\{(.+?)\}
2. 对每个标记执行 Step 2A 的语义映射
3. 直接替换标记为配置值
4. 缺失标记 → 进入 Step 4 询问
```

### Step 3: 多条目选择（工作经历/获奖/论文等）

当匹配到配置中的列表型字段（如 `awards.entries[]`）时，按以下策略智能选择：

```
1. 表格有明确条件 → 按条件筛选
   - "近3年" → date >= 当前年份-3
   - "国家级" → level == "国家级"
   - "前5项" → 取前5条
2. 表格要求单条摘要 → 选最近/最高级别的条目
3. 表格要求多条（如简历/所获荣誉） → 全部列出，按时间倒序排列
4. 无法确定 → 列出所有条目让用户指定
```

**多条目格式化规则**：

| 场景 | 格式 |
|------|------|
| 所获荣誉（列表） | 每条一行："1. 奖项名称（颁发单位，日期）" |
| 个人简历（时间线） | "YYYY.MM - YYYY.MM  学校/公司  职位/专业" |
| 论文列表 | "作者. 标题. 期刊, 日期." |

### Step 4: 处理缺失信息（迭代询问）

对 Step 2 中标记为「缺失」的字段，逐一向用户询问：

```
for each 缺失字段:
  1. 显示字段名和上下文（"表格第3行「手机号码」字段为空"）
  2. 如有智能建议值（来自信息源深度挖掘/推断规则），一并展示
  3. 询问用户
  4. 用户回答 → 立即填入选定格式 → 同时更新配置文件
  5. 提示用户已保存
```

**注意**：每处理完一个字段**立即保存配置文件**，防止断线丢失。

**批量询问优化**：当缺失字段超过 3 个时，将所有缺失字段整理成列表一次性询问，减少交互轮次：

```
以下字段在您的配置中缺失，请补充：
1. 出生年月：____（建议：从高考准考证推断约2006-2007年）
2. 籍贯：____（建议：云南省安宁市，推断自"云南省安宁中学"及"赛区云南"）
3. 民族：____
4. 申报类别（学生/职业青年）：____（建议：学生，推断自"本科"）
5. 上一年度团员教育评议等级：____
```

**智能建议规则**：

| 缺失字段 | 建议来源 | 展示格式 |
|---------|---------|---------|
| birth_date | 高考年份-18年推断出生年份 | "约2006-2007年（推断自高考年份）" |
| birthplace | 高中学校所在地推断 | "XX省XX市（推断自高中校名）" |
| ethnicity | 不主动建议 | 留空，用户自填 |
| 申报类别 | degree推断 | "学生（推断自本科）" |
| league_evaluation | 不主动建议 | 留空，用户自填 |
| 所在单位 | school+department拼接 | "XX大学XX系（自动拼接）" |

### Step 5: AI 内容生成

检测表格中需要 AI 生成内容的字段：

| 内容类型 | 识别标志 | 生成策略 |
|---------|---------|---------|
| 自荐信/个人陈述 | "申报材料"、"自荐信"、"个人陈述" + 字数限制 | 基于配置文件聚合信息，按字数限制生成 |
| 理解/看法 | "对XX的理解"、"对XX的认识" + 字数限制 | 结合用户背景 + 通用模板，控制字数 |
| 个人简历 | "个人简历" + 无字数限制 | 从 education + awards + work_experience 聚合 |
| 获奖描述 | "所获荣誉" | 从 awards.yaml 按格式化规则列出 |

**AI 内容生成流程**：

```
1. 识别需要生成内容的字段
2. 收集相关配置信息（personal + education + awards + ...）
3. 根据字数限制和内容类型生成初稿
4. 在填写对照表中标注「AI 生成」，附上字数统计
5. 用户可要求修改/重写
```

**生成质量要求**：
- 自荐信/个人陈述：语气正式但不僵硬，避免套话，突出个人特色
- 理解/看法类：控制在字数限制的 90-100%，条理清晰
- 简历：时间倒序，信息完整无冗余

### Step 6: 处理附件需求

检测表格是否有附件要求：

| 情况 | 处理方式 |
|------|----------|
| 用户已有文件 | 直接挂载到输出目录 |
| 需要 AI 生成内容（如自荐信） | 根据表格要求生成内容，另存为附件文件 |
| 需要生成图片/PDF | 调用多模态生成工具/插件或提示用户自行准备 |
| 无法生成（如证件照、扫描件） | 明确提示用户自行准备，在对照表中标注「待用户提供」 |

### Step 7: 生成填写结果

- **DOCX 输出**：用 python-docx 生成填写后的 DOCX 文件，保持原表格结构
- **Excel 输出**：用 openpyxl 逐单元格写入
- **PDF 输出**：用 PyMuPDF 填充 AcroForm 字段
- 同时生成**填写对照表**（格式见 templates/audit_table.md）

**输出文件命名**：`{原文件名}_已填写_{YYYYMMDD}.docx`

### Step 7.5: 预览确认 + 一致性校验

在生成最终文件前，执行一致性校验并向用户展示预填方案：

**一致性校验规则**：

| 校验项 | 规则 | 错误级别 |
|-------|------|:-------:|
| 性别-姓名一致性 | 检查性别值是否与姓名常见性别倾向一致（仅作提示，不阻止） | ⚠️ 提示 |
| 年龄-学历一致性 | age < 15 → 不应是本科；age > 35 → 不应是本科生 | ❌ 阻断 |
| 入学年份-年级一致性 | 年级推算值与填写值是否匹配 | ❌ 阻断 |
| 手机号格式 | 11位数字，1开头 | ⚠️ 提示 |
| 学号格式 | 与学校规则匹配（如复旦8位数字） | ⚠️ 提示 |
| 邮箱格式 | 含@和域名 | ⚠️ 提示 |
| 政治面貌-申报资格 | 申报"优秀团员"→必须是"共青团员" | ❌ 阻断 |
| 字数超限 | AI生成内容超出字数限制 | ❌ 阻断 |
| 必填字段为空 | 对照表中有MISS状态字段 | ⚠️ 提示 |

**校验执行流程**：

```
1. 运行所有一致性校验规则
2. 汇总结果：
   - ❌ 阻断级错误 → 必须修正后才能继续
   - ⚠️ 提示级警告 → 展示给用户，用户确认后可跳过
3. 生成预填方案摘要：
   ┌──────────────────────────────────────┐
   │ 预填方案预览                          │
   ├──────────────────────────────────────┤
   │ ✅ 申报人姓名：XXX                    │
   │ ✅ 所在单位：XX系                     │
   │ 🔄 籍贯：XX省XX市（推断，需确认）     │
   │ ❌ 出生年月：缺失                     │
   │ 📝 申报材料：约800字（AI生成）         │
   ├──────────────────────────────────────┤
   │ 校验结果：1个阻断、1个提示             │
   └──────────────────────────────────────┘
4. 用户确认预填方案 → 进入 Step 8 生成文件
5. 用户要求修改 → 回到对应步骤调整
```

### Step 8: 用户审查确认

- 展示填写对照表 + 成品文件
- 用户确认 → 交付最终文件
- 用户指出修改 → 回到 Step 7 调整
- 用户要求重写 AI 生成内容 → 回到 Step 5 重新生成

### Step 8.5: 配置自动丰富

用户确认后，主动将本次填表新发现的信息保存到配置文件：

**自动丰富规则**：

```
1. 对比本次填表使用的信息来源：
   a. 信息源深度挖掘的推断值 → 如用户确认了推断值，保存到配置
   b. 用户手动补充的缺失字段 → 保存到对应配置文件
   c. AI生成的内容 → 不保存到配置（非事实性信息）
   d. 计算推断结果 → 保存推算依据到配置
2. 展示将要保存的新信息清单
3. 用户确认 → 更新配置文件
4. 用户拒绝 → 不保存，但下次填表仍会尝试推断
```

**关键**：推断值只有在用户明确确认后才保存，避免错误信息污染配置。

#### DOCX 填写实操指南

使用 python-docx 填写 DOCX 表格时，需注意以下要点：

**1. 单元格定位**

```python
from docx import Document
doc = Document(source_path)
table = doc.tables[table_index]  # 可能有多个表格，需遍历

# 定位单元格
cell = table.rows[row_idx].cells[col_idx]

# 写入文本（清空原有内容后写入）
for paragraph in cell.paragraphs:
    for run in paragraph.runs:
        run.text = ""
if cell.paragraphs:
    cell.paragraphs[0].text = new_value
```

**2. 合并单元格处理**

DOCX 表格中常出现垂直或水平合并的单元格。python-docx 的 `cell.text` 读取合并单元格时，所有合并区域返回相同文本。写入时只需写入合并区域的第一个单元格即可。

```python
# 检测合并单元格：同一 cell 对象出现在多个 (row, col) 位置
seen_cells = set()
for ri, row in enumerate(table.rows):
    for ci, cell in enumerate(row.cells):
        cell_id = id(cell._tc)
        if cell_id in seen_cells:
            # 这是合并单元格的非首位置，跳过
            continue
        seen_cells.add(cell_id)
```

**3. 多行文本写入**

对于需要换行的长文本（如获奖列表、申报材料）：

```python
# 方法1：单段落内换行
cell.paragraphs[0].text = "第一行\n第二行\n第三行"

# 方法2：多段落（保留格式更好）
cell.paragraphs[0].text = "第一行"
for line in remaining_lines:
    cell.add_paragraph(line)
```

**4. 字数控制**

填写长文本字段前，检查字数限制：

```python
import re
def count_chinese_chars(text):
    """统计中文字符数（不含标点和空格）"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))

# 超出字数限制时截断
if count_chinese_chars(content) > max_chars:
    # 按句子截断，保留完整句子
    sentences = re.split(r'([。！？；])', content)
    result = ""
    for i in range(0, len(sentences)-1, 2):
        trial = result + sentences[i] + (sentences[i+1] if i+1 < len(sentences) else "")
        if count_chinese_chars(trial) > max_chars:
            break
        result = trial
    content = result
```

**5. 文件保存**

```python
import os
os.makedirs(os.path.dirname(output_path), exist_ok=True)
doc.save(output_path)
```

---

## 错误处理

### 文件读取失败

| 错误场景 | 处理方式 |
|---------|---------|
| 文件不存在 | 提示用户检查文件路径 |
| 文件格式不支持 | 列出支持的格式，建议转换 |
| DOCX 内容为空 | 检查是否加密/损坏，提示用户 |
| PDF 无文字层 | 进入扫描 PDF 处理流程（Step 1） |
| OCR 识别质量差 | 提示用户提供更清晰版本或手动输入 |
| Excel 受密码保护 | 提示用户解除保护后重试 |

### 配置文件问题

| 错误场景 | 处理方式 |
|---------|---------|
| YAML 语法错误 | 报告具体行号和错误类型，提供修复建议 |
| 配置字段为空 | 标记为「缺失」，进入 Step 4 询问 |
| 配置值格式异常 | 提示用户修正（如日期格式应为 YYYY-MM-DD） |
| 配置文件不存在 | 首次使用流程，创建配置文件 |

### 字段匹配冲突

| 错误场景 | 处理方式 |
|---------|---------|
| 多个配置字段匹配同一表格字段 | 列出所有候选，让用户选择 |
| 信息源与配置文件信息冲突 | 以配置文件为准，提示用户确认 |
| 计算推断结果不确定 | 标记为「模糊」，让用户确认 |

### 输出失败

| 错误场景 | 处理方式 |
|---------|---------|
| DOCX 写入失败 | 检查文件是否被占用/只读 |
| 字段超出字数限制 | 截断并标注截断位置 |
| 表格结构不兼容 | 降级为纯文本输出，标注结构差异 |

---

## 工具集成指南

### Python 库（跨平台通用）

| 库 | 用途 | 安装 |
|------|------|------|
| python-docx | 生成填写后的 DOCX 文件 | `pip install python-docx` |
| openpyxl | 填写 Excel 文件 | `pip install openpyxl` |
| PyMuPDF (fitz) | PDF 表单字段检测 + AcroForm 填充 | `pip install PyMuPDF` |
| pdf2image | PDF → PNG 转换 | `pip install pdf2image` |
| RapidOCR | 扫描件/图片 OCR 识别（中文优先） | `pip install rapidocr-onnxruntime` |
| PyYAML | 读写 YAML 配置文件 | `pip install pyyaml` |

### Agent 平台功能（按平台适配）

| 功能 | 描述 | 各平台对应 |
|------|------|-----------|
| 文档转换 | DOCX/PDF → Markdown 转换 | markitdown CLI / pandoc / 平台内置转换 |
| 文件读取 | 读取 YAML/文本/二进制文件 | 平台原生文件读取功能 |
| 文件写入 | 写入 YAML/文本文件 | 平台原生文件写入功能 |
| 文件编辑 | 更新已有文件内容 | 平台原生文件编辑功能 |
| LLM 内容生成 | 自荐信/个人陈述/理解类内容 | 当前对话中的 LLM |
| 多模态生成 | 图片/3D 模型等附件 | 平台多模态生成工具/插件 |

### 推荐依赖安装

```bash
pip install rapidocr-onnxruntime pdf2image python-docx openpyxl PyMuPDF pyyaml
# 可选：文档转换工具
pip install markitdown  # 或使用 pandoc
# Tesseract OCR (可选，作为 RapidOCR 的备选)
# Windows: winget install UB-Mannheim.TesseractOCR
# macOS: brew install tesseract
# Linux: sudo apt install tesseract-ocr
```

---

## 平台兼容性

### 支持的 Agent 平台

| 平台 | 安装路径 | 文件名 | 说明 |
|------|---------|--------|------|
| Claude Code | `~/.claude/skills/form-filler/` | SKILL.md | Anthropic 官方 CLI |
| WorkBuddy / CodeBuddy | `~/.workbuddy/skills/form-filler/` | SKILL.md | 国产 AI 编程助手 |
| Cursor | `.cursor/skills/form-filler/` | SKILL.md | AI 代码编辑器 |
| Cline | `.cline/skills/form-filler/` | SKILL.md | VS Code 扩展 |
| OpenClaw | `skills/form-filler/` | SKILL.md | 开源 Agent 框架 |
| Codex CLI | 项目根目录 `.codex/` | SKILL.md | OpenAI CLI |

### 安装

```bash
# 方式1：git clone
git clone https://github.com/quitli888-source/form-filler.git
# 将目录复制到对应平台的 skills/ 路径下

# 方式2：手动下载
# 下载 SKILL.md + templates/ + scripts/ 到目标路径
```

### 平台差异适配

不同 Agent 平台的文件操作方式不同，本模块描述的流程基于「能力」而非具体工具：

| 本文档描述 | Claude Code | WorkBuddy | Cursor |
|-----------|-------------|-----------|--------|
| 文档转换工具 | markitdown CLI | markitdown skill | pandoc / 内置 |
| 文件读取功能 | Read tool | Read tool | 内置 |
| 文件写入功能 | Write tool | Write tool | 内置 |
| 文件编辑功能 | Edit tool | Edit tool | 内置 |
| 用户交互 | 直接对话 | 直接对话 | 直接对话 |

---

## 配置文件模板

### personal.yaml

```yaml
name: ""
name_en: ""
gender: ""
birth_date: ""          # YYYY-MM-DD
id_number: ""
ethnicity: ""           # 民族，如"汉族"
birthplace: ""          # 籍贯，如"云南省安宁市"
political_status: ""    # 政治面貌，如"共青团员"、"中共党员"
```

### contact.yaml

```yaml
phone: ""
email: ""
wechat: ""
qq: ""
current_address:
  province: ""
  city: ""
  district: ""
  detail: ""
  postal_code: ""
emergency_contact:
  name: ""
  relation: ""
  phone: ""
```

### education.yaml

支持多条教育经历：

```yaml
entries:
  - school: ""           # 学校名称
    department: ""       # 院系名称（如"高分子科学系"）
    major: ""            # 专业
    degree: ""           # 学位类型：本科/硕士/博士
    student_id: ""       # 学号
    start_date: ""       # 入学日期 YYYY-MM
    end_date: ""         # 毕业/预计毕业日期 YYYY-MM
    gpa: ""
    ranking: ""
    advisor: ""
    school_type: ""      # 985/211/双一流等
```

### awards.yaml

支持多条获奖记录：

```yaml
entries:
  - name: ""             # 奖项全称
    level: ""            # 级别：国家级/省级/市级/校级/院级
    issuer: ""           # 颁发单位
    date: ""             # YYYY-MM 或 YYYY
    category: ""         # 类别：学科竞赛/科技竞赛/奖学金/综合荣誉/体育/艺术
    description: ""      # 补充说明
```

### work_experience.yaml

支持多条工作经历：

```yaml
entries:
  - company: ""
    position: ""
    start_date: ""
    end_date: ""
    department: ""
    description: ""
    referee: ""
    referee_phone: ""
```

### publications.yaml

支持多条论文/专利：

```yaml
entries:
  - title: ""
    type: ""             # 论文/专利
    journal: ""
    authors: ""
    position: ""         # 第一作者/通讯作者/共同作者
    date: ""
    doi: ""
    level: ""            # SCI 一区/核心期刊等
```

### skills.yaml

```yaml
entries:
  - name: ""
    score: ""
    level: ""
    date: ""
    proficiency: ""      # 了解/熟悉/熟练/精通
    type: ""             # 编程技能/语言能力/专业证书
```

### league.yaml

团组织/党建相关信息：

```yaml
league_registration: ""     # 智慧团建是否注册：是/否
league_evaluation: ""       # 上一年度团员教育评议等级：优秀/合格/基本合格/不合格
league_position: ""         # 团内职务（如有），如"团支书"、"组织委员"
league_join_date: ""        # 入团日期 YYYY-MM
party_status: ""            # 党员状态：群众/共青团员/入党积极分子/预备党员/中共党员
league_activities: ""       # 参与团组织活动情况简述
```

### bank.yaml

```yaml
bank_name: ""
branch: ""
card_number: ""
cardholder: ""
```

---

## 隐私保护声明

- 以上所有配置文件 **仅存储在本机**，不会通过任何渠道传输到外部
- 配置文件的读写操作全部通过本地文件系统完成
- 建议定期审查 `profiles/` 目录下的内容，删除不再需要的字段
- 金融信息（bank.yaml）可额外手动加密存储
- 如需分享此模块给其他人使用，请确保不包含个人配置文件

---

## 端到端实战示例

### 场景：从奖学金申请PDF → 优秀团员申报表DOCX

**输入**：
- 信息源：奖学金申请表（10页扫描PDF）
- 目标表：优秀共青团员申报表（DOCX，含表格结构）

**执行流程**：

```
Step 0: 检查profiles/ → 已有personal/contact/education/awards/league.yaml
Step 1: 检测目标表 → DOCX表格（无模板标记）→ 文档转换后识别18个字段
         检测信息源 → 扫描PDF → RapidOCR提取 → 深度挖掘隐含信息
Step 2A: 语义字段映射 → 18个字段逐一匹配
Step 3: 获奖列表 → 全部列出，按时间倒序
Step 4: 缺失字段批量询问（含智能建议）
Step 5: AI生成申报材料 + 理解类内容
Step 6: 无额外附件需求
Step 7: python-docx填写DOCX，生成对照表
Step 7.5: 一致性校验 → 预填方案预览 → 用户确认
Step 8: 交付已填写DOCX + 对照表
Step 8.5: 自动丰富配置（保存用户确认的推断值）
```

**结果**：11/18 自动匹配 + 3 推断 + 4 缺失需用户补充
**自动填充率**：78%（含推断确认后达89%）

---

## 测试场景模板

### 场景A：纯配置填充（无信息源）
- 输入：DOCX表格 + 本地配置文件
- 预期：所有配置已有字段自动填充，缺失字段逐一询问
- 关键验证：匹配准确率、批量询问格式

### 场景B：信息源 + 目标表
- 输入：扫描PDF信息源 + DOCX目标表 + 本地配置
- 预期：显式提取 + 深度挖掘 + 合并 → 填充率显著提升
- 关键验证：深度挖掘推断准确性、合并冲突处理

### 场景C：模板替换
- 输入：含 `{{字段名}}` 的DOCX模板 + 配置
- 预期：所有标记正确替换
- 关键验证：正则提取完整性、缺失标记处理

### 场景D：纯文字描述
- 输入："帮我填一个奖学金申请"（无文件）
- 预期：LLM提取字段清单 → 匹配配置 → 缺失询问
- 关键验证：字段提取完整性

### 场景E：一致性校验触发
- 输入：配置中政治面貌="群众"，但申报"优秀团员"
- 预期：校验阻断，提示政治面貌不符合申报条件
- 关键验证：校验规则准确性

### 场景F：Excel 多Sheet
- 输入：.xlsx 含多个Sheet，不同Sheet填不同信息
- 预期：逐Sheet识别字段 → 分别映射填充
- 关键验证：Sheet识别、单元格定位
