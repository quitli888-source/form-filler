# Round 6 — Reviewer Output

> Loop status: **ACTIVE** (R5 TERMINATE_DONE 被主 Agent 覆盖，R6 activated；`agent_state/loop_config.json` 的 `loop_status` 字段仍为 "TERMINATED"，以主 Agent 本轮激活决定为准)。
> Project version entering this round: **6.3**（post-R5，score 96.0，88 passed / 4 skipped，cumulative +38.55）。
> 本轮背景变化：主 Agent 已将 **step-5-preview** 配为项目 LLM 内核（`.env.local`，`LLM_BASE_URL=https://api.stepfun.com/v1`，端点可达、返回 402 quota_exceeded），LLM 自愈/反思路径首次具备实测条件。
> 终止标准提醒：`min_quality_delta=3`、`plateau_rounds=2`；R5 已录得 Δ=+2.0（<3）。96.0 已接近天花板，**本轮合理 scope 只能支撑 +1~2**（见 §5 诚实声明）。

Goal of R6: 修复两个**已确认的真实缺陷**（反思反馈闭环 no-op、generate_struct 盲重试），外加一个零 LLM 零依赖的确定性增量（字段类型推断 pre-scan）。全部默认行为保持不变，全部离线可回归。

---

## 1. Fact-check 结果

### 1.1 Researcher 关键声明核实表

| # | Researcher 声明 | 我的验证方法与行号证据 | 成立与否 |
|---|---|---|---|
| F1 | 反思循环 L866-881 **从不把反思原文喂回下一轮** | `scripts/fill_docx.py` L872-878：循环体只有 `r = reflect_fn(text, filled_value, filled_so_far)` → `reflection_text = r`（仅用于 audit 输出，L892 写入 details）→ `filled_so_far[text] = filled_value`。`r` 从未进入任何后续 prompt 或 ctx。**成立** | ✅ 成立 |
| F2 | "temperature=0.0 下第 2 轮与第 1 轮**逐字节相同**" | `model_adapter.py` L259 `temperature=0.0` 属实；但"逐字节相同"**不准确**：默认 `reflect_fn` 把 ctx 包装为 `{"filled_so_far": ctx}`（`fill_docx.py` L793-795），`reflect()` 将其渲染进 `ctx_lines`（L240），而 L878 在第 1 轮后把当前字段加入 `filled_so_far`——第 2 轮 prompt 的「同表已填字段」行**多出当前字段自身**，故非逐字节相同。但结论方向正确：反思原文不到模型手里，temperature=0.0 下两轮任务实质相同，多轮是 near-no-op | ⚠️ **部分成立（机制描述有误，结论成立）** |
| F3 | SKILL.md Step 5.5 承诺「重新调用 Step 5 用反思作为额外上下文重生成一次（仅 1 次重试）」在代码中不存在 | SKILL.md L444 原文 vs `fill_docx.py` L866-881：只有"重反思"，无任何重生成/重填调用。**成立**（这是真实的 spec-impl 漂移） | ✅ 成立 |
| F4 | `generate_struct` 重试循环每次用**同一 prompt**，错误只 print 到 stderr、从不进 prompt | `model_adapter.py` L188-189：`messages = [{"role": "user", "content": prompt}]` 每轮原样重建；异常仅 `print(..., file=sys.stderr)`（L200-203 instructor 分支 / L217-220 plain 分支）后 `continue`。**成立** | ✅ 成立 |
| F5 | reflect() 重试已有"错误回喂"雏形（L280-283 `last_prompt = f"{base_prompt}\n\n上一次回答出错: {exc}\n请重新回答。"`），但 exc 是裸异常字符串 | L280-283 逐字属实。**成立** | ✅ 成立 |
| F6 | plain fallback `schema.model_validate_json(raw)` 对 markdown 围栏/尾逗号零容忍（L214-215） | L214-215 逐字属实；`model_validate_json` 对 ```json 围栏确实直接抛 ValidationError。**成立** | ✅ 成立 |
| F7 | `_is_likely_label()`（L214-232，20 字上限 + 关键词正则）会把「获奖情况请依次填写」类说明句判成 label | 实测逻辑：`len("请依次填写获奖情况")=8 ≤ 20` 且含关键词「获奖」→ 返回 True。**成立**（但影响面有限，见 §2-R6-A3 风险分析：误判 label 只是匹配失败被 skip，不会造成错填） | ✅ 成立 |
| F8 | SCHEMA_SYNONYMS 只支持精确键查找，「差一个字就落到 Pass 2 正则」 | `schemas.py` L266/L287 `SCHEMA_SYNONYMS.get(label, label)` 属实；**但** `find_schema_for_label` L272-276 与 `find_field_in_schema` L292-296 已有 substring 回退（`fname in label or label in fname`）。 Researcher 夸大了差距——「申请人 / 申请人姓名」类变体大部分已被现有 substring 回退覆盖 | ⚠️ **部分成立（差距被夸大）** |
| F9 | pydantic-ai 20,109 stars | `gh api repos/pydantic/pydantic-ai --jq '.stargazers_count'` → **20109**（2026-09-22 实测）。**成立** | ✅ 成立 |
| F10 | kordoc 1,845 stars | `gh api repos/chrisryugj/kordoc --jq '.stargazers_count'` → **1845**。**成立** | ✅ 成立 |
| F11 | json_repair 5,103 stars | `gh api repos/mangiucugna/json_repair --jq '.stargazers_count'` → **5103**（我额外抽查了 R6-A2 的直接依赖源）。**成立** | ✅ 成立 |
| F12 | 基线 88 passed / 4 skipped | `cd "D:/form filler" && python -m pytest tests/ -q` → **88 passed, 4 skipped in 4.53s**。**成立** | ✅ 成立 |
| F13 | §6.3 line-cited 表全部行号 | 抽查 8 条：L866-881（反思循环）✓、L229-291（reflect）✓、L180-227（generate_struct）✓、L214-215（plain fallback）✓、L214-232（_is_likely_label）✓、L128-177（scan_docx_introspect）✓、L841-842（unmatched continue）✓、L936-964（_iter_unique_cells）✓、schemas.py L173-195（SCHEMA_SYNONYMS）✓。**全部准确** | ✅ 成立 |

### 1.2 我方的独立缺陷确认（主 Agent 要求的自有行号证据）

**缺陷 (a)：反思反馈闭环缺失 — 确认存在。**
`scripts/fill_docx.py` L866-881：
```python
reflection_text = ""
if reflexion_rounds > 0 and filled_value and not skip_llm:
    filled_so_far = {
        d["label"]: d["value"] for d in audit["details"] if d.get("value")
    }
    for _ in range(reflexion_rounds):
        r = reflect_fn(text, filled_value, filled_so_far)
        if not r:
            break  # stub: nothing to reflect on
        reflection_text = r
        status_icon = "⚠️"
        filled_so_far[text] = filled_value
