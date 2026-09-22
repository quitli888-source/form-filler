# Round 6 — Researcher Output

> Project: form-filler v6.3 (post-R5, score 96.0, 88 passed / 4 skipped, cumulative +38.55).
> Loop status: **R6 activated** by Main Agent (R5 TERMINATE_DONE overridden).
> 本轮背景变化：主 Agent 已将 **step-5-preview** 配置为项目 LLM 内核
> （`.env.local` + `LLM_BASE_URL=https://api.stepfun.com/v1`，端点可达、key 有效、
> 返回 402 quota_exceeded 而非 401，重试逻辑工作正常）——真实 LLM 路径从
> "smoke-test only" 变成 "随时可跑"，因此**所有涉及 LLM 自愈/反思的机制本轮
> 首次具备实测条件**。R5 deferred 的 4 项逐一复查，另调研 5 个 NEW 前沿项目
> （全部 2026-09-22 实测 star，全部 2026-09 仍在更新）。

---

## 1. Executive Summary — Top 5 patterns for Round 6

1. **pydantic-ai 的 `ModelRetry` + `RetryPromptPart.from_validation_error()` 结构化错误回喂。**
   pydantic-ai 在输出校验失败时不把原始异常字符串丢给模型，而是把
   `ValidationError.errors(include_url=False, include_context=False)` 序列化成
   JSON block 回喂：`"N validation errors:\n```json\n...```\n\nFix the errors and try again."`。
   这正好命中 form-filler 当前**两个已确认的真实缺陷**（见 §3.1）：`reflect()` 的
   多轮循环不把上一轮反思喂回 prompt（temperature=0.0 下第 2 轮与第 1 轮逐字节相同，
   `--reflexion-rounds 2` 实际是 no-op）；`generate_struct()` 的重试循环每次用**同一条
   prompt**重建 messages，错误只 print 到 stderr，从不进 prompt。~60 LOC 修复两处。
2. **kordoc `inferFieldType()` 的确定性字段类型推断（值模式优先、标签关键词回退）。**
   `type ∈ {text, date, phone, email, amount, checkbox, idnum}`，先用值正则判断
   （`^\d{4}\s*[-./년]\s*\d{1,2}...` → date），值不可判时用标签关键词表回退
   （`/생년월일|일시|날짜/` → date）；附带 `isRequiredLabel()`（※·*·★·"(필수)"）和
   `isEmptyValue()`（占位符 `^[\s_()（）\-—–~.·,]*$`）。这是 deferred 项 S1
   （smol-ai enum pre-scan）的**确定性替代版**——不调用 LLM、零新依赖，直接充实
   `--introspect-out` JSON 和 audit 表的「缺失/待填」判定。~100 LOC。
3. **kordoc `findMatchingKey()` 双向前缀匹配 + 0.6/0.75 长度比护栏。**
   精确匹配失败后做前缀匹配，但要求 `key.length >= cellLabel.length * 0.6`
   （正向）或 `cellLabel.length >= key.length * 0.75`（反向），取最长匹配。
   解决了 SCHEMA_SYNONYMS 的「申请人 / 申请人姓名」类变体——form-filler 现在的
   `SCHEMA_SYNONYMS.get(label, label)` 只支持精确键查找，差一个字就落到
   Pass 2 正则。~30 LOC，纯函数可单测。
4. **kordoc `resolveUnmatched()` 的未匹配输入显式反馈。**
   `fillFormFields()` 返回 `unmatched: string[]`——「输入里有、表单里没找到」的
   label 显式列出。form-filler 的 `match_field()` 返回 `unmatched` 后调用方直接
   `continue` 静默丢弃；audit.md 里看不到「你提供了 X 但这个表没有对应字段」。
   ~25 LOC，对 Step 4「缺失信息处理」的用户体验是实质改进。
5. **`json_repair` 作为 `generate_struct()` plain-fallback 的修复层。**
   `repair_json(raw, return_objects=True)` 先尝试严格 `json.loads`，失败才走
   修复解析器（补逗号/引号/截断值/剥离散文）；签名还带 `schema=` 与
   `schema_repair_mode: "standard"|"salvage"` 参数做 schema 引导修复。
   做成 try-import 可选依赖（缺省行为不变），~20 LOC 直接降低真实 LLM
   路径的 JSON 解析失败率——这是 R6 唯一天然适配「provider 无关适配层」的新库。

**R6 最高杠杆建议：R6-A1（反思反馈闭环，修真实缺陷）+ R6-A2（结构化校验错误
回喂 + json_repair）+ R6-A3（确定性类型推断 pre-scan）三件套。** 全部
no-new-mandatory-dependency、全部可离线回归，预计 +240 LOC / +12 tests。

---

## 2. Surveyed Projects（NEW — 本轮新调研）

> 所有 star 数均为 **2026-09-22** 实测。R1–R5 已调研项目（python-docx-template /
> instructor / outlines / guidance / reflexion / form_filling_app / smol-ai /
> LanceDB / python-docx）未重复调研，仅作对比引用。

### Project A: pydantic/pydantic-ai

- **URL:** https://github.com/pydantic/pydantic-ai
- **Stars:** 20,109（`gh api repos/pydantic/pydantic-ai --jq '.stargazers_count'`，2026-09-22；`pushed_at=2026-09-22T04:39:30Z`，当天仍在提交）
- **Language:** Python（MIT）
- **定位:** "How Python does AI. Agents... typed end to end." — Pydantic 官方 agent 框架，typed I/O 贯穿全程。repo 内还含 **`pydantic_evals`**（独立 PyPI 包 `pydantic-evals`）评估库。

**关键机制 1 — `ModelRetry` 异常（`pydantic_ai_slim/pydantic_ai/exceptions.py`）：**

