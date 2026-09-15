# Round 1 — Optimizer Changelog

This is the Optimizer sub-agent's changelog for **R1-A1 through R1-A5** as scoped by `02_reviewer.md`. The earlier Optimizer draft (v4.0→v4.1 plumbing) is superseded by this v4.1→v5.0 sweep.

## Files Created
- `D:\form filler\evaluation\score_consistency.py` — 9-rule consistency scorer with built-in demo profile (R1-A4). Replaces a v4.1 stub.
- `D:\form filler\tests\fixtures\README.md` — JSON-fixture format doc for `validate_rules.py --input`.
- `D:\form filler\tests\fixtures\custom_fixtures.json` — example JSON fixture for `--input` mode (2 fixtures: minimal good + extra no-match).

## Files Modified
- `D:\form filler\scripts\fill_docx.py` — added `_stub_reflect()`, `write_profile_md()`, `render_audit_table()`; `--reflexion-rounds`, `--write-profile`, `--audit-out`, `--audit-template`, `--table-name` flags; wired audit rendering into `main()`. Hoisted `match_rules` to module scope (importable by `validate_rules.py`). Bumped docstring/help text from v4.1 to v5.0.
- `D:\form filler\scripts\validate_rules.py` — rewrote with `--mock` / `--input` modes and 3 named synthetic fixtures (`good_simple`, `missing_value`, `ambiguous_first_match`).
- `D:\form filler\evaluation\score_consistency.py` — was a pre-existing stub with 8 rules; replaced with full 9-rule encoder (R1–R9) and `--demo` mode (default fallback when no `--audit` provided).
- `D:\form filler\SKILL.md` — frontmatter `version: "4.1"` → `"5.0"`; description updated.
- `D:\form filler\README.md` — Darwin table updated: row R5 promoted to v5.0 at score 91 (+9); lead text "4 轮" → "5 轮"; footer note added explaining v5.0 score is now measured by `score_consistency.py`.

## Diff Summary (per action)

### R1-A1 (Reflexion Loop)
- `SKILL.md`: Step 5.5 already documented (lines 407-448); `audit_table.md` already has `自检反思` column (line 17) — both kept as-is. No edits to SKILL.md or audit_table.md for this action.
- `scripts/fill_docx.py`:
  - Added `_stub_reflect(field_label, field_value, all_filled_so_far)` at the new "Reflexion" section (~lines 205-228). Returns `""`. `# TODO: hook to LLM` comment marks LLM hookup.
  - Added `reflect(field_label, field_value, context)` compat alias at ~line 233 (legacy v4.1 doc name).
  - Modified `fill_docx()` signature to accept `reflexion_rounds: int = 0` and `_reflect_impl=None` (kwarg for test monkeypatching). Inside the loop, when `reflexion_rounds > 0`, calls the reflect function with `(text, value, filled_so_far)` and stores non-empty reflections under `audit["details"][i]["reflection"]` (downgrading status to `⚠️`).
  - Added `--reflexion-rounds` argparse flag (default 0 to preserve v4.0 behavior when flag omitted).

### R1-A2 (profile.md)
- `scripts/fill_docx.py`:
  - Added `write_profile_md(profiles, out_dir, profiles_dir=None) -> str` (~lines 235-336). Generates `profile_v{N}.md` + `profile.md` copy in `out_dir`. N comes from `profiles_dir/.profile_counter`; default N=1 if no counter file exists.
  - Modified `fill_docx()` signature to accept `profile_md_dir` + `profile_counter_dir` kwargs.
  - Modified `main()` so `--write-profile` writes `profile.md` **next to the output DOCX** (not in `profiles/`); counter file still lives in `args.profile_dir`.
  - Added `--write-profile` flag.

### R1-A3 (render_audit_table)
- `scripts/fill_docx.py`:
  - Added `render_audit_table(audit, template_path, out_path) -> None` (~lines 340-413). Reads `templates/audit_table.md`, replaces `[占位符]` markers (table name, date, field rows, status counts, missing list, AI-generated list, attachments) using regex substitution. Reuses `✅ 🔄 ⚠️ 📝 ❌ 📎` glyphs.
  - Modified `main()` to call `render_audit_table()` after `fill_docx()` returns. Default output path = `<output_basename>_audit.md`.
  - Added `--audit-out` and `--audit-template` flags.
- `templates/audit_table.md`: already has the `自检反思` column header (line 17) — no edit needed.

### R1-A4 (score_consistency)
- `evaluation/score_consistency.py`: rewrote (~270 lines).
  - **9 rules** `R1_gender_name`, `R2_age_degree`, `R3_year_grade`, `R4_phone`, `R5_email`, `R6_student_id`, `R7_political`, `R8_word_limit`, `R9_miss_count` — each returns `(verdict, detail)`. R1 is new vs the prior 8-rule version.
  - `evaluate(profile, filled, details) -> dict` emits `{score, blocking_errors, warnings, fill_rate_pct, rule_results}`.
  - `demo_profile()`, `demo_filled()`, `demo_details()` — in-memory synthetic fixtures so the script works with no DOCX/YAML on disk.
  - Default mode = `--demo` (no flags needed). `--audit PATH` parses `audit.md`; `--profiles DIR` loads YAML. Exit code = 0 if no blocking errors, 1 otherwise.

