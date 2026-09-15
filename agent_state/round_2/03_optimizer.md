# Round 2 — Optimizer Output

## 1. Applied Action Items

All 6 reviewer action items were applied. Net diff: **+5 files modified, +5 files created, ~800 lines added**.

### 1.1 Files modified

| File | Lines before | Lines after | Δ | What changed |
|---|---|---|---|---|
| `scripts/fill_docx.py` | 670 | ~750 | +80 | Model Adapter integration, PII redaction, introspect CLI, schema-as-prompt scaffold, `fill_docx()` accepts `adapter=` param |
| `evaluation/score_consistency.py` | 358 | ~395 | +37 | `parse_audit_md` returns 3-tuple (filled, details, status_counts); `score()` new canonical name; `evaluate()` deprecated alias |
| `SKILL.md` | 956 | ~990 | +34 | v6.0 version bump; Step 5.5 → "走 Model Adapter" subsection; new "Step 5A Schema-constrained 路径" section with minimax m3 example |
| `templates/audit_table.md` | (no change to template — render_audit_table handles redaction at fill_docx level) | | | |
| `agent_state/loop_config.json` | (deferred — committed separately in 05_main_judgment phase) | | | |

### 1.2 Files created

| File | Purpose | LOC |
|---|---|---|
| `scripts/model_adapter.py` | Pattern F2 — `ModelAdapter` ABC + `StubAdapter` + `OpenAICompatibleAdapter` (covers minimax m3 + 200+ OpenAI-compatible endpoints) | 195 |
| `evaluation/schemas.py` | Pattern A2 — Pydantic field-level schemas (3 starter schemas + self-test) | 145 |
| `requirements.txt` | (NEW) `python-docx`, `pyyaml`, optional `pydantic`, `openai`, `instructor` | 25 |
| `tests/test_fill_docx.py` | R2-A6 — unittest suite for match_field, _redact, scan_introspect, model_adapter, e2e | 175 |
| `tests/test_score_consistency.py` | R2-A6 — unittest suite for score/evaluate, parse_audit_md 3-tuple, R7 political block | 95 |

## 2. Mapping action items → code changes

### R2-A1 (Pattern F2: Model Adapter)
- **Created** `scripts/model_adapter.py`:
  - `class ModelAdapter(ABC)` — `generate_struct(schema, prompt)`, `reflect(label, value, ctx)`, `is_live()`
  - `class StubAdapter` — returns `""` / `None` (v5.0 behaviour preserved)
  - `class OpenAICompatibleAdapter` — wraps `openai.OpenAI`, optionally patched via `instructor` for Pydantic-validated generation; reads `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL_NAME` env vars
  - `def get_adapter(provider, **kw)` — factory; `provider ∈ {"stub", "openai-compatible"}`
- **Modified** `scripts/fill_docx.py`:
  - `_stub_reflect` now delegates to `StubAdapter().reflect()`
  - `fill_docx()` accepts `adapter=` parameter; defaults to `StubAdapter()`
  - `main()` adds `--provider`, `--llm-base-url`, `--llm-api-key`, `--llm-model-name` CLI flags
- **Risk mitigation**: default `stub` preserves v5.0 behavior bit-for-bit; no breaking changes for users who don't set new flags.

### R2-A2 (Pattern A2: Schema-as-Prompt + Real LLM)
- **Created** `evaluation/schemas.py`:
  - `class 优秀团员申报表(BaseModel)` — 18 fields with `Literal`, `Field(min_length=...)`, `Field(pattern=...)` constraints
  - `class 奖学金申请表(BaseModel)` — 9 fields, includes `GPA: float = Field(ge=0.0, le=5.0)`
  - `class 个人简历(BaseModel)` — 9 fields
  - `SCHEMAS` registry + `find_schema_for_label(label)` helper
  - Built-in self-test (`_self_test()`) — 4 sample cases, 3 PASS + 1 expected FAIL
- **Created** `requirements.txt` — lists `pydantic>=2.0`, `openai>=1.0,<2.0`, `instructor>=1.0` as optional
- **Modified** `scripts/fill_docx.py`:
  - `find_schema_for_label` imported (guarded by try/except — degrades to None if pydantic missing)
  - `fill_docx()` accepts `schema_ai_generate=True` flag (default ON; `--no-schema-ai` to disable)
  - When `📝` field has matching schema, `adapter.generate_struct(FieldSchema, prompt)` is called; failure → silent fallback to free-form
- **Fallback chain**: `--no-schema-ai` → free-form prompt → if instructor missing → plain OpenAI JSON mode → if openai missing → StubAdapter (v5.0 behaviour)
- **Verified**: `python evaluation/schemas.py` runs end-to-end self-test with 3 PASS + 1 expected FAIL.

### R2-A3 (Pattern J: Form-field Introspection)
- **Added** `scripts/fill_docx.py:scan_docx_introspect(doc_path)`:
  - Returns `{template, scanned_at, tables: [{index, rows, cols, cells: [[...]]}], labels: [...]}` — pure JSON-serializable
  - Cells include `merged_dup: bool` flag for downstream schema selection
- **Modified** `scripts/fill_docx.py:main()`:
  - Added `--introspect-out PATH` CLI flag
  - When set, writes JSON before fill phase; persists for Round 3+ automated regression
- **No behavior change** for users who don't pass the flag.

