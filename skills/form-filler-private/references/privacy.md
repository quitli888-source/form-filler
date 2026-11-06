# 严格本地版隐私边界

本版不包含cloud_draft.py、standard_workflow.py或其云端测试/示例。EDITION固定为private，endpoint_url(local=False)始终拒绝外部请求；模型适配器仍仅允许回环，目的地固定，禁环境代理、重定向和SDK重试。没有可由环境变量打开的云端开关。

这是防误调用的代码约束，不是恶意agent或系统管理员无法突破的安全沙箱。能执行任意代码的进程可改脚本或绕过适配器；强制禁止外发还需要系统网络策略、进程隔离和受控本地宿主。不要承诺“装了skill就对所有软件绝对安全”。

资料、原件、模型上下文和OCR仅在用户控制的本机处理。默认本地规则无网络；本机模型服务必须确认为真正离线，回环地址本身并不证明没有转发。宿主如在云端，不得读原文或截图入对话；要求连元数据都本地时需使用本地宿主。

Windows档案位于FormFillerPrivate，使用当前用户DPAPI，不启用LOCAL_MACHINE。加密失败停止留存，不生成明文替代；同账户恶意程序、管理员和账户失陷不在保护保证内。更换账户/设备或重置凭据可能无法解密，由用户决定备份策略，不擅自导出明文。
非Windows未实现自动加密持久化，可显式读取用户已有YAML，依赖用户的系统加密卷/存储。Windows输出继承ACL，POSIX临时文件0600、新建末级目录0700；成品、原件和显式导出仍是本地明文，不等于DPAPI档案。

本次使用不默认长期记忆，新增/覆盖/迁移/备份须确定范围。旧档案、旧版Markdown副本不自动复制或删除。默认不产生OCR全文、全量profile历史、原始反思和调试转储；审计省略所有原始值。
删除只限用户指定任务范围，不声称能彻底清除内存、交换文件、SSD、编辑器缓存、同步备份或系统记录。

参考：[DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)、[HTTPX环境变量](https://www.python-httpx.org/environment_variables/)、[重定向](https://www.python-httpx.org/compatibility/#redirects)。

模型调用期间的openai/httpx/httpcore标准logging记录会在交给handler前遮盖消息与异常正文，即使OPENAI_LOG=debug。调用结束恢复原日志factory，非模型日志不受影响；这不能控制第三方自定义print或宿主遥测。

已有加密档案默认拒绝覆盖；--replace-section明确替换整个section而非合并。目标目录有同类明文时先拒绝，避免同时生成两种格式后无法读取。源文件仍保留，不自动迁移或删除。