```
`r` 的三个去向：审计输出（`reflection_text`）、状态降级（`⚠️`）、ctx 增补——**没有一个是"喂回下一轮 reflect 调用"**。配合 `model_adapter.py` L259 的 `temperature=0.0` 与 L241-247 的固定 `base_prompt`，`--reflexion-rounds 2` 的第 2 轮相对第 1 轮的唯一变化是 ctx 里多出当前字段自身（F2 修正），模型收到的反思反馈为零。SKILL.md L444 承诺的"重生成"则完全不存在（F3）。**裁定：真实缺陷，R6 必修。**

**缺陷 (b)：generate_struct 盲重试 — 确认存在。**
`scripts/model_adapter.py` L188-221：`for attempt in range(max(1, self.max_retries))` 内 `messages = [{"role": "user", "content": prompt}]`（L189）用同一 `prompt` 重建；两条失败路径（instructor 分支 L199-205、plain 分支 L216-221）都只 print 到 stderr 后 `continue`，`prompt` 变量在循环内从未被修改。**裁定：真实缺陷，R6 必修。** 附带事实：现有测试无一覆盖 `OpenAICompatibleAdapter.generate_struct` 的重试路径（`grep generate_struct tests/` 仅命中 MockLLMAdapter 的 4 处），A2 有干净的改动面。

### 1.3 对 Researcher 的修正要求（Optimizer 不得转抄错误表述）

1. 实现/文档中**不得**声称"第 2 轮 prompt 与第 1 轮逐字节相同"——正确表述是"反思原文从不回喂，temperature=0.0 下多轮反思任务实质相同（near-no-op）"。
2. R6-A4 的动机表述"差一个字就落到 Pass 2 正则"不准确——`find_schema_for_label`/`find_field_in_schema` 已有 substring 回退（`schemas.py` L272-276、L292-296）。这是 A4 被 DEFER 的理由之一（§2、§4）。

---

## 2. 逐项评审（R6-A1..A6）

### R6-A1：反思反馈闭环 + ReflexionStrategy 枚举 + ReflectionMemory + JSONL

**裁定：SHIP（大幅收窄）——只修缺陷本身（反馈闭环），砍掉枚举与 JSONL。**

| 维度 | 评估 |
|---|---|
| Ratchet | 修的是"SKILL.md 白纸黑字承诺 vs 代码 no-op"的真实缺陷（F1+F3），属最高优先级的缺陷修复类；附 SKILL.md 同步直接修复 spec 漂移。符合"可测量的缺陷修复"计入 ratchet。 |
| 与 v6.3 差距 | 真实缺陷：多轮反思的反馈语义不存在。这是本项的全部价值，收窄后完整保留。 |
| 风险 | 收窄后风险低：`--reflexion-rounds` 默认 0（`fill_docx.py` L992-993），循环根本不执行 → 默认用户零变化；`rounds=1` 时 prior 列表为空，prompt 必须与 v6.3 逐字节相同（设为硬门槛）。砍掉枚举/JSONL 后无新 CLI 面、无新产物文件。 |
| 成本 | 收窄后 ~+45 app LOC（model_adapter reflect 加可选参数 + fill_docx 循环注入 + 默认 reflect_fn 适配）+ ~90 test LOC（3 tests）。 |
| 可测量性 | Robustness（反思机制从 no-op 变生效）、Skill spec completeness（Step 5.5 文档与代码对齐，消除漂移）、Evaluation（新增 3 tests + prompt 断言）。 |
| 砍掉部分及理由 | **ReflexionStrategy 枚举 → REJECT（R6）**：无任何用户请求 4 值语义，R5 已以同一理由 defer，理由本轮不变；新增 `--reflexion-strategy` CLI + SKILL.md 文档面，零可测量收益。**JSONL 持久化 → REJECT（R6）**：只写不读的产物（Researcher 自引 Anti-pattern F），且反思文本引用字段值，会绕过 audit.md 的 `_redact` 脱敏链路（`fill_docx.py` L886）——在隐私优先原则下是 Privacy&UX 维度的净负资产，直到有检索方出现。 |

### R6-A2：generate_struct 结构化校验错误回喂 + json_repair 修复层

**裁定：SHIP（完整采纳，含可选依赖设计）。**

| 维度 | 评估 |
|---|---|
| Ratchet | 修缺陷 (b)（F4）：真实 LLM 路径的自愈率从"盲重试"升级为"带错误反馈重试"；step-5-preview 就位后该路径首次可实测。 |
| 与 v6.3 差距 | 真实缺陷：重试不带反馈等于浪费 attempt（尤其 temperature=0.0 时第 2 次与第 1 次同结果）。json_repair 层解决 plain fallback 对围栏/尾逗号零容忍（F6）的脆弱性。 |
| 风险 | 低。两条硬约束可机械验证：(1) 首次尝试成功时发送的 prompt 与 v6.3 逐字节相同（反馈块只在失败后的重试追加）；(2) json_repair 缺失时行为与 v6.3 完全一致（try-import，参照 instructor 的 L171-178 模式）。注意 json_repair **当前环境未安装**——必须进 requirements.txt 的 Optional 区（非 core），测试需同时覆盖"已安装"与"模拟缺失"两条路径。 |
| 成本 | ~+60 app LOC（`_format_validation_feedback()` 辅助 + generate_struct 改动 + try-import）+ ~90 test LOC（3 tests，复用 `tests/test_minimax_smoke.py::TestReflectRetryLogic` 的 `patch.object(adapter._client.chat.completions, "create", ...)` 模式，零网络）。 |
| 可测量性 | Robustness（LLM 路径自愈，直接对应"edge cases"维度）、Evaluation（+3 tests；MockLLM 的 sha256 prompt 寻址不受影响——重试路径才会改 prompt，现有 MockLLM generate_struct 测试全走 happy path）。 |
| 备注 | instructor 分支的重试同样获得反馈（pydantic ValidationError 经 `_format_validation_feedback` 序列化）；instructor 内部 max_retries=2 保留不变。 |

### R6-A3：确定性字段类型推断 pre-scan（field_types.py + introspect 充实 + _is_likely_label hardening）

**裁定：SHIP（收窄）——保留新模块 + `--introspect-out` JSON 充实；label hardening 降级为"条件性 hunk"；砍掉 audit 表新增列。**

| 维度 | 评估 |
|---|---|
| Ratchet | 零 LLM 零依赖的确定性增量；`--introspect-out`（`fill_docx.py` L1012-1013，默认 None，本身就是 opt-in 面）新增 type/required/empty 三个可观测键 → Evaluation 维度可测量。 |
| 与 v6.3 差距 | Pattern J 的自然延伸（introspect JSON 从 text/is_label/merged_dup 三元扩到六元）。label 缺陷（F7）真实但影响面低：误判成 label 的说明句只会 match 失败被 skip（L841-842），不会造成错填——所以 hardening 是 nice-to-have，不是 driver。 |
| 风险 | 低，但分两档：introspect 加键是纯 additive（默认输出不变，因为该 JSON 只在显式传 `--introspect-out` 时产生）；`_is_likely_label` hardening 改变默认 cell-walk 路径的标签判定，是**默认行为变更**——与"零行为变化"硬约束冲突，因此设为条件性 hunk：以 88 条现有测试全绿为门槛，任何一条因 hardening 失败即回退该 hunk、保留其余部分。 |
| 成本 | ~+65 app LOC 必选（field_types.py ~90 中含 introspect 接入；净计）+ ~25 LOC 条件性（hardening）+ ~110 test LOC（4-5 tests）。 |
| 可测量性 | Evaluation（新模块 + 新 JSON 键 + 新测试）、Robustness（hardening 若过关则 +0.5~1）、Code quality（+0.5）。 |
| 砍掉部分及理由 | **audit 表新增「类型/必填」列 → REJECT（R6）**：`render_audit_table()`（L696-703 的正则替换行）+ `templates/audit_table.md`（L17 表头）都会变，即**所有用户的 audit.md 默认输出改变**，违反默认行为不变硬约束；且 `score_consistency.py:parse_audit_md()`（L258-285）按列下标解析，加列有破坏 harness 的风险。留到 R7 与 A4 的 unmatched 反馈一起作为"audit 输出增强"议题整体设计。 |

### R6-A4：findMatchingKey 双向前缀匹配（0.6/0.75）+ resolveUnmatched audit 反馈

**裁定：DEFER 到 R7（不进本轮 scope）。**

- Ratchet：无缺陷修复成分；现有 substring 回退（F8）已覆盖大部分变体场景，真实差距比 Researcher 描述的小。
- 风险：前缀匹配 + 长度比护栏改变默认填写路径的匹配语义，对 88 条测试的回归面不可控（`test_synonyms.py` 10 条 + `test_fill_docx.py` 39 条都压在 match_field 上）。
- 默认行为：`resolveUnmatched` 会在 audit.md 新增 ❓ 行 → 改变所有用户默认输出，且 `rule_miss_count`（score_consistency L139-144）按 ❌ 计数，语义交互需重新设计。
- 成本/容量：本轮已有 3 项，A4 的两个子项都不满足"缺陷修复优先于新能力"的排序。
- R7 形态建议：`resolveUnmatched` 做成 opt-in `--show-unmatched` flag；`find_alias_key` 仅在有具体未匹配变体案例报告后再做。

### R6-A5：ValueCursor 多条目按序消耗（Step 3 落地）

**裁定：DEFER 到 R7（与 Researcher 一致）。** 新能力非缺陷；名册型表格无当前用户诉求；+55 LOC / +3 tests 会挤压本轮缺陷修复的容量。

### R6-A6：fillInCellPatterns 单元格内联占位符

**裁定：DEFER 到 R7（与 Researcher 一致）。** 新能力非缺陷；内联占位改写有改坏模板文本的风险（「□男 □女」的替换逻辑对误匹配零容忍度）；应在 A5 的多条目机制之后一起设计。

---

## 3. R6 最终 scope

**三项，全部离线可回归，无新增必需依赖，默认行为零变化：**

| ID | 名称 | 来源 pattern | app LOC | tests | 性质 |
|---|---|---|---|---|---|
| R6-A1 | 反思反馈闭环（修 no-op 缺陷 + SKILL.md Step 5.5 同步） | pydantic-ai ModelRetry 语义 + deferred R1+R2 之缺陷部分 | +45 | +3 | 缺陷修复 |
| R6-A2 | generate_struct 结构化错误回喂 + json_repair 可选修复层 | pydantic-ai `RetryPromptPart.from_validation_error` + json_repair | +60 | +3 | 缺陷修复 + 韧性 |
| R6-A3 | 确定性字段类型推断（field_types.py + introspect JSON 充实） | kordoc `inferFieldType` + deferred S1 重构（确定性版） | +65（+25 条件性） | +4~5 | 增量能力（opt-in 面） |
| **合计** | | | **+170（≤+195 含条件性）** | **+10~11（88→98/99）** | |

### R6-A1 实现指引（给 Optimizer）

**目标文件与行号级改动点：**

1. `scripts/model_adapter.py` — `reflect()`（L229-291）：
   - 签名加可选参数：`def reflect(self, field_label: str, field_value: Any, ctx: dict, prior_reflections: Optional[list] = None) -> str`。
   - 在 `base_prompt`（L241-247）构建后、进入 attempts 循环前：若 `prior_reflections` 非空，追加反馈块（仅取最后 3 条）：
     ```python
     if prior_reflections:
         prior_block = "\n".join(f"- {r}" for r in prior_reflections[-3:])
         base_prompt += (
             f"\n\n之前轮次的反思记录:\n{prior_block}\n"
             "请在上述反思基础上重新审计该字段。"
         )
     ```
   - **硬约束**：`prior_reflections` 为 None/空列表时，prompt 必须与 v6.3 逐字节相同（不追加任何块）。
   - 同步更新 docstring（L230-239）说明新参数与多轮语义。
2. `scripts/fill_docx.py` — 反思循环（L866-881）与默认 reflect_fn（L793-795）：
   - 循环内维护 `prior_reflections: list = []`，每轮调用 `reflect_fn(text, filled_value, filled_so_far, prior_reflections)`，`r` 非空时 `prior_reflections.append(r)`。
   - 默认实现改为 4 参：`lambda lbl, val, ctx, prior=None: adapter.reflect(lbl, val, {"filled_so_far": ctx}, prior_reflections=prior)`。
   - `_reflect_impl`（测试注入点，L750）契约升级为接受可选第 4 参；**允许**同步修改 `tests/test_fill_docx.py` L453-454 的 `tracking_reflect(label, value, ctx)` 加 `prior_reflections=None`（一行、行为中性）——除此之外不得改动任何现有测试。
3. `SKILL.md` — Step 5.5（L439-453）**必须同步**（否则正是本轮要修的漂移类型）：
   - 「反思结果处理」表 L444 行：把"重新调用 Step 5 用反思作为额外上下文重生成一次（仅 1 次重试）"改写为实现后的真实语义——多轮反思时后续轮次的反思 prompt 携带之前轮次的反思原文（v6.4），并明确"重生成"未实现（标注为 future work 或删除该承诺，二选一，但文档与代码必须 1:1）。
   - L449「CLI 控制」：补充 `--reflexion-rounds N≥2` 的反馈语义一句话。

**验收门（机械验证）：**

- [ ] `tests/test_reflexion.py::test_round2_prompt_contains_round1_reflection` — `reflexion_rounds=2` + 记录型 reflect 替身；第 2 次调用的 prompt 包含第 1 次反思原文。
- [ ] `tests/test_reflexion.py::test_single_round_prompt_identical_to_v6_3` — `rounds=1` 时 prompt 与 v6.3 基线逐字节相同（无"之前轮次的反思记录"块）。
- [ ] `tests/test_reflexion.py::test_prior_reflections_empty_no_block` — `adapter.reflect(..., prior_reflections=[])` 与 `prior_reflections=None` 产出 prompt 相同。
- [ ] `tests/test_reflexion.py::test_rounds_zero_no_reflect_calls` — 默认 `reflexion_rounds=0` 时 reflect 零调用（默认行为不变）。
- [ ] SKILL.md Step 5.5 与代码行为人工 cross-check：Optimizer 在 `03_optimizer.md` 贴出改后 L439-453 文本与对应代码行的对照。

### R6-A2 实现指引（给 Optimizer）

**目标文件与行号级改动点：**

1. `scripts/model_adapter.py` — 新增模块级辅助 `_format_validation_feedback(exc) -> str`（pydantic-ai `RetryPromptPart.from_validation_error` 风格）：
   - `pydantic.ValidationError`（含 pydantic_core）→ `json.dumps(exc.errors(), ensure_ascii=False, indent=2)` 只留 loc/msg/type，包成 `"{n} validation error(s):\n```json\n...\n```\n\nFix the errors and try again."`；
   - 其他异常 → `str(exc)` + 同一指令式收尾。
   - 不引入 pydantic-ai 依赖（只借格式）。
2. `generate_struct()`（L180-227）：
   - instructor 分支（L190-205）：`except` 内若还有剩余 attempt，`prompt = f"{prompt}\n\n{_format_validation_feedback(exc)}"` 后再 `continue`；messages 在循环内按当前 prompt 重建。
   - plain 分支（L206-221）：同样在 `except` 追加反馈；另外把 L215 的 `schema.model_validate_json(raw)` 包一层：先严格 `model_validate_json`，失败且 `self._json_repair` 可用时走 `json_repair.loads(raw)` → `schema.model_validate(obj)`；`self._json_repair` 为 None 时原样 raise（v6.3 行为）。
   - **硬约束**：首次尝试（未发生任何失败时）发送的 prompt 与 v6.3 逐字节相同。
3. `scripts/model_adapter.py` L170-178 附近：仿 instructor 增加 `try: import json_repair; self._json_repair = json_repair except ImportError: self._json_repair = None`。
4. `requirements.txt`：在 Optional 区（instructor 行后）加 `json-repair` 一行并注释"optional; 缺失时 generate_struct 行为同 v6.3"。**不得**进 Core 区。Optimizer 需实际 `pip install json-repair` 使测试覆盖到修复路径。
5. 环境无网络时测试不受影响（json_repair 为纯 Python 本地库）。

**验收门（机械验证）：**

- [ ] `tests/test_adapter_feedback.py::test_retry_prompt_contains_validation_errors` — patch `create` 先返回违反 schema 的 JSON、再返回合法 JSON；断言第 2 次调用的 messages 含 `validation error` 与 `Fix the errors and try again.`，且最终返回合法 schema 实例。
- [ ] `tests/test_adapter_feedback.py::test_json_repair_fallback` — canned `'{"姓名": "张三",}'`（尾逗号）与 ```json 围栏变体，`generate_struct` 均返回合法实例。
- [ ] `tests/test_adapter_feedback.py::test_no_json_repair_matches_v6_3` — monkeypatch `adapter._json_repair = None`，坏 JSON 下行为与 v6.3 一致（重试耗尽 → None + stderr exhausted 警告）。
- [ ] `python -m pytest tests/ -q` 全绿（88 旧 + 新）；`python scripts/model_adapter.py` self-test 仍输出合法 JSON（stub/mock）。
- [ ] `grep json-repair requirements.txt` 位于 Optional 区；`pip uninstall` 模拟缺失时旧测试不回归（由上门第 3 条覆盖）。