```python
class ModelRetry(Exception):
    """Exception to raise to request a model retry.

    Can be raised from tool functions, output validators, and capability hooks
    (such as `after_model_request`, `after_tool_execute`, etc.) to send a
    retry prompt back to the model asking it to try again.
    """
    message: str
    """The message to return to the model."""
```

设计要点：**「重试消息」是一等公民**——不是框架内部字符串，而是可被业务代码
（validator / tool）主动抛出的异常，message 即回喂给模型的文本。这比
form-filler 现在的「异常对象 → stderr」强：模型看得到失败原因。

**关键机制 2 — `RetryPromptPart`（`pydantic_ai_slim/pydantic_ai/messages.py:1770-1850`）：**

```python
class RetryPromptPart:
    """A message back to a model asking it to try again.

    * Pydantic validation of a structured response failed, here content is derived
      from a Pydantic [`ValidationError`][pydantic_core.ValidationError]
    * an output validator raised a [`ModelRetry`][pydantic_ai.exceptions.ModelRetry]
    """
    content: list[pydantic_core.ErrorDetails] | str

    @classmethod
    def from_validation_error(cls, error, tool_name=None, tool_call_id=None):
        content = (
            error.errors(include_url=False, include_context=False)
            if isinstance(error, pydantic_core.ValidationError)
            else error.message
        )
        ...

    def model_response(self) -> str:
        ...
        json_errors = error_details_ta.dump_json(self.content, exclude=exclude, indent=2)
        description = f'{len(self.content)} validation error{"s" if plural else ""}:\n```json\n{json_errors.decode()}\n```'
        return f'{description}\n\nFix the errors and try again.'
```

值得逐字级借鉴的三点：
1. `error.errors(include_url=False, include_context=False)` —— 剥掉 pydantic 的
   docs URL 和内部 ctx，只留 loc/msg/type，JSON block 喂回；
2. NativeOutput 重试时 `exclude = {i: {'ctx', 'input'} ...}` —— 去掉 `input`
   字段避免把模型刚生成的坏 JSON 重复塞进上下文（tool-call 重试则保留 `input`）；
3. 固定结尾 `"Fix the errors and try again."` —— 指令式收尾。

**关键机制 3 — `pydantic_evals`（`pydantic_evals/README.md`）：**

```python
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, IsInstance

class MatchAnswer(Evaluator[str, str]):
    def evaluate(self, ctx: EvaluatorContext[str, str]) -> float:
        if ctx.output == ctx.expected_output: return 1.0
        ...

dataset = Dataset(name='capital_eval', cases=[case], evaluators=[IsInstance(...), MatchAnswer()])
report = dataset.evaluate_sync(answer_question)
```

Case(inputs, expected_output) + Evaluator（返回 float 分数）+ report 表格
（含 Assertions ✔ 列）。**与 form-filler 的 `score_consistency.py` 同构**——
我们已有 9 条规则函数 + score；差别在 evals 框架把「规则」升级为可组合的
Evaluator 对象并把 expected_output 纳入 case 定义。见 §3/S-pattern 讨论。

**与 form-filler 的结合点：**
- `model_adapter.py:OpenAICompatibleAdapter.reflect()`（L229-291）：重试时
  `last_prompt = f"{base_prompt}\n\n上一次回答出错: {exc}\n请重新回答。"` —— 已有
  雏形，但 exc 是裸异常字符串。升级为 `RetryPromptPart` 风格的 JSON block。
- `model_adapter.py:generate_struct()`（L180-227）：**完全没有错误回喂**
  （见 §3.1 缺陷确认），直接照搬 `from_validation_error`。
- 实现成本：**+60 LOC / +3 tests**（model_adapter.py 内新增
  `_format_validation_feedback(exc) -> str` 辅助函数，两个方法共用）。

### Project B: chrisryugj/kordoc

- **URL:** https://github.com/chrisryugj/kordoc
- **Stars:** 1,845（`gh api repos/chrisryugj/kordoc --jq '.stargazers_count'`，2026-09-22；`pushed_at=2026-09-21T05:17:22Z`）
- **Language:** TypeScript（npm `kordoc`，Node 20+；同时提供 CLI + MCP server + Claude Code plugin）
- **定位:** 韩国政府文档（HWP/HWPX/PDF/Office）解析 + **양식 자동 채우기（表单自动填充）** + 신구대조（新旧对照 diff）+ lint。作者自述「在韩国文档地狱里撑了 7 年的公务员」——与 form-filler 的「中文申报表」问题域**同构**（都是官方表格、合并单元格、标签-值模式、格式保留填充），是 R5 调研的 jerryjliu/form_filling_app 之外问题域最匹配的项目。

**关键机制 1 — `isLabelCell()`（`src/form/recognize.ts`）标签判别，比 form-filler 的 `_is_likely_label()` 精细得多：**

```typescript
const NUMERIC_VALUE_RE = /^제?\d+(?:[.,]\d+)*[십백천만억조]*(?:원|명|건|개|회|부|매|장|점|호|번|년|월|일|시|분|초|개월|주년|차례|퍼센트)?$/
const SENTENCE_ENDING_RE = /(?:입니다|합니다|습니다|하세요|십시오|시오|바랍니다|바람|할 것|할것|하며|하고|한다|된다|됨|음|임)$/

export function isLabelCell(text: string): boolean {
  const trimmed = text.trim().replace(/[¹²³⁴⁵⁶⁷⁸⁹⁰*※]+$/g, "").trim()  // 脚注号剥离
  if (!trimmed || trimmed.length > 30) return false
  for (const kw of LABEL_KEYWORDS) { if (trimmed.includes(kw)) return true }
  const compact = trimmed.replace(/\s/g, "")
  if (/^[가-힣0-9()（）·:：\-]+$/.test(compact)
    && compact.length >= 2 && compact.length <= 12
    && (compact.match(/[가-힣]/g) ?? []).length >= 2
    && (compact.length <= 8 || trimmed.split(/\s+/).length <= 2)   // 长标签限 ≤2 词
    && !NUMERIC_VALUE_RE.test(compact)      // 「6개월」「1억원」不是标签
    && !SENTENCE_ENDING_RE.test(trimmed)    // 说明语句不是标签
    && !/^[(（]주[)）]|^주식회사/.test(compact)) return true
  if (/^[가-힣A-Za-z\s]+[:：]$/.test(trimmed)) return true           // 「标签:」形态
  // 无冒号英文标签（双语表单）：白名单单词 1-3 个
  if (/^[A-Za-z][A-Za-z\s./&-]*$/.test(trimmed) && trimmed.length <= 20) {
    const words = trimmed.toLowerCase().split(/[\s/&]+/).filter(w => w && !ENGLISH_STOPWORDS.has(w))
    if (words.length >= 1 && words.length <= 3 && words.every(w => ENGLISH_LABEL_WORDS.has(w.replace(/\.$/, "")))) return true
  }
  return false
}
```

