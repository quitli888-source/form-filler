# Round 2 — Researcher Output

## 1. Surveyed Projects (6 — focus: form-filling + structured-output ecosystems)

### 1.1 jxnl/instructor — https://github.com/jxnl/instructor
- **Stars:** 13,893
- **One-line description:** Structured outputs for LLMs — patch any LLM client to return **validated Pydantic models** via function-calling / tool-use / JSON-mode. Field-level constraints (regex, `Literal`, `Field(min_length=...)`, `Field(max_length=...)`, `conint(ge=...)`) become *ungoogleable* generation rules.
- **Key architectural ideas observed:**
  - `from openai import OpenAI; client = instructor.from_openai(OpenAI())` — **provider-agnostic by patching the underlying client** (works with OpenAI, Anthropic, Gemini, Cohere, Mistral, llama.cpp, etc.).
  - **Pydantic-first** — the model IS the prompt. No string templating of constraints.
  - **Validation hooks** (`MaxRetries`, `ValidationError` re-raise) — LLM auto-retries within budget when validation fails.
  - **`Iterable[T]` / `Maybe[T]`** for "extract all" / "extract or None" patterns.
  - `client.chat.completions.create(..., response_model=MySchema, messages=[...], max_retries=2)` — single-call UX, multi-model backend.
- **Source quote:** "Use Pydantic models to define the structure of your LLM output. Instructor patches the client to enforce schema on the response. Works with any OpenAI-compatible client."

### 1.2 dottxt-ai/outlines — https://github.com/dottxt-ai/outlines
- **Stars:** 15,807
- **One-line description:** **Structured generation at token level** — regex/CFG/JSON/Pydantic/function-call constraints enforced during sampling, not after. The LLM *cannot* emit an invalid token.
- **Key architectural ideas observed:**
  - **Provider-agnostic** — same `outlines.generate.json(model, MySchema)(prompt)` over vLLM, transformers, llama.cpp, OpenAI, Ollama.
  - **Type-as-prompt** — `Literal["男","女"]`, Pydantic, regex pattern, JSON schema all become generation constraints.
  - **Application pattern** — `@outlines.prompt` + output type = reusable component (Pattern F + A combined).
  - **Multiple output types** unified under one API: regex, JSON, multiple-choice, function-call, grammar.
- **Source quote:** "Pass the desired output type directly... Guaranteed valid structure matching Python type hints or Pydantic models. Works with any model across providers."

### 1.3 microsoft/guidance — https://github.com/microsoft/guidance
- **Stars:** 21,753
- **One-line description:** A **programming paradigm** for steering LLMs — templated control flow, constrained generation, JSON/Pydantic, regex/grammar, **token-level fast-forwarding**.
- **Key architectural ideas observed:**
  - **Token-level fast-forwarding** — when constraint pins tokens (e.g. a date starts with "20"), insert without a forward pass → cuts cost/latency.
  - **Offline grammar debugging** via `guidance.Mock()` — test grammars/JSON schemas with zero API cost.
  - **Composable `@guidance` functions** — a DSL for LLM output.
  - **Pydantic-style JSON generation** with structural guarantees.
- **Source quote:** "Constrained generation... Force model output to match regex patterns, grammar rules, or be selected from a predefined list of options. fast-forwarding reduces GPU usage and latency."

### 1.4 noahshinn/reflexion — https://github.com/noahshinn/reflexion
- **Stars:** 3,265 (NeurIPS 2023)
- **One-line description:** Agents that **verbally self-critique** after each failed attempt and store reflections in **persistent memory** for the next try.
- **Key architectural ideas observed:**
  - **Last-attempt + self-reflection** appended as context for next trial (vs. only retry).
  - **Persistent memory file** of reflections survives across runs (file-based, plain markdown).
  - **Four reflexion strategies** (NONE / LAST_ATTEMPT / REFLEXION / LAST_ATTEMPT_AND_REFLEXION) are first-class knobs.
  - **ReAct trace + reflection log** = auditable iteration history.
- **Source quote:** "Self-reflection on the last attempt as context... Persistent memory for self-reflections across trials and resumption of logged runs."