### R6-A3 实现指引（给 Optimizer）

**目标文件与行号级改动点：**

1. 新文件 `scripts/field_types.py`（~90 LOC，纯标准库）：
   - `infer_field_type(label: str, value: str) -> str`：值模式优先（date `^\d{4}\s*[-./年]\s*\d{1,2}...`、phone `^0?\d{3}[-.\s]?\d{4}...`、email、amount `^\d{1,3}(,\d{3})+$` 或带单位数量、checkbox `□☑✓`）、标签关键词回退（中文表：`出生|日期|年月` → date，`手机|电话|联系` → phone，`邮箱|邮件` → email，`金额|数量|合计` → amount），默认 text。裸数字不让位 amount（邮编/编号歧义，抄 kordoc 的注释级细节）。
   - `is_required_label(label)`：`[*※★]|（\s*必填\s*）|\(\s*必填\s*\)`。
   - `is_empty_value(value)`：空串或 `^[\s_()（）\-—–~.·,]*$` 占位符。
2. `scripts/fill_docx.py:scan_docx_introspect()`（L128-177）：cell dict（L148-152）新增 `"type"` / `"required"` / `"empty"` 三键（additive；`merged_dup` 分支 L144 同步补三键保持 schema 一致）。现有键 text/is_label/merged_dup 不动。
3. `scripts/fill_docx.py:_is_likely_label()`（L214-232）— **条件性 hunk**：增加两条排除——数值/单位值（"6个月""1万元"类）与说明语句结尾（"……请依次填写""……如下"类）。**门槛：88 条现有测试全绿；任一失败即整体回退本 hunk，A3 其余部分照常交付。**
4. **不做**：audit 表加列、`render_audit_table()` 改动、`templates/audit_table.md` 改动（见 §2 理由）。

