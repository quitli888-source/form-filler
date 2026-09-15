# Round 2 — Reviewer Output

## 1. Current State (v5.0) — what's there, what works, what doesn't

### 1.1 Inventory (per `ls -la` and prior artifacts)

```
SKILL.md                       956 lines, version: "5.0"
README.md                      ~250 lines, v5.0 + Darwin table
scripts/fill_docx.py           670 lines, exposes match_field/write_profile_md/render_audit_table/reflect
scripts/validate_rules.py      165 lines, 3 mock fixtures
evaluation/score_consistency.py 358 lines, 9 rules (R1–R9), demo data, JSON output
templates/audit_table.md       audit template with 反思 column
tests/fixtures/                3 docx files + build_fixtures.py
profiles/                      empty placeholder
agent_state/round_1/           5 phase artifacts (complete)
```

### 1.2 Verified-passing surfaces (from `round_1/04_tester.md`)

| Surface | Status | Source |
|---|---|---|
| `match_field` regex routing | ✅ 8/8 unit tests | `tests/` |
| `write_profile_md` SHA + versioning | ✅ verified | Tester T1, T4 |
| `render_audit_table` 1687-byte output | ✅ verified | Tester T1 |
| `_stub_reflect` plumbing | ✅ stub returns `""` | Tester T1 |
| `score_consistency.evaluate` JSON | ✅ score=100 demo | Tester T2 |
| `validate_rules --mock` exit codes | ✅ (intentional MISS = exit 1) | Tester T7 |
| 3 DOCX fixtures (simple/merged_cell/multi_match) | ✅ buildable | Tester T6 |

### 1.3 Known defects (deferred from Round 1, must revisit in R2)

