# Round 2 — Reviewer Output

> Evaluates the Round 2 Researcher's proposals (Patterns A, F, L, I, J, K, M)
> against the v5.0 surface (per `agent_state/round_1/05_main_judgment.md`).
> Goal: ship ≤3 patterns this round that produce a *measurable* Δ against the
> Round-1 baseline (69.5 / 100) using `evaluation/score_consistency.py`.

---

## 0. Working-tree vs task framing (one-time housekeeping note)

The task description frames v5.0 as the live state and the Researcher's
proposals as pending. The on-disk working tree, however, already contains a
v6.0-labeled surface:

- `scripts/fill_docx.py:3` declares `v6.0`; `SKILL.md:3` declares `version: "6.0"`.
- `scripts/model_adapter.py` exists (`StubAdapter` + `OpenAICompatibleAdapter`,
  uses `openai>=1.0` + `instructor>=1.0`).
- `evaluation/schemas.py` exists with 3 Pydantic models
  (优秀团员申报表 / 奖学金申请表 / 个人简历) and `find_schema_for_label()`.
- `scripts/fill_docx.py:160–187` ships `_redact()` (PII masking) and `_redact_label()`.
- `scripts/fill_docx.py:104–153` ships `scan_docx_introspect()` (Pattern J-style).
- `tests/test_fill_docx.py` and `tests/test_score_consistency.py` exist (R2-A6).
- `requirements.txt` lists `pydantic`, `openai`, `instructor` as optional.

This reviewer writes against the **task-framed v5.0 baseline** because that
is what `01_researcher.md` was written against, and because the Optimizer
needs a clean v5.0 → v6.0 spec it can either (a) keep the in-tree v6.0
features that already align with the spec, or (b) reset to v5.0 and re-apply
in a tighter shape. Both paths are valid; §4 below describes the *narrowest*
v5.0-clean way to deliver the proposed Δ.

**Dependencies that already exist in the environment** (verified at review
time, not assumed): `pydantic 2.12.0`, `openai 2.38.0`, `instructor 1.17.0`.
Pydantic's hard runtime deps are 4: `annotated-types`, `pydantic-core`,
`typing-extensions`, `typing-inspection` (+ 2 conditional extras:
`email-validator`, `tzdata`). This is comfortably below the task's ≤5
transitive-deps ceiling, so Pattern A's Pydantic adoption is **free of new
install cost** when these packages are already present.

---

## 1. v5.0 Code Health Snapshot

### 1.1 What's working from Round 1 (preserve verbatim)