可迁移点（form-filler `scripts/fill_docx.py:_is_likely_label()` L214-232 只有
>20 字符 + 34 个关键词正则）：
- **NUMERIC_VALUE 排除**（对应中文「6个月」「1万元」——数量/单位值不是标签）；
- **SENTENCE_ENDING 排除**（对应「……如下」「请填写」类说明文字——当前
  `_is_likely_label` 会把「获奖情况请依次填写」这种长句因含「获奖」判成 label，
  虽有 20 字上限部分缓解）；
- **脚注号/※ 剥离**（「姓名¹」→「姓名」）；
- **短标签词数限制**（9-12 字短文本要求 ≤2 词，防三词以上标题句混入）。

**关键机制 2 — `inferFieldType()` 字段类型推断（`src/form/recognize.ts`，v3.1）：**

```typescript
export type FormFieldType = "text" | "date" | "phone" | "email" | "amount" | "checkbox" | "idnum"

const LABEL_TYPE_RULES: Array<[RegExp, FormFieldType]> = [
  [/주민등록번호|외국인등록번호/, "idnum"],
  [/생년월일|일시|날짜|일자|기간|연월일|년월일|신청일|작성일|발급일|접수일/, "date"],
  [/전화|연락처|휴대폰|핸드폰|팩스/, "phone"],
  [/이메일|전자우편|email/i, "email"],
  [/금액|단가|수량|합계|소계|예산|비용|인원|급여|연봉/, "amount"],
]

export function inferFieldType(label: string, value: string): FormFieldType {
  if (/[□☑✓✔]/.test(value) || /[□☑✓✔]/.test(label)) return "checkbox"
  const v = value.trim()
  if (v) {
    if (/^\d{6}[-\s]?[1-4]\d{6}$/.test(v)) return "idnum"
    if (/^\d{4}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}\s*일?\s*\.?$/.test(v)) return "date"
    if (/^0\d{1,2}[-.)\s]?\d{3,4}[-.\s]?\d{4}$/.test(v)) return "phone"
    if (/^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$/.test(v)) return "email"
    if (/^[\d,.\s]+(?:원|명|건|개|회|부|매|%)$/.test(v) && /\d/.test(v)) return "amount"
    if (/^\d{1,3}(?:,\d{3})+$/.test(v)) return "amount"
  }
  const norm = label.replace(/\s/g, "")
  for (const [re, type] of LABEL_TYPE_RULES) { if (re.test(norm)) return type }
  return "text"
}
```

**值模式优先、标签关键词回退**的两段式结构，以及「裸数字不让位 amount
（邮编/编号/年份歧义）」的注释级细节，值得照抄。配套：

```typescript
function isRequiredLabel(label: string): boolean {
  return /[*※★]|\(\s*필수\s*\)|（\s*필수\s*）/.test(label)
}
function isEmptyValue(value: string): boolean {
  const v = value.trim()
  if (!v) return true
  return /^[\s_()（）\-—–~.·,]*$/  // 下划线/括号空白/破折号占位符
}
```

`extractFormSchema()` 输出 `FormFieldSchema[] = {label, value, row, col, type, required?, empty}`
——这正是 form-filler `--introspect-out` JSON 缺的三个维度（现在只有
text/is_label/merged_dup）。

**关键机制 3 — `findMatchingKey()` 前缀匹配护栏（`src/form/match.ts`）：**

```typescript
export function normalizeLabel(label: string): string {
  return label.trim().replace(/[:：\s()（）·]/g, "")
}

export function findMatchingKey(cellLabel, values): string | undefined {
  if (values.has(cellLabel)) return cellLabel          // 1) 精确
  let bestKey, bestLen = 0
  for (const key of values.keys()) {
    if (cellLabel.startsWith(key)) {
      if (key.length >= cellLabel.length * 0.6 && key.length > bestLen) { bestLen = key.length; bestKey = key }
    } else if (key.startsWith(cellLabel)) {
      // 反向（短单元格吸收长 key）阈值 0.75 —— 0.6 会让单元格「대리인」吸收 key「대리인성명」
      if (cellLabel.length >= key.length * 0.75 && cellLabel.length > bestLen) { bestLen = cellLabel.length; bestKey = key }
    }
  }
  return bestKey
}
```

注释里写了阈值的来历：反向阈值必须比正向高，否则「大表头的短单元格」会
错误吸收「更具体的长 key」。这是**带反例校准的参数**，直接可迁移到
`evaluation/schemas.py:SCHEMA_SYNONYMS` 的查找路径（「申请人」vs「申请人姓名」）。

**关键机制 4 — `ValueCursor` 重复标签数组值消耗（`src/form/match.ts:119`）：**

