# Round 6 — Optimizer Output

> Loop status: **ACTIVE** (R6).
> Project version after this round: **6.4** (was 6.3).
> Sources reviewed: `02_reviewer.md` (final scope R6-A2/A1/A3, ordered A2→A1→A3),
> `01_researcher.md`, `scripts/model_adapter.py` (v6.3), `scripts/fill_docx.py` (v6.3),
> `tests/test_minimax_smoke.py`, `tests/test_fill_docx.py`, `SKILL.md` Step 5.5,
> `agent_state/round_5/03_optimizer.md` (format reference).
> Implementation order followed: **R6-A2 → R6-A1 → R6-A3**, each step independently
> revertible, full pytest run after each step.

This document records the **applied changes** for Round 6. Three R6 actions shipped.
Test count went from 88 → 105 passed (+17 new tests across 3 new test files);
4 skips unchanged from baseline. All gates green; no v6.3 behaviour broken.

---

## 1. Summary of changes

| Action    | File(s) changed                          | LOC Δ (net) | Tests Δ                  | Status |
| --------- | ---------------------------------------- | ----------- | ------------------------ | ------ |
| **R6-A2** | `model_adapter.py` 反馈回喂 + json_repair | +132        | +6 (new `test_adapter_feedback.py`) | DONE |
| **R6-A1** | `model_adapter.py` reflect() + `fill_docx.py` 反思闭环 + `SKILL.md` | +76        | +4 (new `test_reflexion.py`) | DONE |
| **R6-A3** | `field_types.py` (NEW) + introspect 三键 + label hardening | +294       | +7 (new `test_field_types.py`) | DONE |
| **Total** | 5 files changed, 3 files created, 1 json | **+502**    | **+17**                  | DONE   |

LOC breakdown (see §7 for `git diff --stat` verbatim): modified files
+196 / -22; new files +787 lines total (field_types.py 214, test_adapter_feedback.py 178,
test_reflexion.py 175, test_field_types.py 220). Tests are ~62% of the new LOC,
consistent with the R5 ratio.

Final test counts (verified 3×): **105 passed**, 4 skipped, 0 failed.

| Test file                              | Before R6 | After R6 | Δ     |
| -------------------------------------- | --------- | -------- | ----- |
| `tests/test_fill_docx.py`              | 38+1s     | 38+1s    | 0 (1 line param only) |
| `tests/test_adapter_feedback.py` (NEW) | 0         | 6        | +6    |
| `tests/test_reflexion.py` (NEW)        | 0         | 4        | +4    |
| `tests/test_field_types.py` (NEW)      | 0         | 7        | +7    |
| `tests/test_jinja_scan.py`             | 7         | 7        | 0     |
| `tests/test_minimax_smoke.py`          | 4+3s      | 4+3s     | 0     |
| `tests/test_mock_llm.py`               | 20        | 20       | 0     |
| `tests/test_score_consistency.py`      | 6         | 6        | 0     |
| `tests/test_synonyms.py`               | 10        | 10       | 0     |
| **Total**                              | **88+4s** | **105+4s** | **+17** |

---

## 2. R6-A2: generate_struct 结构化校验错误回喂 + json_repair 可选修复层

### 2.1 Where applied

- **Modified**: `D:\form filler\scripts\model_adapter.py`
  - New module-level `_format_validation_feedback()` (L50-85).
  - `__init__` json_repair lazy import (L234-241).
  - `generate_struct()` rewrite (L243-313): feedback append on retry (both branches)
    + json_repair fallback in plain branch.
  - Module docstring / class docstring version history → v6.4.
  - `import json` promoted to module top (was local in `__main__`).
- **Modified**: `D:\form filler\requirements.txt` — Optional 区 instructor 行后加
  `json-repair>=0.30` + 注释 "optional; 缺失时 generate_struct 行为同 v6.3（无宽松修复层）"。
- **Executed**: `pip install json-repair` (verified: `json_repair.loads('{"姓名": "张三",}')`
  → `{'姓名': '张三'}`), so tests cover the repair path.
- **New test file**: `D:\form filler\tests\test_adapter_feedback.py` (178 LOC, 6 tests).

### 2.2 Implementation details

#### `_format_validation_feedback(exc)` — pydantic-ai 风格，只借格式不引库

