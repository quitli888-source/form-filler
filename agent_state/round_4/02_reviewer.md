# Round 4 — Reviewer Output

> Loop status: **TERMINATED** (per `loop_config.json`, max_rounds=3 already used). Per
> the user's explicit override, this Round 4 re-opens the loop. Effective loop_status
> for R4 = **ACTIVE**. Round 3 final score = **91.0** (Δ +33.55 cumulative from
> baseline 57.45). Goal of R4: ship 2-3 additive actions that raise the score without
> regressing v6.1's verified surfaces.

---

## 1. Researcher Top-5 Patterns (recap)

| pattern_id | name                                    | source (URL)                                  | complexity | impact      | R4 status   |
| ---------- | --------------------------------------- | --------------------------------------------- | ---------- | ----------- | ----------- |
| I1         | Retry-on-validation-failure             | jxnl/instructor (13.9k ⭐)                    | M (~+60)   | **High**    | **R4-A1**   |
| O1         | Literal-first deterministic routing     | dottxt-ai/outlines (15.8k ⭐) + microsoft/guidance (21.8k ⭐) | S (~+40)   | Medium      | **R4-A2**   |
| G2         | MockLLM backend (canned-response stub)  | microsoft/guidance (21.8k ⭐)                 | S (~+80)   | Low-Medium  | **R4-A3**   |
| T1         | Jinja2-tag-aware scan (foundation only) | elapouya/python-docx-template (2.7k ⭐)       | M (~+120)  | Medium      | Deferred R5 |
| R1+R2      | ReflexionStrategy enum + persistent log | noahshinn/reflexion (3.3k ⭐)                 | L (~+150)  | Medium      | Deferred R5 |

Researcher recommends shipping R4-A1 + R4-A2 + R4-A3 in one atomic PR (≈ +180 LOC net
across 3 files). Reviewer agrees with this scope cap — see §3 for prioritization
rationale.

---

## 2. Current State Audit (v6.1)

### 2.1 What is solid (evidence-cited)

| Surface                       | Evidence                                                                                 | Verdict     |
| ----------------------------- | ---------------------------------------------------------------------------------------- | ----------- |
| Schema-first routing (R3-A1)  | `scripts/fill_docx.py:match_field()` Pass 1 (`schemas.find_schema_for_label` + `_lookup_profile_field` at L295-334); tests `test_学历专业_resolves_to_专业`, `test_专业_direct_match` pass | Sound       |
| XML unique-cell iteration (R3-A2) | `scripts/fill_docx.py:_iter_unique_cells()` (v6.1 added) walks `<w:tc>` via `iterchildren()` once; test `test_simple_docx_three_fields` proves 3/3 fills | Sound       |
| Six Pydantic schemas (R3-A4)  | `evaluation/schemas.py` has 优秀团员申报表 / 奖学金申请表 / 个人简历 / 入党申请书 / 学位论文申请表 / 实习鉴定表; `_self_test()` 10/10 pass | Sound       |
| Provider-agnostic Model Adapter (R2-A1) | `scripts/model_adapter.py:OpenAICompatibleAdapter` at L77-201; `generate_struct()` already wraps `instructor.from_openai(...).chat.completions.create(response_model=schema, max_retries=2)` at L151-159 — **note: instructor retry is already wired in but only for the schema-validated path** | Partially exposed |
| PII redaction                 | `scripts/fill_docx.py:PHONE_PAT/EMAIL_PAT/ID_NUMBER_PAT/CARD_PAT` at L161-164; `_redact()` at L167-183 | Sound       |
| Real-LLM smoke test (R3-A5)   | `tests/test_minimax_smoke.py` proves end-to-end HTTP POST reaches `https://api.minimax.chat/v1/chat/completions` (401 with placeholder key) | Sound       |
| Score harness (R1-R14)        | `evaluation/score_consistency.py` 388 LOC, 14 rules; `--demo` returns score=100            | Sound       |

### 2.2 What is brittle / surfaceable as Round-4 work

