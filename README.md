# Form Filler v8.0.1 — 双版本填表 Skill

两种可独立安装的版本：严格本地的绝对隐私版，以及支持脱敏云端推测和写作的常态版。

| 版本 | 用途 | 源码与说明 | 安装包 |
|---|---|---|---|
| 绝对隐私版（严格本地） | 原始资料和脱敏素材均不发外部模型；本地规则及可选真正本机模型 | [form-filler-private](skills/form-filler-private) | [ZIP](dist/form-filler-private-v8.zip) |
| 常态版 | 外部模型基于选定、脱敏的素材进行合理推测与文本生成，本机还原身份并填写 | [form-filler-standard](skills/form-filler-standard) | [ZIP](dist/form-filler-standard-v8.zip) |

两个skill可同时安装；资料目录分别使用FormFillerPrivate和FormFillerStandard，不静默切换或复制档案。普通填表使用常态版，要求不得外发时明确使用form-filler-private。

## 安装

下载对应ZIP，将其中的form-filler-private或form-filler-standard文件夹放到agent的skills目录，保留文件夹名称。也可从本仓库skills目录复制对应文件夹。
Python 3.10+，在所选版本目录执行：

```powershell
pip install -r requirements.txt
# 只有需要本机模型/常态云端时才安装
pip install -r requirements-model.txt
```

依赖可预先准备；联网安装不构成上传真实资料的许可。本次不自动迁移、覆盖或删除旧版个人档案。已安装旧版form-filler时，建议由用户决定停用旧入口，避免误选。

## 常态版工作流

本地读取必要事实 → 稳定占位符和常见标识符脱敏 → 只发送用户选定素材 → 模型返回依据、假设和置信度 → 本机还原 → 带标记草稿或用户接受后的正式填写。

可提出年级、申报/经历类别、技能、奖项级别和岗位匹配等有依据候选，或根据已知事实撰写申请理由、陈述等。未确认推测可标“【待确认推测】”写入草稿，正式填写只采用用户接受的项，不自动写回长期档案。
不猜身份证、籍贯、生日、民族、政治、健康或财务等敏感事实，也不虚构成绩、奖项、日期和经历。源格式、合成示例和命令见[常态版流程](skills/form-filler-standard/references/standard-workflow.md)。

用户需知接收方、精确地址与模型、素材范围和用途；明确任务授权可覆盖批量字段，无需逐字段重复询问。扩展披露范围、换服务、传原件或重试需重新确认。

## 隐私范围

“绝对隐私版”是严格本地策略的名称，不是对操作系统、宿主、管理员、恶意程序或备份的无条件安全保证。全程不出机需要本地宿主、真正离线模型和用户控制的系统网络策略。云端宿主读取本地原文也可能外发。
常态脱敏不能证明完全匿名，未知姓名和稀有经历组合仍须本机核查。映射、原件、成品和复核文件属于本地敏感数据。Windows经同意可用当前用户DPAPI加密档案，非Windows使用用户已有加密存储；成品等明文文件建议放用户控制的加密目录。
默认诊断和审计不回显原始填写值、敏感路径和自由文本反思。两版均不自动提交、分享、发邮件或发布成品。

## 验证

从仓库根目录一次验证两版，各版测试在独立Python进程和独立工作目录运行，避免同名模块混入另一版：

```powershell
python tools/check_editions.py
# 只检查某一版
python tools/check_editions.py --edition private
```

检查同时核对dist安装包与受控源码范围、ZIP完整性及SHA-256。源码改动后用以下命令重新打包；固定文件顺序、时间戳及文本换行，同样的源码生成相同ZIP。真实档案、密钥配置、缓存和临时输出不在打包白名单内：

```powershell
python tools/manage_packages.py build
python tools/manage_packages.py check
```

维护工具需要所选版本的开发依赖。也可以在各版本目录单独运行：

```powershell
# 进入所选skills/form-filler-private或skills/form-filler-standard目录
pip install -r requirements-dev.txt
python -m pytest tests -q
```

根目录的`python -m pytest`只运行轻量维护检查，不收集旧版tests或混合两版测试；完整回归使用`tools/check_editions.py`。

本次验证：绝对隐私版168 passed、1 skipped；常态版221 passed、1 skipped；根维护检查8 passed。全部测试采用合成数据并禁止socket联网，云端模型响应模拟；Windows实际DPAPI加解密往返通过，两个SKILL格式检查通过。
Python执行器支持DOCX表格；Excel/PDF/OCR为本地agent流程，不代表完整多格式执行器。安装包校验见[SHA-256](dist/SHA256SUMS.txt)。

仓库根目录原有scripts/evaluation/tests/agent_state为旧版兼容/历史资料；v8使用skills下的独立实现，根SKILL只负责路由，不执行旧版流程。MIT License。
