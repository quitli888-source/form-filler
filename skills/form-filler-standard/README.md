# Form Filler 常态版 v8.0.1

允许外部模型使用选定、经本地脱敏的素材做合理推测、文本生成，再在本机还原身份与填表。独立skill名form-filler-standard，与严格版可同时安装且档案目录分开。

Python 3.10+，解压到agent的skills目录后：

```powershell
pip install -r requirements.txt
pip install -r requirements-model.txt
```

普通事实填表用fill_docx.py；云端推测、写作和填表：

```powershell
# 离线准备，只选择必要素材
python scripts/standard_workflow.py prepare --source <case.json> --template <模板.docx> --base-url https://provider.example/v1 --model <模型> --request-out <新request.json> --plan-out <新plan.json>
# 用户本次授权覆盖接收方和素材范围后发送
python scripts/cloud_draft.py send --request <request.json> --approved-sha256 <请求摘要> --response-out <新response.txt>
# 本地验证、还原并产生复核摘要
python scripts/standard_workflow.py review --plan <plan.json> --request <request.json> --response <response.txt> --review-out <新review.json>
# 先填带标记草稿；正式版去掉--draft，且仅选择用户接受的字段
python scripts/standard_workflow.py apply --review <review.json> --approved-sha256 <复核摘要> --accept T1,T2 --output <新草稿.docx> --draft
```

key仅在本地FORM_FILLER_CLOUD_API_KEY环境变量中设置，不进入聊天、命令行、请求文件或版本库。请求/复核摘要由对应命令输出，生成摘要不是用户授权。

examples/case.json和examples/template.docx是合成示例；[完整输入格式](references/standard-workflow.md)与[隐私边界](references/privacy.md)说明字段、依据与标记。

默认Windows档案目录%LOCALAPPDATA%/FormFillerStandard，留存需用户单独同意，可用DPAPI加密。映射/成品/复核是敏感本地明文，需用户控制的加密存储。脱敏不保证匿名，未知姓名与罕见经历需本机核查。

严格要求不外发时使用绝对隐私版与本地宿主。Python执行器仅支持DOCX表格，Excel/PDF/OCR为agent本地流程。

测试：
```powershell
pip install -r requirements-dev.txt
python -m pytest tests -q
```
全用合成资料、模拟模型响应，禁止socket联网。

本次修复：保留预填单元格与已有格式；scan-only不依赖档案或模型；审计模板按安装位置查找。SDK调试日志中的模型调用正文也会隐藏。已有加密section不默认覆盖，确需替换整个section时显式使用--replace-section。