**验收门（机械验证）：**

- [ ] `tests/test_field_types.py::test_infer_field_type_table` — 值模式与标签回退两段式各 ≥3 例（date/phone/email/amount/text/checkbox）。
- [ ] `tests/test_field_types.py::test_required_and_empty_detection` — ※/必填/占位符判定。
- [ ] `tests/test_field_types.py::test_introspect_json_has_type_required_empty` — `scan_docx_introspect()` 输出每个非 merged cell 含三新键，且 `merged_dup` 分支键集合一致。
- [ ] `tests/test_field_types.py::test_is_likely_label_hardening`（条件性）— "6个月" / "1万元" / "请依次填写获奖情况" → False；"姓名" → True（回归锚）。
- [ ] `python -m pytest tests/ -q` 全绿；`--introspect-out` CLI 端到端产出含新键的 JSON。

---

## 4. DEFER / REJECT 清单

| 项 | 裁定 | 理由 | 去向 |
|---|---|---|---|
| ReflexionStrategy 四值枚举 + `--reflexion-strategy` flag（R6-A1 子项） | **REJECT（R6）** | 无用户请求；R5 已以同一理由 defer；新增 CLI + 文档面，零可测量收益 | R7 候选：仅在出现 `--reflexion-rounds > 2` 真实使用数据后重议 |
| `audit_reflections.jsonl` 持久化（R6-A1 子项 / R2 残留） | **REJECT（R6）** | 只写不读（Anti-pattern F）；反思文本含字段值，绕过 `_redact` 脱敏链路，Privacy&UX 净负 | R7 候选：必须与"检索/展示读者"成对设计，且先接脱敏 |
| audit 表「类型/必填」列（R6-A3 子项） | **REJECT（R6）** | 改变所有用户 audit.md 默认输出；`parse_audit_md` 按下标解析有破坏 harness 风险 | R7：与 unmatched 反馈作为"audit 输出增强"整体设计 |
| R6-A4 `findMatchingKey` 0.6/0.75 前缀匹配 | **DEFER → R7** | 现有 substring 回退已覆盖大部分场景（F8，Researcher 夸大差距）；改默认匹配语义回归面大 | R7，需具体未匹配案例驱动 |
| R6-A4 `resolveUnmatched` audit 反馈 | **DEFER → R7** | 改变默认 audit 输出；与 ❓/❌ 状态计数语义（rule_miss_count）有交互 | R7，做成 opt-in `--show-unmatched` |
| R6-A5 ValueCursor 多条目消耗 | **DEFER → R7** | 新能力非缺陷；无当前用户诉求 | R7 |
| R6-A6 fillInCellPatterns 内联占位 | **DEFER → R7** | 新能力非缺陷；误替换风险；应在 A5 之后设计 | R7 |
| S2 LlamaParse / docling | **维持 defer** | docling 重依赖（torch 生态）与隐私优先原则的权衡未变；source-doc 解析非当前瓶颈 | 记录为 S2 未来本地方案 |
| S3 LanceDB audit | **维持 defer** | audit.md 覆盖 1-2 张/学期用量；pyarrow 过重 | 出现第 3 个跨表对比诉求再议 |
| pydantic-ai / marvin / docling 依赖化 | **永久拒绝** | 依赖哲学（stdlib + pydantic + python-docx + pyyaml）不可摧毁；只借模式不引库 | Never |
| promptfoo / deepeval 替换 score_consistency | **永久拒绝（R6）** | Node 工具链 / LLM-provider 依赖；现有 9 规则 harness 已闭环 | R7+ 可参考 pydantic_evals 形状做轻量重构（规则 >15 条时） |
| microsoft/table-transformer | **永久拒绝** | 停更两年 + torch 重量级；DOCX 原生表格场景杀鸡用牛刀 | Never |

