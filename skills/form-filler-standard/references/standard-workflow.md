# 常态版流程与输入格式

case.json包含facts、replacements、targets，完整合成示例在examples/case.json，搭配examples/template.docx。

- facts每项含id（F数字）、kind、text、allow_cloud。kind仅education/experience/award/skills/intent/public_requirement；只有allow_cloud=true才发送。不要把整个profile作为fact。
- replacements是稳定占位符→真实值的本地映射，例如“{{PERSON_1}}”→“合成姓名”。程序还会为常见号码/邮箱等产生PRIVATE占位符，映射不发送。
- targets每项含id（T数字）、table/row/col（从0起）、kind（infer/generate）、label、requirements、min_chars、max_chars。坐标仅本地使用，目标必须为空，不覆盖已有事实。
- infer仅支持年级、学历年级、申报类别、经历类别、技能概述、获奖级别、岗位匹配；获奖级别不能仅靠“决赛”二字确定。
- generate仅支持申请理由、自荐信、个人陈述、主要事迹、自我评价、技能概述、创新点摘要、实习总结、团员理解、研究计划，不通过生成路径猜身份或代替他人鉴定。
- 长度按Python字符串字符数计算，还原占位符后重新校验，不宣称等于所有表格的“中文字数”。requirements也会脱敏，但实际request仍要本机核查。

模型返回格式：
```json
{"items":[
  {"target_id":"T1","value":"本科二年级","basis":["F1"],"assumptions":[],"confidence":"high"},
  {"target_id":"T2","value":"{{PERSON_1}}在{{SCHOOL_1}}学习化学，积极参与课程实验与小组数据整理。","basis":["F1","F2"],"assumptions":[],"confidence":"high"}
]}
```

basis必须引用实际外发的素材id，不能引用allow_cloud=false内容。无法支持时省略该项，review.unanswered显示未回答目标。拒绝未知目标/占位符、直接号码/邮箱/链接、无来源引用或超长文字。语义依据是否充分仍需用户核查，程序不能证明模型没有夸大事实。

review包含还原后的真实值、依据、假设、置信度和状态，属于敏感本地文件；在本机打开，不输出全文到云端聊天。
复核hash绑定候选和模板指纹，修改后需重审。

apply --draft在正文保留“【待确认推测】”和“【AI生成草稿】”，标记也计入max_chars，超长时缩短内容而不悄悄删标记。正式版只选择用户接受的T id并省略--draft；其余目标留空，已有事实与原件保留。接受填写不代表同意长期保存。