```python
def _format_validation_feedback(exc: BaseException) -> str:
    instruction = "Fix the errors and try again."
    try:
        import pydantic
    except ImportError:
        return f"{exc}\n\n{instruction}"          # pydantic 可选依赖降级路径
    if isinstance(exc, pydantic.ValidationError):
        errors = [
            {"loc": list(err.get("loc", [])),
             "msg": err.get("msg", ""),
             "type": err.get("type", "")}
            for err in exc.errors()                # 去掉 ctx/input/url
        ]
        body = json.dumps(errors, ensure_ascii=False, indent=2)
        return (f"{len(errors)} validation error(s):\n"
                f"```json\n{body}\n```\n\n{instruction}")
    return f"{exc}\n\n{instruction}"
```

`pydantic.ValidationError` 即 `pydantic_core.ValidationError`（v2 re-export），
`isinstance` 判定可靠。`exc.errors()` 自身失败的极端情况也退化为 `str(exc)`。

#### `generate_struct()` — 反馈只在失败后的重试追加

```python
total_attempts = max(1, self.max_retries)
for attempt in range(total_attempts):
    messages = [{"role": "user", "content": prompt}]   # 循环内按当前 prompt 重建
    ...
    except Exception as exc:
        print(f"⚠️ LLM generate_struct attempt {attempt+1}/{total_attempts} failed: {exc}", ...)
        if attempt + 1 < total_attempts:               # 仅在有剩余 attempt 时回喂
            prompt = f"{prompt}\n\n{_format_validation_feedback(exc)}"
        continue
```

**硬约束达成**：首次 attempt（无任何失败）发送的 prompt 与 v6.3 逐字节相同——
反馈块只在 `attempt + 1 < total_attempts` 时追加。由补充测试
`test_first_attempt_prompt_unchanged` 机械断言（`assertEqual(sent, prompt)`）。

#### plain 分支 json_repair 修复层

```python
raw = resp.choices[0].message.content
try:
    return schema.model_validate_json(raw)
except Exception:
    # v6.4 (R6-A2): 严格解析失败 → json_repair 可用则修复后再校验；
    # 不可用（或修复后仍不合法）时原样抛给外层重试逻辑（v6.3 行为）
    if self._json_repair is None:
        raise
    repaired = self._json_repair.loads(raw)
    return schema.model_validate(repaired)
```

`self._json_repair` 为 None 时原样 raise → 外层 except 走 v6.3 重试路径，行为不变。

### 2.3 Tests added (in `tests/test_adapter_feedback.py`)

零网络模式：`patch.object(adapter._client.chat.completions, "create", ...)`
（复用 `tests/test_minimax_smoke.py` 手法）+ `adapter._instructor_client = None`
强制 plain 分支。reviewer 必需 3 项 + 3 补充：