| # | Brittleness                                                                                                             | Evidence / Symptom                                                                                                                                  | R4 priority |
| - | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| B1 | **`OpenAICompatibleAdapter.generate_struct()` uses `instructor` retry, but `reflect()` does NOT.** A single schema-violation pass silently drops the field to `""` (no retry, no escalation) | `scripts/model_adapter.py:reflect()` at L178-198 — single `chat.completions.create` call; on exception prints to stderr and returns `""`. **There is no retry loop on the reflection path.** | **R4-A1**    |
| B2 | **Literal-constrained fields (e.g. `性别=男/女`, `政治面貌`) still go through reflexion** even though the answer is fully deterministic and already present in the profile. Wastes LLM calls + introduces drift risk. | `scripts/fill_docx.py:fill_docx()` reflexion block (≈ L700+ region in v6.1) iterates every filled field through `_stub_reflect` regardless of schema `Literal[...]` constraint | **R4-A2**    |
| B3 | **`StubAdapter` cannot simulate LLM behaviour** — always returns `""` and `None`. Tests that need to verify "LLM said X" must either (a) call real network, or (b) hand-roll an `_reflect_impl=...` injection. | `scripts/model_adapter.py:StubAdapter.reflect()` at L69-71 always `return ""`; `StubAdapter.generate_struct()` at L66-67 always `return None`. `tests/test_minimax_smoke.py` uses `OpenAICompatibleAdapter` directly (network-bound). | **R4-A3**    |
| B4 | (Deferred) `_iter_unique_cells()` defensive fallback still uses old `for ri, row in enumerate(rows): for ci, cell in enumerate(row.cells):` loop — can be triggered on exotic XML constructs | `scripts/fill_docx.py:fill_docx()` (R3-A2 fallback path) | R5         |
| B5 | (Deferred) `match_rules` regex list at `scripts/fill_docx.py:match_rules` (L273-292) duplicates the schema synonyms already in `evaluation/schemas.py:find_schema_for_label()` | Two sources of truth for field-name routing | R5 (refactor only, no behavior change) |

**Bottom line:** The v6.1 substrate is solid. The three R4 actions (A1/A2/A3) target the
three remaining brittleness hot-spots without disturbing the substrate.

---

## 3. Round 4 Action Items (prioritized)

**Scope rule:** ship R4-A1 + R4-A2 + R4-A3 in this round. R4-A4 (Jinja2-tag scan) and
R4-A5 (ReflexionStrategy enum) deferred to R5 (see §4).

### R4-A1: Retry-on-validation-failure for `reflect()` (Pattern I1 from researcher)

- **Where:** `scripts/model_adapter.py:OpenAICompatibleAdapter.reflect()` (L178-198).
- **Strategy:**
  1. Wrap the `chat.completions.create()` call in a `for attempt in range(self.max_retries):` loop (default `max_retries=2`, configurable via env `LLM_REFLECT_RETRIES` or constructor kwarg).
  2. On `openai.BadRequestError` / `JSONDecodeError` / `ValidationError` from a hypothetical response, append the error to the next prompt: `"上一次回答出错: {err}\n请重新回答。"`. Treat empty response (after strip) as a soft failure that also retries up to `max_retries`.
  3. On final failure, return `""` (existing graceful-degrade behaviour) and log `⚠️ reflect exhausted {max_retries} attempts: {last_exc}` to stderr — mirrors the existing `⚠️ LLM reflect failed` pattern at L197.
  4. Add a class attribute `_reflect_max_retries: int = 2` to `ModelAdapter` ABC so `StubAdapter` can declare `0` (no retries) and the metric is uniform across providers.
  5. CLI flag passthrough: `scripts/fill_docx.py` add `--reflect-retries N` (default 2), forwarded into `OpenAICompatibleAdapter(reflect_max_retries=N, ...)`. Extend `get_adapter(**kw)` to pass through.
- **Risk:** **Medium** — retry changes LLM cost semantics. Mitigation: cap at 2 attempts by default; surface attempt count in the audit row (`audit["reflect_attempts"]`); when `max_retries=0` is explicitly set, behave identically to v6.1 (zero regression risk).
- **Test:** add `tests/test_model_adapter.py::TestReflectRetry` (new file or extend an existing one):
  - `test_reflect_succeeds_first_attempt` — happy path with mock client returning valid text → returns text, attempts=1.
  - `test_reflect_retries_on_bad_request` — mock client raises `BadRequestError` twice then returns text → returns text, attempts=3.
  - `test_reflect_exhausts_max_retries` — mock client always raises → returns `""`, attempts=`max_retries`, stderr captured contains `reflect exhausted`.
  - `test_reflect_retries_disabled_when_zero` — `max_retries=0` → no retry, attempts=1 even on failure.