```typescript
export class ValueCursor {
  private nextIdx = new Map<string, number>()
  consume(key: string): string | undefined {   // 数组值按出现顺序逐项消耗；标量永远返回同一值
    const v = this.values.get(key); if (v === undefined) return undefined
    if (typeof v === "string") return v
    const i = this.nextIdx.get(key) ?? 0; if (i >= v.length) return undefined
    this.nextIdx.set(key, i + 1); return v[i]
  }
  available(key) / peek(key) / isArray(key)  // 预览不消耗
}
```

对应 form-filler SKILL.md Step 3「多条目选择」——目前只写在文档里，
`fill_docx.py` 无实现。ValueCursor 是 40 行的最小可行实现（名册型表格：
多个「获奖名称」行按顺序消耗 awards.entries[]）。

**关键机制 5 — `fillInCellPatterns()` 单元格内联模式填充（`src/form/match.ts:229`）：**

```typescript
// 1) 括号空白: 「일반(  )통」→ key「일반통」或「일반」→ 「일반(값)통」
text = text.replace(/([가-힣A-Za-z]+)\(\s{1,}\)([가-힣A-Za-z]*)/g, ...)
// 2) 复选框: 「□부」→ 值 truthy(☑/✓/v/V/true/1/yes) → 「☑부」；空串 = 不勾选
text = text.replace(/□([가-힣A-Za-z]+)/g, ...)
// 3) 注释空白: 「(한자：     )」→ 「(한자：金民秀)」
text = text.replace(/\(([가-힣A-Za-z]+)[:：]\s{1,}\)/g, ...)
```

中文申报表的对应物：「民族（  ）」「□男 □女」「（拼音：    ）」。form-filler
现在只写相邻空单元格，**单元格内联占位符完全不支持**——这是 R6-A4 的候选。

**关键机制 6 — `coveredPositions()` 合并覆盖坐标（`src/form/filler.ts`）：**

```typescript
/** 병합으로 덮인 격자 좌표("r,c") — 앵커가 아닌 플레이스홀더 위치.
 *  builder 렌더는 이 칸을 그리지 않으므로 여기 쓴 값은 조용히 사라진다. */
function coveredPositions(table: IRTable): Set<string> { /* rowSpan/colSpan 展开标记被覆盖的 (r,c) */ }
```

与 form-filler R3-A2 的 `_iter_unique_cells()`（D2 XML 遍历）解决同一问题的
另一面：**写入侧**要知道哪些网格坐标是被合并覆盖的「幻影单元格」（写进去的
值不会渲染）。我们目前靠 `seen_cells` 跳过重复 tc，但没有显式的覆盖坐标集。

**关键机制 7 — corpus 基准门（README/CHANGELOG 自述）：** kordoc 用
HWPX 291 文档「表 1,673/1,673、单元格 27,714/27,714 无损」、HWP↔PDF 单元格
文本 Jaccard 0.965 等**带数字的对照 Gate** 驱动每轮发布（v4.12.2 把 PDF 表
GT cellExact 从 0.73 实测到 0.96 后上调 gate floor）。这是「bench 数字说话」
工程文化的范例——对 form-filler 的启示见 §4 R6-A3 验收门。

**与 form-filler 的结合点 + 成本：**
| 机制 | 落点 | LOC | tests |
|---|---|---|---|
| `inferFieldType` + required/empty | 新模块 `scripts/field_types.py`，充实 `scan_docx_introspect()` 输出 | +90 | +4 |
| `isLabelCell` 四条排除规则 | `fill_docx.py:_is_likely_label()` L214-232 增量替换 | +25 | +3 |
| `findMatchingKey` 0.6/0.75 | `evaluation/schemas.py` 新增 `find_alias_key()` | +30 | +3 |
| `resolveUnmatched` 反馈 | `fill_docx.py:match_field()` 调用方 + audit 汇总 | +25 | +2 |
| `ValueCursor` 多条目消耗 | `fill_docx.py` 多标签行填充（Step 3 落地） | +55 | +3 |
| `fillInCellPatterns` 内联占位 | `fill_docx.py` 单元格写入前预处理 | +45 | +3 |

### Project C: mangiucugna/json_repair

- **URL:** https://github.com/mangiucugna/json_repair
- **Stars:** 5,103（`gh search repos "json-repair" --sort stars --limit 5 --json stargazersCount`，2026-09-22；`pushedAt=2026-09-17`）
- **Language:** Python（MIT；PyPI `json-repair`）
- **定位:** "Repair malformed JSON from LLMs, APIs, logs, and user input in Python."

**关键机制 — `repair_json()`（`src/json_repair/json_repair.py:37-95`）：**

```python
def repair_json(
    json_str: str = "",
    return_objects: bool = False,
    skip_json_loads: bool = False,
    logging: bool = False,
    json_fd: TextIO | None = None,
    chunk_length: int = 0,
    stream_stable: bool = False,
    strict: bool = False,
    schema: Any | None = None,                                    # ← schema 引导修复
    schema_repair_mode: Literal["standard", "salvage"] = "standard",
    **json_dumps_args: Any,
) -> ...
```

README 明确的调用纪律（反 anti-pattern 提示）：
> try the built-in `json.loads()` first; if that fails, run the repair parser.

即**先严格后修复**，且库内部已做这件事——调用方不需要自己写
`try: json.loads except: repair`（那是 wasteful antipattern）。支持：
尾逗号、单引号、未加引号的 key、Python 元组、注释、截断值自动补全
（`null`/`""` 默认值）、`true/false/null/None` 大小写不敏感识别。

**与 form-filler 的结合点：**
`model_adapter.py:OpenAICompatibleAdapter.generate_struct()` 的 plain-fallback 分支：

```python
raw = resp.choices[0].message.content
return schema.model_validate_json(raw)     # ← 这里对 markdown ```json 围栏/尾逗号零容忍
```

改为（try-import，缺库时行为不变）：

```python
try:
    import json_repair