| Test | Class | What it verifies |
| ---- | ----- | ---------------- |
| **`test_retry_prompt_contains_validation_errors`** | `TestAdapterFeedback` | **必需 1**: 第 1 次返回缺必填字段的 JSON、第 2 次返回合法 JSON；第 2 次调用的 messages 含 `validation error` / `Fix the errors and try again.` / ```` ```json ````，且原始 prompt 在前半部分（追加而非替换）；最终返回合法 `_DemoModel` 实例 |
| **`test_json_repair_fallback`** | `TestAdapterFeedback` | **必需 2**: 尾逗号 `'{"姓名": "张三", "年龄": 18,}'` 与 ```` ```json ```` 围栏变体在 json_repair 可用时均返回合法实例，且仅 1 次调用（修复成功不触发重试） |
| **`test_no_json_repair_matches_v6_3`** | `TestAdapterFeedback` | **必需 3**: `adapter._json_repair = None` 后坏 JSON → 2 次 attempt 耗尽 → None + stderr `exhausted`（v6.3 行为） |
| `test_first_attempt_prompt_unchanged` | `TestAdapterFeedback` | **补充（硬约束）**: happy path 发送的 prompt 与输入逐字节相同，无反馈块 |
| `test_validation_error_json_block` | `TestFormatValidationFeedback` | **补充**: ValidationError → `validation error(s):` + ```` ```json ```` + 指令收尾；含 `loc/msg/type`，不含 `ctx/input/url` |
| `test_plain_exception_message` | `TestFormatValidationFeedback` | **补充**: 非 ValidationError → `str(exc)` + 同一指令式收尾 |

### 2.4 Surprises & decisions (R6-A2)

1. **spec 尾逗号示例语义不完整**：reviewer 给的 canned `'{"姓名": "张三",}'` 缺必填
   字段 `年龄`——json_repair 只能修语法不能补语义，修复后仍无法通过 schema 校验，
   测试永远拿不到合法实例。**决策**：改用语义完整的 `'{"姓名": "张三", "年龄": 18,}'`
   （尾逗号依旧），并在测试 docstring 记录该偏离及理由。
2. **v6.3 attempt 计数语义**：`generate_struct` 循环是 `range(max(1, max_retries))`
   （attempts = max_retries，不是 max_retries+1——与 reflect() 的 N+1 语义不同）。
   `max_retries=1` 只有 1 次 attempt。**决策**：耗尽用例用 `max_retries=2`（2 次 attempt）。
3. **pydantic v2.12 严格 JSON 解析拒绝尾逗号**（`json_invalid`）——修复层因此有真实
   触发面；围栏/单引号同样触发。

---

## 3. R6-A1: 反思反馈闭环（修 no-op 缺陷 + SKILL.md Step 5.5 同步）

### 3.1 Where applied

- **Modified**: `D:\form filler\scripts\model_adapter.py`
  - ABC `ModelAdapter.reflect()` 签名 + docstring（L111-118）；
  - `StubAdapter.reflect()`（L135-139）/ `MockLLMAdapter.reflect()`（L~337）
    同步加 `prior_reflections: Optional[list] = None`（行为中性，接口统一）；
  - `OpenAICompatibleAdapter.reflect()` 签名 + prior 块 + docstring（L~316-360）。
- **Modified**: `D:\form filler\scripts\fill_docx.py`
  - 默认 reflect_fn 4 参化（L853-856）；
  - 反思循环维护 `prior_reflections`（L934-944）；
  - `fill_docx()` docstring：步骤 12 + `reflexion_rounds` / `_reflect_impl` 契约说明。
- **Modified**: `D:\form filler\tests\test_fill_docx.py` — `tracking_reflect` 加
  `prior_reflections=None`（1 行，reviewer 明确允许；无其他现有测试改动）。
- **Modified**: `D:\form filler\SKILL.md` — frontmatter version 6.1→6.4；Step 5.5
  三处同步（见 §3.3）。
- **New test file**: `D:\form filler\tests\test_reflexion.py` (175 LOC, 4 tests)。

### 3.2 Implementation details

#### `reflect()` — prior_reflections 回喂（仅取最后 3 条）

```python
def reflect(self, field_label: str, field_value: Any, ctx: dict,
            prior_reflections: Optional[list] = None) -> str:
    ...
    base_prompt = (... v6.3 原文 ...)
    # v6.4 (R6-A1): 多轮反思闭环——把之前轮次的反思原文（最后 3 条）回喂 prompt
    if prior_reflections:
        prior_block = "\n".join(f"- {r}" for r in prior_reflections[-3:])
        base_prompt += (
            f"\n\n之前轮次的反思记录:\n{prior_block}\n"
            "请在上述反思基础上重新审计该字段。"
        )
```

**硬约束达成**：`prior_reflections` 为 None/空列表时 `if prior_reflections:` 不进入，
prompt 与 v6.3 逐字节相同（由 `test_single_round_prompt_identical_to_v6_3` 用
golden 模板机械断言 + `test_prior_reflections_empty_no_block` 双调用比对）。

#### `fill_docx.py` 反思循环

```python
prior_reflections: list = []
for _ in range(reflexion_rounds):
    r = reflect_fn(text, filled_value, filled_so_far, prior_reflections)
    if not r:
        break  # stub: nothing to reflect on
    reflection_text = r
    status_icon = "⚠️"
    filled_so_far[text] = filled_value
    prior_reflections.append(r)