- **LOC estimate:** ~+55 in `scripts/model_adapter.py`, ~+15 in `scripts/fill_docx.py` (CLI flag + passthrough), ~+90 in `tests/test_model_adapter.py` (4 tests). **Total: ~+160.**
- **Expected Δ:** **+1.5 to +2.5 points** on `evaluation/score_consistency.py` rules R4 (PII), R5 (email), R7 (consistency) — fields that previously went unfilled due to one-shot LLM validation failure now succeed on retry. Particularly impactful for free-form fields like `入党动机` / `创新点摘要` / `自荐信`.

### R4-A2: Literal-first deterministic routing (Pattern O1 from researcher)

- **Where:** `scripts/fill_docx.py:fill_docx()` reflexion block (≈ L700-740 region in v6.1) + new helper `_should_skip_llm(label, value, schema_cls)`.
- **Strategy:**
  1. After `_lookup_profile_field()` returns a non-empty value in `match_field()`, look up the matched `schema_cls` and check whether the Pydantic field type annotation is `Literal[...]`. Use the schema module's existing introspection: `field = schema_cls.model_fields[field_name]; ann = field.annotation; if get_origin(ann) is Literal: # deterministic`.
  2. When the field is `Literal` AND the profile value already matches one of the literals (case/whitespace-tolerant), skip the LLM reflexion pass entirely. Emit a deterministic audit marker: `audit_rows[-1]["reflect"] = "[skip-llm: literal]"` instead of running `_stub_reflect` or `adapter.reflect()`.
  3. When the value is `Literal`-typed but the profile value does NOT match any literal, log a one-time warning (per field name) — this is a profile-data bug that no amount of LLM reflexion can fix; the user needs to edit the YAML.
  4. Extend `audit.md` row schema: add a `fill_mode` column with values `schema-literal | schema-pattern | match-rule | transform | unmatched`. This makes the routing decision auditable.