### 1.5 atharvakarval-dev/Form-Flow-AI — https://github.com/atharvakarval-dev/Form-Flow-AI
- **Stars:** 18 (low, but high topical relevance)
- **One-line description:** "**The Ultimate AI Form Filler.** Automate complex web forms & PDFs with Voice, generic LLMs (Gemini/Phi-2), and Playwright. The best open-source autonomous form filling agent."
- **Key architectural ideas observed:**
  - **Web form + PDF in one product** — both browser DOM (Playwright) and PDF parse paths are first-class.
  - **Multi-modal input** — voice (speech-to-text) → LLM → structured extraction → fill.
  - **Generic LLM backend** — Gemini/Phi-2 listed, not tied to one vendor.
  - **FastAPI + React frontend** — production-grade scaffold (form-filler is currently scripts-only).
- **Source quote (from description):** "Automate complex web forms & PDFs with Voice, generic LLMs (Gemini/Phi-2), and Playwright."
- **Gap analysis vs form-filler:** They focus on browser forms; form-filler focuses on DOCX/Excel/PDF tables. **These are complementary, not competing.** Form-filler's niche (Chinese-style 申请表 / 申报表 with semantic mapping) is unique.

### 1.6 WestHealth/pdf-form-filler — https://github.com/WestHealth/pdf-form-filler
- **Stars:** 17 (low, but topical)
- **One-line description:** Python library to **automate PDF form filling** (especially AcroForm/XFA medical records).
- **Key architectural ideas observed:**
  - **Form-field introspection first** — list all AcroForm fields, then map.
  - **JSON profile schema** for inputs (one source of truth for fillable data).
  - **Field-type aware** — text vs checkbox vs radio vs signature handled separately.
- **Source quote:** "Python Library to Automate Form Filling"
- **Gap analysis vs form-filler:** PDF-only; form-filler already chose python-docx as primary. The AcroForm piece is **directly transferable** to a future `fill_pdf.py` — we noted PyMuPDF in SKILL.md but never built the wrapper.

---

## 2. Transferable Patterns for Round 2 (4 ideas — narrowed focus)

> Round 1 already adopted Patterns C/D/E/H (Reflexion, profile.md, validate_rules, score_consistency). Round 2's priorities are the *deferred* high-impact items: A (Schema-as-Prompt) and F (Provider Adapter). Plus two new patterns specific to form-filling ecosystems.

### Pattern A2 — **Production-grade Schema-as-Prompt** (extends Round 1 Pattern A)
- **Source projects:** jxnl/instructor (primary) + dottxt-ai/outlines + microsoft/guidance
- **What it is:** Use **`jxnl/instructor`** as the structured-output backend. Define each form field as a Pydantic slot (`recommendation_letter: str = Field(min_length=200, max_length=400)`, `gender: Literal["男","女"]`, `phone: str = Field(pattern=r"^1\d{10}$")`, `email: str = Field(pattern=EMAIL_RE)`). One `client.chat.completions.create(response_model=FormSchema, ...)` call — **the LLM physically cannot return a value that violates the schema.**
- **Why it applies to form-filler:** SKILL.md currently warns about word-count limits (Step 5) and the evaluator has R8 (`rule_word_limit`) as a *blocking* check. With Pattern A2, R8 violations become **structurally impossible** for fields declared via instructor — the LLM never produces an over-limit value. This is the difference between *catching* and *preventing*.
- **Round 1 deferred because:** requires D (profile.md substrate) — now in place as of v5.0.
- **Estimated effort:** medium (1) `pip install instructor pydantic`, (2) `evaluation/schemas.py` defining field-level types, (3) `scripts/fill_docx.py` calls instructor instead of raw LLM, (4) fallback when no LLM key set).
- **Estimated impact:** very high — directly upgrades R8, R1 (gender-name), R4/R5/R6 (format rules) from runtime checks to compile-time constraints.

### Pattern F2 — **Provider-Agnostic Model Adapter with Stub Default** (extends Round 1 Pattern F)
- **Source projects:** jxnl/instructor (patches OpenAI client) + langchain (model registry) + dottxt-ai/outlines
- **What it is:** Define a `ModelAdapter` interface with two implementations:
  1. `OpenAIAdapter` — wraps `instructor.from_openai(OpenAI())` for OpenAI / OpenAI-compatible endpoints.
  2. `StubAdapter` — returns deterministic stub reflections (`""` / `"OK"`) so the system runs end-to-end without any API key (CI-friendly; current behaviour).
  3. (Future) `AnthropicAdapter`, `LocalVLLMAdapter`, `OllamaAdapter` — same interface, just different `__init__`.