---

## 5. 评分预测与诚实声明

**预期 Δ：+1.0 ~ +2.0（中位 +1.5）。明确低于 `min_quality_delta=3`。**

依据（对照 R5 主判的 5 维 ledger：Skill spec completeness / Code quality / Robustness / Evaluation / Privacy&UX）：

| 维度 | v6.3 | R6 预期 | 依据 |
|---|---:|---:|---|
| Skill spec completeness | 90 | +1 | Step 5.5 文档与代码对齐（漂移修复）；无新增承诺面 |
| Code quality of fill_docx.py | 89 | +0.5~1 | 反思循环缺陷修复；改动集中且小 |
| Robustness to edge cases | 82 | +1~1.5 | generate_struct 从盲重试到带反馈重试 + json_repair 兜底（step-5-preview 就位后直接受益） |
| Evaluation / testability | 97 | +1 | 新模块 field_types.py + 3 个新测试文件 + introspect 新键；88 → ~98 passed |
| Privacy & UX | 90 | 0 | 本轮无 PII/UX 面改动（JSONL 被砍正因它是该维度的净负） |
| **加权合计** | **96.0** | **≈ +1.5** | |

诚实声明：

1. **本轮不可能 +3。** 96.0 已接近天花板；剩余可做项中缺陷修复只有两个（均已纳入），其余全部是新能力（按 ratchet 排在缺陷之后）或装饰（枚举/JSONL）。R5 的 +2.0 已是同类 scope 的现实上限。
2. **plateau 判定预告**：R5 Δ=+2.0（<3）+ R6 Δ≈+1.5（<3）= 连续两轮低于 `min_quality_delta`，满足 `plateau_rounds=2`。若 R6 实测 Δ < 3，主 Agent 应判 **TERMINATE_PLATEAU**（R6 的缺陷修复仍然值得交付——ratchet 的"零收益不做"针对的是零收益工作，不是拒绝次阈值轮次；R5 本身即以 +2.0 交付）。
3. **`score_consistency.py --demo` 的说明（重要）**：该 harness 的 9 条规则跑内置合成数据恒返回 score=100（R5 主判证据），它**无法**感知 A1/A2/A3 的改进；A1/A2/A3 的可测量性来自 (a) 新增测试数与缺陷修复（ratchet 允许的计入项）与 (b) 主 Agent 的 5 维 ledger 重新打分。5 维 ledger 不在 `score_consistency.py` 内，而在 `agent_state/round_5/05_main_judgment.md` 的 "Round 5 score ledger"——本轮 tester/主判应沿用同一张表。
4. **测试数目标**：88 → 98~99 passed（+10~11），4 skipped 不变；无新增必需依赖；无网络依赖。

