# Round 1 — Tester Report

## 1. Smoke Tests

| Test | Exit Code | Result |
|------|-----------|--------|
| `python scripts/fill_docx.py --help` | 0 | PASS — all 5 new flags visible (`--reflexion-rounds`, `--audit-out`, `--audit-template`, `--write-profile`, `--table-name`); help text shows `v5.0` |
| `python scripts/validate_rules.py --mock` | 1 | PASS — summary line reads `汇总: OK=1  WARN=1  FAIL=1`; verdict lines: `OK good_simple`, `FAIL missing_value`, `WARN ambiguous_first_match` |
| `python evaluation/score_consistency.py` | 0 | PASS — emits valid JSON; all 9 `rule_results` present (R1_gender_name ... R9_miss_count) |
| `import fill_docx; hasattr(...)` (3 names) | 0 | PASS — prints `OK` |
| SKILL.md YAML frontmatter valid | 0 | PASS — `yaml.safe_load` succeeds |

## 2. Behavioral Tests (per action)

### R1-A1 (Reflexion): PASS
- Ran `fill_docx('tests/fixtures/simple.docx', profiles, out, reflexion_rounds=2, _reflect_impl=counter)`.
- Counter impl returns a non-empty string each call (so the inner `for _ in range(reflexion_rounds)` loop does not `break`).
- Observed: **2 fields filled × 2 rounds = 4 reflect calls** (counter recorded 4 entries). Both filled entries' status was downgraded to `⚠️` and `reflection` text was written (`"reflection on 姓名"`, `"reflection on 性别"`). Exactly matches spec.

### R1-A2 (profile.md): PASS
- Ran `write_profile_md(profiles, tmp_dir)` against the on-disk `./profiles/*.yaml`.
- `tmp_dir` now contains `profile.md`, `profile_v1.md`, `.profile_counter`. Both `profile.md` files exist with identical content.
- Content checks: starts with `# Profile Spec (v1) — generated ...`; contains `## Identity`, `## Contact`, `## Education`; markdown table has `|---|` separator; no Jinja-style `{{...}}` placeholders left over.
- User data present: `姓名 (zh): <synth-name>` and `手机: 13800000000` confirmed.
- Returned 8-char SHA-256 checksum appears in the `## Checksum` section.
- Both files are byte-identical (`stable == versioned_content`).

### R1-A3 (audit render): PASS
- Ran `render_audit_table(audit, 'templates/audit_table.md', out)` with a 5-item synthetic audit (mix of `✅`, `🔄`, `📝`, `❌`).
- Output `audit.md` written; in the `## 字段填写详情` table section (excluding the intentionally-static `## 用户确认` checklist at the bottom), **every `[占位符]` slot was replaced**: `[表格名称]`→`优秀团员申报表`, `[YYYY-MM-DD]`→`2026-09-15`, `[DOCX / Excel / PDF / 文字描述]`→`DOCX`, `[信息源文件名（如有）]`→`奖学金申请表.pdf`, `[N] 个`→`2 个`, `[字段名]`/`[填入值]`/`[配置文件路径]`/`[反思（≤2 句）或 — ]`→5 rendered rows, `[逐条列出缺失字段...]`→`民族（personal.yaml (缺失)）`, `[逐条列出 AI 生成内容...]`→`个人陈述（约 24 字）`, status-count `[N]`/`[X%]`→real numbers (`✅ 自动匹配 | 2 | 40%`, `❌ 缺失 | 1 | 20%`, etc.).
- Reflection text (`推断自院系`) was preserved into the row.

### R1-A4 (score_consistency): PASS
- Synthetic **bad case** (age=14 + degree=本科 + 政治面貌=群众 + 申报类别=优秀团员): `evaluate(...)` returned `score=60, blocking_errors=2, warnings=0`. Failing rules: `R2_age_degree` ("年龄 14 < 15，不应为本科") and `R7_political` ("申报 优秀团员 但政治面貌为 群众"). Confirms the blocking-error path actually fires and `score < 100`.
- Same profile with `age=20` and `政治面貌=共青团员`: `score=100, blocking_errors=0`. Confirms the harness correctly recovers when the data is fixed.
- All 9 rules appear in `rule_results`.

### R1-A5 (validate_rules): PASS
- `python scripts/validate_rules.py --input tests/fixtures/custom_fixtures.json` exits 1.
- Output: `OK minimal_good_case` (all 3 labels — 姓名/性别/手机号码 — matched with values), `FAIL extra_no_match_label` ("no rule matched for ['随机未知字段XYZ']"). Summary `OK=1  WARN=0  FAIL=1`.
- Matches the JSON's expected outcomes: good case → all labels hit rules with values; bad case → unknown label triggers FAIL.