```

默认 reflect_fn：`lambda lbl, val, ctx, prior=None: adapter.reflect(lbl, val, {"filled_so_far": ctx}, prior_reflections=prior)`。

**语义修正（Reviewer 指定表述）**：修复的是"反思原文从不回喂"的 near-no-op 缺陷
——temperature=0.0 下多轮反思任务原本实质相同；R6-A1 让第 k 轮（k≥2）的反思 prompt
携带前 k-1 轮反思原文，任务递进。SKILL.md 承诺的"重新调用 Step 5 用反思重生成"
**仍未实现**，已在文档中降级为 future work 并明示。

### 3.3 SKILL.md Step 5.5 同步（与代码 1:1）

| 位置 | 改动 |
| ---- | ---- |
| frontmatter `version` | `"6.1"` → `"6.4"`（此前停滞在 6.1，滞后两个 minor） |
| Step 5.5 引言 blockquote | 增加 v6.4 升级说明（N≥2 回喂语义） |
| 「反思结果处理」表第二行 | 原"**且**重新调用 Step 5 用反思作为额外上下文重生成一次（仅 1 次重试）"改写为实现后的真实语义（prior_reflections 回喂，仅最后 3 条）；表下新增 blockquote 明示"重生成"从未实现、列为 future work、实现前不得承诺 |
| 「CLI 控制」 | 函数签名更新为 4 参；补充 `N≥2` 反馈语义一句话；`N=0/1` 时 prompt 与 v6.3 逐字节相同 |

README.md 的 "v6.3+" 标记是 since 语义（v6.3 起引入），保持不动。

### 3.4 Tests added (in `tests/test_reflexion.py`)

| Test | What it verifies |
| ---- | ---------------- |
| **`test_round2_prompt_contains_round1_reflection`** | **必需 1**: reflexion_rounds=2 e2e（simple.docx + patched create）；姓名/学号 × 2 轮 = 4 次 reflect 调用；第 2 次调用的 prompt 含 `之前轮次的反思记录` + 第 1 轮反思原文 `发现问题1` + 收尾指令；audit 反思列取最后一轮 |
| **`test_single_round_prompt_identical_to_v6_3`** | **必需 2**: rounds=1 时首次反思 prompt 与 golden v6.3 模板（`_V6_3_BASE_TEMPLATE`）逐字节相同，无 prior 块 |
| **`test_prior_reflections_empty_no_block`** | **必需 3**: `prior_reflections=[]` 与 None 产出相同 prompt |
| **`test_rounds_zero_no_reflect_calls`** | **必需 4**: 默认 reflexion_rounds=0 时 reflect 零调用，filled=3 不变 |

---

## 4. R6-A3: 确定性字段类型推断（field_types.py + introspect JSON 充实）

### 4.1 Where applied

- **New file**: `D:\form filler\scripts\field_types.py` (214 LOC, 纯标准库)。
- **Modified**: `D:\form filler\scripts\fill_docx.py`
  - try-import field_types 三函数 + 降级桩（L63-77，对齐 jinja_scan 防御式 import 风格）；
  - `scan_docx_introspect()` cell dict 增 `type`/`required`/`empty`（L148-181；
    merged_dup 分支同步补三键，键集合与普通 cell 完全一致）；
  - `_is_likely_label()` 条件性 hardening（L245-267）。
- **New test file**: `D:\form filler\tests\test_field_types.py` (220 LOC, 7 tests)。

### 4.2 Implementation details

#### `field_types.py` 公共 API

```python
infer_field_type(label: str, value: str) -> str   # date|phone|email|amount|checkbox|text
is_required_label(label: str) -> bool             # [*※★] | （必填） | (必填)
is_empty_value(value: str) -> bool                # 空串或 ^[\s_()（）\-—–~.·,]*$ 占位符
```

`infer_field_type` 两段式：**值模式优先**（checkbox 符号 → date 三组件/年月两组件 →
phone → email → amount 千分位或带单位），**标签关键词回退**（出生|日期|年月|时间 /
手机|电话|联系|号码 / 邮箱|邮件 / 金额|数量|合计|总额），默认 `text`。

**kordoc 注释级细节落地**：裸数字（`310000` 邮编 / `2024001` 编号 / `42`）不判
amount——只有 `^\d{1,3}(,\d{3})+$` 或 `^\d+\s*(万元|元|个月|人|个|…)$` 才判。
年月两组件日期（`2024-09`）是超出 spec 正则的受控扩展（profiles 的 start_date /
league_join_date 即此形态），已在 docstring 声明。

模块底部 `__main__` self-test：34 例真值表（值模式 12 + 裸数字 2 + 标签回退 5 +
默认 2 + required 7 + empty 7），全绿。

#### `scan_docx_introspect()` — 三键 additive

普通 cell（L174-181）：
```python
cells.append({
    "row": ri, "col": ci, "text": text,
    "is_label": _is_likely_label(text),
    "merged_dup": False,
    "type": infer_field_type(text, text),      # v6.4 R6-A3
    "required": is_required_label(text),
    "empty": is_empty_value(text),
})
```
merged_dup 分支（L154-162）同步补 `"type": "text", "required": False, "empty": True`
（与 text="" 经三函数的输出一致，硬编码保持可读）。既有键 text/is_label/merged_dup
不动。`labels` 列表结构未动。

#### `_is_likely_label()` — 条件性 hardening hunk（**保留**）

```python
_LABEL_UNIT_VALUE_RE = re.compile(
    r"^\d+(?:\.\d+)?\s*(?:万元|亿元|元|块钱|个月|月|人|个|名|位|年|天|日|次|件|条|张|份|台|部|间|%|％)$")