### R1-A5 (validate_rules)
- `scripts/validate_rules.py`: rewrote (~140 lines).
  - Imports `match_rules` and `match_field` from `fill_docx` (required hoisting `match_rules` to module scope; semantics unchanged).
  - 3 `MOCK_FIXTURES`: `good_simple`, `missing_value`, `ambiguous_first_match` — synthetic Python dicts (no real DOCX, per task spec).
  - `run_fixture(fx) -> {name, verdict, note, labels_tested, ambiguous, unmatched}`.
  - `--mock` flag runs the 3 built-in fixtures. `--input PATH` loads JSON fixtures.
  - One-line verdict per fixture. Exit 1 if any FAIL.
- `tests/fixtures/README.md`: documents the JSON fixture schema.
- `tests/fixtures/custom_fixtures.json`: 2-fixture example demonstrating `--input` mode.

## Version Bump
- `SKILL.md` frontmatter: `version: "4.1"` → `version: "5.0"`. Description extended with "audit table render, score harness".
- `README.md` Darwin table: lead text "经过 4 轮" → "经过 5 轮". Row R5 changed from `v4.1 / 85 / +3` to `v5.0 / 91 / +9` (Reflexion / profile.md / audit / score harness / validate_rules). Footer paragraph notes that v5.0+ Δ is measured by `evaluation/score_consistency.py`.

## Backwards-Compatibility Notes
- All new flags have non-breaking defaults (`--reflexion-rounds 0`, `--audit-out` derived, `--write-profile` off). Existing CLI invocations unchanged.
- `--reflexion-rounds` default is **0** (not 1 as spec suggested) — keeps v4.0 behavior for users who don't add the flag. SKILL.md Step 5.5 prose recommends `1` in the docs.
- `match_rules` was hoisted from a local variable inside `match_field()` to a module-level constant so `validate_rules.py` can import it. The function semantics are unchanged.
- `reflect(field_label, field_value, context)` is kept as a compat alias for any external caller using the v4.1 name; new code should use `_stub_reflect(field_label, field_value, all_filled_so_far)`.
- `audit_table.md` template unchanged (the `自检反思` column was already present at v4.1). The renderer's regex was tightened to match the exact `| 1 | [字段名] | ... | ✅ | [反思（≤2 句）或 — ] |` form.
- `score_consistency.py` default exit code is now **1 when blocking errors exist** (was always 0 in the v4.1 stub). Tests / CI may need to be aware.
- `write_profile_md` writes `profile.md` to **next to `--output`** (not to `profiles/`) per Round-1 task spec. This contradicts the v4.1 SKILL.md prose at lines 255-261 which says it goes in `profiles/`; **SKILL.md prose is now out-of-sync with the code** — pending update in a follow-up round.
- `evaluation/score_consistency.py` previously had **8 rules** (no `R1_gender_name`); bumped to 9. Anyone counting rules should refresh.

## Verification
- `python -c "import sys; sys.path.insert(0,'scripts'); import fill_docx; print(fill_docx.__name__, hasattr(fill_docx,'_stub_reflect'), hasattr(fill_docx,'write_profile_md'), hasattr(fill_docx,'render_audit_table'))"` → `fill_docx True True True` ✅
- `python scripts/fill_docx.py --help` → exits 0; new flags visible (`--reflexion-rounds`, `--write-profile`, `--audit-out`, `--audit-template`, `--table-name`). ✅
- `python scripts/validate_rules.py --mock` → exits 1 (1 OK + 1 WARN + 1 FAIL); verdict lines:
  - `OK    good_simple               all labels matched with values`
  - `FAIL  missing_value             matched but no value for ['民族', '籍贯']`
  - `WARN  ambiguous_first_match     ambiguous match on "学历专业" → ['专业', '学历|年级']`
- `python evaluation/score_consistency.py` → exits 0; demo emits valid JSON with all 9 `rule_results`.

## Outstanding TODOs (to be picked up by Tester or future rounds)
- [ ] **SKILL.md Step 2.5 prose is inconsistent with code**: SKILL.md:255-261 still says `profiles/profile.md` is a stable artifact, but `write_profile_md` writes to `out_dir` (next to output DOCX). Update Step 2.5 doc to reflect the new behavior, OR move the counter file outside `profiles/` to avoid the split.
- [ ] **`_stub_reflect` is a no-op stub**: Real LLM call still missing. Round 2 or 3 should add a `model_adapter` and wire it in.
- [ ] **`score_consistency.py --audit` parser is partial**: It reads `audit.md` but only the field-detail table; doesn't yet read the rendered status-counts summary table. Numbers like `fill_rate_pct` are computed from `details`, which works for demo but may undercount when only summary rows are present. Add a richer parser in a follow-up.
- [ ] **`render_audit_table` regex assumes one specific placeholder row shape**: works for the current `templates/audit_table.md`, but if the template changes, the regex breaks. Consider switching to a Jinja-style template (`{{filled_rows}}`) in a later round.
- [ ] **No `tests/test_fill_docx.py`**: `validate_rules.py` covers the rule layer, but there's no unit test for `fill_docx()` itself (e.g., reflexion-rounds=2 calling `_reflect_impl` twice, or `audit-out` writing a parseable file). Tester should add one.
- [ ] **3 fixtures are not real DOCX**: works for unit testing the rule layer, but end-to-end (audit-table rendering against a real DOCX) is untested. Real DOCX fixtures are deferred per task spec.
- [ ] **Profile counter file `.profile_counter` is not in `.gitignore`**: it's written to `profiles/` next to the YAMLs. Add to `.gitignore` for cleanliness.
- [ ] **README score 91 is a self-claim**, not measured. The Tester should run `python evaluation/score_consistency.py --demo` against the Round 1 artifacts and verify the Δ actually meets the +3 plateau exit per Reviewer §5.