- **Why it applies to form-filler:** form-filler currently bakes in "the agent platform's LLM is available" as an implicit assumption. With a ModelAdapter, the same `fill_docx.py` works offline (CI, demos, sensitive docs) or against any cloud provider. **The user's minimax m3 endpoint is itself an OpenAI-compatible endpoint** — Pattern F2 makes that integration a 5-line config change instead of a code rewrite.
- **Round 1 deferred because:** higher priority items (C/D/E/H) shipped first.
- **Estimated effort:** small-medium (single new file `scripts/model_adapter.py` with 2 classes; one CLI flag `--provider {stub,openai}`).
- **Estimated impact:** high — unblocks (a) real-LLM Reflexion (Pattern C upgrade), (b) future Anthropic/local backends, (c) the minimax m3 key the user provided.

### Pattern I — **Field-type-aware form schema** (NEW — informed by Form-Flow-AI + WestHealth)
- **Source projects:** WestHealth/pdf-form-filler (PDF introspection) + Form-Flow-AI (voice/form dual-input)
- **What it is:** Treat each form template as having a **first-class schema** (`templates/schemas/*.py`):
  - `class 优秀团员申报表(BaseModel):`
  - `   姓名: str = Field(min_length=2, max_length=20)`
  - `   性别: Literal["男","女"]`
  - `   学历年级: Literal["24级本科生","24级硕士生","24级博士生"]`
  - `   申报类别: Literal["优秀团员","优秀团干","三好学生"]`
  - `   自荐信: str = Field(min_length=200, max_length=800)`
  - `   手机: str = Field(pattern=r"^1\d{10}$")`
- The **schema file** becomes the single source of truth for (a) field constraints, (b) profile.md mapping, (c) audit-table column headers, (d) score_consistency rule selection. The current match_rules list is *one* view into this; the schema unifies all four views.
- **Why it applies to form-filler:** Right now `match_rules` lives in `fill_docx.py`, the SKILL.md Step 7.5 rules live in `score_consistency.py`, the audit column headers live in `templates/audit_table.md`, and the profile.md template lives in `SKILL.md §Step 2.5`. **Four places, one concept.** A unified schema collapses all four into one Pydantic file + generated artefacts.
- **Estimated effort:** medium (1) one new file `templates/schemas/youth_league.py`, (2) generator `scripts/build_schema.py` that emits `match_rules`, audit headers, score_consistency rules from the schema.
- **Estimated impact:** high — turns a maintenance burden (4 places to keep in sync) into a single source.

### Pattern J — **Form-field introspection as Step 0** (NEW — informed by WestHealth + Form-Flow-AI)
- **Source projects:** WestHealth/pdf-form-filler (AcroForm introspection) + smol-ai/developer (plan → file paths)
- **What it is:** Before any filling, run a **Step 0.5 form-introspection** that:
  1. Scans the input DOCX/Excel/PDF template,
  2. Lists every writable cell/field with its label + current value + (if DOCX) `is_label` heuristic,
  3. Emits `introspect.json` next to `profile.md`.
- The optimizer then **uses `introspect.json` to pick which form template schema applies** (e.g. `introspect.json` says labels include "申报类别" + "团员评议" → load `youth_league.py` schema).
- **Why it applies to form-filler:** Today `fill_docx.py` does scan tables (the `scan_docx_tables` function), but the output is only printed — not persisted. **Persisting it lets Round 3+ do automated regression on schema detection** ("did Step 0.5 correctly identify this as 优秀团员申报表?").
- **Estimated effort:** small (a) persist scan output to JSON, (b) write `--introspect` flag.
- **Estimated impact:** medium — enables future automated tests + schema auto-selection.

---

## 3. Top 3 Recommendations for Round 2

### 1. Pattern F2 — Model Adapter (do FIRST) — **enables everything else**
- **Why first:** Tiny effort, unblocks Pattern A2's real-LLM hookup. Without F2, A2 can only be tested with stubs. With F2, we can plug in the user's `minimax m3` endpoint and verify the LLM hook actually works on a real table.
- **Concrete deliverable:**
  - `scripts/model_adapter.py` — `ModelAdapter` ABC + `StubAdapter` + `OpenAICompatibleAdapter` (covers OpenAI + minimax + DeepSeek + 任何 OpenAI 兼容 endpoint)
  - `--provider {stub,openai-compatible}` CLI flag on `fill_docx.py`
  - `--llm-base-url` + `--llm-api-key` + `--llm-model-name` flags for the openai-compatible case
  - **Default remains `stub`** — no behaviour change for users without LLM access.
- **Risk:** none — additive. Stub is still the default.