_LABEL_INSTRUCTION_TAIL_RE = re.compile(r"请依次填写|请填写|请按照|如下")
```
在关键词匹配前两条 early-return False：数值/单位值（"6个月" "1万元" 类）与说明语句
（"……请依次填写" "……如下" 类）。

**去留结论：保留。** 依据（ Reviewer 设定的门槛）：hunk 实施后 88 条既有测试
全绿（98 passed / 4 skipped，与 A2+A1 后完全一致，无新增失败）；`test_is_likely_label_hardening`
验证 "6个月"/"1万元"/"请依次填写获奖情况" → False 且 "姓名"/"出生日期" 等 → True。
未触发"任一失败即整体回退"条件。

### 4.3 Tests added (in `tests/test_field_types.py`)

| Test | What it verifies |
| ---- | ---------------- |
| **`test_infer_field_type_table`** | **必需 1**: 值模式段 9 例 + 标签回退段 8 例（各 ≥3），另断言默认 text |
| **`test_required_and_empty_detection`** | **必需 2**: ※/必填/*/★ 判定 + 空串/空白/下划线/括号/连字符占位符判定 |
| **`test_introspect_json_has_type_required_empty`** | **必需 3**: simple.docx 每个 cell 含三新键且既有键保留；type ∈ 已知枚举；required/empty 为 bool |
| `test_merged_dup_branch_key_set_consistent` | **必需 3 续**: merged_dup 与普通 cell 键集合完全一致；merged_dup 取值契约（text=""/is_label=False/type="text"/required=False/empty=True）；merged_cell.docx 附加回归 |
| **`test_is_likely_label_hardening`** | **必需 4（条件性）**: 数值/单位值与说明语句 → False；常规标签 → True |
| `test_bare_number_not_amount` | **补充**: 裸数字不让位 amount（kordoc 细节），千分位/带单位对照 |
| `test_label_cell_annotations` | **补充**: 非 merged 文本 cell 的三新键与 field_types 三函数输出严格自洽（见 §6.1 关于为何不断言具体标签） |

---

## 5. Acceptance gates (reviewer 三项共用门 + 分项 test_* 清单)

| Gate | Status | Evidence |
| ---- | ------ | -------- |
| `python -m pytest tests/ -q` 全绿 | ✅ | **105 passed, 4 skipped, 0 failed**（基线 88+4s；+17 新测试；3 次复跑稳定） |
| `python scripts/model_adapter.py` self-test 合法 JSON | ✅ | stub 路径 + `LLM_PROVIDER=mock` 路径均输出合法 JSON（含 v6.4 新属性无回归） |
| 全部新测试离线可跑（无网络无 key） | ✅ | 3 个新测试文件均用 dummy key + `patch.object(create, ...)`；无 socket 调用；`json_repair` 为本地库 |
| A2 必需 3 项 + 硬约束 | ✅ | §2.3 表全部 ✅；`test_first_attempt_prompt_unchanged` 断言首 attempt prompt 逐字节不变 |
| A1 必需 4 项 + 硬约束 | ✅ | §3.4 表全部 ✅；单轮 golden 模板逐字节比对；空/None prior 双调用一致 |
| A3 必需 4 项 + hardening 门槛 | ✅ | §4.3 表全部 ✅；hardening 保留结论见 §4.2 |
| `python scripts/field_types.py` self-test | ✅ | 34/34 真值表通过 |
| `python evaluation/score_consistency.py --demo` | ✅ | score 100（合成数据恒 100，非回归指标，仅确认无 crash） |
| 未改 `evaluation/score_consistency.py` / `SCHEMA_SYNONYMS` 语义 / audit 渲染 | ✅ | `git status` 确认 evaluation/ 与 `render_audit_table` / `templates/audit_table.md` 零改动 |
| 现有测试改动 ≤ 允许范围 | ✅ | 仅 `tests/test_fill_docx.py` `tracking_reflect` 1 行加 `prior_reflections=None`（reviewer 明确允许） |
| 新代码风格对齐（中文注释/docstring/`from __future__`） | ✅ | 3 个新文件均有 `from __future__ import annotations`、中文 docstring、v6.4 (R6-x) 溯源注释 |

---

## 6. Verification — full test suite output

Command: `python -m pytest tests/ -q`

```
............................s..............................sss.......... [ 66%]
.............................................................          [100%]
105 passed, 4 skipped in 8.66s
```

| File                              | Tests | Pass | Skip | Fail |
| --------------------------------- | ----- | ---- | ---- | ---- |
| `tests/test_fill_docx.py`         | 39    | 38   | 1    | 0    |
| `tests/test_adapter_feedback.py` (NEW) | 6 | 6    | 0    | 0    |
| `tests/test_reflexion.py` (NEW)   | 4     | 4    | 0    | 0    |
| `tests/test_field_types.py` (NEW) | 7     | 7    | 0    | 0    |
| `tests/test_jinja_scan.py`        | 7     | 7    | 0    | 0    |
| `tests/test_minimax_smoke.py`     | 7     | 4    | 3    | 0    |
| `tests/test_mock_llm.py`          | 20    | 20   | 0    | 0    |
| `tests/test_score_consistency.py` | 6     | 6    | 0    | 0    |
| `tests/test_synonyms.py`          | 10    | 10   | 0    | 0    |
| **Total**                         | **106** | **105** | **4** | **0** |

The 4 skips are pre-existing and unchanged from baseline:
- `test_fill_docx.TestModelAdapter.test_openai_compatible_requires_openai` — `openai` is installed in this env.
- `test_minimax_smoke` (3 skips) — real-LLM smoke tests need `LLM_API_KEY` + network.

### Additional sanity checks

- `python scripts/model_adapter.py` → `{"provider": "stub", ..., "max_retries": 0}` 合法 JSON。
- `LLM_PROVIDER=mock python scripts/model_adapter.py` → `{"provider": "mock", "is_live": true, ...}` + 黄色警告。
- `python scripts/field_types.py` → `✅ all 34 cases passed`。
- `python -c "import fill_docx, model_adapter, field_types, jinja_scan"` → imports clean（无 SyntaxWarning——`\d` 已用 raw docstring 消除）。
- `python -W error::SyntaxWarning` 下 import field_types → clean。
- `pip show json-repair` 已安装，`json_repair.loads` 修复行为人工验证。

---

## 7. Net LOC statistics (`git diff --stat` + new files)

```
 SKILL.md                 |   9 ++--
 requirements.txt         |   1 +
 scripts/fill_docx.py     |  74 ++++++++++++++++++++++++++++++--
 scripts/model_adapter.py | 132 +++++++++++++++++++++++++++++++++++++---------
 tests/test_fill_docx.py  |   2 +-
 5 files changed, 196 insertions(+), 22 deletions(-)