---

## 6. 给 Optimizer 的实现顺序

**顺序：R6-A2 → R6-A1 → R6-A3。**

1. **先 R6-A2（model_adapter.py 独占）**：唯一完全落在单文件、且零默认行为争议的缺陷修复；`_format_validation_feedback` 的"错误回喂"格式随后被 A1 的反思块沿用（同一份"结构化反馈"风格），先立格式后复用。json_repair 的 pip 安装与 requirements.txt Optional 行也在这一步落。
2. **再 R6-A1（model_adapter.py + fill_docx.py + SKILL.md）**：与 A2 同改 `model_adapter.py`，review 上下文最近；随后动 `fill_docx.py` 反思循环并立即同步 SKILL.md Step 5.5（文档同步必须与代码同一 PR，防止再次漂移）。`_reflect_impl` 4 参契约升级 + 唯一一行既有测试签名修改放在这一步。
3. **最后 R6-A3（新模块 + introspect + 条件性 hardening）**：新文件零冲突；hardening hunk 放在最后，以便在 A1/A2 都已合入、测试基线扩大后单独验证其"88 旧测试全绿"门槛——不过关就地回退该 hunk，不影响已交付部分。

每步独立可回退；三步共用验收门：`python -m pytest tests/ -q` 全绿、`python scripts/model_adapter.py` self-test 合法、`python evaluation/score_consistency.py --demo` ≥ 96.0（无回归）、全部新测试离线可跑。

---

## 7. 给主 Agent 的摘要（供塞进 Optimizer prompt 后的决策参考）

- **R6 最终 scope：R6-A1（反思反馈闭环 + SKILL.md 同步，收窄版）+ R6-A2（结构化错误回喂 + json_repair 可选层）+ R6-A3（field_types.py + introspect 充实，hardening 条件性）。** 砍掉枚举与 JSONL，DEFER A4/A5/A6。
- **诚实预期 Δ = +1.0 ~ +2.0（中位 +1.5）< min_quality_delta=3**；与 R5 的 +2.0 合计构成连续两个 plateau 轮，主 Agent 应按 `plateau_rounds=2` 判 TERMINATE_PLATEAU。缺陷修复本身值得交付。
- **硬约束已写入每项验收门**：默认行为零变化（rounds=0/1 与首次尝试成功的 prompt 逐字节不变）、json_repair 仅 Optional、audit.md 渲染不动、SKILL.md 与代码同 PR 对齐。

---

**End of round-6 Reviewer output.**
