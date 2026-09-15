# Round 1 — Reviewer Output

## 1. Current Code Health Snapshot

The repo at v4.0 is **mature on paper, thin on measurement**. README's self-claimed score of 82 is reasonable as a *coverage* score (the skill spec *describes* nearly every step) but **overstates the implementation depth**: the only Python helper is a 350-line DOCX filler, there are no automated tests, no evaluation harness, and the audit table is a static template that nothing actually renders.

### What is solid today (do not reinvent)

- **SKILL.md workflow (Step 0 → 8.5)** is comprehensive and well-numbered; the 7-level matching priority in Step 2A (`SKILL.md:217-223`) and the 9-row consistency rule table at `SKILL.md:358-368` are both genuinely useful artifacts.
- **Information-source deep-mining rules** at `SKILL.md:111-120` are concrete, with confidence levels and worked examples — this is the v4.0 highlight and should be preserved verbatim.
- **Privacy posture** (`SKILL.md:41-45`, `SKILL.md:755-761`): local YAML, `.gitignore` exclusion, bank.yaml called out as encryptable — solid, do not regress.
- **fill_docx.py core mechanics** (`scripts/fill_docx.py:54-60`, `scripts/fill_docx.py:232-238`) — the `_tc` identity trick for handling merged cells is correct and battle-tested.
- **audit_table.md status icons** at `templates/audit_table.md:24-31` (`✅ 🔄 ⚠️ 📝 ❌ 📎`) — already the de-facto vocabulary. Reuse it everywhere; do not invent new glyphs.

### Concrete defects observed

1. **`scripts/fill_docx.py:300-314` — `print_audit()` only prints to stdout.** The skill spec promises a `templates/audit_table.md` artifact (`SKILL.md:348`, `README.md:133`) but nothing actually emits that file. This is the single most user-visible bug: after running the script, the user has no auditable artifact.
2. **`scripts/fill_docx.py:98-136` — `match_field()` is first-match-wins with no scoring.** Two rules can both match (e.g., `r"学历|年级"` and `r"专业"` both match "学历专业") and the *first* listed rule always wins, regardless of confidence. Real schemas need priority/score.
3. **`scripts/fill_docx.py:283-297` — `_find_value_cell()` only tries "right, then down".** Many Chinese forms put the value *below-left* or two cells over. Silent miss → silent data loss.
4. **`scripts/fill_docx.py:77-95` — `_is_likely_label()` is a hard-coded Chinese keyword list with no English/Pinyin fallback and no length-aware confidence.** A label of length 2 ("姓名") scores the same as one of length 19.
5. **`SKILL.md:308-330` (Step 5) — AI content generation is one-shot, no self-critique before the value is committed.** The consistency check in Step 7.5 runs *after*; there is no "before-audit" reflection.
6. **`SKILL.md:268-292` (Step 4) — Missing-field iteration has no notion of *why* an inference was made.** The user sees "suggested: 浙江省杭州市" but no provenance trail.
7. **No `profile.md` intermediate artifact.** The user's scattered YAMLs are read piecemeal; nothing exists that *cross-references* name/date/school across fields. This is the source of "John Smith / Jon Smith" inconsistency in long forms.
8. **No evaluation harness.** No `evaluation/` directory, no test fixtures, no scoring script. The optimization loop has no way to *measure* whether a change made things better — every round's Δ is a guess.
9. **`SKILL.md:415-417` — Step 8.5 says "推断值只有用户明确确认后才保存" but no audit-trail of *what was confirmed when*** — i.e., the profile evolves with no versioned history.

---

## 2. Research → Code Mapping

For each of the 8 researcher patterns:

