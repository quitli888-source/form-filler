# Round 3 — Reviewer Output

## 1. Current State (v6.0 → v6.1)

### 1.1 Verified v6.0 surfaces (from R2 tester)
- 26 unittest tests pass (1 skipped by intent)
- `evaluation/schemas.py` self-test 4/4
- `validate_rules --mock` exit 1 (intentional MISS sentinel — same as R1)
- `score_consistency --demo` returns score=100 JSON

### 1.2 Known defects (R1-deferred → R3-eligible)

| # | Defect | Evidence | Impact |
|---|--------|----------|--------|
| 2 | first-match-wins: `学历专业` → `学历|年级` wins over `专业` | `validate_rules --mock` WARN output: `ambiguous match on "学历专业" → ['专业', '学历|年级']` | Wrong field gets filled in production |
| 3 | Merged-cell traversal: simple.docx's diagonal merge `(0,0)↔(1,1)` causes value_cell writes to overwrite label_cell (and 1/3 labels get skipped) | `wc -l` on simple.docx shows 3 labels but audit shows 2 filled | Wrong fills on any merged-cell DOCX |

Both defects now have a feasible fix path (Pattern A3 + D2 substrate is in place after R2).

## 2. Action Item Mapping

### R3-A1: Fix defect #2 (first-match-wins)
- **Where in code:** `scripts/fill_docx.py` `match_field()` function (lines 187-202)
- **Strategy:** Add a `schema_first` branch:
  1. If `evaluation.schemas.SCHEMAS` is importable AND `find_schema_for_label(label)` returns a schema class AND `label in schema.model_fields` → use the schema's field directly (no regex ambiguity).
  2. Otherwise, fall back to the existing `match_rules` regex loop (v5.0 behavior).
- **Why this works:** A Pydantic field named `专业` cannot be matched by a regex `r"学历|年级"` because `学历` is not in the field name. The schema-first path bypasses the regex list entirely.
- **Risk:** Low — additive; only kicks in when schemas exist + label matches a schema field exactly.
- **Test:** Extend `tests/test_fill_docx.py` `TestMatchField` with a `test_schema_first` case: `match_field("专业", ...)` with the R2 schemas in `SCHEMAS` → returns `education.entries.0.major` (not `学历|年级` matched to `degree`).

### R3-A2: Fix defect #3 (merged-cell traversal)
- **Where in code:** `scripts/fill_docx.py` `fill_docx()` (lines 600-660)
- **Strategy:** Replace `for ri, row in enumerate(rows): for ci, cell in enumerate(cells):` with a **single XML tree walk** via `table._tbl.iter('w:tc')`. Track:
  - `seen_tc_elements`: set of `id(w:tc)` already processed
  - `merged_spans`: dict mapping `tc_id` → list of (row, col) positions where it appears
- **Why this works:** A `<w:tc>` element appears in the XML tree exactly once even when merged; iterating by element (not by row position) avoids the duplicate-encounter bug.
- **Risk:** Medium — refactor of central loop. Mitigation: keep the existing `for ri, row in enumerate(rows)` as fallback when `etree` not available; log when XML iteration is used.
- **Test:** Add `tests/test_fill_docx.py::TestFillDocxEnd2End::test_simple_docx_three_fields` — asserts `audit["filled"] == 3` on simple.docx (currently 2 due to defect #3).

### R3-A3: Pattern I — Unified form-schema generator
- **Where in code:**
  - `scripts/build_schema.py` (NEW): reads `evaluation/schemas.py`, emits:
    - `scripts/fill_docx.py` `match_rules` (regex → profile_field mapping)
    - `templates/audit_table.md` field column header candidates
    - `evaluation/score_consistency.py` rule candidates
  - Or alternatively: write a **runtime** unification — `match_field()` consults schemas first, no file regeneration needed.
- **Strategy:** Adopt the runtime unification (lighter weight; no regeneration step in CI). `match_field()` checks schemas first, then falls back to `match_rules`.
- **Risk:** Low — runtime check is idempotent.
- **Test:** Verify `match_field()` returns different result for ambiguous labels when schemas include the more specific field.

### R3-A4: 3 more Pydantic schemas
- **Where in code:** `evaluation/schemas.py` (add 3 more classes + extend `SCHEMAS`)
- **Schemas to add:**
  1. `入党申请书` — fields: 姓名, 性别, 出生年月, 籍贯, 申请日期, 入党动机 (200-800 chars)
  2. `学位论文申请表` — fields: 姓名, 学号, 院系, 专业, 导师, 论文题目 (max 100 chars), 答辩日期, 创新点摘要 (300-1000 chars)
  3. `实习鉴定表` — fields: 姓名, 学号, 实习单位, 实习岗位, 实习起止, 鉴定意见 (200-800 chars), 指导老师
- **Total added fields:** ~21 new Pydantic fields
- **Test:** Extend `evaluation/schemas.py:_self_test()` with 3 more cases (one per new schema, all PASS)

### R3-A5: Real LLM smoke test
- **Where in code:** Test script `tests/test_minimax_smoke.py` (NEW)
- **Strategy:** Export the user's `LLM_BASE_URL=https://api.minimax.chat/v1` and `LLM_API_KEY=sk-cp-...` then call `OpenAICompatibleAdapter.reflect("姓名", "张三", {})`. Assert that:
  1. The call completes without throwing (network reachability)
  2. The response is a non-empty string
  3. The response is parseable (returns "OK" or a non-empty critique)
- **Risk:** Network might be unreachable from the test environment; if so, skip the test gracefully and document in the artifact.
- **Mitigation:** Use Python's `pytest.skip` with a clear reason if `requests` to the endpoint fails. Still logs the attempt for evidence.

## 3. Prioritization

All 5 items ship in this round. Effort breakdown:

| ID | Effort | Lines | Test |
|---|---|---|---|
| R3-A1 | XS | +30 | 1 new test |
| R3-A2 | S | +50 | 1 new test (assert filled=3) |
| R3-A3 | M | +80 | covered by R3-A1's test |
| R3-A4 | S | +120 | +3 self-test cases |
| R3-A5 | XS | +50 | 1 new test (may skip if no network) |
| **Total** | M | ~330 | 4-5 new tests |

## 4. Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| R3-A2 XML iteration changes semantics on edge fixtures | Medium | Keep row/col loop as fallback; gated by try/except |
| R3-A5 network unreachable | Medium | Skip with clear message + log attempt |
| R3-A4 schema fields don't match real DOCX fixtures | Low | Self-test only validates internal consistency, not DOCX match — that's R4 work |

## 5. Termination Criterion

`max_rounds: 3` — after R3, the loop **must terminate** regardless of Δ. The termination logic:
- R3 Δ ≥ +3 → terminate with `verdict: TERMINATE_DONE`
- R3 Δ < +3 → terminate with `verdict: TERMINATE_PLATEAU` (still terminate — no R4)

Either way, R3 is the last round. **Ship and close.**