| Capability | Location | Status |
|---|---|---|
| Reflexion plumbing (`--reflexion-rounds`) | `scripts/fill_docx.py:316–321`; `_stub_reflect` returns `""` | Working — stub returns `""`, `_reflect_impl` injects test doubles. |
| `profile.md` intermediate spec | `scripts/fill_docx.py:334–431` (`write_profile_md`); `--write-profile` flag at `scripts/fill_docx.py:727–728` | Working — produces `profile.md` + `profile_v{N}.md` next to output; SHA-256 returned. |
| Audit-table render | `scripts/fill_docx.py:438–532` (`render_audit_table`); `--audit-out` flag at `scripts/fill_docx.py:723–724` | Working — emits real markdown file with 7 sections; legacy CLI writes audit by default. |
| 9-rule eval harness | `evaluation/score_consistency.py:148–158` (R1–R9) | Working — emits valid JSON; demo = 100/100. |
| Rule-layer regression test | `scripts/validate_rules.py:44–81` (3 mock fixtures); `tests/fixtures/{simple,merged_cell,multi_match}.docx` | Working — exits 1 by intent (one FAIL sentinel). |
| Match-rules table | `scripts/fill_docx.py:272–291` (18 regex rules) | Working, but first-match-wins (defect #2 from Round-1 Reviewer §1 is still live). |

### 1.2 What's still broken / missing in v5.0 (citations)

| # | Gap | Citation | Severity |
|---|---|---|---|
| **G1** | `_stub_reflect` is a no-op (returns `""`) — real `reflect()` LLM hook was explicitly deferred from R1 (see `round_1/05_main_judgment.md` Round-1 backlog item 2). | `scripts/fill_docx.py:316–321` | **High** — blocks any real reflexion value. |
| **G2** | No structured-output substrate. Every AI-generated field is produced by free-form text; R8 (word-limit) only fires *after* the fact. | `scripts/fill_docx.py` AI-gen path emits raw string; `evaluation/score_consistency.py:128–136` (R8 = post-hoc `len > 2000` check) | **High** — Round-1 Reviewer defect #5 still open. |
| **G3** | First-match-wins `match_field()` (defect #2) — `学历专业` resolves to `学历\|年级` not `专业`. | `scripts/fill_docx.py:285` (rule order); confirmed by `round_1/04_tester.md` §2 R1-A5 trace | **Medium** — surfaces as WARN in `validate_rules.py` fixture `ambiguous_first_match`; no test currently asserts the wrong behavior. |
| **G4** | `_find_value_cell()` right-then-down heuristic only (defect #3 from Round-1 Reviewer). | `scripts/fill_docx.py:679–693` | **Medium** — silent data loss for below-left and 2-cell-over layouts. |
| **G5** | `audit.md` writes PII in cleartext (phone / email / ID / bank) — privacy gap, Round-1 Reviewer §1 defect. | `scripts/fill_docx.py:454–459` (raw `value` written to audit) | **Medium-High** — Round-1 backlog item 5. |
| **G6** | No provider abstraction. There is no seam to attach any LLM without touching `fill_docx.py`. | `scripts/fill_docx.py:316–327` (`reflect` only; no `generate`) | **High** — blocks Pattern A from having any caller. |
| **G7** | No persistent record of LLM calls. Each run starts from zero; Round-3 Reviewer cannot query "which prompt changed". | n/a (absent) | **Medium** — measurement substrate for future rounds. |
| **G8** | `evaluate()` vs `score()` naming drift (Round-1 backlog item 4). | `evaluation/score_consistency.py:315–322` (5.0: only `evaluate()` exists) | **Low** — cosmetic. |
| **G9** | `parse_audit_md` only reads the field-detail table, not the rendered status-counts summary table. | `evaluation/score_consistency.py:239–294` | **Low** — `fill_rate_pct` still computable from `details`, but a richer parse is feasible. |
| **G10** | `.profile_counter` gitignore entry exists, but no `.gitignore` rule for any future SQLite log file. | `.gitignore:22` (only `.profile_counter`) | **Low** — preventive. |
| **G11** | `score_consistency.py --audit` is invoked on a markdown file, not directly on `(profile, audit)` pairs; the v5.0 demo path silently uses synthetic data when `--audit` is missing. | `evaluation/score_consistency.py:366–373` | **Low** — by-design, but couples the demo to silence. |
| **G12** | No schema-aware regex source-of-truth. `match_rules` regex patterns and `score_consistency.py` regex constants (`PHONE_RE`, `EMAIL_RE`, `STUDENT_ID_RE`) duplicate the same patterns. | `scripts/fill_docx.py:281` (`r"邮箱\|电子邮件"`); `evaluation/score_consistency.py:27–29` (`EMAIL_RE`); `evaluation/score_consistency.py:84–111` (R4/R5/R6) | **Medium** — schema-as-prompt would unify these. |

### 1.3 New gaps introduced or surfaced by Round 1 (carryover)

- **`_stub_reflect` no-op confirmed live.** Round-1's R1-A1 wired the
  plumbing (`--reflexion-rounds`, `for _ in range(reflexion_rounds)` loop,
  `reflection` column in audit) but the underlying call returns `""`. The
  test at `tests/test_fill_docx.py:211–221` (already in tree) asserts this
  no-warning behavior for `StubAdapter`; this is correct v5.0 surface and
  must not regress.
- **Match-rule ordering frozen.** R1 did not touch `match_rules`, so defect
  #2 from `round_1/02_reviewer.md §1` is still observable in
  `validate_rules.py --mock` output (`WARN ambiguous_first_match`).
- **Audit emission is on by default now** (R1-A3). v4.0 users who relied on
  stdout-only output will see a new `{output}_audit.md` file; this is
  documented and the `.gitignore` already excludes it.

### 1.4 Score estimate at the v5.0 baseline

Mirroring the Round-1 Reviewer's 5-dimension weighting (Skill 25 / Code 20 /
Robust 20 / Eval 25 / Privacy 10):

| Dimension | v4.0 (R0) | v5.0 (R1) | R1 Δ | Source |
|---|---:|---:|---:|---|
| Skill spec completeness | 80 | 84 | +4 | Step 2.5 + Step 5.5 prose added |
| Code quality of `fill_docx.py` | 62 | 67 | +5 | profile.md, audit render, reflexion plumbing |
| Robustness to edge cases | 55 | 58 | +3 | validate_rules.py; multi-match WARN visible |
| Evaluation / testability | 25 | 62 | +37 | score_consistency.py (9 rules) + fixtures |
| Privacy & UX | 78 | 80 | +2 | audit file always emitted; .gitignore grown |
| **Weighted total** | **57.45** | **69.50** | **+12.05** | matches `round_1/05_main_judgment.md` |

This is the **starting point** Round 2 should improve on.

---

## 2. Pattern-by-Pattern Evaluation

Scoring scale:
- **Applicability:** high (gap clearly present in v5.0), medium (partial gap
  or already partially mitigated), low (no gap or wrong scope).
- **Effort:** S = ≤0.5 day, M = 0.5–1.5 days, L = ≥2 days.
- **Impact:** high (≥+5 score points), medium (+2 to +5), low (<+2 or unmeasurable).
- **Risk:** low / medium / high.

| # | Pattern | Applicability | Effort | Impact | Risk | **Verdict** | One-line reason |
|---|---|---|---|---|---|---|---|
| **A** | Schema-as-Prompt (Pydantic) | **High** (gaps G2, G12) | **M** (~150 LOC across `templates/schemas/*.py` + `scripts/schema_gen.py` + wiring) | **High** (+5 via R10–R12) | **Low** — Pydantic 4 transitive deps, already-installed in env per §0 | **INCLUDE** | v5.0 has zero structured-output substrate; this is the structural fix that lets R8/R4/R5 become compile-time-impossible. |
| **F** | Provider-Agnostic Adapter | **High** (gaps G1, G6) | **M** (~120 LOC, stdlib only per Researcher §3.2; + adapter factory + 4 CLI flags + replace `_stub_reflect`) | **High** (+2 via R13; unlocks A's caller) | **Medium** — needs careful default-handling so v5.0 stub path is byte-identical | **INCLUDE** | Without this seam, `_stub_reflect` stays a no-op forever and Pattern A has no caller. |
| **L** | SQLite Logging | **Medium** (gap G7) | **S** (~50 LOC, stdlib `sqlite3`; 1 CLI flag) | **Medium** (+1 via R14; precondition for R3 attribution scoring) | **Low** — stdlib; gitignore one-line addition | **INCLUDE** (if scope permits) | Cheapest, most future-proof win; cheap enough to bundle with A+F. |
| **I** | Validation-Repair-Retry Loop | **Medium-High** (depends on A) | **S** (one extra parameter on `generate_structured()`) | **Medium** (+1–2 to A's impact) | **Low** (cap with `max_retries=2`) | **INCLUDE** (fold into A) | It's not a standalone action — it's the retry hook *inside* Pattern A's generator. Bundled with R2-A2. |
| **J** | Schema-Guided JSON Repair (json_repair) | **Low** | **S** (~30 LOC + optional `json_repair` PyPI dep) | **Low** (<+1; catches last 5% of edge cases) | **Low-Medium** — adds a dep for marginal benefit | **DEFER** | Premature: v5.0 has zero LLM calls; we don't yet know how often A's retry alone is insufficient. Defer to R3 once we have real call data. |
| **K** | Trajectory Tracing (deepeval) | **Low** | **M** (refactor `fill_docx()` to emit trace events; new `traces/` dir) | **Low** (doesn't add measurable score) | **Low** | **DEFER** | v5.0 audit table is sufficient for scoring; trajectory is overkill before any LLM call exists. |
| **M** | Provider Failover Chains | **Low** | **M** (config schema + retry loop) | **Low** (production reliability, not correctness) | **Low** | **DEFER** | Failover without a primary is meaningless. Wait until Pattern F has at least one run of real data. |

**Verdict summary:** 4 INCLUDE (A, F, L, I — with I folded into A), 3 DEFER (J, K, M).

The Researcher recommended A + F + L as the Top-3. **I concur on the Top-3** and add Pattern I as a non-separate companion of Pattern A. The Researcher's Anti-pattern 1 (LiteLLM 30-transitive-deps) is endorsed; the Reviewer reinforces Anti-pattern 2 (avoid Outlines-only constrained decoding — OpenAI/Ollama cloud don't support logit masks).

**Researcher-vs-Reviewer disagreement on Anthropic.** The Researcher's §3.2 hand-rolled adapter has explicit Anthropic support (~30 LOC of `_anthropic_call`). For Round 2, this is dead weight: v5.0 has no Anthropic caller, the Ollama-compatible path is the documented privacy-first target, and Anthropic support doubles the surface area the Optimizer must test. **Recommendation: drop Anthropic support in R2-A1**; add back in R3 if/when a user requests it. The adapter remains `<provider>:<model>`-compatible (per aisuite convention) so Anthropic drops in cleanly later.

---

## 3. Measurability Analysis — R10–R14

For each rule the Researcher proposed, check: (1) is the rule encodable in
`evaluation/score_consistency.py`? (2) what input does it need? (3) do we
have that input today? (4) effort to add.

| New rule | Feasibility | Input required | Have today? | Effort | Notes |
|---|---|---|---|---|---|
| **R10_schema_compliance** | Yes | `details[i].schema_ref` (e.g., `"templates/schemas/优秀团员申报表.py:优秀团员申报表.手机"`) | No — v5.0 audit detail dict has `label, value, source, status, reflection` only. | **S** (~30 LOC: add `schema_ref` to detail dict when AI-gen matches a schema; new rule function reads schema via soft import, re-validates `value` with `model_validate_json`, returns fail/pass) | Soft import (`try: from pydantic import BaseModel; from importlib import import_module; ...`) — missing dep → rule returns `warn` with "pydantic not installed". |
| **R11_word_limit_within_field_type** | Yes | Same `schema_ref` link | No — same as R10 | **S** (covered by R10's machinery: re-validate via Pydantic, count violations of `min_length`/`max_length`) | Differs from R8 by being *per-field-typed* — R8 fires on `len > 2000`, R11 fires on per-schema bound. |
| **R12_literal_enum_compliance** | Yes | Same `schema_ref` link | No — same | **S** (covered by R10's machinery: Pydantic `Literal[...]` validation catches off-enum values) | Catches "性别=男性" when schema says `Literal["男","女"]`. |
| **R13_provider_log_present** | Yes | `details[i].model_id` (e.g., `"stub"` / `"openai-compatible:MiniMax-M3"`) | No — v5.0 audit detail has no `model_id` | **S** (~15 LOC: rule reads any detail with `status="📝"` or `"⚠️"`; checks for `model_id` key; returns warn if absent) | Severity = **warn** (not blocking) — R13 signals capability presence, not correctness. Stub mode yields `"stub"` and passes. |
| **R14_log_correlation** | Yes | `audit.md` frontmatter carries `fill_run_id` UUID; SQLite at `--log-db` has a row keyed by that UUID | No — v5.0 has no `fill_run_id` and no `--log-db` | **S** (~25 LOC: rule reads `audit.md` frontmatter for `fill_run_id`; if `--log-db` path passed via CLI flag, opens SQLite and checks for matching `fill_run_id`; returns warn if absent) | Depends on Pattern L. Severity = **warn**. |

**Effort total for R10–R14:** ~70 LOC across 5 small rule functions + 1 schema-lookup helper. All 5 are **additive** to the existing 9 (R1–R9) — no existing rule is replaced. The `RULES` tuple at `evaluation/score_consistency.py:148–158` grows from 9 entries to 14.

**We have everything needed *except* the carrier data.** R10–R12 need `schema_ref` written into the audit detail; R13 needs `model_id`; R14 needs `fill_run_id`. All three are produced by the three Optimizer actions in §4.

**One concern the Researcher missed:** `details[i]` is currently a `dict`
serialized by `render_audit_table` at `scripts/fill_docx.py:654–660`. Adding
3 new keys (`schema_ref`, `model_id`, `fill_run_id`) means the rendered
audit markdown's field-detail table at `templates/audit_table.md:17–19` needs
3 new columns OR the new keys live in audit JSON sidecar. The
lower-friction path is a sidecar: emit `audit.json` next to `audit.md`
with the same data + the new keys, and have R10–R14 read from JSON.
**Recommendation: do the sidecar.** It avoids breaking the human-readable
markdown format and keeps the score harness machine-readable.

---

## 4. Round 2 Scope — concrete deliverables (max 3 actions)

The Round-2 ship targets **exactly 3 Optimizer actions**, each with file
citations, line ranges, exact changes, new harness rules, acceptance
criteria, and a backwards-compat note. **R2-A1 first** (foundation),
**R2-A2 second** (the structural fix on top), **R2-A3 third** (the
measurement substrate).

### R2-A1 — Provider-Agnostic Adapter (Pattern F, stdlib only)

**Files to change**
- **NEW** `scripts/model_adapter.py` (~120 LOC, stdlib `urllib` + `json` + `os`).
- `scripts/fill_docx.py`:
  - Lines 316–327 (v5.0: `_stub_reflect` + `reflect` aliases): leave `_stub_reflect` body unchanged (it's already a back-compat alias), but ensure `main()` instantiates an adapter and threads it into the inner loop. The `_reflect_impl=` injection path stays — that's how `tests/test_fill_docx.py:79–82` works.
  - Lines 715–745 (v5.0: argparse `main()`): add 4 flags — `--provider {stub,openai-compatible}`, `--llm-base-url`, `--llm-api-key`, `--llm-model-name`. Defaults: `--provider stub`, env-var overrides for the rest.
  - Lines 554–580 (v5.0: `fill_docx()` signature): add `adapter=None` kwarg; if `None`, instantiate `StubAdapter()` so existing callers (e.g., `tests/test_fill_docx.py:198`) are unchanged.
- **NEW** `tests/test_model_adapter.py` (~50 LOC, stdlib `unittest`): asserts `StubAdapter().reflect()` returns `""`; asserts `--provider bogus` raises `ValueError`; asserts Ollama-style base URL is accepted.

**Exact changes**

1. `scripts/model_adapter.py` (new) implements:
   - `class StubAdapter`: `reflect(...) -> ""`, `generate(...) -> ""`, `name = "stub"`.
   - `class OpenAICompatibleAdapter`: `_openai_call(system, user, response_format=None, max_retries=3)` via `urllib.request.Request` to `{base_url}/chat/completions`. No `instructor`, no Pydantic on this path — pure stdlib.
   - `def get_adapter(provider: str, **kw) -> ModelAdapter`: factory; `(provider in {"stub","none","offline"})` → `StubAdapter()`; otherwise `OpenAICompatibleAdapter`.
   - **Drop the Anthropic branch** from the Researcher's §3.2 recipe — R2 scope is Ollama-compatible only.
   - **Default `base_url`** for `openai-compatible` provider: `http://localhost:11434/v1` (Ollama default, the documented privacy-first target in SKILL.md:485–503).

2. `scripts/fill_docx.py` modifications:
   - At top: `from model_adapter import StubAdapter, get_adapter`.
   - `_stub_reflect` body unchanged (already a back-compat alias).
   - `fill_docx()`: add `adapter=None` kwarg; if None, default to `StubAdapter()`. **This preserves the existing test signature `fill_docx(..., adapter=StubAdapter())` byte-identically.**
   - `main()`: instantiate adapter via `get_adapter(provider=args.provider, base_url=args.llm_base_url, api_key=args.llm_api_key, model_name=args.llm_model_name)`. Print `adapter.name` and `adapter.is_live()` to stdout (informational).

3. New tests:
   - `tests/test_model_adapter.py::TestStubAdapter::test_reflect_empty` (mirrors `tests/test_fill_docx.py:79–82`).
   - `tests/test_model_adapter.py::TestGetAdapter::test_unknown_raises`.
   - `tests/test_model_adapter.py::TestGetAdapter::test_stub_default`.

**New harness rules:** none directly. R2-A1 is the *seam*; rules R13 (model_id presence) and R10 (schema_ref) are wired by R2-A2 and R2-A3.

**Acceptance criteria (Tester will check)**
- `python scripts/fill_docx.py --help` lists `--provider`, `--llm-base-url`, `--llm-api-key`, `--llm-model-name`. Help still works without any LLM key set.
- `python scripts/fill_docx.py --template <fixture> --profile-dir ./profiles --output /tmp/o.docx` (no `--provider`) runs end-to-end with `StubAdapter` and produces identical audit bytes to v5.0 (the `_stub_reflect` no-op path is preserved).
- `python scripts/fill_docx.py --provider bogus` exits 2 (argparse reject).
- `python -m unittest tests/test_model_adapter.py -v` passes all assertions.
- `python -m unittest tests/test_fill_docx.py -v` still passes (no regression — `adapter=StubAdapter()` keyword preserved).

**Backwards-compat**
- `--reflexion-rounds` default = `0` (unchanged).
- `--write-profile` default = False (unchanged).
- `--audit-out` default = None (unchanged).
- New flags all have safe defaults; `--provider stub` is the implicit v5.0 behavior.
- The `_reflect_impl=` injection path in `fill_docx()` is preserved unchanged, so existing test doubles still work.

**Anti-pattern check:** This action adds **zero new pip deps**. `urllib.request` is stdlib. Compatible with the task's "no new heavy deps" rule.

---

### R2-A2 — Schema-as-Prompt with Pydantic (Pattern A + Pattern I)

**Files to change**
- **NEW** `templates/schemas/__init__.py` (~5 LOC, empty).
- **NEW** `templates/schemas/excellent_youth_league.py` (~80 LOC) — single Pydantic `BaseModel` with fields taken from `scripts/fill_docx.py:272–291` `match_rules` regex set, encoded as `Field(min_length=, max_length=, pattern=, description=)` plus `Literal["男","女"]` for `性别`, `Literal["共青团员","中共党员","预备党员","入党积极分子","群众"]` for `政治面貌`, etc.
- **NEW** `scripts/schema_gen.py` (~120 LOC):
  - `schema_to_prompt(model_cls) -> str`: converts `model.model_json_schema()` to a human-readable constraint list (per Researcher's §2.2 step 3 code sketch — keep it ≤80 LOC).
  - `generate_structured(prompt, schema, adapter, max_retries=2) -> schema_instance`: validate-and-retry loop (Pattern I). On final failure, returns `None` and the caller falls back to the existing free-form prompt path.
  - `find_schema_for_label(label: str) -> Optional[Type[BaseModel]]`: best-effort substring match, mirroring the on-disk `evaluation/schemas.py:115–125` logic.
- `scripts/fill_docx.py`:
  - Lines 49–53 (v5.0: empty stub for `SCHEMAS`): replace with `try: from schema_gen import generate_structured, find_schema_for_label; except ImportError: ...`.
  - Lines 554–580 (v5.0: `fill_docx()` signature): add `schema_ai_generate: bool = True` kwarg (default on; user can pass `False` to disable).
  - Lines 600–669 (v5.0: per-cell processing loop): for each AI-gen candidate field (detected by label keyword like `自荐信` / `个人陈述` / `申请理由`), if `schema_ai_generate=True` AND `find_schema_for_label(label)` returns a schema AND `adapter.is_live()`, call `generate_structured(...)`. On success, write the validated value. On failure or schema-miss, fall back to the existing prompt-and-write path (preserves v5.0 behavior).
  - Lines 654–660 (v5.0: audit detail dict construction): add `"schema_ref"` key when a schema was matched, e.g., `"templates/schemas/excellent_youth_league.py:ExcellentYouthLeagueForm.手机"`. Add `"model_id"` key = `adapter.name + (":" + adapter.model_name if adapter.is_live() else "")`.
- **NEW** `tests/test_schema_gen.py` (~60 LOC):
  - Assert `schema_to_prompt(ExcellentYouthLeagueForm)` contains `"手机"`, `"pattern: ^1\\d{10}$"`, `"Literal["男","女"]"`.
  - Assert `find_schema_for_label("手机")` returns the schema class; `find_schema_for_label("xyz_nonexistent")` returns `None`.
  - Assert `generate_structured(...)` returns the instance on a valid JSON; returns `None` after `max_retries` on invalid JSON.

**Exact changes (high-level)**

```python
# scripts/schema_gen.py (skeleton — full code follows Researcher's §2.2 step 3)
from typing import Type, Optional
from pydantic import BaseModel

def schema_to_prompt(model: Type[BaseModel]) -> str:
    schema = model.model_json_schema()
    bits = ["Output ONLY valid JSON matching this schema:"]
    for name, spec in schema.get("properties", {}).items():
        line = f"  - {name} ({spec.get('type', 'any')})"
        if "pattern" in spec: line += f"  pattern: {spec['pattern']}"
        if "enum" in spec:    line += f"  one of: {spec['enum']}"
        if "minLength" in spec or "maxLength" in spec:
            line += f"  length: [{spec.get('minLength','-')}, {spec.get('maxLength','-')}]"
        if "minimum" in spec or "maximum" in spec:
            line += f"  range: [{spec.get('minimum','-')}, {spec.get('maximum','-')}]"
        if spec.get("description"): line += f"  desc: {spec['description']}"
        bits.append(line)
    return "\n".join(bits)

def generate_structured(prompt, schema, adapter, max_retries=2):
    sys_prompt = schema_to_prompt(schema)
    last_err = None
    for attempt in range(max_retries + 1):
        user = prompt + (f"\n\n[previous attempt failed: {last_err}]" if last_err else "")
        raw = adapter.generate(system=sys_prompt, user=user,
                               response_format={"type": "json_object"})
        if not raw:
            return None
        try:
            return schema.model_validate_json(raw)
        except Exception as e:
            last_err = str(e).splitlines()[0]
    return None  # caller falls back to free-form
```

**New harness rules:** **R10_schema_compliance**, **R11_word_limit_within_field_type**, **R12_literal_enum_compliance**. All three share the `schema_ref` carrier; all three use a soft-import of Pydantic and a generic schema lookup helper. Implementation lives in `evaluation/score_consistency.py` as new functions `rule_schema_compliance`, `rule_word_limit_typed`, `rule_literal_enum`; they append to the `RULES` tuple at line 148–158. The three functions can share a `_load_schema(schema_ref)` helper (~10 LOC).

**Acceptance criteria**
- `python -c "from scripts.schema_gen import schema_to_prompt, generate_structured, find_schema_for_label; print('ok')"` prints `ok`.
- `python -m unittest tests/test_schema_gen.py -v` passes.
- A demo end-to-end run with `--provider stub` (no LLM) on a fixture still completes; audit `details[i].schema_ref` is `None` for non-AI fields and the field name for matched AI-gen fields.
- `python evaluation/score_consistency.py --audit <new_audit.md>` reports `rule_results` with **14 entries** (R1–R14) when audit was produced with R2-A2; **9 entries** when audit was produced by v5.0 (additive — no rule is dropped).

**Backwards-compat**
- Soft import: missing Pydantic → `find_schema_for_label` returns `None` → AI-gen path falls back to free-form prompt → v5.0 behavior preserved.
- `--no-schema-ai` flag (new) lets users explicitly disable Pattern A.
- `find_schema_for_label("手机")` returns `None` for any label not present in `templates/schemas/excellent_youth_league.py` — v5.0 fields outside the schema are unaffected.

**Anti-pattern check:** Pydantic's 4 transitive deps (`annotated-types`, `pydantic-core`, `typing-extensions`, `typing-inspection`) are within the ≤5 ceiling. The on-disk env already has them installed (§0). **No new pip install required** for users who already have Pydantic.

---

### R2-A3 — SQLite Logging + Audit JSON Sidecar (Pattern L + R13/R14 carriers)

**Files to change**
- **NEW** `scripts/prompt_log.py` (~80 LOC, stdlib `sqlite3`):
  - `init_db(path: str) -> sqlite3.Connection`: creates `llm_calls` table with columns `(id, ts, fill_run_id, model, provider, schema_ref, prompt, response, tokens_in, tokens_out, latency_ms)`. Idempotent (`CREATE TABLE IF NOT EXISTS`).
  - `log_call(conn, **fields) -> None`: single-row insert.
  - `query_by_run(conn, fill_run_id) -> list[dict]`: fetch all calls for a run.
- `scripts/model_adapter.py`:
  - `OpenAICompatibleAdapter.generate()`: wrap the `urllib.request.urlopen` call in `time.perf_counter()` instrumentation; after success, if a `_conn` attribute is set (injected by `fill_docx`), call `log_call(...)`.
- `scripts/fill_docx.py`:
  - Lines 554–580 (`fill_docx()` signature): add `log_db_path: str = None` and `fill_run_id: str = None` kwargs. If `fill_run_id is None`, generate `uuid.uuid4().hex`.
  - Lines 715–745 (`main()` argparse): add `--log-db PATH` (default = `./profiles/llm_log.sqlite`).
  - Lines 654–660 (audit detail dict): add `"fill_run_id"` key.
  - After `fill_docx()` returns in `main()`: write `audit.json` sidecar at `{audit_path}.json` with the full audit dict (including `schema_ref`, `model_id`, `fill_run_id`).
- `evaluation/score_consistency.py`:
  - New rule **R13_provider_log_present** (~15 LOC): iterate `details`; for any detail with `status="📝"` or `"⚠️"`, check `model_id` key presence; warn if absent.
  - New rule **R14_log_correlation** (~25 LOC): read `--llm-log` CLI flag (default None); if set and audit JSON sidecar is present at `{audit_path}.json`, open SQLite, look up `fill_run_id`; warn if no row.
  - `parse_audit_md` extended to read 3 new columns from the field-detail table OR fall back to `audit.json` sidecar if present (sidecar preferred when both exist).
- `.gitignore`: add one line — `profiles/llm_log.sqlite*` (matches `*.sqlite`, `*.sqlite-journal`, `*.sqlite-wal`, `*.sqlite-shm`).
- **NEW** `tests/test_prompt_log.py` (~40 LOC): asserts `init_db` is idempotent; asserts `log_call` then `query_by_run` returns the row.

**Exact changes (high-level)**

```python
# scripts/prompt_log.py (skeleton)
import sqlite3, time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    fill_run_id TEXT NOT NULL,
    provider TEXT, model TEXT, schema_ref TEXT,
    prompt TEXT, response TEXT,
    tokens_in INTEGER, tokens_out INTEGER, latency_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_run ON llm_calls(fill_run_id);
"""

def init_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

def log_call(conn, *, fill_run_id, provider, model, schema_ref,
             prompt, response, tokens_in, tokens_out, latency_ms):
    conn.execute(
        "INSERT INTO llm_calls (ts, fill_run_id, provider, model, schema_ref,"
        " prompt, response, tokens_in, tokens_out, latency_ms) VALUES"
        " (datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fill_run_id, provider, model, schema_ref,
         prompt, response, tokens_in, tokens_out, latency_ms),
    )
    conn.commit()

def query_by_run(conn, fill_run_id):
    cur = conn.execute(
        "SELECT * FROM llm_calls WHERE fill_run_id = ? ORDER BY id",
        (fill_run_id,),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
```

**New harness rules:** **R13_provider_log_present**, **R14_log_correlation**.

**Acceptance criteria**
- `python -m unittest tests/test_prompt_log.py -v` passes.
- `python scripts/fill_docx.py --template <fixture> --profile-dir ./profiles --output /tmp/o.docx --log-db /tmp/log.sqlite` runs end-to-end; after the run, `/tmp/log.sqlite` exists; `sqlite3 /tmp/log.sqlite "SELECT COUNT(*) FROM llm_calls"` returns `0` (stub path) or `>0` (live path).
- `python scripts/fill_docx.py ... --log-db /nonexistent/dir/log.sqlite` does NOT crash (parent dirs are auto-created).
- `python evaluation/score_consistency.py --audit /tmp/o_audit.md` produces a JSON with 14 `rule_results` rows.
- The `.gitignore` change is one line; `git status` after a fill run does not show `llm_log.sqlite*` as untracked.

**Backwards-compat**
- `--log-db` default = `./profiles/llm_log.sqlite`, but the file is **only created** if at least one LLM call is made; v5.0 stub mode produces no calls → no file → `.gitignore` is preventive only.
- `fill_docx()` `log_db_path=None` and `fill_run_id=None` defaults preserve all existing test signatures.
- `audit.json` sidecar is *additive* — existing `audit.md` consumers (humans reading the markdown) are unaffected.

**Anti-pattern check:** stdlib `sqlite3` only — zero new pip deps.

---

### R2-A1 + A2 + A3 combined acceptance (Tester checklist)

After all three actions land, the following must hold:

1. **All v5.0 tests pass unchanged.** `python -m unittest tests/test_fill_docx.py tests/test_score_consistency.py -v` exits 0.
2. **New tests pass.** `python -m unittest tests/test_model_adapter.py tests/test_schema_gen.py tests/test_prompt_log.py -v` exits 0.
3. **`--help` works without LLM keys.** `python scripts/fill_docx.py --help` exits 0.
4. **Stub-mode end-to-end runs are byte-identical to v5.0** for `audit.md` content (modulo the new `audit.json` sidecar which is additive). The `_stub_reflect` no-op path is preserved.
5. **`validate_rules.py --mock` exits 1 by intent** (unchanged from v5.0) — the `missing_value` fixture is still a FAIL sentinel.
6. **`score_consistency.py` emits 14 `rule_results` entries** when scoring an audit produced by R2; emits 9 when scoring a v5.0 audit (additive rule growth).
7. **No new pip deps for the default install path.** `pip install python-docx pyyaml` is sufficient for the stub-mode default. Pydantic is the optional new dep, gated behind the existing soft-import pattern.
8. **One-line `.gitignore` change** (the `llm_log.sqlite*` rule).
9. **Zero changes to `evaluation/score_consistency.py` existing rules.** R1–R9 are byte-identical.
10. **SKILL.md adds ≤40 lines** (a new `### Step 5A: Schema-constrained 路径` subsection). No existing prose is removed or moved.

---

## 5. Backlog (DEFER items for Round 3)

| Pattern | Why defer | Suggested Round-3 framing |
|---|---|---|
| **J — Schema-Guided JSON Repair** | Premature: v5.0 has zero LLM calls. Don't pay the dep cost until Pattern A has been exercised on at least one real model and we have data on retry-exhaustion rate. | R3 candidate: re-evaluate after R2 ships; if R10 failure rate > 5%, add Pattern J as `max_retries` final fallback. |
| **K — Trajectory Tracing** | Overkill for current scope. The audit table + JSON sidecar from R2-A3 is the trajectory for now. | R3 candidate: only if a debuggability crisis emerges in R2 (e.g., a scoring regression with no root cause visible in the audit). |
| **M — Provider Failover Chains** | Failover without a primary is meaningless. Wait until Pattern F has at least one run of real data. | R3 candidate: add `--fallback-models` flag + retry loop in `OpenAICompatibleAdapter.generate()`. |
| **Round-1 Reviewer defect #2 (first-match-wins)** | Requires lookup-by-schema before regex — naturally fits Pattern A. Now feasible in R3 because R2-A2 ships schemas. | R3-A1 (per `loop_config.json` `round_3_priorities`): `find_schema_for_label()` before `match_rules` regex scan. |
| **Round-1 Reviewer defect #3 (right-then-down heuristic)** | Needs XML-tree iteration; orthogonal to Pattern A. | R3-A2: iterate XML tree once instead of row/col double-loop. |
| **PII redaction in audit.md** | The on-disk v6.0 has `R2-A4` but the Researcher did not propose it. Reviewer note: G5 is real, but the score harness doesn't measure PII leakage (no rule in R1–R14). | R3 candidate: add `_redact()` to `render_audit_table` at `scripts/fill_docx.py:438`. |
| **Cosmetic `evaluate()` → `score()` rename** | Already done on-disk (R2-A5). Not in Researcher proposals. | N/A — already shipped. |
| **More Pydantic schemas** | The on-disk `evaluation/schemas.py` ships 3 schemas (优秀团员申报表, 奖学金申请表, 个人简历). R2 only needs the first to prove the substrate. | R3-A4 per `loop_config.json`: add 入党申请书 / 学位论文申请表 / 实习鉴定表. |
| **Real-LLM smoke test** | Requires network + an API key in CI. Out of scope for a code-only review. | R3-A5 per `loop_config.json`. |

---

## 6. Stop Conditions / Escalation

The Optimizer should STOP and escalate to the Main Agent if any of these
become true mid-implementation:

1. **Pydantic not importable in the target environment despite §0 evidence.**
   If `python -c "import pydantic; print(pydantic.__version__)"` fails in
   the Optimizer's environment, Pattern A's substrate is gone and the
   soft-import fallback path must be the *primary* implementation. R2-A2
   then becomes "ship `templates/schemas/` as a documented future capability,
   do not wire into `fill_docx()`". Escalate.

2. **Schema-to-label matching rate < 50%.** If the Optimizer's first cut of
   `find_schema_for_label()` matches fewer than half of the demo profile's
   labels against `templates/schemas/excellent_youth_league.py`, the schema
   coverage is too narrow to be useful as a substrate. Either expand the
   schema (add 5–10 more fields) or accept a low match rate and continue.
   If match rate stays < 30% after one expansion pass, the schema is wrong;
   do NOT ship R10–R12 with this failure mode. Escalate.

3. **`audit.json` sidecar breaks an existing test.** No existing test reads
   `audit.json`; if one does (e.g., added between R1 and R2), the sidecar
   contract must be negotiated before R2-A3 lands. The sidecar must be
   additive — never modify the existing `audit.md` schema beyond the
   pre-approved column additions.

4. **Stub-mode audit bytes diverge from v5.0.** This is the single hardest
   backwards-compat constraint. The Optimizer must diff v5.0 audit.md against
   the R2-ship audit.md in stub mode (`--provider stub`, no LLM calls) and
   confirm zero text changes. If they differ, the wiring in `fill_docx()`
   is over-eager — a label that didn't match before is now matching, etc.
   Roll back the offending branch and escalate.

5. **Test count regression.** Round 1's 8/8 tests must all pass. Round 2
   should add tests but never drop one. If a previously-passing test fails
   on the v5.0-baseline fixture inputs, the change is breaking v5.0
   contracts — STOP.

6. **`.gitignore` line added but `git status` still shows `llm_log.sqlite*`
   as untracked.** Indicates the pattern syntax is wrong (e.g., missing the
   trailing `*`). Fix or escalate.

7. **Total LOC growth > 600 across the 3 actions.** Indicates scope creep.
   Per-file ceilings: `model_adapter.py` ≤130 LOC; `schema_gen.py` ≤130 LOC;
   `prompt_log.py` ≤90 LOC; `fill_docx.py` delta ≤+80 LOC; `score_consistency.py`
   delta ≤+90 LOC; total ≤520 LOC. If exceeded, defer the lowest-priority
   feature (likely `audit.json` sidecar — write to sidecar in R3 instead).

---

## 7. Round 2 Scoring Plan

### 7.1 Apples-to-apples measurement

The Round-1 Tester correctly flagged (in `round_1/04_tester.md §5`) that
the v5.0 `score_consistency.py` score and the v4.0 baseline 57.45 are
incommensurable (different methodologies). For Round 2, **apples-to-apples
comparison requires running both v5.0 and v6.0 on the same input set, then
comparing scores**. The score harness itself grows additively from 9 to 14
rules, but the underlying 9 rules are byte-identical, so the comparison is
fair.

**Procedure (Tester runs both):**

1. Run `python scripts/fill_docx.py --template tests/fixtures/simple.docx
   --profile-dir ./profiles --output /tmp/v5.docx` on the v5.0 git tag,
   capture `audit.md`, score with `python evaluation/score_consistency.py
   --audit /tmp/v5_audit.md --profiles ./profiles`. Record score.

2. Checkout `main`, run the same command on the R2-shipped tree, capture
   `audit.md` (and `audit.json` sidecar), score with the new harness (14
   rules). Record score.

3. **The v5.0 score is the apples-to-apples baseline for Round 2's Δ.**

For a meaningful Δ, the Tester should also run the demo path (`python
evaluation/score_consistency.py` with no args) on both v5.0 and the R2 tree
and report both scores.

### 7.2 Artifact produced for the harness

- `audit.md` (unchanged format) — already produced by v5.0; carries the
  human-readable field-detail table + status counts.
- `audit.json` (NEW in R2-A3) — carries the same data + `schema_ref`,
  `model_id`, `fill_run_id` per detail. The 5 new rules (R10–R14) read
  from this sidecar.
- `tests/fixtures/llm_log.sqlite` (NEW in R2-A3) — produced only when at
  least one LLM call is made; R14 verifies `fill_run_id` correlation.

### 7.3 Realistic expected score range

Hypothesis: **Δ ≥ +5** against the v5.0 apples-to-apples baseline. The 5
new rules are warn-only by design (R13, R14) or fail-on-mismatch (R10,
R11, R12), so on the demo path the score should land **at or near 100**
because the demo data was hand-curated to satisfy all 14 rules. On real
inputs, R10–R12 may fail on legacy AI-gen fields until schemas catch up —
this is the *expected* baseline regression that motivates adding more
schemas in R3.

| Rule | Behavior on v5.0 audit | Behavior on R2 audit |
|---|---|---|
| R1–R9 | pass (unchanged) | pass (unchanged) |
| R10_schema_compliance | warn (no schema_ref carrier) | pass for matched fields; warn for unmatched |
| R11_word_limit_within_field_type | warn (no schema_ref) | pass for schema-typed fields |
| R12_literal_enum_compliance | warn (no schema_ref) | pass for fields with `Literal[...]` |
| R13_provider_log_present | warn (no model_id) | pass (every detail now has model_id) |
| R14_log_correlation | warn (no log_db) | warn (no LLM call in stub mode) |

**Predicted score on demo path:** **100 / 100** (R10–R14 all `warn` not
`fail`, so they don't deduct points).

**Predicted score on real end-to-end run with stub mode:** **100 / 100**
(same reasoning).

**Predicted score on a hypothetical run with a live LLM that emits valid
JSON matching schemas:** **100 / 100**.

**Predicted score on a hypothetical run with a live LLM that emits
off-enum gender (`"性别": "未知"`):** **80 / 100** (R12 fails; −20 per
`score_consistency.py:345` formula). This is the *desired* behavior — the
rule surfaces the bug.

**Predicted Δ vs v5.0 baseline:** **+5 to +10 score points** on the
5-dimension Reviewer weighting (per §1.4 methodology):
- Skill spec completeness: +3 (Step 5A section added)
- Code quality: +3 (model_adapter, schema_gen, prompt_log modules)
- Robustness: +2 (Pydantic catches off-enum, off-length values at source)
- Evaluation: +2 (3 new rule rows; sidecar enables machine-readable audit)
- Privacy: +1 (log gitignored; model_id lets users audit which model touched their data)

**Weighted Δ ≈ +2.0 +0.6 +0.4 +0.5 +0.1 ≈ +2.4** by the 5-dim weighting.
This is *below* the `loop_config.json` `min_quality_delta: 3` threshold if
strictly interpreted as apples-to-apples with the v5.0 baseline. **However**:
- The 5-dim Reviewer scoring is qualitative and subjective; the new
  harness's quantitative `score` is the more reliable metric.
- If the Tester can score a real LLM call on the demo profile with the
  new 14-rule harness, the score *should* be 100, same as v5.0 — so the
  harness-level Δ is ~0, but the *capability* delivered is enormous
  (real LLM-driven generation with schema validation is now possible).

**The honest framing for the Main Agent:** Round 2 is a *capability*
round, not a *score* round. The score harness has been extended to measure
the new capability (5 new rules), but until a real LLM is plugged in, the
harness-level delta is small. Round 3 can measure the real Δ once a live
LLM is wired in.

### 7.4 Exit criterion for Round 2

**Pass:** All 3 actions land; ≥10/10 new + existing unit tests pass; v5.0
stub-mode audit bytes are unchanged; `score_consistency.py` emits 14
rule_results; `loop_config.json.round_history[1]` records
`score_before: 69.5, score_after: ~71.5, quality_delta: ~+2.0,
main_judgment: CONTINUE, patterns_adopted: [A_partial, F, L], main_rationale: capability round, R3 to deliver defect fixes + more schemas + real-LLM smoke test`.

**Fail:** Any of the §6 stop conditions triggers; or any v5.0 test
regresses; or stub-mode audit bytes diverge from v5.0.

---

## Reviewer recommendation summary

**Ship R2-A1 + R2-A2 + R2-A3 in that order. That's Pattern F + A (with I folded in) + L — the Researcher's Top-3, slightly tightened.** Three concrete Optimizer actions, ~520 LOC total, zero new pip deps for the default install, all 5 new harness rules (R10–R14) feasible and additive, all v5.0 backwards-compat preserved, expected Δ ≈ +2 score points (capability round), with Round 3 positioned to land the real scoring Δ once a live LLM is wired in.

**End of Round-2 Reviewer output.**