except ImportError:
    json_repair = None
...
raw = resp.choices[0].message.content
try:
    return schema.model_validate_json(raw)
except Exception:
    if json_repair is None:
        raise
    obj = json_repair.loads(raw)            # 先严格后修复
    return schema.model_validate(obj)       # 修复后的 dict 再走 schema 校验
```

成本 **+20 LOC / +2 tests**（用 MockLLMAdapter 的 canned JSON 喂坏 JSON 即可
离线测：`'{"姓名": "张三",}'`、`'```json\n{...}\n```'`）。
注意 `schema=` 参数（schema 引导修复 + salvage 模式）留作 v6.4+ 储备，
本轮只用无 schema 的 `loads()`。

### Project D: PrefectHQ/marvin

- **URL:** https://github.com/PrefectHQ/marvin
- **Stars:** 6,198（`gh api repos/PrefectHQ/marvin --jq '.stargazers_count'`，2026-09-22；`pushed_at=2026-09-11`）
- **Language:** Python
- **定位:** "an ambient intelligence library" — 结构化输出工具库（3.0 起原生基于 Pydantic AI models）。

**关键机制 — `extract/cast/classify/generate` 四件套（README verbatim）：**

```python
result = marvin.extract("i found $30 on the ground and bought 5 bagels for $10", int,
                        instructions="only USD")     # → [30, 10]
