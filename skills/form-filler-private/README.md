# Form Filler 绝对隐私版（严格本地）v8

独立skill：form-filler-private。默认本地规则，可选真正本机模型；没有云端发送器，脱敏素材也不发外部模型。本版与常态版可以同时安装，资料目录隔离。

“绝对隐私版”是版本名称。它不能控制恶意软件、操作系统、同步备份和宿主遥测；全程不出机需要本地宿主/工具以及用户控制的环境。

Python 3.10+：
```powershell
pip install -r requirements.txt
# 仅在用户需要本机模型时
pip install -r requirements-model.txt
python scripts/fill_docx.py --template <模板.docx> --profile-dir <已有资料目录> --output <本地成品.docx>
```
依赖应在处理真实资料前准备；安装可能联网，不代表允许上传资料。普通本地规则无需模型依赖。

默认Windows资料目录%LOCALAPPDATA%/FormFillerPrivate；非Windows为XDG下form-filler-private。留存单独确认，Windows可用profile_store.py按当前用户DPAPI加密，失败不落明文。旧YAML仅显式指定读取；不迁移、删除或复制其他版档案。

真实值只在本机成品/资料中，默认日志、扫描和审计不回显。成品仍是明文敏感文档，建议用户控制的加密存储。
本机模型只允许回环，但该服务自身是否转发云端需用户确认。云端宿主读取本地原文仍可能外发，不能将原文输出给云端聊天做“本地处理”。

详见 [SKILL.md](SKILL.md) 和 [隐私边界](references/privacy.md)。Python执行器支持DOCX表格；Excel/PDF/OCR为agent本地流程。

测试：
```powershell
pip install -r requirements-dev.txt
python -m pytest tests -q
```
全用合成资料，测试禁止socket联网。
