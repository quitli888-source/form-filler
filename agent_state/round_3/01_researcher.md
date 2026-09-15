# Round 3 — Researcher Output

## Focus
R3 is a **cleanup round** — R1+R2 unlocked the substrate (profile.md + adapter + schemas + tests).
R3 closes 2 long-standing defects and applies Pattern I (unified form-schema).

Round 1 surveyed: microsoft/guidance, dottxt-co/Outlines, noahshinn/reflexion, THUDM/LongWriter, smol-ai/developer.
Round 2 surveyed: jxnl/instructor, dottxt-ai/outlines, microsoft/guidance (re-confirmed), noahshinn/reflexion (re-confirmed), atharvakarval-dev/Form-Flow-AI, WestHealth/pdf-form-filler.
Round 3 does not need new external surveys — R2's substrate is sufficient. Focus is **internal pattern application**, not external research.

## Re-confirmed patterns applied this round

### Pattern A3 — **Schema-first routing** (fixes defect #2)
- **Source projects:** jxnl/instructor (R2 survey) + dottxt-ai/outlines (R2 survey)
- **What it is:** Before running regex `match_rules`, query `evaluation/schemas.SCHEMAS` for a Pydantic field whose **name matches the label** (synonym table optional later). If found, route directly via the schema's `model_fields` — bypass the ambiguous regex ordering entirely.
- **Fix:** In `fill_docx.match_field()`, add a `schema_first=True` path. If `find_schema_for_label(label)` returns a schema class AND `label in schema_cls.model_fields`, use the schema's field constraints (literal, regex pattern) as the ground truth for routing.
- **Why now:** Pattern A2 (R2) shipped the schemas; we can finally wire them into the routing layer without invasive changes.

### Pattern D2 — **Iterate the XML tree, not the (row,col) view** (fixes defect #3)
- **Source projects:** python-docx source code (iterparse patterns) + smol-ai/developer (R1 survey — "plan → file paths" pattern adapted to "iterate the source of truth once")
- **What it is:** Instead of `for row in table.rows: for cell in row.cells:` (which re-encounters merged cells multiple times), walk the underlying `w:tbl` XML using `lxml` / `etree.iter()` and process each `w:tc` element **exactly once**. Track merged-cell coordinates via `w:gridSpan` / `w:vMerge` so value_cells and label_cells are correctly attributed.
- **Why now:** All three R1/R2 fixtures (simple / merged_cell / multi_match) have merge patterns; the test fixtures exist precisely to enable this fix.

### Pattern I — **Unified form-schema generator** (R3-A3)
- **Source projects:** Pydantic's own `model_json_schema()` + WestHealth/pdf-form-filler (R2 — `JSON profile schema for inputs`)
- **What it is:** A single `templates/schemas/form.py` defines Pydantic models. A `scripts/build_schema.py` generator reads the Pydantic models and **emits**:
  - `scripts/fill_docx.py:match_rules` (the regex list)
  - `templates/audit_table.md` field column headers
  - `evaluation/score_consistency.py:R1-R9` rule list (with auto-generated regex patterns)
- **Why now:** Right now, `match_rules`, `R1-R9`, and audit headers live in **three** places. A typo or new field needs three coordinated edits. Pattern I collapses all three into one source.

## Not surveyed this round (deferred to R4 or N/A)

| Pattern | Reason deferred |
|---|---|
| B (Plan-Outline-Expand from LongWriter) | Not applicable — form-filler uses single-shot LLM fills; plan-mode adds complexity without measurable benefit |
| G (Token Fast-Forwarding from guidance) | Requires serving the LLM locally (vLLM/llama.cpp); no online endpoint supports it. Re-evaluate when local models are added |
| Real-LLM smoke test | R3-A5, NOT a survey item |
| H (Evaluation harness expansion) | Already in place from R1 |

## Top 3 Recommendations for Round 3

1. **R3-A1 (Schema-first routing)** — defect #2 fix; ~30 LOC; high impact (eliminates a class of wrong-fill bugs)
2. **R3-A2 (XML tree iteration)** — defect #3 fix; ~50 LOC; medium impact (correctness on merged-cell fixtures)
3. **R3-A3 (Pattern I generator)** — refactor; ~150 LOC; medium impact (single source of truth for schema-driven surfaces)

Plus:
4. **R3-A4 (3 more schemas)** — adds 入党申请书 / 学位论文申请表 / 实习鉴定表; ~120 LOC; medium impact (test coverage breadth)
5. **R3-A5 (Real LLM smoke test)** — exercise the user's minimax m3 key; documents that Pattern F2 actually works end-to-end

## Anti-patterns to avoid (R3)

### Anti-pattern 6 — String-based regex lists
The current `match_rules` is a list of `(pattern, config, field, transform)` tuples. Adding a new field requires writing a regex. Pattern A3 + I move this to Pydantic `Field(pattern=...)` — the regex lives next to the constraint, and is generated into `match_rules` automatically. Don't add new fields by hand-editing `match_rules` — add them to the schema instead.

### Anti-pattern 7 — Premature optimization of LLM calls
With real LLM access now available, an anti-pattern would be to add caching/memoization/reflection-on-reflexion logic that adds latency but no quality. R3-A5 just verifies the basic `reflect()` call works — no caching layer. (That can be R4 work if needed.)

### Anti-pattern 8 — Schemas that aren't actually used
Adding 3 more Pydantic schemas (R3-A4) only counts if `find_schema_for_label()` actually routes through them. We will write tests verifying each schema gets matched by at least one form-label fixture (real or synthetic).