result = marvin.classify("shut up and take my money", SupportDepartment)  # → SupportDepartment.SALES
primes = marvin.generate(int, 10, "odd primes")      # → [3, 5, 7, 11, 13, 17, 19]
```

对 form-filler 最有价值的是 **`instructions` 参数模式**：提取时附带一段
自然语言指令（"only USD"）来消解歧义，而不是把歧义留给默认行为。
这对应 SKILL.md「信息源深度挖掘」的挖掘规则表（校名→籍贯、决赛→国家级）
——目前这些规则只存在于文档/LLM prompt 里，没有代码载体。

**与 form-filler 的结合点：** **不建议引入 marvin 依赖**（与 form-filler
"stdlib + pydantic + python-docx 必需依赖" 的最小依赖哲学冲突，且 marvin 3.0
本身依赖 pydantic-ai，引入即传递依赖一整个 agent 框架）。可迁移的是
**instructions 模式的形状**：给 `OpenAICompatibleAdapter.generate_struct()`
增加可选的 `instructions: str` kwarg（透传到 prompt 尾部），~10 LOC，
让 deep-mining 类生成能带规则指令。仅此而已，见 §5。

### Project E（context/future）: docling-project/docling

- **URL:** https://github.com/docling-project/docling
- **Stars:** 67,559（`gh api repos/docling-project/docling --jq '.stargazers_count'`，2026-09-22；`pushed_at=2026-09-21`）
- **Language:** Python（MIT，LF AI & Data 基金会）
- **定位:** "Get your documents ready for gen AI" — IBM 主导的通用文档解析器（PDF/DOCX/XLSX/图片 → 统一 `DoclingDocument` IR + Markdown/JSON/DocTags 导出），本地执行、air-gapped 友好。
- **与本轮的相关性：** 它是 deferred 项 S2（LlamaParse）的**本地方案替代**——若未来 source-doc 解析质量成为瓶颈，docling（MIT、纯本地、MIT license）比 LlamaParse（商业 API、vendor lock）更适合 form-filler 的隐私优先原则。但它是重依赖（torch/transformers 生态），**本轮不建议引入**，仅记录为 S2 的未来解。见 §3/§5。

### 本轮看过但未入选的项目（含排除理由）

| Project | Stars (2026-09-22) | 排除理由 |
|---|---|---|
| promptfoo/promptfoo | 25,351 | 声明式 YAML eval + red teaming；form-filler 的 Python harness + pytest 已覆盖需求，引入 Node 工具链不划算（详见 §5） |
| confident-ai/deepeval | 18,379 | pytest 风格 LLM eval 框架；同上，且与 score_consistency 功能重叠 |
| microsoft/table-transformer | 2,948 | TATR 表格结构识别 + GriTS 指标；但 `pushed_at=2024-06-24`，**两年未更新**，不满足活跃度门槛 |
| calebhearth/formulaic | 554 | Ruby/Capybara Web 表单填充，问题域不符 |
| docling-graph | 898 | 文档→知识图谱，与填表问题域有距离 |

---

## 3. Deferred items 复查（R4/R5 遗留）

### 3.1 R1+R2_reflexion_strategy_enum — **现在值得做，且发现了真实缺陷**（升格 R6-A1）

R5 判定「被 R5-A2 中央化解锁但无用户请求 `--reflexion-rounds > 2`」而 defer。
本轮重新定位后结论改变，理由是三重新事实：

1. **step-5-preview 内核已就位**（主 Agent 铺垫）——多轮反思第一次有了
   真实模型可跑，此前的「无人使用」部分原因是「没有可用的 LLM」。
2. **发现真实 spec-impl 缺陷**（`scripts/fill_docx.py:fill_docx()` L866-881）：

   ```python
   for _ in range(reflexion_rounds):
       r = reflect_fn(text, filled_value, filled_so_far)
       if not r:
           break
       reflection_text = r
       status_icon = "⚠️"
       filled_so_far[text] = filled_value     # ← 只把同一 (label, value) 加回去
   ```

   循环**从不把 `r`（反思原文）喂给下一次调用**；而默认 `reflect_fn` 走
   `adapter.reflect()`，后者每次用同一 `base_prompt` 且 `temperature=0.0`
   （`model_adapter.py:258-260`）——因此 `--reflexion-rounds 2` 的第 2 轮与
   第 1 轮**逐字节相同**，是彻底的 no-op。SKILL.md Step 5.5 承诺的
   「重新调用 Step 5 用反思作为额外上下文重生成一次（仅 1 次重试）」
   **在代码中不存在**（没有重生成，只有重反思）。
3. **R5-A2 中央化已完成**（SCHEMA_SYNONYMS 单一数据源），新增枚举/记忆模块
   不再有双写风险。

**修正后的方案（R6-A1）**：新模块 `scripts/reflexion.py`：
- `class ReflexionStrategy(str, Enum): NONE | LAST_ATTEMPT | REFLEXION | LAST_ATTEMPT_AND_REFLEXION`（沿用 R5 记录的 noahshinn/reflexion 四值语义）；
- `@dataclass ReflectionMemory(max_reflections=3)`（MONISMALIK1  lift：`add()` 去空白忽略空串、切片裁剪、`format_for_prompt()` 空时返回 `""` 保证首轮 prompt 不变）；
- **修复缺陷本身**：反思循环把上一轮 `reflection_text` 经
  `memory.format_for_prompt()` 注入下一轮 reflect prompt（LAST_ATTEMPT_AND_REFLEXION
  语义），让 `--reflexion-rounds 2` 名副其实；
- JSONL 持久化（`audit_reflections.jsonl`，追加写）作为 R2 部分——只写不读检索
  （Anti-pattern F：persistence before substance，检索留给未来轮次）。
- 成本：**+130 LOC / +5 tests**。

### 3.2 S1_smolai_enum_pre_scan — **重构为确定性版本后值得做**（R6-A3）

R5 的原方案是「一次 LLM function-call 枚举所有字段+类型」。本轮结合 kordoc
后重新定性：**LLM 枚举部分应放弃**（R5 Anti-pattern H：routing 层不放 LLM；
且 step-5-preview 有 402 quota 风险，路由层不应依赖网络），**确定性类型推断
部分应采纳**：

- kordoc `inferFieldType()` 证明类型推断可以完全离线完成（值正则 + 标签关键词表）；
- form-filler 的 Pass 1 schema-first routing 已经做了「一个 label 一次」的
  schema 查找；pre-scan 的增量价值在于**一次性产出全表字段画像**
  （`[(label, type, required, empty)]`），用于：(a) audit 表新增「类型/必填」
  列；(b) `--introspect-out` JSON 充实（Pattern J 的自然延伸）；
  (c) 上游告诉用户「18 个字段：11 个可自动填、5 个 Literal、2 个需 AI 生成」。
- 成本：**+90 LOC / +4 tests**（`scripts/field_types.py` 新模块）。

### 3.3 S2_llamaparse — **维持 defer，未来解改为 docling**

R5 判定 overkill 成立：用户场景是「每学期 1-2 张表 + profiles/*.yaml」，
RapidOCR + cell-walk 已覆盖。补充本轮发现：若未来确需升级 source-doc 解析，
**docling（67.6k★、MIT、本地执行）是比 LlamaParse 更合适的路径**（隐私优先
原则下 vendor API 不可接受）。仍不投入本轮。

### 3.4 S3_lancedb_audit — **维持 defer**

无变化：audit.md 覆盖写在 1-2 张/学期的用量下完全够用；版本化存储的查询
需求（「Fall 2025 所有政治面貌=共青团的行」）目前不存在真实请求方。
LanceDB 依赖（pyarrow）对一个 skill 仓库过重。R6+ 若出现第 3 个
「跨表对比」诉求再重议。

---

## 4. 优先级建议（R6 action items）

| Priority | ID | Pattern | 来源 | LOC Δ | Tests | Impact | Risk | 建议 |
|---|---|---|---|---|---|---|---|---|
| 1 | **R6-A1** | **反思反馈闭环 + ReflexionStrategy 枚举 + ReflectionMemory**（修 `--reflexion-rounds 2` no-op 缺陷 + SKILL.md Step 5.5 承诺的「带反思重生成」） | pydantic-ai ModelRetry + MONISMALIK1 ReflectionMemory + deferred R1+R2 | +130 | +5 | 高（真实缺陷修复，新内核首次可实测） | 中（改反思语义，默认 strategy=NONE 保持 v6.3 行为） | **SHIP** |
| 2 | **R6-A2** | **结构化校验错误回喂**（`generate_struct` 重试循环从「同一 prompt 盲重试」升级为 `RetryPromptPart` 风格 JSON block）+ **json_repair 修复层** | pydantic-ai `RetryPromptPart.from_validation_error` + json_repair | +60 | +3 | 高（真实 LLM 路径自愈率；step-5-preview 402/坏 JSON 场景直接受益） | 低（可选依赖 try-import；缺库行为不变） | **SHIP** |
| 3 | **R6-A3** | **确定性字段类型推断 pre-scan**（`inferFieldType` + required/empty + `isLabelCell` 四条排除规则，充实 `--introspect-out` 与 audit） | kordoc `src/form/recognize.ts` + deferred S1 重构 | +115 | +7 | 中高（零 LLM 零依赖；Step 4 缺失处理与 Pattern J 的直接升级） | 低（纯函数 + 新增模块） | **SHIP** |
| 4 | R6-A4 | `findMatchingKey` 双向前缀匹配（0.6/0.75）+ `resolveUnmatched` audit 反馈 | kordoc `src/form/match.ts` | +55 | +5 | 中（匹配质量 + 未匹配输入可见性） | 低 | SHIP（若容量允许） |
| 5 | R6-A5 | `ValueCursor` 多条目按序消耗（Step 3 落地） | kordoc `ValueCursor` | +55 | +3 | 中（名册型表格） | 中 | Defer to R7 |
| 6 | R6-A6 | `fillInCellPatterns` 单元格内联占位符（「□男 □女」「民族（ ）」） | kordoc `fillInCellPatterns` | +45 | +3 | 中 | 中 | Defer to R7 |

**推荐 R6 PR scope：R6-A1 + R6-A2 + R6-A3（+A4 如容量允许）。**
**Estimated total LOC：+305 net（含 A4），+15 tests（88→103 目标）。**
**Expected score Δ：+1.5 ~ +2.5**（A1/A2 修真实缺陷是主要得分点；
A3 是零风险增量）。**无新增必需依赖**（json_repair 为可选；
其余纯标准库 + 已有 pydantic/python-docx）。

**取舍理由：**
- **A1 优先于一切**：它修的是「功能宣称存在但代码是 no-op」的缺陷
  （SKILL.md Step 5.5 白纸黑字 vs L866-881 实现），且 R5 的两个 deferred
  前置条件（中央化、可用内核）本轮全部满足——再 defer 就是技术债。
- **A2 与 A1 共享同一主题**（LLM 自愈），一个 PR 里改 `model_adapter.py`
  同一区域，review 成本最低；json_repair 是本轮唯一「新库直接可用」的
  模式，且可选依赖设计对现存用户零影响。
- **A3 零 LLM 零依赖**，在 A1/A2 动 LLM 路径的同时提供确定性保险；
  即使 step-5-preview quota 耗尽（402），A3 的功能完全不受影响。
- **A5/A6 defer**：多条目与内联占位符是「新能力」而非「缺陷修复」，
  按 ratchet 纪律排在真实缺陷之后。

### R6-A1 文件布局

```
D:\form filler\scripts\reflexion.py          (NEW, ~110 LOC: enum + ReflectionMemory + JSONL append)
D:\form filler\scripts\fill_docx.py          (MODIFY, +30 LOC: 反思循环注入 memory.format_for_prompt(); --reflexion-strategy flag)
D:\form filler\scripts\model_adapter.py      (MODIFY, +15 LOC: reflect() 接受可选 prior_reflections 参数)
D:\form filler\tests\test_reflexion.py       (NEW, ~130 LOC, 5 tests)
```

### R6-A2 文件布局

```
D:\form filler\scripts\model_adapter.py      (MODIFY, +60 LOC: _format_validation_feedback(); generate_struct 错误回喂; json_repair fallback)
D:\form filler\tests\test_adapter_feedback.py (NEW, ~90 LOC, 3 tests: MockLLM canned 坏 JSON / validation error feedback prompt 断言)
```

### R6-A3 文件布局

```
D:\form filler\scripts\field_types.py        (NEW, ~90 LOC: infer_field_type / is_required_label / is_empty_value / 中文 LABEL_TYPE_RULES)
D:\form filler\scripts\fill_docx.py          (MODIFY, +25 LOC: _is_likely_label 增量 hardening + introspect JSON 增加 type/required/empty)
D:\form filler\tests\test_field_types.py     (NEW, ~110 LOC, 7 tests)
```

### Acceptance gates for R6

- [ ] v6.3 基线无回归：88 passed / 4 skipped 全绿；`python evaluation/score_consistency.py --demo` ≥ 96.0。
- [ ] R6-A1：`--reflexion-rounds 2 --reflexion-strategy last_attempt_and_reflexion` 下，第 2 轮 reflect prompt 包含第 1 轮反思原文（用 MockLLMAdapter 记录 prompt 断言）；strategy=none（默认）时 prompt 与 v6.3 逐字节相同。
- [ ] R6-A2：MockLLM 返回 `'{"姓名":"张三",}'` / 围栏 markdown JSON 时，`generate_struct` 仍产出合法 schema 实例（json_repair 路径）；validation 失败重试时 prompt 含 `N validation errors` + `Fix the errors and try again.`。
- [ ] R6-A3：`--introspect-out` JSON 每个 cell 增加 `type`/`required`/`empty`；「6个月」「1万元」「请依次填写获奖情况」不再被判为 label（回归测试）。
- [ ] 全部新测试离线可跑（无网络、无 API key）——step-5-preview 402 quota 不影响 CI。

---

## 5. 明确不建议做的

1. **引入 pydantic-ai / marvin / docling 作为依赖** — 只借模式不引库。form-filler 的依赖哲学是「必需：stdlib + pydantic + python-docx + pyyaml」，引入 agent 框架或 torch 生态会摧毁 skill 的可移植性（25+ 平台安装）。marvin 3.0 本身依赖 pydantic-ai——引 marvin 等于引一整个框架。
2. **promptfoo / deepeval 替换 score_consistency.py** — 25.4k★/18.4k★ 很香，但前者是 Node/YAML 工具链、后者自带一堆 LLM-provider 依赖；我们的 9 条规则 harness + pytest 已经闭环且每轮产出 Δ。pydantic_evals 的 Case/Dataset/Evaluator 形状值得 R7 参考做轻量重构（纯 Python、无新依赖），但不是 R6。
3. **microsoft/table-transformer（TATR）** — 2,948★ 但 `pushed_at=2024-06-24` 已停更两年，且是 torch 重量级模型；表格结构识别对我们「DOCX 原生表格」场景是杀鸡用牛刀（扫描 PDF 表格由 RapidOCR + 现有 cell-walk 覆盖）。
4. **S1 的 LLM function-call 枚举原方案** — routing 层不放 LLM（R5 Anti-pattern H 延续）；类型推断用 kordoc 的确定性正则版。
5. **pydantic_evals 化重构 score_consistency.py** — 当前 harness 工作正常且是评分事实源；重构只有美学收益，违反 ratchet 的「每轮必须可测量提升」纪律。R7+ 若新增规则超过 15 条再考虑。
6. **LanceDB / LlamaParse** — S2/S3 维持 defer（§3.3/3.4），未来解分别是 docling（本地）与继续用 audit.md。

---

## 6. Appendix

### 6.1 本轮实测 star 数（命令 + 日期）

| Project | Stars | 验证命令（2026-09-22） |
|---|---|---|
| pydantic/pydantic-ai | 20,109 | `gh api repos/pydantic/pydantic-ai --jq '.stargazers_count'` |
| chrisryugj/kordoc | 1,845 | `gh api repos/chrisryugj/kordoc --jq '.stargazers_count'` |
| mangiucugna/json_repair | 5,103 | `gh search repos "json-repair" --sort stars --limit 5 --json stargazersCount` |
| PrefectHQ/marvin | 6,198 | `gh api repos/PrefectHQ/marvin --jq '.stargazers_count'` |
| docling-project/docling | 67,559 | `gh api repos/docling-project/docling --jq '.stargazers_count'` |
| promptfoo/promptfoo | 25,351 | `gh api repos/promptfoo/promptfoo --jq '.stargazers_count'` |
| confident-ai/deepeval | 18,379 | `gh api repos/confident-ai/deepeval --jq '.stargazers_count'` |
| microsoft/table-transformer | 2,948 | `gh api repos/microsoft/table-transformer --jq '.stargazers_count'`（pushed_at 2024-06-24，停更，排除） |

R1–R5 已调研项目的 star 数沿用 R5 记录（python-docx-template 2,703 / instructor 13.9k / outlines 15.8k / guidance 21.8k / reflexion 3,265 等），未重新实测。

### 6.2 Method notes

- 深读方式：`gh api repos/OWNER/REPO/contents/PATH --jq .content | base64 -d` 直取源文件（pydantic-ai 的 `exceptions.py` / `messages.py` / `pydantic_evals/README.md`；kordoc 的 `src/form/recognize.ts` / `src/form/match.ts` / `src/form/filler.ts`；json_repair 的 `src/json_repair/json_repair.py`）；README 用同法获取。
- 搜索路径：`gh search repos "pydantic ai agent framework"`、`"json repair llm"`、`"unstructured documents"`、`"form filling" --sort stars`、`"docx mailmerge python"`、`"schema inference form extraction"`、`"xgrammar OR lm-format-enforcer"`（最后两者无高星新结果，约束解码方向本轮无新增可迁移项目——instructor/outlines 已覆盖）。
- kordoc 为 TypeScript 项目，机制按「算法/正则/数据结构」层面迁移（与 R5 处理 python-docx-template 的方式一致：提升正则与数据结构，不提升语言实现）。
- form-filler 侧缺陷确认方法：直接读 `scripts/fill_docx.py` L866-881（反思循环）与 `scripts/model_adapter.py` L188-227（generate_struct 重试循环），并在本机跑 `python -m pytest tests/ -q` 确认基线 88 passed / 4 skipped（2026-09-22）。

### 6.3 Line-cited codebase references for R6

| Item | File | Lines | R6 action |
|---|---|---|---|
| 反思循环（no-op 缺陷） | `D:\form filler\scripts\fill_docx.py` | L866-881 | R6-A1 |
| `reflect()` 重试 + temperature=0.0 | `D:\form filler\scripts\model_adapter.py` | L229-291 | R6-A1 |
| `generate_struct()` 盲重试（无错误回喂） | `D:\form filler\scripts\model_adapter.py` | L180-227 | R6-A2 |
| plain fallback `model_validate_json(raw)` | `D:\form filler\scripts\model_adapter.py` | L214-215 | R6-A2（json_repair） |
| `_is_likely_label()` 标签判别 | `D:\form filler\scripts\fill_docx.py` | L214-232 | R6-A3（hardening） |
| `scan_docx_introspect()` JSON 输出 | `D:\form filler\scripts\fill_docx.py` | L128-177 | R6-A3（type/required/empty） |
| `match_field()` unmatched 静默丢弃 | `D:\form filler\scripts\fill_docx.py` | L841-842 | R6-A4 |
| `SCHEMA_SYNONYMS` 单一数据源 | `D:\form filler\evaluation\schemas.py` | L173-195 | R6-A4（find_alias_key） |
| `_iter_unique_cells()` XML 遍历 | `D:\form filler\scripts\fill_docx.py` | L936-964 | （R6-A5 的合并覆盖坐标参照） |

### 6.4 One-paragraph summary for Optimizer

本轮 5 个新前沿项目（pydantic-ai 20.1k★ / kordoc 1.8k★ / json_repair 5.1k★ /
marvin 6.2k★ / docling 67.6k★，全部 2026-09-22 实测且活跃）中，最可迁移的
是三个模式：**pydantic-ai 的 `RetryPromptPart.from_validation_error()` 结构化
校验错误回喂**（直接修复 `generate_struct()` 重试循环「同一 prompt 盲重试」
的已确认缺陷，以及 `reflect()` 多轮循环「反思从不回喂、temperature=0.0 下
第 2 轮逐字节重复第 1 轮」的 no-op 缺陷——SKILL.md Step 5.5 承诺的「带反思
重生成」在代码中不存在）；**kordoc `inferFieldType()` 的确定性字段类型推断**
（值正则优先 + 标签关键词回退 + required/empty 检测，零 LLM 零依赖，是
deferred 项 S1 的正确重构版）；**json_repair 作为 generate_struct 的可选
修复层**（先严格 `json.loads` 后修复，+20 LOC）。加上 R1+R2
（ReflexionStrategy 枚举 + ReflectionMemory）因 step-5-preview 内核就位 +
缺陷确认为「现在值得做」。**推荐 R6 做 A1（反思闭环 +130 LOC）+ A2
（结构化错误回喂 + json_repair，+60 LOC）+ A3（类型推断 pre-scan，+115 LOC），
合计 +305 LOC / +15 tests，无新增必需依赖，全部离线可回归，预期 score Δ
+1.5~+2.5。** docling 记录为 S2（LlamaParse）的未来本地方案；promptfoo /
deepeval / table-transformer / pydantic-ai 依赖化明确不做。

---

**End of round-6 Researcher output.**