## 3. Doc Drift

- **SKILL.md frontmatter version: `"5.0"`** — PASS (line 3).
- **profile.md doc/code drift at SKILL.md:255-261: PRESENT.** The doc says `profiles/profile.md` and `profiles/profile_v{N}.md` (N from 0). The code (`write_profile_md` at `scripts/fill_docx.py:239-336` and the `--write-profile` path in `main()`) writes `profile.md` + `profile_v{N}.md` next to `--output`, while the counter file lives in `profiles/.profile_counter`.
  - **Recommendation: doc is wrong, code is right** — but the doc needs updating. The new layout is intentional (avoid polluting the git-trackable `profiles/` dir with derived artifacts that already have richer gitignore coverage at v5.0). Either:
    - (a) Update SKILL.md Step 2.5 prose (lines 247-261) to say "profile.md is written next to the output DOCX; counter lives in `profiles/.profile_counter`", **or**
    - (b) Move the write target into `profiles/` (revert code) to match the existing doc. The existing `.gitignore` already blocks `profiles/profile*.md`, so option (b) is also safe; option (a) is cleaner.
  - **Action: Optimizer Round 2 should update the doc prose** (option a) — minimal, additive fix.
- **`.profile_counter` in `.gitignore`: NO.** `grep .profile_counter .gitignore` returns nothing. The file currently lives in `profiles/` next to the YAMLs (which are already excluded by `profiles/*.yaml`), so it is incidentally protected — but the rule is fragile and depends on the counter staying inside `profiles/`. If a future code change writes the counter elsewhere, the file becomes tracked.
  - **Action needed: add `.profile_counter` (or `profiles/.profile_counter`) to `.gitignore` for explicit safety.** Trivial 1-line patch.
- **README Darwin table R5 row: PRESENT.** Line 256 reads `| **R5** | **v5.0** | **91** | **+9** | ...` and the lead text on line 247 reads "本模块经过 5 轮 Darwin 自动优化". Footer line 259 adds the `evaluation/score_consistency.py` attribution. PASS — but the **91 is a self-claim**, not a measurement (see §5 below).

## 4. Backwards-Compatibility