### 2. Pattern A2 — Schema-as-Prompt via instructor (do SECOND) — **core v6.0 feature**
- **Why second:** Needs F2 to test with real LLM. Highest payoff — turns R8 from runtime check to impossible-by-construction.
- **Concrete deliverable:**
  - `evaluation/schemas.py` — Pydantic models for 优秀团员申报表 / 奖学金申请表 / 个人简历 (3 starter schemas)
  - `scripts/fill_docx.py` — when `pattern='📝'` (AI-generated field) AND a matching schema field exists, call `adapter.generate(FieldSchema)` instead of free-form prompt
  - `scripts/validate_rules.py` — `--schema-mode` flag to validate that a JSON output satisfies the Pydantic schema (Pattern E upgrade)
- **Risk:** instructor requires `openai` package — already a transitive dep. `pip install instructor pydantic` is the only install step. **No new heavy dependency.**
- **Fallback:** if instructor not installed, fall back to the current free-form prompt (still call LLM, just no schema enforcement).

### 3. Pattern I — Unified form-schema (do THIRD) — **the structural cleanup**
- **Why third:** Bigger refactor (4 files → 1 schema). Doesn't unlock new functionality, but **prevents future bugs** where R8 says one thing, audit column header says another, and `match_rules` says a third.
- **Concrete deliverable:**
  - `templates/schemas/youth_league.py` — Pydantic model with all 优秀团员申报表 fields
  - `scripts/build_schema.py` — generates `scripts/fill_docx.py` `match_rules`, `templates/audit_table.md` column headers, and `evaluation/score_consistency.py` R1–R9 from the schema
  - Three schemas total: `youth_league.py`, `scholarship.py`, `resume.py`
- **Risk:** if a schema generator bug ships, the whole pipeline breaks. **Mitigate by keeping generated files checked in** + a CI step that re-generates and diffs.

---

## 4. Anti-patterns to avoid (Round 2 specific)

### Anti-pattern 3 — Vendor-lockin to one LLM SDK
Several form-filling repos (Form-Flow-AI uses Gemini SDK directly) lock to one provider. When the provider deprecates, you re-write the integration. Pattern F2 explicitly avoids this — `OpenAICompatibleAdapter` covers 90% of Chinese LLM providers (minimax, DeepSeek, Moonshot, Zhipu, Qwen all expose OpenAI-compatible endpoints). **Don't import anthropic / google / cohere directly — use the OpenAI-compatible shim.**

### Anti-pattern 4 — Schemas as Python-string regexes
Some form fillers encode constraints as regex strings (e.g., `"^1\\d{10}$"`). This is fragile and untyped. Pattern I/Pydantic gives `pattern=r"^1\d{10}$"` AND `pattern=PHONE_RE` (a `Field(pattern=...)`) — IDE-checked, re-validated on every model load, error messages are Pydantic-style ("String should match pattern '^1\\d{10}$'") instead of regex-compile tracebacks. **Always use Pydantic Field constraints, never raw regex strings.**

### Anti-pattern 5 — Generating schema-by-example ("just show the LLM a JSON example")
This is tempting ("here's a JSON of what we want, copy it"). It *works* until the LLM adds a key, drops a key, or uses snake_case vs camelCase. Pattern A2's `response_model=MySchema` is **declarative** — the LLM is told the exact JSON shape by the API, not by example. Avoid the example-based pattern except as a fallback.

---

## 5. Round 2 ship target summary

| ID | Pattern | Code area | LOCs (est.) | Risk |
|----|---------|-----------|-------------|------|
| F2 | Model Adapter | `scripts/model_adapter.py` (new) | +120 | low |
| A2 | Schema-as-Prompt (instructor) | `scripts/fill_docx.py`, `evaluation/schemas.py` (new) | +200 | medium |
| I | Unified form-schema | `templates/schemas/*` (new), `scripts/build_schema.py` (new) | +300 | medium |
| J | Form-field introspection | `scripts/fill_docx.py` (`scan_docx_tables` + `--introspect`) | +50 | low |
| **Total new code** | | | **~670 lines** | |

Existing v5.0 surfaces preserved: profile.md, audit.md, validate_rules.py, score_consistency.py, all fixtures.

**Expected Δ vs v5.0 (per Reviewer):**
- Skill spec: +6 (schema-as-prompt §new)
- Code quality: +8 (model_adapter abstraction)
- Robustness: +5 (introspection persistence)
- Evaluation: +10 (schema-validated fixtures)
- Privacy/UX: +3 (provider opt-in, no key required by default)
- **Total: +32 (vs v5.0 = 69.5 → target ~101, capped at 100)**