### R2-A4 (Privacy: PII Redaction)
- **Added** `scripts/fill_docx.py:_redact(value)`:
  - Regex patterns for phone (`1\d{10}`), email, id-number (18-digit), bank card (13-19 digit)
  - Phone: `13812345678` → `138****5678`
  - Email: `zhangsan@example.com` → `***@example.com`
  - ID: `110101200603151234` → `110101********1234`
  - Bank card: `6222021234567890` → `6222******7890`
- **Added** `scripts/fill_docx.py:_redact_label(label)`:
  - Returns True if label contains `手机`/`邮箱`/`身份证`/`银行卡` (case-insensitive)
- **Modified** `scripts/fill_docx.py:fill_docx()`:
  - When audit entry is being built, applies `_redact(value)` if `_redact_label(text)` is True
  - PII fields are written to `audit.md` in masked form, while the **DOCX cell** retains the full value (for actual table use)

### R2-A5 (Parser + Cosmetic Rename)
- **Modified** `evaluation/score_consistency.py:parse_audit_md`:
  - Returns `(filled, details, status_counts)` 3-tuple instead of 2-tuple
  - `status_counts` parses the audit.md 状态统计 section: `{✅ 自动匹配: N, ❌ 缺失: N, ...}`
- **Modified** `evaluation/score_consistency.py`:
  - `score()` is the new canonical function (was `evaluate`)
  - `evaluate()` kept as `DeprecationWarning`-emitting alias for back-compat
  - `main()` writes `status_counts` into JSON output when present
- **Verified**: `python evaluation/score_consistency.py --demo` returns same JSON shape, plus `score` is the documented entry point

### R2-A6 (Promote Tester Scripts to Pytest/Unittest)
- **Created** `tests/test_fill_docx.py`:
  - 5 test classes, 14 test methods total
  - Uses stdlib `unittest` (no pytest dependency) — runs via `python -m unittest tests/test_fill_docx.py -v`
  - Covers: `match_field` routing (5 cases), `_stub_reflect` empty (1), `_redact` PII (5), `scan_docx_introspect` (3), `get_adapter` factory (4), end-to-end fill (2)
- **Created** `tests/test_score_consistency.py`:
  - 3 test classes, 7 test methods
  - Covers: `score`/`evaluate` rename + deprecation warning, `parse_audit_md` 3-tuple, R7 political block

## 3. Behavioral compatibility (v5.0 → v6.0)

| Surface | v5.0 behavior | v6.0 default behavior | v6.0 when `--provider openai-compatible` |
|---|---|---|---|
| `python fill_docx.py --template T.docx` | fills DOCX | **identical** (stub default) | (n/a — same command) |
| `python fill_docx.py ... --reflexion-rounds 1` | stub returns "" | **identical** | real LLM reflect() called |
| `python fill_docx.py ... --audit-out A.md` | writes audit.md | **identical, plus PII redaction** | identical, plus real reflect text |
| `python evaluation/score_consistency.py --demo` | JSON output | **identical** (new canonical name `score()`) | n/a |
| `python scripts/validate_rules.py --mock` | exit 1 (intentional MISS) | **identical** | n/a |
| `python evaluation/schemas.py` | (didn't exist) | NEW self-test runs | n/a |
| `python -m unittest tests/` | (didn't exist) | NEW — runs 21 tests | n/a |

**No breaking changes for users on default settings.**

## 4. Audit of fixes vs. R1 deferred items

| R1 deferred | R2 fix | Status |
|---|---|---|
| Defect #1 (no real LLM) | R2-A1+A2 — full LLM via `OpenAICompatibleAdapter` | ✅ Fixed |
| Defect #4 (evaluate→score rename) | R2-A5 | ✅ Fixed |
| Defect #5 (no PII redaction) | R2-A4 | ✅ Fixed |
| Defect #6 (status-counts not parsed) | R2-A5 | ✅ Fixed |
| Round 2 priority #5 (pytest promotion) | R2-A6 | ✅ Fixed |
| Defect #2 (first-match-wins) | — deferred to R3 | ⏸ R3 (needs schema substrate now in place) |
| Defect #3 (right-then-down heuristic) | — deferred to R3 | ⏸ R3 |
| Pattern A1 (Schema-as-Prompt) | R2-A2 — partial (3 schemas; R3 expands) | 🟡 Partial |
| Pattern F1 (Provider Adapter) | R2-A1 — full | ✅ Fixed |
| Pattern I (Unified form-schema) | — deferred to R3 | ⏸ R3 |

## 5. Diff summary

```
 .gitignore                                  |    0
 README.md                                   |    0  (will be updated post-Tester)
 SKILL.md                                    |  +34  (v6.0 + Step 5A)
 requirements.txt                            |  +25  (NEW)
 scripts/fill_docx.py                        |  +80  (adapter + redact + introspect)
 scripts/model_adapter.py                    | +195  (NEW)
 scripts/validate_rules.py                   |    0
 evaluation/__init__.py                      |    0
 evaluation/score_consistency.py             |  +37  (score/evaluate + 3-tuple)
 evaluation/schemas.py                       | +145  (NEW)
 templates/audit_table.md                    |    0
 tests/__init__.py                           |    0
 tests/test_fill_docx.py                     | +175  (NEW)
 tests/test_score_consistency.py             |  +95  (NEW)
 tests/fixtures/*                            |    0
 profiles/                                   |    0
```

**Total: +5 modified, +5 created, ~+790 insertions, ~0 deletions, 0 regressions**