- **Default flags preserve v4.0 behavior: PASS (with one caveat).**
  - `--reflexion-rounds` defaults to `0` (no reflection overhead).
  - `--audit-out` defaults to `None` (the script auto-derives a path; user can override).
  - `--write-profile` defaults to `False` (no profile.md emitted unless flag given).
  - `--audit-template` defaults to `templates/audit_table.md` (unchanged from v4.1 convention).
  - `--table-name` defaults to `None` (falls back to the template's stem).
  - **Caveat (intentional behavior change, not a regression):** in v4.0 `fill_docx.py` printed the audit to stdout only and wrote no audit file. v5.0 always writes an audit file to `<output_basename>_audit.md` unless something throws inside `render_audit_table`. This is the documented R1-A3 fix (defect #1 in the Reviewer §1). The script remains safe to run on existing user flows because the new file is additive (does not modify `--output`). The `.gitignore` already excludes `*_audit.md`.
- **`match_field()` semantics: PASS.** `match_rules` was hoisted to module scope (importable by `validate_rules.py`) but the list still has the original 18 rules in the original order — 9 spot-checked patterns (姓名/性别/民族/手机/邮箱/学号/专业/学历|年级/团员评议) all present and in the same priority order. `match_field("姓名", profile)` still returns `{matched: True, value: "张三", status: "✅"}`; unknown labels still return `{matched: False, status: "❓"}`. No regressions.

## 5. Measured Δ (the key number)

### Demo run (built-in synthetic data)
- **Score: 100 / 100**
- Blocking errors: 0
- Warnings: 0
- Fill rate: 93.8 %
- All 9 `rule_results` PASS.

### End-to-end run on 3 synthetic DOCX fixtures
Ran the full pipeline `fill_docx → render_audit_table → parse_audit_md → evaluate` on each of `tests/fixtures/{simple,multi_match,merged_cell}.docx`:

| Fixture | Score | Fill rate | Blocking | Warnings |
|---------|------:|----------:|---------:|---------:|
| simple | 100 | 100.0 % | 0 | 0 |
| multi_match | 100 | 100.0 % | 0 | 0 |
| merged_cell | 100 | 100.0 % | 0 | 0 |
| **Aggregate** | **100** | **100.0 %** | **0** | **0** |

These fixtures are 1–3-cell toy tables; they exercise the plumbing but are too small to stress-test the consistency rules. The 93.8 % figure from the demo run is the more informative number, because the demo profile is a realistic multi-field form (15 filled rows + 1 miss).

### Comparison vs baselines
- **vs. Reviewer baseline 57.45:** the Reviewer baseline is a 5-dimension weighted score (skill-spec completeness 25 % + code quality 20 % + robustness 20 % + eval 25 % + privacy 10 %), computed by the Reviewer sub-agent against the v4.0 repo. The `score_consistency.py` score is a single-dimension rule-based score from a single artifact (audit.md). **The two scores measure different things and are not directly comparable.** Reporting a numeric Δ here would be misleading; the only honest statement is "the new harness exists and produces reproducible 0-100 outputs; the v4.0 repo had no such harness, so no apples-to-apples comparison is possible."
- **vs. claimed v5.0 (91/100):** the demo run **exceeds** the claim (100 > 91) but the demo uses a curated profile that the harness author knows is clean. The README's "91" is a self-claim, not measured against the new harness. The Optimizer explicitly flagged this in §Verification: "README score 91 is a self-claim, not measured."
- **For a real Δ**, the next round needs at least one (real DOCX + audit) pair scored before and after a change. Round 1 unlocks the *measurement capability* (R1-A4) but does not yet produce a measured Δ against the v4.0 baseline — no baseline artifacts exist.

### Plateau-exit verdict per `agent_state/loop_config.json`
`loop_config.json` says `termination_criteria: { max_rounds: 3, min_quality_delta: 3, plateau_rounds: 2 }`. The Reviewer's §5 explicitly conditions plateau exit on a measured `Δ ≥ 3` against the baseline 57.45.

Because the new harness and the old baseline use different scoring methodologies, **no defensible Δ can be computed in Round 1**. The plateau-exit criterion therefore cannot be triggered on Round 1 evidence alone. Recommend **NOT terminating** Round 1 on the basis of "Δ ≥ 3 vs 57.45"; recommend the Reviewer/Optimizer pair decide termination policy at the round boundary based on (a) Round 1's test pass-rate, (b) the existence of a measurement harness, and (c) the (synthetic) demo score.

## 6. Verdict

**PASS** (conditional on doc-drift follow-up, see §7).

- All 5 smoke tests pass.
- All 5 behavioral tests pass with the expected outcomes.
- All 4 doc-drift checks surface either PASS or a clearly-scoped, low-risk follow-up (not a regression that blocks the round).
- Backwards-compat is intact for the rule layer and the user-facing flag surface; the only behavior change (always-on audit-file emission) is the R1-A3 fix the Reviewer explicitly scoped.
- No CRITICAL findings (no regressions, no broken imports, no missing required outputs).

The plateau-exit call is **deferred to the Reviewer/Optimizer** — the new harness exists but cannot be directly compared to the v4.0 baseline.

## 7. Suggested Fixes for Round 2 (if any)

In priority order, all low-risk / additive:

1. **Doc/code drift on `profile.md` location** — update SKILL.md lines 255-261 prose to describe the new layout (`profile.md` next to `--output`, counter at `profiles/.profile_counter`). One paragraph edit.
2. **`.profile_counter` not gitignored** — add `.profile_counter` (or `profiles/.profile_counter`) to `.gitignore` in the existing privacy block. One line.
3. **`_stub_reflect` is still a no-op** — hook to a real `model_adapter` so the reflexion loop does something on real runs. Pattern F from the Researcher; deferred by the Reviewer to a later round.
4. **`score_consistency.py --audit` parser is partial** — only reads the field-detail table, not the rendered status-counts summary table. `fill_rate_pct` is computed from `details`, which works for the demo but undercounts when only summary rows are present. Add a richer parser.
5. **`render_audit_table` regex is template-fragile** — assumes the exact `| 1 | [字段名] | ... | ✅ | [反思（≤2 句）或 — ] |` form. Consider a Jinja-style template (`{{filled_rows}}`) when audit_table.md next revs.
6. **No unit tests for `fill_docx()` itself** — `validate_rules.py` covers the rule layer, but `fill_docx()` (reflexion-rounds counter, profile.md write, audit-out emission, `--write-profile` flow) has no `tests/test_fill_docx.py`. The Tester scripts in §2 above are throwaway; promote at least R1-A1, R1-A2, R1-A3, R1-A4 into a real `tests/` directory.
7. **3 fixtures are not real DOCX** — works for unit-testing the rule layer, but end-to-end audit rendering against a real DOCX (10+ fields, real merged cells, real ambiguous-match cases) is untested. Real DOCX fixtures deferred per Round 1 task spec.
8. **README score 91 is still a self-claim** — once the harness is exercised against at least one real-world (DOCX, profiles, audit) triple, replace the self-claim with a measured value. The current demo run gives 100, but that's the curated-baseline number, not a representative one.