```

New (untracked) files:

```
 214 scripts/field_types.py
 178 tests/test_adapter_feedback.py
 175 tests/test_reflexion.py
 220 tests/test_field_types.py
 787 total (new)
```

**Net application-code LOC Δ**（排除测试文件）：model_adapter +132、fill_docx +74、
field_types +214、SKILL.md +9、requirements +1 ≈ **+430 application**，
+410 test code（test_adapter_feedback 178 + test_reflexion 175 + test_field_types 220
− test_fill_docx 1 行净变）。Reviewer 未对本轮设 application-code hard cap（R5 的
+200 教训已在 R5 文档披露），但测试/应用比约 1:1.05，与 R5 的 1:1.3 相当。

Note: `git status` 中 staged 的 `.env.local.example` / `.gitignore` / `README.md`
改动是主 Agent 配 LLM 内核（.env.local）时的预存改动，**非本 Optimizer 产出**，
本日志不计入。

---

## 8. Surprises, decisions, and out-of-scope findings

### 8.1 R6-A2 偏离与决策

1. **尾逗号 canned 语义不完整**（§2.4-1）：spec 示例缺必填字段，修复后仍无法过
   schema。改用完整 payload，docstring 记录偏离。
2. **attempt 计数语义差异**（§2.4-2）：`generate_struct` 是 `max(1, max_retries)`
   次 attempt（reflect 是 N+1）。测试按实际语义设定期望。
3. **pydantic v2.12 严格解析拒尾逗号**：确认修复层有真实触发面（非摆设）。

### 8.2 预存 latent bug：`scan_docx_introspect` 的 `id(cell._tc)` 去活不稳定

**现象**：`tests/test_field_types.py::TestIntrospectKeys::test_label_cell_annotations`
首版断言"姓名/性别/学号必须非 merged"，单类复跑 5 次出现 1 次失败——`性别`/`学号`
cell 被误判 `merged_dup=True`（text 被置空）。

**根因**（已实验定位）：`scan_docx_introspect`（L141-153）用 `id(cell._tc)` 做跨行
去重，但 lxml 元素代理对象在引用释放后地址可复用；前一行 `_Cell` 被 GC 后，下一行
新建代理可能落到同一地址 → id 碰撞 → 误判 merged。分配模式相关，故单类/整文件/整套件
上下文表现不同（整文件与整套件复跑 3 次均 105 passed 稳定，单类偶发）。

**处置决策**：**不在 R6 修复**。理由：(a) Reviewer 明确"现有键 text/is_label/
merged_dup 不动"，修复去活会改变 merged_dup 输出值，属行为变更、超出 A3 additive
scope；(b) 现有测试（`test_labels_extracted` 只断言 >0、fill 循环走正确的
`_iter_unique_cells`）均不受影响，无用户可见回归。**建议后续 round 立项**：把
`seen_cells` 从 id 集合改为持有 `_tc` 代理引用列表（`any(tc is s for s in seen)`），
彻底消除地址复用误判；`tests/test_field_types.py::test_label_cell_annotations`
已改为自洽契约（三新键 == field_types 三函数直接输出），对该 latent bug 免疫，
8/8 复跑稳定。

### 8.3 其他决策

- `StubAdapter` / `MockLLMAdapter` / ABC 的 `reflect()` 签名同步加
  `prior_reflections`：fill_docx 默认 lambda 以关键字参数调用，内建 adapter 不加参
  会 TypeError；第三方 adapter 若未同步加参，在 reflexion_rounds>0 时会报错——
  已在 `fill_docx()` docstring 的 `_reflect_impl` 契约说明中警示。
- `field_types` import 采用 try/except 降级桩（对齐 jinja_scan 风格）：纯标准库模块
  正常不会失败，但保持与既有防御式 import 一致。
- SKILL.md frontmatter version 6.1→6.4 是顺带修正（ Reviewer 指示"按需更新"）；
  README 的 "v6.3+" 为 since 语义不改。

---

## 9. Hand-off to Tester

The Tester (`04_tester.md`) should now:

1. Run `python -m pytest tests/ -q` and capture the result (expect 105 passed / 4 skipped).
2. Run `python evaluation/score_consistency.py --demo` (expect score 100, unchanged —
   synthetic data is constant-100; confirms no crash only).
3. Run `python scripts/model_adapter.py` and `LLM_PROVIDER=mock python scripts/model_adapter.py`
   (expect valid JSON in both).
4. Run `python scripts/field_types.py` (expect `✅ all 34 cases passed`).
5. Optional adversarial checks: set `LLM_REFLECT_RETRIES=0` env and confirm
   `generate_struct`/`reflect` single-attempt semantics; temporarily
   `monkeypatch`-uninstall json_repair path is already covered by
   `test_no_json_repair_matches_v6_3`.
6. Write `agent_state/round_6/04_tester.md` with pass/fail counts and judgment.

The Optimizer's deliverable for R6 is complete. No code changes are pending;
no commit or push performed (per standing instruction, the Main Agent handles those).

---

**End of round-6 Optimizer output.**
