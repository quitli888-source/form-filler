# Round 5 — Reviewer Output

> Loop status: **ACTIVE** (per `agent_state/loop_config.json`, override by user through R4).
> Project version entering this round: **6.2** (post-R4, score 94.0, cumulative +36.55).
> R4 deferred 4 patterns to R5: T1 (Jinja2-tag scan), R1+R2 (ReflexionStrategy enum +
> persistent log), B5 (match_rules dedup), B4 (XML iter hardening). Researcher recommends
> shipping R5-A1 + R5-A2 as one atomic PR. This reviewer concurs with that recommendation
> **and adds a small R5-A3 (B4 hardening) because the LOC budget allows it and it is
> strictly defensive**.

Goal of R5: ship 2-3 additive, low-risk actions that either (a) open a new authoring
surface (T1) or (b) clean up v6.2's two known-but-deferred brittleness points (B5, B4)
without regressing the verified score.

---

## 1. Researcher Top Recommendations (recap)

| Rank | ID    | Pattern                                                | Source                                                    | LOC Δ | Tests | Direct Δ | Indirect Δ                | R5 status |
| ---- | ----- | ------------------------------------------------------ | --------------------------------------------------------- | ----- | ----- | -------- | ------------------------- | --------- |
| 1    | T1    | Jinja2-tag-aware scan (`striptags()` regex, NOT DOM walk) | elapouya/python-docx-template 2.7k ⭐                     | +120  | +3    | +0.5 to +1.5 | New authoring mode (~5–15% adoption) | **R5-A1** (SHIP) |
| 2    | B5    | `match_rules` dedup via `SCHEMA_SYNONYMS` single source | Internal (two duplicate SYNONYMS dicts)                   | +20 net | +4 | 0 | Eliminates silent divergence; future R6 S1 trivial | **R5-A2** (SHIP) |
| 3    | R1+R2 | ReflexionStrategy enum + persistent `audit_reflections.jsonl` | noahshinn/reflexion 3.3k ⭐ + MONISMALIK1 `ReflectionMemory` | +150 | +5 | 0 (cosmetic) | Semantic clarity | Defer R6 |
| 4    | B4    | XML iter fallback → `audit["warnings"]` log entry      | Internal (`_iter_unique_cells` try/except at L786-794)   | +20   | +2    | 0         | Silent-fail → loud-fail    | **R5-A3** (SHIP) |
| 5    | S1    | smol-ai `specify_file_paths`-style enum pre-scan       | smol-ai/developer                                          | +60   | +2    | +0.5      | Pre-cache Literal decisions | Defer R6 |
| 6    | S2    | LlamaParse source-context pipeline                     | jerryjliu/form_filling_app 207 ⭐                          | +200  | +4    | +2.0      | Vendor lock-in             | Defer indefinitely |
| 7    | S3    | LanceDB versioned audit log                            | lancedb/lancedb                                            | +120  | +4    | 0 (UX)    | Future-state for ≥10k rows | Defer indefinitely |

**Recommended R5 PR scope:** R5-A1 + R5-A2 + R5-A3 in one atomic commit.
**Estimated total LOC:** ~+160 net, +9 tests. Comfortably under the ≤+200 cap.
**Expected score Δ:** +0.5 to +1.5 direct (T1 only); B5 + B4 are zero-direct-score but
prevent future regression.

---

## 2. Current State Audit (v6.2)

### 2.1 What is solid (post-R4 verification, evidence-cited)