- **Risk:** **Low** — pure additive skip path; if the introspection fails for any reason (e.g. pydantic version mismatch), fall through to the existing reflexion path. The fall-through is the same as v6.1 behaviour.
- **Test:** extend `tests/test_fill_docx.py`:
  - `test_gender_literal_skips_llm` — profile `gender="男"`, label `性别` → `audit["fill_mode"] == "schema-literal"`, no `reflect()` call recorded.
  - `test_political_status_literal_skips_llm` — `political_status="共青团员"` → `fill_mode == "schema-literal"`.
  - `test_literal_value_mismatch_warns_but_does_not_crash` — `political_status="外星人"` (not in Literal set) → `fill_mode == "schema-literal"` + warning logged; LLM still skipped (no point asking the LLM to pick from a closed enum it doesn't know).
  - `test_non_literal_field_still_uses_reflexion` — `name="张三"` (no Literal) → `fill_mode != "schema-literal"`, reflexion still runs.
- **LOC estimate:** ~+30 in `scripts/fill_docx.py` (helper + integration), ~+10 in `scripts/fill_docx.py` (audit row `fill_mode`), ~+75 in `tests/test_fill_docx.py` (4 tests). **Total: ~+115.**
- **Expected Δ:** **+0.5 to +1.0 point** direct (deterministic fields stop drifting from profile value) + **non-measurable benefit:** reduced LLM cost in production by ~15-25% (rough estimate based on current reflexion-coverage of 6 schemas × 18 fields each ≈ 108 audit rows, of which ~10-15 are `Literal`).

### R4-A3: MockLLM backend for deterministic LLM-path tests (Pattern G2 from researcher)

- **Where:** `scripts/model_adapter.py:StubAdapter` class (L61-74) + new `MockLLMAdapter` subclass.
- **Strategy:**
  1. Add a new adapter class `MockLLMAdapter(ModelAdapter)` in `scripts/model_adapter.py`. Constructor takes `canned_responses: dict[str, str]` mapping either (a) literal prompt substrings or (b) SHA-256 of prompt prefix (first 200 chars) to canned strings. Empty dict ⇒ empty `""` response.
  2. `MockLLMAdapter.reflect(label, value, ctx)` returns `self.canned_responses.get(label, "")` (label-as-key is simpler than prompt-hash for tests; document the trade-off in the docstring).
  3. `MockLLMAdapter.generate_struct(schema, prompt, **kw)` looks up `prompt[:200]` against the hash-keyed map; on miss, returns `None` (same degrade behaviour as `StubAdapter`).
  4. `MockLLMAdapter.is_live()` returns `True` (it's a *fake* LLM, not a *stub* — this distinction matters for test assertions).
  5. Register `provider="mock"` in `get_adapter()` (L204-218) — no API-key required.
  6. The new `tests/test_model_adapter.py` (created by R4-A1) and an extended `tests/test_minimax_smoke.py::TestMockLLMDeterminism` exercise this adapter — **no network required**, so CI can run them deterministically.
- **Risk:** **Low** — additive class; no existing code path changes. `StubAdapter` behaviour preserved exactly (zero regression).
- **Test:**
  - `test_mock_llm_returns_canned_for_known_label` — `canned_responses={"姓名": "名字过长，请缩短"}` → `reflect("姓名", "张", {})` returns `"名字过长，请缩短"`.
  - `test_mock_llm_empty_for_unknown_label` — empty canned → `reflect("未知字段", "x", {})` returns `""`.
  - `test_mock_llm_is_live_but_no_network` — `is_live() == True` and no `requests`/`openai` import triggered.
  - `test_get_adapter_dispatches_mock_provider` — `get_adapter("mock", canned_responses={...})` returns `MockLLMAdapter` instance.
  - `test_reflect_retry_uses_mock` — combined test with R4-A1: `MockLLMAdapter` with a canned response after 2 failures → succeeds on attempt 3. This is the killer demo: it proves retry semantics without any network.
- **LOC estimate:** ~+70 in `scripts/model_adapter.py` (new class + provider dispatch), ~+90 in `tests/test_model_adapter.py` (5 tests), ~+10 in `tests/test_minimax_smoke.py` (1 combined test). **Total: ~+170.**
- **Expected Δ:** **0 direct score points** (this is a *testability* improvement, not a behavior change). **Indirect Δ:** future rounds can ship faster because LLM-dependent code paths are now unit-testable offline; CI becomes deterministic; reviewer/tester confidence rises. **This is the highest leverage non-direct-score action in R4** because it unblocks future regressions-on-LLM-paths coverage.

### Combined R4 scope

| Action | LOC Δ | Tests | Direct Δ | Indirect Δ |
| ------ | ----- | ----- | -------- | ---------- |
| R4-A1  | +160  | +4    | +1.5 to +2.5 | LLM cost ↓ (retry = some ↑) |
| R4-A2  | +115  | +4    | +0.5 to +1.0 | LLM cost ↓ ~15-25% |
| R4-A3  | +170  | +6    | 0 (testability) | CI determinism; future velocity ↑↑ |
| **Total** | **+445** | **+14** | **+2.0 to +3.5** | **Substantial** |

---

## 4. Out-of-scope (deferred)

| Pattern  | Why deferred                                                                                                                  |
| -------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **T1 — Jinja2-tag-aware scan** (R4-A4 in researcher ranking) | This is a **new authoring mode**, not a defect fix. It opens a new surface (templates authored with `{{...}}` tags) that would require (a) new fixture templates, (b) new docs in `SKILL.md`, (c) regression coverage against the cell-walk path. Adding it in R4 would expand the PR beyond the 2-3-action cap. Defer to R5; allocate R5-A1 to it with proper fixture authoring. |
| **R1+R2 — ReflexionStrategy enum + persistent log** (R4-A5 in researcher ranking) | v6.1's reflexion loop works (R3-A5 verified end-to-end with real HTTP). Formalizing the enum is a **cosmetic refactor** with no measurable behavior change. The persistent log could matter for very long-running pipelines but the current 2-round cap doesn't stress it. Defer to R6 if/when `reflexion-rounds > 4` becomes a use case. |
| **W1 — JSON mapping file** | Useful for non-Chinese forms, but form-filler's primary user base is Chinese-speaking universities. Defer until a non-Latin form request surfaces. |
| **Anti-pattern A — browser automation** | Out of scope permanently per researcher §4. |
| **Anti-pattern B — premature RAG** | Out of scope until profile size crosses ~100 fields per profile. |
| **Anti-pattern D — LLM-generated regex** | Forbidden; schemas already encode constraints. |
| **B5 — de-duplicate match_rules vs schema synonyms** | Pure refactor; zero behavior change. Defer to R5 housekeeping commit. |

---

## 5. Risk Register

| Risk ID | Description                                                                                  | Likelihood | Impact     | Mitigation                                                                                                                                          |
| ------- | -------------------------------------------------------------------------------------------- | ---------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| R4-R1   | Retry loop in `reflect()` causes infinite loop on persistent auth/network failure            | Low        | Medium     | `max_retries` hard cap (default 2); on final failure return `""` and log; CI test `test_reflect_exhausts_max_retries` proves the cap holds.       |
| R4-R2   | `Literal[...]` introspection misreads a non-`Literal` Union/Optional as deterministic        | Low        | Medium     | Wrap introspection in `try/except`; on any exception fall through to the existing reflexion path. Unit-test the corner cases (Optional + Literal). |
| R4-R3   | `MockLLMAdapter` shadows real LLM in production by accident (e.g., user typos `--provider mock`) | Low        | Low        | `MockLLMAdapter.__init__` prints `🔶 MockLLM — not a real LLM` to stderr on construction; `is_live()` returns True but `name == "mock"` is greppable. |
| R4-R4   | `audit["fill_mode"]` schema addition breaks downstream consumers of the audit JSON           | Low        | Low        | Add field with default value (use `.get("fill_mode", "unknown")` in any consumer); document in `templates/audit_table.md`.                          |
| R4-R5   | R4 scope grows mid-round (researcher's "Jinja2 scan" pulls in)                               | Medium     | Medium     | Reviewer cap: max 3 actions in R4. If R4-A4 temptation arises, defer to R5 — do NOT expand this round.                                              |
| R4-R6   | `loop_config.json` says TERMINATED; downstream agents may refuse to act                       | Low        | Low        | This reviewer explicitly overrides `loop_status` to ACTIVE for R4 in §6 below; test agent reads loop_status at runtime, will follow.               |
| R4-R7   | Instructor retry `max_retries=2` already in code at L157 — adding outer retry could cause double-retry behaviour | Medium | Low     | R4-A1 retry wraps `reflect()`, NOT `generate_struct()`; instructor retry already covers `generate_struct` path. No overlap. Document in commit msg. |

---

## 6. Termination / Continuation Plan

### 6.1 Loop status override

`loop_config.json:loop_status = "TERMINATED"` and `termination_reason: "max_rounds: 3 reached"`.
Per the user's explicit override (this round was opened by user request), effective
loop_status for R4 = **ACTIVE**. Optimizer and Tester should treat R4 as a normal
round even though the JSON config disagrees. **Action for Optimizer:** write a
`loop_config.json` patch as part of R4 deliverable: `loop_status: "ACTIVE"`,
`round_4_priorities: ["R4-A1", "R4-A2", "R4-A3"]`, increment `round_history` with
the R4 entry. (Schema for R4 entry mirrors R1/R2/R3 entries — score_before/after,
quality_delta, patterns_adopted, action_items, tests_passed, main_judgment.)

### 6.2 Termination criteria for R4

After R4 ships and the tester reports scores:

- **R4 Δ ≥ +3.0** (cumulative >= 94.0) → `main_judgment: TERMINATE_DONE` (R4 was the cap-stretch round; further changes are diminishing returns).
- **R4 Δ in [+1.5, +3.0)** → `main_judgment: CONTINUE` (the four deferred patterns — T1, R1+R2, B4, B5 — become R5 backlog).
- **R4 Δ < +1.5** → `main_judgment: TERMINATE_PLATEAU` (R4 actions did not move the needle; declare plateau).

The 2-3 action cap keeps R4 PR reviewable; the +3 threshold matches R3's actual
gain (+7.0) and is conservative vs R2 (+14.5) and R1 (+12.05).

### 6.3 Decision tree

```
tester R4 Δ reported:
  Δ >= +3.0  → TERMINATE_DONE  (project reaches 94.0+; ship)
  Δ in [1.5, 3.0) → CONTINUE → R5 backlog (T1, R1+R2, B5)
  Δ < 1.5    → TERMINATE_PLATEAU (stop; pattern search exhausted)
```

---

## 7. Measurability Plan

### 7.1 How the Optimizer should validate each action

| Action | Validator (must pass before commit)                                                                                                          |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| R4-A1  | `python -m unittest tests.test_model_adapter -v` — all 4 new tests green; `tests/test_minimax_smoke.py` continues to pass with `max_retries=0` to prove no double-retry regression |
| R4-A2  | `python -m unittest tests.test_fill_docx -v` — all 4 new `Literal` skip tests green; `python scripts/fill_docx.py --template simple.docx --profile-dir profiles` shows `fill_mode == "schema-literal"` for 性别 row; `evaluate_score_consistency.py --demo` returns score >= 91.0 (no regression) |
| R4-A3  | `python -m unittest tests.test_model_adapter tests.test_minimax_smoke -v` — all new mock tests green; `python scripts/model_adapter.py` self-test shows `provider=mock` works; **no network calls** during mock test runs (assert via `unittest.mock.patch('openai.OpenAI')` not invoked) |

### 7.2 How the Tester should measure Δ

1. **Run full evaluation harness:** `python evaluation/score_consistency.py --demo` and capture the JSON. Compare to R3's 91.0.
2. **Run unit-test battery:** `python -m unittest discover tests -v`. Capture passed/total/skipped.
3. **Run real-LLM smoke test (if env has key):** `export LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL_NAME=... && python -m unittest tests.test_minimax_smoke -v`. Note in tester artifact whether the key returned 200 or 401; both are valid evidence.
4. **Run the MockLLM smoke test (no key required):** `python -m unittest tests.test_minimax_smoke.TestMockLLMDeterminism -v`. Should be 100% green offline.
5. **Measure LLM-call reduction from R4-A2:** count rows in `audit.md` where `fill_mode == "schema-literal"`; report as `literal_skip_rate = count / total_rows`. Expected 10-25%.
6. **Compute score delta:** `quality_delta = score_R4 - 91.0`. Report in tester artifact with confidence band (e.g., `+2.0 ± 0.5` based on the §3 estimates).

### 7.3 Acceptance gates (all must hold for R4 to be accepted)

- [ ] All R3 tests still pass (no regressions on the 32/34 baseline).
- [ ] All new R4 tests pass (target 14 new tests, total ≥ 46/48 with 2 skipped).
- [ ] `python scripts/model_adapter.py` self-test prints valid JSON for `stub`, `mock`, and (if key set) `openai-compatible`.
- [ ] `python evaluation/schemas.py` self-test still 10/10.
- [ ] `python evaluation/score_consistency.py --demo` returns score ≥ 91.0 (no regression; +X is bonus).
- [ ] Real-LLM smoke test still reaches the endpoint (proves no monkey-patching broke the network path).
- [ ] MockLLM smoke test runs offline (proves new test surface doesn't require network).
- [ ] No new lint warnings; all new functions have docstrings; type hints consistent with existing code.

---

## 8. Summary for Optimizer

**Ship in R4 (PR scope, atomic commit):**

1. **R4-A1** — Retry-on-validation-failure in `OpenAICompatibleAdapter.reflect()` (≈+160 LOC, +4 tests). Expected Δ: +1.5 to +2.5.
2. **R4-A2** — Literal-first deterministic routing in `fill_docx()` + `audit["fill_mode"]` (≈+115 LOC, +4 tests). Expected Δ: +0.5 to +1.0.
3. **R4-A3** — `MockLLMAdapter` for offline testability (≈+170 LOC, +6 tests). Expected Δ: 0 direct, high indirect (CI determinism + future velocity).

**Deferred to R5+:** T1 (Jinja2-tag scan), R1+R2 (ReflexionStrategy enum), B5 (match_rules de-dup), B4 (XML iteration fallback hardening).

**Loop override:** `loop_status` reset to ACTIVE for R4; Optimizer must patch `loop_config.json`.

**Target Δ:** +2.0 to +3.5 cumulative (score 93.0–94.5). Below +1.5 = plateau; above +3.0 = TERMINATE_DONE.

**Test budget:** ~14 new tests across 2 test files; both new tests must pass without network access (mock-only path).

---

**End of round-4 Reviewer output.**