| # | Pattern | Verdict | 1-line reason |
|---|---------|---------|---------------|
| A | Schema-as-Prompt (Outlines/guidance) | **Adapt (round 2)** | Big code change, but the highest-payoff structural fix; needs Round 1 to lay the `profile.md` groundwork first. |
| B | Plan → Outline → Expand (LongWriter) | **Reject (defer)** | Only applies to long fields (>500 words); most form fields are short. Wrong tool for the median case (Anti-pattern 1 risk). |
| C | Reflexion Loop on each filled field | **Adopt (Round 1, item #1)** | Smallest LLM-call increment with the largest audit-failure reduction; reuses the existing audit-table column structure. |
| D | Intermediate Spec Artifact (`profile.md`) | **Adopt (Round 1, item #2)** | Documentation/convention change only — eliminates cross-field name drift for free. |
| E | Offline Grammar / Field-Rule Debugging | **Adapt (Round 1, item #5)** | Scope down: not a full grammar DSL, just a regex/Pydantic-shape validator for the current `match_field` rules. |
| F | Provider-Agnostic Model Adapter | **Reject (defer to round 3)** | Bigger refactor; current SKILL.md is already intentionally platform-agnostic. |
| G | Token Fast-Forwarding | **Reject (defer)** | Depends on A; meaningless without structured output. |
| H | Evaluation Harness | **Adopt (Round 1, item #4)** | The optimizer loop is blind without measurement. Minimal harness now, fuller one later. |

If Adopt/Adapt, where the change lives:

- **Pattern C** → new sub-section **Step 5.5 自检反思** in `SKILL.md` (insert after line ~330); extend `templates/audit_table.md:17-19` with a `reflection:` column; add `--reflexion-rounds N` flag to `scripts/fill_docx.py` (around line ~322).
- **Pattern D** → new sub-section **Step 2.5 生成 profile.md 中间产物** in `SKILL.md` (insert after line ~245); introduce a `profile.md` writer in `scripts/fill_docx.py` (new function, ~30 lines).
- **Pattern E** → new file `scripts/validate_rules.py` (~50 lines) + `tests/fixtures/` directory; minimal CLI: `python validate_rules.py --mock`.
- **Pattern H** → new directory `evaluation/` with one file `evaluation/score_consistency.py` (~80 lines) that re-runs the Step 7.5 rule table and emits a 0–100 score per run.

---

## 3. Prioritized Action Items for Optimizer (5, ordered)

### R1-A1 — Add Reflexion Loop (Step 5.5) and reflection column
- **Source pattern:** Pattern C (Reflexion).
- **Files to change:** `D:\form filler\SKILL.md`, `D:\form filler\templates\audit_table.md`, `D:\form filler\scripts\fill_docx.py`.
- **Concrete change:**
  1. In `SKILL.md` after line ~330, add `### Step 5.5: 自检反思（Reflexion）` with sub-bullets: (a) one LLM call per generated field asking "does this contradict other filled fields? Does it violate word/format limits? Did I hallucinate a number/name?"; (b) append the 1-2 sentence reflection to the audit table; (c) if reflection flags an issue, loop back to Step 5 with the reflection as context. Cap at `--reflexion-rounds N` (default 1).
  2. In `templates/audit_table.md:17-19`, extend the field-detail table header from `| 序号 | 表格字段名 | 填入值 | 数据来源 | 状态 |` to `| 序号 | 表格字段名 | 填入值 | 数据来源 | 状态 | 自检反思 |`. Reuse existing `✅/❌` glyphs; do not invent new ones.
  3. In `scripts/fill_docx.py:322`, add `--reflexion-rounds` argparse flag (default 1). Stub the reflection logic to call a `reflect(field_label, field_value, all_filled_so_far) -> str` function that returns "" (so the script still runs end-to-end without an LLM). Real LLM hookup is left as a TODO with a clearly marked `def _stub_reflect():` so the test harness can monkeypatch it.
- **Estimated effort:** S.
- **Expected score delta:** +4 (justification: directly addresses the largest defect — no self-correction; produces measurable evidence that other rounds can compare against).
- **Risk / side-effects:** doubles LLM cost per field on real runs; mitigated by default `N=1` and by deferring Pattern G (fast-forwarding) for later rounds.

### R1-A2 — Promote `profile.md` to a first-class intermediate spec artifact
- **Source pattern:** Pattern D (shared_dependencies.md).
- **Files to change:** `D:\form filler\SKILL.md`, `D:\form filler\scripts\fill_docx.py`.
- **Concrete change:**
  1. In `SKILL.md` after line ~245 (between Step 2B and Step 3), add `### Step 2.5: 生成 profile.md 中间产物` — after every successful Step 2A/2B run, write a versioned `profile_v{N}.md` (and symlink `profile.md` to the latest) that consolidates name (with pinyin + English), date-of-birth, all school/department/major tuples, contact info, and a one-line "do not contradict" list at the top. Every subsequent prompt in Steps 3–8 must reference `profile.md` first (Anti-pattern 2 mitigation).
  2. In `scripts/fill_docx.py`, add a `write_profile_md(profiles: dict, out_path: str) -> str` function (new, ~30 lines) that flattens the YAML dicts into a human-readable markdown spec and returns a short SHA-256 checksum (8 chars). Persist `profile_v{N}.md` where N increments on each call.
- **Estimated effort:** S.
- **Expected score delta:** +3 (justification: eliminates a whole class of cross-field name drift errors, which the v4.0 metrics flag as the largest remaining noise source after MISS/INFER).
- **Risk / side-effects:** none — additive. The YAMLs remain the source of truth; `profile.md` is a derived artifact.

### R1-A3 — Make `fill_docx.py` actually write the audit table file (not just print)
- **Source pattern:** Concrete defect #1 (`scripts/fill_docx.py:300-314`).
- **Files to change:** `D:\form filler\scripts\fill_docx.py`, `D:\form filler\templates\audit_table.md`.
- **Concrete change:**
  1. Add a `render_audit_table(audit: dict, template_path: str, out_path: str) -> None` function in `scripts/fill_docx.py` (~40 lines) that reads `templates/audit_table.md`, fills the `[占位符]` slots (table name, date, field rows, status counts, missing list, AI-generated list, attachments) from the `audit` dict, and writes to `out_path`. Reuse the existing `✅/🔄/⚠️/📝/❌/📎` status icons.
  2. Wire it into `main()` (around `scripts/fill_docx.py:344`) so the audit file is written alongside the filled DOCX, defaulting to `{output_basename}_audit.md`.
  3. Add a `--audit-out` argparse flag (default: derive from `--output`) so users can override the path.
- **Estimated effort:** S.
- **Expected score delta:** +2 (justification: closes a *user-visible* bug — the skill spec promises the audit file and nothing delivers it; the user has no way to retain or share what the script produced).
- **Risk / side-effects:** low — only adds output, no behavior change for existing flags.

### R1-A4 — Minimal evaluation harness (`evaluation/score_consistency.py`)
- **Source pattern:** Pattern H (Evaluation Harness), scoped down.
- **Files to change:** `D:\form filler\evaluation\score_consistency.py` (new), `D:\form filler\agent_state\README.md` (one-paragraph note on how to invoke it).
- **Concrete change:**
  1. Create `evaluation/score_consistency.py` (~80 lines). It reads a filled DOCX + its `audit.md`, re-runs the 9 consistency rules from `SKILL.md:358-368` (age↔degree, year↔grade, phone/email regex, political-status↔申报资格, word-limit, MISS count), and emits a JSON `{ "score": 0-100, "blocking_errors": N, "warnings": N, "fill_rate_pct": X, "rule_results": [...] }` to stdout. The 9-rule table is the *measurement baseline* for all future rounds.
  2. The script must work on the artifacts produced by `fill_docx.py` after R1-A3 — no new dependencies beyond `python-docx` and `pyyaml` (already required).
- **Estimated effort:** M (because the script needs to faithfully encode 9 rule rows).
- **Expected score delta:** +3 (justification: without this, the loop cannot tell whether a round improved things — this *unlocks* measurement, which is the precondition for the next two rounds being meaningful).
- **Risk / side-effects:** low — pure additive; no existing user path is broken.

### R1-A5 — Offline rule validator (`scripts/validate_rules.py --mock`)
- **Source pattern:** Pattern E (Offline Grammar Debugging), scoped down.
- **Files to change:** `D:\form filler\scripts\validate_rules.py` (new), `D:\form filler\tests\fixtures\` (new directory with 3 sample DOCX fixtures).
- **Concrete change:**
  1. Create `scripts/validate_rules.py` (~50 lines). It loads the `match_rules` from `fill_docx.py:101-121`, runs them against 3 fixture DOCX templates in `tests/fixtures/` (good case, missing-value case, multi-match-ambiguous case), and reports which rules fired, which values were filled, and any rule whose first-match-wins logic picks the wrong target.
  2. Create `tests/fixtures/` with three minimal DOCX files (no real PII — synthetic labels only) covering: (a) simple 姓名/性别 row, (b) row with merged value cell, (c) row where two rules both match.
  3. Output a one-line verdict per fixture: `OK` / `WARN: ambiguous match on "<label>"` / `FAIL: no value cell found`.
- **Estimated effort:** M.
- **Expected score delta:** +2 (justification: catches match-rule regressions before they reach the user; the multi-match-ambiguous case is a known defect #2 and a fix can be evaluated objectively with this harness).
- **Risk / side-effects:** low — only touches the rule layer; existing runs are unaffected.

---

## 4. Quality Scoring (out of 100) — be brutally honest

| # | Dimension | Score | Justification (one sentence) |
|---|-----------|------:|-----------------------------|
| 1 | Skill spec completeness (SKILL.md coverage of real workflows) | **80/100** | Steps 0–8.5 are well-named and the consistency rule table is concrete, but there is no reflexion, no `profile.md` intermediate spec, and no evaluation hooks. |
| 2 | Code quality of `scripts/fill_docx.py` | **62/100** | 350-line single file, no tests, no type hints, hard-coded Chinese keyword list, first-match-wins matching, fragile value-cell heuristic, and the audit table it promises is never written. |
| 3 | Robustness to edge cases (OCR errors, missing fields, conflicting values) | **55/100** | Step 7.5 consistency check runs *after* generation; no offline rule validation; OCR error path is described in prose but no automated retry; conflict resolution is prompt-driven with no fall-back. |
| 4 | Evaluation / testability (can the loop measure improvement?) | **25/100** | No `evaluation/` directory, no test fixtures, no automated scorer — the optimization loop currently flies blind, which is the single largest gap. |
| 5 | Privacy & UX | **78/100** | Local YAML, `.gitignore`, batch-ask for >3 missing, preview-before-commit are all good; missing are: bank.yaml encryption is mentioned but not provided, and no PII redaction in the audit-table output. |

**Weighted total:** Skill 25% + Code 20% + Robust 20% + Eval 25% + Privacy 10%
= 0.25·80 + 0.20·62 + 0.20·55 + 0.25·25 + 0.10·78
= 20.0 + 12.4 + 11.0 + 6.25 + 7.8
= **57.45 / 100**

The README's self-claimed score of 82 is a **coverage** score (does the spec describe the workflow), not an **implementation** score (does the code actually deliver it). The gap (57 vs 82) is exactly the space this loop is supposed to close.

---

## 5. Recommendation to Main Agent

**Round 1 first action: Pattern C — Reflexion Loop.**

Why C over D (the researcher's pick) or A: D is correct as the *cheapest* change, but C produces *measurable evidence* (the new `reflection:` column entries) on every run — and that evidence is what makes R1-A4's evaluation harness meaningful. Without C, the harness measures the wrong thing (post-hoc audit). With C, the harness measures whether self-critique actually catches errors before they reach the user. **D is action #2 in the same round, not the lead**, because it is the substrate C writes into.

**Definite deferrals to round 2 / round 3:**

- **Pattern A (Schema-as-Prompt):** defer to round 2 — biggest code change, depends on D being in place to feed the schemas.
- **Pattern B (Plan → Outline → Expand):** defer — only relevant for long fields; not in the median path.
- **Pattern F (Provider-Agnostic Adapter):** defer to round 3 — bigger refactor; SKILL.md already abstracts by design.
- **Pattern G (Token Fast-Forwarding):** defer — meaningless without A.

**Round 1 risk if shipped as ordered (A1 → A5):** all five items are independent and additive; no item blocks another. Worst-case LLM cost increase is ~1× (the reflexion call), bounded by `--reflexion-rounds 1` default. No source files outside this list should be touched in round 1.

**Plateau exit (per `loop_config.json`):** if the round 1 tester reports a Δ ≥ 3 against the baseline 57, terminate after one round; otherwise round 2 should target Pattern A (schemas) + Pattern F (adapter) together as a structural rewrite.