| Surface                              | Evidence                                                                                                            | Verdict |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------- | ------- |
| Retry-on-validation-failure (R4-A1)  | `D:\form filler\scripts\model_adapter.py:OpenAICompatibleAdapter.reflect()` retry loop, `max_retries=2` default; 5 tests in `tests/test_minimax_smoke.py::TestReflectRetryLogic` all green | **Solid** |
| Literal-first routing (R4-A2)        | `D:\form filler\scripts\fill_docx.py:_is_literal_field()` (L299-329) + `_literal_values()` (L332-351); `match_field()` Pass 0 at L374-412; `fill_docx()` skip-LLM branch at L828-847; 11 tests in `tests/test_fill_docx.py::TestLiteralFirstRouting` + `::TestFillModeAuditColumn` all green | **Solid** |
| MockLLM backend (R4-A3)             | `D:\form filler\scripts\model_adapter.py:MockLLMAdapter` (NEW in R4); `🔶 MockLLM` stderr warn on construct; 20 tests in `tests/test_mock_llm.py` all green; CI offline | **Solid** |
| Schema-first routing (R3-A1)         | `D:\form filler\scripts\fill_docx.py:match_field()` Pass 1 at L368-433 uses `find_schema_for_label` + `_lookup_profile_field`; survives 36 new R4 tests | **Solid** |
| XML unique-cell iteration (R3-A2)    | `D:\form filler\scripts\fill_docx.py:_iter_unique_cells()` (L897-925) walks `<w:tc>` via `iterchildren()` once; happy-path tests green | **Solid** but with B4 caveat (§2.2) |
| Six Pydantic schemas (R3-A4)         | `D:\form filler\evaluation\schemas.py` ships 6 schemas; `_self_test()` 10/10 pass                                  | **Solid** |
| PII redaction                        | `D:\form filler\scripts\fill_docx.py:PHONE_PAT/EMAIL_PAT/ID_NUMBER_PAT/CARD_PAT` at L165-168; `_redact()` at L171-187; `_redact_label()` at L190-192 | **Solid** |
| Score harness                        | `D:\form filler\evaluation\score_consistency.py`; R4 reported score = 94.0 (Δ +3.0 vs R3's 91.0)                  | **Solid** |
| Test surface                         | 70 passed, 2 skipped (test_fill_docx 37 + test_minimax_smoke 7 + test_mock_llm 20 + test_score_consistency 6)      | **Solid** |

### 2.2 What is brittle / surfaceable as Round-5 work

| #     | Brittleness                                                                                                                                 | Evidence / Symptom                                                                                                                                                                                              | R5 priority |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| B5    | **Two sources of truth for field-name routing.** `match_rules` regex list in `scripts/fill_docx.py` (L277-296) duplicates the SYNONYMS dict in `evaluation/schemas.py:find_schema_for_label()` (L179-191) and `find_field_in_schema()` (L212-224). Adding a new alias requires editing two files in sync; the regex form `r"申报人姓名\|申请人\|姓名"` diverges from the dict `{"申请人": "姓名", "申报人": "姓名", "申请人姓名": "姓名"}` semantically. | Verified at line-level (see §3.2 cross-reference table); risk is **silent divergence** — one file gets updated and the other doesn't. | **R5-A2** |
| T1    | **Label-only scan brittle on novel DOCX labels.** `_is_likely_label()` (L195-213) is a hardcoded regex list of 25+ Chinese label keywords. Novel labels (or English/mixed-language forms) fall through to "unmatched" with no signal that they were *intentionally* not recognized. A user-authored `{{姓名}}` tag would be unambiguous. | The label regex list at `D:\form filler\scripts\fill_docx.py` L195-213 has not grown since R2; future expansion requires a code change. | **R5-A1** |
| B4    | **`_iter_unique_cells` try/except fallback is silent and lands in a known-wrong state.** L786-794 catches any exception, prints to stderr, then falls back to the OLD `for ri, row in enumerate(table.rows): for ci, cell in enumerate(row.cells)` loop — which is exactly the double-counting pattern that the XML iter was written to fix. So if the XML iter ever fires on exotic XML, the system silently regresses. | `D:\form filler\scripts\fill_docx.py` L786-794; the comment at L789 says "fallback to old behavior if XML iteration fails (defensive)" — but `table.rows[ri].cells[ci]` *is* the bug. | **R5-A3** |
| R1+R2 | **`--reflexion-rounds N` is a single scalar, not an enum.** Semantic clarity gap only — the value is read once in `fill_docx()` (`for _ in range(reflexion_rounds):`) and used as a counter. The four ReflexionStrategy modes (NONE / LAST_ATTEMPT / REFLEXION / LAST_ATTEMPT_AND_REFLEXION) would be a stronger API but require a non-trivial CLI change. | `D:\form filler\scripts\fill_docx.py` L953-954 — `argparse --reflexion-rounds` int. No persistent log: the profile.md LLM reflection is ephemeral (re-generated each run). | Deferred R6 |

**Bottom line:** The v6.2 substrate is solid (94.0 verified). The three R5 actions
target (a) a new authoring surface (T1), (b) a silent-divergence hot-spot (B5), and (c)
a silent-fail hot-spot (B4) — all strictly additive, all under the +200 LOC cap.

---

## 3. Round 5 Action Items (prioritized)

### R5-A1: Jinja2-tag-aware scan (foundation only)

- **Where:**
  - **New file** `D:\form filler\scripts\jinja_scan.py` (~ 80 LOC) — `striptags()`, `find_jinja_tags()`, `parse_tag()` helpers.
  - **Modify** `D:\form filler\scripts\fill_docx.py:fill_docx()` (~ +25 LOC) — mode-switch + audit wiring when any `{{...}}` is found.
  - **New fixture** `D:\form filler\templates\with_jinja_tags.docx` (programmatic construction in test is acceptable; ~ 10 LOC helper in test).
  - **New tests** `D:\form filler\tests\test_jinja_scan.py` (NEW file, ~ 110 LOC, 3 tests).

- **Strategy:**
  1. **Lift `striptags()` verbatim** from `python-docx-template:docxtpl/template.py:patch_xml` (researcher §2, line 65-78). The 4-line regex `re.sub("</w:t>.*?(<w:t>|<w:t [^>]*>)", "", m.group(0), flags=re.DOTALL)` solves the Word run-boundary problem (`{{ var }}` split across multiple `<w:r><w:t>` runs).
  2. **`find_jinja_tags(xml_text) -> List[str]`** applies `striptags` to a serialised `<w:tc>`, then runs `re.findall(r"\{\{(.*?)\}\}", stripped, flags=re.DOTALL)` to enumerate tag identifiers.
  3. **`parse_tag(identifier) -> (schema_cls, field_name) | None`** tries `evaluation.schemas.SCHEMAS` for an exact field-name match; falls back to returning the raw identifier as a profile key (for users who want `{{ user_var }}` without schema coupling).
  4. **Mode-switch in `fill_docx()`:** before the existing cell-walk loop, run `find_jinja_tags(serialized_table_xml)` for each table. If any tag is found, **skip `_is_likely_label()` entirely** and iterate tags instead. Each tag becomes one audit entry with `"fill_mode": "jinja"`.
  5. **Fallback:** if zero tags, the existing cell-walk runs unchanged (v6.2 behavior preserved, zero regression risk).

- **Risk:** **Low**.
  - T1-R1 (researcher): User template has literal `{{` (e.g., math formula). Mitigation: emit a `warnings` entry in audit and skip tag-mode if any tag parse fails; ship the literal case as known limitation with stderr warning.
  - T1-R2 (researcher): Tag contains a filter (e.g., `{{ name | upper }}`). Mitigation: parse only bare identifiers in v6.3; defer filter support to v6.4.
  - Cross-effect: T1 introduces a *new* `fill_mode` value ("jinja") that downstream consumers must recognize. Mitigation: add `"jinja"` to the documented `fill_mode` set; use `.get("fill_mode", "unknown")` defensively in `render_audit_table()`.

- **Test:**
  - `tests/test_jinja_scan.py::test_simple_tag_in_cell` — fixture DOCX with one cell containing `{{姓名}}`; assert `audit["details"][0]["fill_mode"] == "jinja"` and the tag is mapped to schema field `姓名`.
  - `tests/test_jinja_scan.py::test_tag_split_across_runs` — fixture with `{{ 姓 }}` and `{{ 名 }}` in two consecutive `<w:r>` runs (simulated via `cell._tc` XML mutation); assert `striptags()` correctly joins them and only one tag is emitted.
  - `tests/test_jinja_scan.py::test_no_tags_falls_back_to_cell_walk` — fixture without tags; assert audit row count and `fill_mode` distribution is identical to a v6.2 baseline run.

- **LOC estimate:**
  - `scripts/jinja_scan.py` (NEW): +80 LOC.
  - `scripts/fill_docx.py`: +25 LOC.
  - `tests/test_jinja_scan.py` (NEW): +110 LOC (3 tests + fixtures).
  - **Net: +215 LOC total but +120 net on the application code** (tests count separately; the budget is on the application surface).

- **Expected Δ:** **+0.5 to +1.5 points** direct on the score harness (new authoring mode enables forms that previously fell through to "unmatched"); +5-15% adoption potential for users authoring their own templates.

---

### R5-A2: `match_rules` dedup via `SCHEMA_SYNONYMS` single source of truth

- **Where:**
  - **Modify** `D:\form filler\evaluation\schemas.py` (~ +25 LOC) — export module-level `SCHEMA_SYNONYMS` dict; delete the two duplicate inline `SYNONYMS` dicts in `find_schema_for_label` (L179-191) and `find_field_in_schema` (L212-224); have both functions read from `SCHEMA_SYNONYMS`.
  - **Modify** `D:\form filler\scripts\fill_docx.py:match_rules` (~ -40 LOC net) — generate the list at module-import time from `SCHEMA_SYNONYMS` rather than hand-coding `r"申报人姓名|申请人|姓名"`. The schema-only entries (literals like `性别`, `民族`, `院系`, `专业`) are already matched by schema-first routing and can be removed from `match_rules` entirely (Pass 1 catches them first).
  - **New tests** `D:\form filler\tests\test_match_rules_dedup.py` (NEW file, ~ 80 LOC, 4 tests).

- **Strategy (cross-reference table from R4-A2 / R5-A1 research):**

  | `match_rules` pattern (L278-292)              | `SCHEMA_SYNONYMS` key                          | schemas.py line |
  | ---------------------------------------------- | ---------------------------------------------- | --------------- |
  | `r"申报人姓名\|申请人\|姓名"` (L278)             | `申请人`, `申报人`, `申请人姓名`               | L180-182        |
  | `r"邮箱\|电子邮件"` (L285)                       | `email`, `电子邮件`, `E-mail`                  | L184-186        |
  | `r"手机\|电话"` (L284)                           | `联系方式`, `联系电话`                          | L187-188        |
  | `r"学号\|工号"` (L286)                           | — (regex-only; add to SYNONYMS)                | —               |
  | `r"民族"` (L280)                                | — (regex-only; covered by schema-first)        | —               |
  | `r"籍贯\|出生地"` (L281)                         | — (regex-only)                                 | —               |

  → **The "name/email/phone" synonyms appear in BOTH places**, with slight regex
  divergence. Plan:

  1. **Promote SYNONYMS** to a single module-level dict in `schemas.py`:
     ```python
     SCHEMA_SYNONYMS: dict[str, str] = {
         # Source-of-truth; consumed by schemas.find_schema_for_label,
         # schemas.find_field_in_schema, AND scripts.fill_docx.match_rules.
         "申请人": "姓名", "申报人": "姓名", "申请人姓名": "姓名",
         "E-mail": "邮箱", "email": "邮箱", "电子邮件": "邮箱",
         "联系方式": "手机", "联系电话": "手机",
         "指导教师": "指导老师", "校内导师": "指导老师",
         "论文标题": "论文题目",
         # R5-A2 additions: regex-only patterns promoted to canonical fields
         "工号": "学号", "出生地": "籍贯", "电话": "手机",
     }
     ```
  2. **`find_schema_for_label` and `find_field_in_schema`** read `SCHEMA_SYNONYMS.get(label, label)` (delete the two inline dicts).
  3. **`match_rules` becomes a generated list** at module import:
     ```python
     # At top of scripts/fill_docx.py, after importing schemas:
     try:
         from evaluation.schemas import SCHEMA_SYNONYMS as _SYNONYMS
     except ImportError:
         _SYNONYMS = {}
     # Reverse-map: for each synonym cluster, generate one match_rule with a
     # "alias|alias2|canonical" pattern.
     _SYNONYM_CLUSTERS: dict[str, list[str]] = {}
     for alias, canonical in _SYNONYMS.items():
         _SYNONYM_CLUSTERS.setdefault(canonical, []).append(alias)
     # Schema-only entries (literals) are removed from match_rules entirely —
     # Pass 1 (schema-first) catches them. Remaining match_rules entries
     # (transform-based, e.g. _compute_grade) stay explicit.
     match_rules = [
         (r"学历|年级", "education", "entries.0.degree", _compute_grade),
         (r"所在单位", "education", None, _compute_workplace),
         (r"申报类别", "education", "entries.0.degree", _compute_category),
     ]
     # Append auto-generated synonym rules.
     for canonical, aliases in _SYNONYM_CLUSTERS.items():
         pattern = "|".join(re.escape(a) for a in sorted({canonical, *aliases}))
         match_rules.append((pattern, _resolve_config_file(canonical),
                             _resolve_field_path(canonical), None))
     ```
  4. **`_resolve_config_file(canonical) -> str`** is a tiny new helper that maps canonical schema field names to profile YAML config files (e.g., `姓名 → "personal"`, `学号 → "education"`, `手机 → "contact"`). Mirrors the current hardcoded mapping in `match_rules` L277-296.

- **Risk:** **Very Low** (this is a refactor with strict regression coverage).
  - The dedup is purely subtractive (delete 18 hardcoded regex entries, replace with 11 generated ones).
  - All 36 R4 tests pass against the current behavior; R5 adds 4 invariant tests that lock the surface (see below).
  - **Invariant to preserve:** any `label` that previously matched `match_rules` must still match after R5-A2. The new `test_match_rules_dedup.py::test_invariance_against_v6_2_baseline` enumerates the 18 v6.2 patterns and asserts each still produces a `matched=True` result.

- **Test:**
  - `tests/test_match_rules_dedup.py::test_synonyms_dict_is_single_source` — assert `SCHEMA_SYNONYMS` is a module-level dict and that `find_schema_for_label("申请人")` returns the same schema as `find_schema_for_label("姓名")`.
  - `tests/test_match_rules_dedup.py::test_match_rules_includes_all_synonym_clusters` — iterate `SCHEMA_SYNONYMS.values()`, assert each canonical field name is reachable through `match_field(label, profiles)`.
  - `tests/test_match_rules_dedup.py::test_match_rules_no_longer_duplicates_schemas_coverage` — assert the literal `r"申报人姓名|申请人|姓名"` no longer exists in `match_rules` source (grep-style string check via `inspect.getsource`).
  - `tests/test_match_rules_dedup.py::test_invariance_against_v6_2_baseline` — assert the 18 v6.2 patterns still match for fixture labels: `["姓名", "性别", "民族", "籍贯", "出生年月", "政治面貌", "手机", "邮箱", "学号", "专业", "院系", "学校", "学历", "所在单位", "申报类别", "团员评议", "入团日期", "团内职务"]`.

- **LOC estimate:**
  - `evaluation/schemas.py`: +25 LOC (export `SCHEMA_SYNONYMS`, delete 2 inline dicts, add helper for config-file mapping).
  - `scripts/fill_docx.py`: -40 LOC net (delete 18 hand-coded regex entries + helpers; add ~10 LOC for the auto-generation block).
  - `tests/test_match_rules_dedup.py` (NEW): +80 LOC (4 tests).
  - **Net: +20 LOC application code (refactor), +80 LOC tests.**

- **Expected Δ:** **0 direct score points** (zero behavior change in the happy path). **High indirect value:** R6's S1 (smol-ai function-call enum pre-scan) becomes ~30 LOC instead of ~60 LOC because the SYNONYMS centralization lets S1 enumerate `[(canonical_name, config_file, field_path)]` for free.

---

### R5-A3: XML iter fallback hardening (silent fail → loud fail)

- **Where:**
  - **Modify** `D:\form filler\scripts\fill_docx.py:fill_docx()` L786-794 (try/except around `_iter_unique_cells`) — replace silent fallback with structured audit warning.
  - **New tests** `D:\form filler\tests\test_xml_iter_fallback.py` (NEW file, ~ 50 LOC, 2 tests).

- **Strategy:**

  The current code at L786-794:
  ```python
  try:
      cell_iter = list(_iter_unique_cells(table))
  except Exception as exc:
      # Fallback to old behavior if XML iteration fails (defensive)
      print(f"⚠️ _iter_unique_cells failed, fallback: {exc}")
      cell_iter = []
      for ri, row in enumerate(table.rows):
          for ci, cell in enumerate(row.cells):
              cell_iter.append((ri, ci, cell, id(cell._tc)))
  ```

  Two issues:
  1. The fallback duplicates the double-counting pattern that the XML iter was written to fix. So if the iter ever fires, the system silently regresses to a known-wrong state.
  2. The print-to-stderr is invisible to programmatic consumers (only human eyes watching terminal).

  R5-A3 fixes:

  1. **Replace silent fallback with structured audit warning:**
     ```python
     try:
         cell_iter = list(_iter_unique_cells(table))
     except Exception as exc:
         # R5-A3: surface the fallback in the audit, not just stderr
         audit.setdefault("warnings", []).append(
             f"_iter_unique_cells failed on table {ti}: {exc}; "
             "falling back to legacy cell-walk (known to double-count merged cells)"
         )
         cell_iter = []
         for ri, row in enumerate(table.rows):
             for ci, cell in enumerate(row.cells):
                 cell_iter.append((ri, ci, cell, id(cell._tc)))
     ```

  2. **Hoist `table` index into scope** (currently `for table in doc.tables:` lacks the index; rename to `for ti, table in enumerate(doc.tables)`).

  3. **One-line safety net:** if `audit["warnings"]` is non-empty after the loop, print a single `⚠️ form-filler: {N} warnings; see audit.md for details` line at the end of `fill_docx()`. Keeps human visibility while making the warning machine-readable.

- **Risk:** **Very Low**.
  - The change is purely additive (adds `audit["warnings"]`); no existing audit consumer reads it.
  - The fallback still falls back (preserves v6.2 graceful degrade behavior); the only difference is the warning is now in `audit.md` too.
  - If `_iter_unique_cells` never fires (the happy path), `audit["warnings"]` stays empty and behavior is bit-identical to v6.2.

- **Test:**
  - `tests/test_xml_iter_fallback.py::test_fallback_writes_audit_warning` — monkey-patch `_iter_unique_cells` to raise `RuntimeError("test")`; run `fill_docx()` on a fixture; assert `audit["warnings"]` contains the expected string and that the fill still completed (graceful degrade preserved).
  - `tests/test_xml_iter_fallback.py::test_no_warnings_on_happy_path` — run `fill_docx()` on a normal fixture; assert `audit.get("warnings", []) == []`.

- **LOC estimate:**
  - `scripts/fill_docx.py`: +20 LOC (rename loop variable, add `audit.setdefault("warnings", ...)`, add final warning summary print).
  - `tests/test_xml_iter_fallback.py` (NEW): +50 LOC (2 tests).
  - **Net: +20 LOC application code, +50 LOC tests.**

- **Expected Δ:** **0 direct score points** (defensive hardening only). **Indirect value:** if a future R6+ exotic DOCX template triggers the XML iter failure, the user sees a clear audit warning instead of silently-incorrect fills.

---

### Combined R5 scope

| Action   | LOC Δ (app) | LOC Δ (tests) | Tests Δ | Direct Δ        | Indirect Δ                | Risk      |
| -------- | ----------- | ------------- | ------- | --------------- | ------------------------- | --------- |
| R5-A1    | +120        | +110          | +3      | +0.5 to +1.5    | New authoring mode        | Low       |
| R5-A2    | +20 net     | +80           | +4      | 0               | Eliminates silent divergence | Very Low |
| R5-A3    | +20         | +50           | +2      | 0               | Silent fail → loud fail   | Very Low  |
| **Total**| **+160**    | **+240**      | **+9**  | **+0.5 to +1.5**| Substantial               | Low       |

Application-code LOC Δ (the budget constraint) = **+160**, comfortably under the
+200 cap. Total LOC Δ including tests = +400 (tests don't count against the budget).

---

## 4. Out-of-scope (deferred)

| Pattern     | Why deferred                                                                                                                                                                                  | Target round |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| R1+R2       | ReflexionStrategy enum is **cosmetic** — `--reflexion-rounds 1..3` is the only used shape. Persistent JSONL log has zero user demand right now (no user has requested `--reflexion-rounds > 2`). Once R5-A1 ships, R6 can revisit this with actual usage data. | R6 (if user requests) |
| S1 (smol-ai enum pre-scan) | Depends on R5-A2's `SCHEMA_SYNONYMS` centralization. After R5-A2 ships, S1 becomes ~+30 LOC instead of +60. Sequencing matters. | R6 (after R5-A2 lands) |
| S2 (LlamaParse) | Vendor lock-in + API key requirement + ~+200 LOC for a use case (PDF→form) that has zero current users. Researcher's anti-pattern G explicitly warns against this. | Defer indefinitely |
| S3 (LanceDB versioned audit) | `audit.md` is sufficient for the 1-2 forms/semester use case. Only becomes valuable when audit volume > ~10k rows. | Defer indefinitely |
| W1 (JSON mapping file)       | Form-filler's user base is Chinese-speaking universities; non-Latin forms have no current demand. Defer until requested.                                                              | Defer until requested |
| B1 (browser automation)      | Anti-pattern A from R4 — out of scope permanently.                                                                                                                                          | Never        |
| D (LLM-generated regex)      | Anti-pattern D from R4 — schemas already encode constraints. Forbidden.                                                                                                                     | Never        |

---

## 5. Risk Register

| Risk ID | Description                                                                                                                              | Likelihood | Impact     | Mitigation                                                                                                                                                                                |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R5-R1   | T1 `striptags()` regex misfires on non-`<w:t>` XML (e.g., embedded `<w:instrText>` field codes).                                       | Low        | Medium     | Constrain the regex to the `<w:t>` context only (lift from python-docx-template which already does this). Add a unit test with a fixture that has an `<w:instrText>` page-number field.       |
| R5-R2   | T1 mode-switch breaks the existing cell-walk for fixtures that have BOTH a `{{姓名}}` tag AND a non-tagged "姓名" label.                  | Low        | Medium     | Document the precedence rule: tag-mode wins when ANY tag is detected. Add a unit test that asserts a mixed fixture produces ONLY tag-mode audit rows (no fallback rows).                  |
| R5-R3   | B5 refactor changes routing for a label that was previously regex-matched but not schema-matched (regression on the 70/72 R4 baseline). | Low        | High       | The 4 new R5-A2 tests include `test_invariance_against_v6_2_baseline` which enumerates all 18 v6.2 pattern/label pairs and asserts each still routes correctly. Plus the existing 70 R4 tests. |
| R5-R4   | B3 audit `warnings` schema addition breaks a downstream consumer that doesn't expect the new key.                                     | Low        | Low        | Use `audit.setdefault("warnings", [])` so the key is only added when needed. Any consumer using `.get("warnings", [])` is safe.                                                            |
| R5-R5   | R5 scope grows mid-round (e.g., researcher surfaces a must-fix issue during the optimization phase).                                   | Medium     | Medium     | Reviewer cap: max 3 actions in R5. The +200 LOC budget is the hard ceiling. If a fourth action surfaces, defer to R6 — do NOT expand this round.                                              |
| R5-R6   | T1 introduces `fill_mode="jinja"` which downstream `render_audit_table()` doesn't know about; column rendering breaks.                  | Low        | Low        | `render_audit_table()` reads `fill_mode` via `.get()` (defensive); "jinja" will display as a new column value but won't crash. Document the new value in the audit_table.md template comment. |
| R5-R7   | Jinja tag could contain Python expressions or control flow (`{% if %}`) that the v6.3 scanner doesn't handle; users get cryptic errors. | Medium     | Low        | Document supported v6.3 syntax as bare identifiers only (`{{姓名}}`, NOT `{{ user['name'] }}`). Emit `warnings` entry when a tag contains disallowed characters (`[`, `]`, `.`, `(`, `)`). |

---

## 6. Termination / Continuation Plan

### 6.1 Loop status

`agent_state/loop_config.json:loop_status = "ACTIVE"` (set by R4). Effective status
for R5 = **ACTIVE** (no override needed).

### 6.2 Termination criteria for R5

After R5 ships and the tester reports scores:

- **R5 Δ ≥ +2.0** (cumulative >= 96.0) → `main_judgment: TERMINATE_DONE` (project
  has reached diminishing returns; further changes are noise).
- **R5 Δ in [+1.0, +2.0)** → `main_judgment: CONTINUE` (R6 backlog = R1+R2 + S1,
  both small and unblockable by R5-A2's centralization).
- **R5 Δ < +1.0** → `main_judgment: TERMINATE_PLATEAU` (R5 actions did not move
  the needle; declare plateau).

The R5 expected Δ is **+0.5 to +1.5** per researcher; the +1.0 threshold reflects
that R5-A1 is the only direct-score action. R5-A2 and R5-A3 are zero-direct-score
housekeeping that earn their keep via defensive value, not score.

### 6.3 Decision tree

```
tester R5 Δ reported:
  Δ >= +2.0  → TERMINATE_DONE  (project reaches 96.0+; ship)
  Δ in [1.0, 2.0) → CONTINUE → R6 backlog (R1+R2 + S1)
  Δ < 1.0    → TERMINATE_PLATEAU (housekeeping shipped but no score gain)
```

### 6.4 Optimizer handoff

The Optimizer must:

1. Apply R5-A1, R5-A2, R5-A3 in one atomic PR (or three sequential commits that
   squash at merge time).
2. Patch `agent_state/loop_config.json`:
   - `current_version`: `"6.2"` → `"6.3"`.
   - `previous_version`: `"6.1"` → `"6.2"`.
   - `round_5_priorities`: `null` → `["R5-A1", "R5-A2", "R5-A3"]`.
   - Append R5 entry to `round_history` with `main_judgment: "TBD"` and the
     R5 patterns adopted.
3. Write `agent_state/round_5/03_optimizer.md` documenting the actual LOC delta,
   test counts, and any deviations from this reviewer's plan.

---

## 7. Measurability Plan

### 7.1 How the Optimizer should validate each action

| Action | Validator (must pass before commit)                                                                                                                                          |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R5-A1  | `python -m unittest tests.test_jinja_scan -v` — all 3 new tests green; `tests/test_fill_docx.py` regression test (1 new) green; `python scripts/fill_docx.py --template templates/with_jinja_tags.docx --profile-dir profiles --output /tmp/filled.docx` shows `fill_mode="jinja"` rows in audit.md |
| R5-A2  | `python -m unittest tests.test_match_rules_dedup -v` — all 4 new tests green; **all 70 R4 tests still pass** (the invariance test is the safety net); `python evaluation/schemas.py` self-test still 10/10 |
| R5-A3  | `python -m unittest tests.test_xml_iter_fallback -v` — both new tests green; full `python -m unittest discover tests -v` ≥ 79 passed (70 R4 + 9 R5), 2 skipped                  |

### 7.2 How the Tester should measure Δ

1. **Run full evaluation harness:** `python evaluation/score_consistency.py --demo`
   and capture the JSON. Compare to R4's 94.0. Expected: 94.5–95.5.
2. **Run unit-test battery:** `python -m unittest discover tests -v`. Target:
   ≥ 79 passed (70 R4 + 9 R5), 2 skipped unchanged.
3. **Run schemas self-test:** `python evaluation/schemas.py`. Should still be
   10/10 (the B5 dedup must not break any schema).
4. **Run model adapter self-test:** `python scripts/model_adapter.py` (default
   stub). Should print valid JSON with `max_retries: 0` and `provider: stub`.
5. **Run fixture end-to-end:** `python scripts/fill_docx.py --template templates/with_jinja_tags.docx --profile-dir profiles --output /tmp/r5_jinja_filled.docx` (after the fixture exists). Capture audit.md and count `fill_mode="jinja"` rows.
6. **Compute score delta:** `quality_delta = score_R5 - 94.0`. Report in tester
   artifact with confidence band (e.g., `+1.0 ± 0.5` based on §3 estimates).
7. **Compute LOC delta:** `wc -l scripts/*.py evaluation/*.py` before and after;
   report actual delta vs reviewer's +160 estimate.

### 7.3 Acceptance gates (all must hold for R5 to be accepted)

- [ ] All R4 tests still pass (no regressions on the 70/72 baseline).
- [ ] All new R5 tests pass (target 9 new tests, total ≥ 79/81 with 2 skipped).
- [ ] `python scripts/model_adapter.py` self-test prints valid JSON for `stub`,
      `mock`, and (if key set) `openai-compatible`.
- [ ] `python evaluation/schemas.py` self-test still 10/10 (B5 dedup preserves
      all synonym coverage).
- [ ] `python evaluation/score_consistency.py --demo` returns score ≥ 94.0
      (no regression; +X is bonus).
- [ ] `python scripts/fill_docx.py` on `templates/with_jinja_tags.docx` (new
      fixture) emits `fill_mode="jinja"` rows in `audit.md`.
- [ ] `python scripts/fill_docx.py` on a v6.2 regression template emits the SAME
      `fill_mode` distribution as R4 (no silent regression from B5 refactor).
- [ ] No new lint warnings; all new functions have docstrings; type hints
      consistent with v6.2 style.
- [ ] Total application-code LOC Δ ≤ +200 (target +160, hard cap +200).
- [ ] `loop_config.json` patched with R5 entry and `current_version: "6.3"`.

---

## 8. Summary for Optimizer

**Ship in R5 (one atomic PR, three commits or one squash):**

1. **R5-A1** — Jinja2-tag-aware scan in `scripts/jinja_scan.py` (NEW, +80 LOC) +
   `scripts/fill_docx.py` mode-switch (+25 LOC) + 3 tests (+110 LOC). Expected Δ:
   +0.5 to +1.5.
2. **R5-A2** — `SCHEMA_SYNONYMS` single source of truth in
   `evaluation/schemas.py` (+25 LOC) + `scripts/fill_docx.py:match_rules`
   auto-generation (-40 net LOC) + 4 tests (+80 LOC). Expected Δ: 0 direct, high
   indirect (R6 S1 becomes trivial).
3. **R5-A3** — `audit["warnings"]` for XML iter fallback in
   `scripts/fill_docx.py:fill_docx()` L786-794 (+20 LOC) + 2 tests (+50 LOC).
   Expected Δ: 0 direct, defensive value.

**Total application LOC:** +160 net (under the +200 cap). **Total tests:** +9 (target
79/81 with 2 skipped).

**Deferred to R6+:** R1+R2 (ReflexionStrategy enum), S1 (smol-ai enum pre-scan, now
trivial after R5-A2), S2 (LlamaParse), S3 (LanceDB versioned audit).

**Loop override:** None needed; `loop_status` is already ACTIVE.

**Target Δ:** +0.5 to +1.5 cumulative (score 94.5–95.5). Below +1.0 = plateau;
above +2.0 = TERMINATE_DONE.

**Test budget:** 9 new tests across 3 new test files; all must pass without
network access (R4-A3 MockLLM guarantees this).

**Key sequencing note:** R5-A2 must ship BEFORE R5-A1 only if both touch
`scripts/fill_docx.py:match_field()` — but they don't (R5-A1 touches the
table-walk loop; R5-A2 touches the SYNONYMS dict + match_rules list). They are
independent and can be developed in parallel; ordering at commit time is cosmetic.

---

## 9. Appendix — file/line cross-reference (for Optimizer's convenience)

| Item | File | Lines | R5 action |
| ---- | ---- | ----- | --------- |
| `match_rules` (18 entries to dedup) | `D:\form filler\scripts\fill_docx.py` | L277-296 | R5-A2 |
| `find_schema_for_label` inline SYNONYMS (dup source A) | `D:\form filler\evaluation\schemas.py` | L179-191 | R5-A2 |
| `find_field_in_schema` inline SYNONYMS (dup source B) | `D:\form filler\evaluation\schemas.py` | L212-224 | R5-A2 |
| `_iter_unique_cells` try/except fallback | `D:\form filler\scripts\fill_docx.py` | L786-794 | R5-A3 |
| `_iter_unique_cells` XML walker | `D:\form filler\scripts\fill_docx.py` | L897-925 | R5-A3 (no change) |
| `_is_likely_label` (label detection) | `D:\form filler\scripts\fill_docx.py` | L195-213 | R5-A1 (parallel, not replacement) |
| `match_field` (schema-first routing) | `D:\form filler\scripts\fill_docx.py` | L354-450 | R5-A1 (mode-switch adds), R5-A2 (no change) |
| `fill_docx` main loop | `D:\form filler\scripts\fill_docx.py` | L734-877 | R5-A1 (mode-switch), R5-A3 (warnings) |
| `scan_docx_tables` | `D:\form filler\scripts\fill_docx.py` | L78-106 | R5-A1 (no change; tag scan is parallel) |

---

**End of round-5 Reviewer output.**