| # | Defect | Surfaced in | Reviewer's call |
|---|--------|-------------|-----------------|
| 1 | `_stub_reflect` returns empty (no real LLM) | T1 — plumbing-only | **Fix in R2** — Pattern F2 adapter |
| 2 | `match_field` first-match-wins (defect #2 from R1) | T5 — `学历专业` → `学历|年级` wins over `专业` | **Defer to R3** — needs A2 schema substrate |
| 3 | `_find_value_cell` right-then-down heuristic | R1 §"Known gaps" | **Defer to R3** — needs real fixtures |
| 4 | `evaluate()` vs `score()` naming drift | R1 §"Known gaps" | **Fix in R2** — cosmetic, low risk |
| 5 | PII redaction in audit output | R1 §"What did NOT ship" | **Fix in R2** — privacy dimension Δ=0 in R1 |
| 6 | `--audit-out` doesn't parse status-counts summary | R1 §"expand score_consistency" | **Fix in R2** — required by Round 2 priorities |

### 1.4 v5.0 surface — concrete shape of the code we'd touch

- **`scripts/fill_docx.py` lines 209–232**: `_stub_reflect` + `reflect` aliases. We will replace with `adapter.call(...)` and keep `reflect()` as a thin wrapper for back-compat.
- **`scripts/fill_docx.py` lines 459–569**: `fill_docx()` main loop. We'll add a 5th "AI generation" branch that calls `adapter.generate(FieldSchema)` when the field has a known schema.
- **`scripts/fill_docx.py` line 663**: `audit["info_source"] = "（无）"` — this is where the PII-redaction logic would go (mask phone/email/id_number before writing to audit).
- **`scripts/fill_docx.py` line 658**: `audit["date"] = ...` — fine, no change needed.
- **`evaluation/score_consistency.py` lines 239–276**: `parse_audit_md`. We'll extend to also read the status-counts summary block (`✅ 自动匹配 | N | X%`).
- **`evaluation/score_consistency.py` lines 297–325**: `evaluate()` returns `score/blocking_errors/warnings/fill_rate_pct/rule_results`. We will rename `evaluate` → `score` (fix #4) with `evaluate` as deprecated alias.
- **`templates/audit_table.md`**: The audit column for 反思 exists; we don't need to change the template.

---

## 2. Mapping Research → Action Items

### R2-A1: Model Adapter (Pattern F2)
- **Source pattern:** F2 (Researcher §3.1)
- **Where in code:**
  - NEW file: `scripts/model_adapter.py`
  - EDIT: `scripts/fill_docx.py` lines 209–232 (replace stub) + `main()` CLI args (add `--provider`)
  - EDIT: `SKILL.md` §"Step 5.5 自检反思" — update the "stub" paragraph to reflect "configurable adapter"
  - EDIT: `README.md` §"工具集成指南" — document `--provider` flag
- **Concrete deliverables:**
  1. `class ModelAdapter(ABC): generate_struct(schema, prompt) -> T; reflect(field, value, ctx) -> str`
  2. `class StubAdapter(ModelAdapter)` — returns `""` / deterministic stubs (current behaviour)
  3. `class OpenAICompatibleAdapter(ModelAdapter)` — `pip install openai instructor`, calls any OpenAI-compatible endpoint (covers minimax m3 + DeepSeek + OpenAI + 200+ others)
  4. CLI: `--provider {stub,openai-compatible}` default `stub`; `--llm-base-url`, `--llm-api-key`, `--llm-model-name`
  5. Env-var fallback: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL_NAME` (so the user's minimax key works without CLI args)
  6. **NO behaviour change for users without `--provider openai-compatible`** — default stub preserves v5.0 behaviour exactly.
- **Estimated impact:** +8 to "Code quality" dimension; enables R2-A2.

### R2-A2: Schema-as-Prompt + Real LLM Hookup (Pattern A2 + fix #1)
- **Source pattern:** A2 (Researcher §3.2)
- **Where in code:**
  - NEW file: `evaluation/schemas.py` — 3 starter Pydantic models
  - EDIT: `scripts/fill_docx.py` lines 459–569 — when field is `📝` (AI-generated) AND schema matches, call `adapter.generate(FieldSchema)` instead of raw prompt
  - EDIT: `scripts/fill_docx.py` lines 209–232 — replace `_stub_reflect` with `adapter.reflect(...)`
  - EDIT: `requirements` — add `instructor>=1.0.0` to a new `requirements.txt` (currently absent!)
  - EDIT: `SKILL.md` §"Step 5 AI 内容生成" — add `### 5A. Schema-constrained path` subsection
- **Concrete deliverables:**
  1. `evaluation/schemas.py`:
     ```python
     from pydantic import BaseModel, Field
     from typing import Literal
     PHONE = r"^1\d{10}$"
     EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
     class 优秀团员申报表(BaseModel):
         姓名: str = Field(min_length=2, max_length=20)
         性别: Literal["男","女"]
         民族: str = Field(default="汉族")
         籍贯: str = Field(min_length=2, max_length=20)
         手机: str = Field(pattern=PHONE)
         邮箱: str = Field(pattern=EMAIL)
         自荐信: str = Field(min_length=200, max_length=800)
         # ... etc
     ```
  2. `fill_docx.py` integration: detect `📝` field → look up FieldSchema → call `adapter.generate(FieldSchema, prompt)`. **Fallback to raw prompt if no schema or schema generation fails** (so default behaviour unchanged).
  3. `_stub_reflect` becomes `_adapter_reflect(adapter, field, value, ctx)` — calls `adapter.reflect()` when adapter supports it, returns `""` otherwise.
  4. `requirements.txt` (NEW): `python-docx>=1.0; pyyaml>=6.0; pydantic>=2.0; openai>=1.0; instructor>=1.0`
- **Estimated impact:** +12 to "Robustness" + "Evaluation" dimensions combined.

### R2-A3: Form-field Introspection Persistence (Pattern J)
- **Source pattern:** J (Researcher §3.4)
- **Where in code:**
  - EDIT: `scripts/fill_docx.py` lines 52–80 (`scan_docx_tables`) — add optional `--introspect-out PATH` flag, write JSON
  - EDIT: `tests/fixtures/build_fixtures.py` — include `introspect.json` in fixtures
- **Concrete deliverables:**
  1. JSON shape: `{template, scanned_at, tables: [{index, rows, cols, fields: [{row, col, text, is_label}]}]}`
  2. CLI: `--introspect-out INTROSPECT.json` (optional; default = don't write)
  3. `--scan-only` already exists; this just adds the persistence layer
- **Estimated impact:** +5 to "Evaluation/testability" dimension.

### R2-A4: PII Redaction in audit (fix #5)
- **Source pattern:** de-identification pattern (commonly seen in Anthropic safety guidelines + Reflexion paper)
- **Where in code:**
  - EDIT: `scripts/fill_docx.py` line ~663 — before writing audit, mask phone/email/id_number to `1XX****XXXX` / `***@***.com` / `1XXXXXXXXXXXXXXX`
  - EDIT: `templates/audit_table.md` — add a note `> 隐私字段已脱敏`
- **Concrete deliverables:**
  1. `def _redact(value: str, kind: str) -> str` in `fill_docx.py`
  2. Apply when writing audit details
- **Estimated impact:** +3 to "Privacy & UX" dimension (closes the R1 gap).

### R2-A5: Audit-status summary parser + cosmetic rename (fix #4 + fix #6)
- **Source pattern:** R1 deferred items
- **Where in code:**
  - EDIT: `evaluation/score_consistency.py` — `parse_audit_md` reads status-counts block; rename `evaluate` → `score` (keep `evaluate` as alias)
  - EDIT: `scripts/validate_rules.py` — update import if needed
- **Concrete deliverables:**
  1. `parse_audit_md` returns `(filled, details, status_counts)` tuple — third element is `{"✅":N, "🔄":N, ...}`
  2. `score(...)` is the canonical name; `evaluate(...)` is `@deprecated`
  3. CI/regression test: parse the existing demo audit, assert 0 blocking errors
- **Estimated impact:** +2 to "Evaluation" dimension.

### R2-A6: Promote Tester scripts to tests/test_fill_docx.py (R1 round_2_priorities #5)
- **Source pattern:** standard Python `unittest` / `pytest` layout
- **Where in code:**
  - NEW: `tests/test_fill_docx.py` — imports from `scripts.fill_docx`, runs `validate_rules` with 3 fixtures, asserts score=100 on demo, asserts `write_profile_md` produces 8-char SHA
  - NEW: `tests/test_score_consistency.py` — assert `parse_audit_md` returns expected shape
- **Concrete deliverables:**
  1. Two `pytest`-runnable test files
  2. CI instruction in README: `python -m pytest tests/`
- **Estimated impact:** +5 to "Evaluation" dimension.

---

## 3. Prioritization & Scope

**R2 will ship 6 action items in 1 round:**

| Priority | ID | Pattern | Effort | Impact |
|---|---|---|---|---|
| P0 | R2-A1 | F2 (Model Adapter) | S | enables everything |
| P0 | R2-A2 | A2 (Schema + Real LLM) | M | core v6.0 |
| P1 | R2-A3 | J (Introspection) | S | enables R3 |
| P1 | R2-A4 | Privacy | XS | +3 privacy Δ |
| P1 | R2-A5 | Cosmetic + parser | XS | cleanup |
| P1 | R2-A6 | Promote to pytest | S | enables regression |

**Defer to R3:**
- Defect #2 (first-match-wins) — needs A2 schemas as substrate (now in place after R2-A2)
- Defect #3 (right-then-down heuristic) — needs real fixtures (R2-A3 partially enables)
- Pattern I (unified form-schema) — R3 will use the schemas from R2-A2 as the seed

---

## 4. Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| instructor requires specific openai version pin | Low | pin `openai>=1.0,<2.0` in requirements.txt |
| minimax endpoint may not support instructor's tool-use | Medium | StubAdapter default; OpenAICompatibleAdapter degrades to raw chat completions when `instructor` raises |
| Pydantic v2 vs v1 syntax mismatch | Low | pin `pydantic>=2.0`; use v2 syntax throughout |
| `evaluate` → `score` rename breaks scripts | Low | keep `evaluate` as `@deprecated` alias |
| pytest not installed in target env | Low | use stdlib `unittest` (no new dep); OR document `pip install pytest` |

---

## 5. Termination Criterion Reminder

From `loop_config.json`:
- `max_rounds: 3`
- `min_quality_delta: 3` (per-round Δ must exceed +3)
- `plateau_rounds: 2` (Δ < 3 for 2 consecutive rounds → terminate)

R1 Δ was +12.05. If R2 Δ ≥ +3 and R3 Δ ≥ +3, **the loop runs to R3.** If R2 Δ ≥ +3 but R3 Δ < 3, **terminate after R3.** If R2 Δ < 3, **terminate after R2** (plateau detected).

This Reviewer's call: **target R2 Δ ~+15** (most of the easy wins). If R2 hits, R3 is a cleanups + Pattern I round. If R2 misses (< +5), R3 is a fallback round on defects only.