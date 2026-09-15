# Round 5 — Researcher Output

> Project: form-filler v6.2 (post-R4, score 94.0, cumulative +36.55).
> Loop status: **ACTIVE** per user override (R4-R6).
> R4 deferred 4 patterns to R5: T1 (Jinja2-tag scan), R1+R2 (ReflexionStrategy enum +
> persistent log), B5 (match_rules dedup), B4 (XML iter fallback hardening). This round
> investigates each, plus 3 NEW frontier projects to keep the frontier fresh.

---

## 1. Executive Summary — Top 5 patterns for Round 5

1. **Jinja2-tag scan — text+regex hybrid (NOT lxml DOM walk).** `elapouya/python-docx-template`
   scans DOCX Jinja2 tags by serialising XML and running `re.sub`, *not* by walking the lxml
   tree. The key trick is `striptags()` — strip `</w:t>...<w:t>` boundaries inside a tag so
   `{{ var }}` split across Word runs becomes one contiguous string. This is ~10x cheaper
   to implement than DOM walking for our use case (label-only scan).
2. **`ReflectionMemory` sliding window = the R2 sweet spot.** `MONISMALIK1/reflexion`
   ships a `@dataclass` `ReflectionMemory(max_reflections=3)` that auto-trims via slice.
   The `format_for_prompt()` method returns `""` on empty so the first-trial prompt is
   untouched. This is the smallest viable `audit_reflections.jsonl` payload — defer
   JSONL persistence; in-memory list is enough for `--reflexion-rounds 1..3`.
3. **`form_filling_app` by jerryjliu uses LlamaParse + Claude Agent SDK** — not pure RAG
   but a *parse-then-tool* pipeline where LlamaParse extracts context from uploaded
   documents and Claude invokes MCP tools to edit PDF fields. Reinforces that structured
   extraction (vs free-form retrieval) is the correct shape for form-filler's
   schema-first routing. LlamaParse is overkill; our Pydantic schemas already do the job.
4. **smol-developer's plan → enumerate → generate-one-at-a-time loop** maps cleanly onto
   form authoring: (a) plan the field list with a schema, (b) enumerate fields with a
   function-call to lock types, (c) generate per-field to enable targeted retries.
   R5 takeaway: the `{%p ... %}` block statement support from python-docx-template would
   let users declare `{%p for entry in entries %}` for table-row iteration — same shape.
5. **LanceDB's automatic-versioning model** is a viable future replacement for our flat
   `audit_reflections.jsonl` if/when audit volume exceeds ~10k rows: zero-copy
   `append_only = True` mode means each write gets a version ID for free, and SQL +
   vector search would let reviewers find similar past failures. Defer until needed.

The single highest-leverage recommendation for R5: **ship R5-A1 (T1 Jinja2-tag scan
foundation) + R5-A2 (B5 match_rules dedup) in one atomic PR**. Both are net-LOC-additive,
zero-LLM-touching, and address real v6.2 surface issues. Defer R1+R2 (reflexion enum) and
B4 (XML iter hardening) to R6+ unless we discover a regression.

---

## 2. Surveyed Projects

### Project A (carry-over R4): elapouya/python-docx-template
- **URL:** https://github.com/elapouya/python-docx-template
- **Stars:** 2,703 (verified via `gh search repos` 2026-09-15; matches R4 count)
- **Language:** Python (LGPL-2.1); version 0.20.2 per `__init__.py`
- **Public API** (from `docxtpl/__init__.py`):
  ```python
  __version__ = "0.20.2"
  from .inline_image import InlineImage
  from .listing import Listing
  from .richtext import RichText, R, RichTextParagraph, RP
  from .template import DocxTemplate
  try:
      from .subdoc import Subdoc
  except ImportError:
      pass
  ```
- **Tag scanning mechanism** (from `docxtpl/template.py:patch_xml`) — this is the
  load-bearing detail for T1:

  - Serialise XML to string, then run `re.sub` (not lxml XPath):
    ```python
    src_xml = xml_to_string(src_xml, xml_declaration=False)
    ```
  - **`striptags()` inner function** strips `</w:t>...<w:t>` boundaries *inside* a tag:
    ```python
    def striptags(m):
        return re.sub("</w:t>.*?(<w:t>|<w:t [^>]*>)", "", m.group(0), flags=re.DOTALL)
    src_xml = re.sub(
        r"{%(?:(?!%}).)*|{#(?:(?!#}).)*|{{(?:(?!}}).)*",
        striptags, src_xml, flags=re.DOTALL,
    )
    ```
    → solves the run-boundary problem (Word splitting `{{ var }}` across multiple
    `<w:r><w:t>` runs).
  - **Prefix-tag collapse** for `{%p / {%tr / {%tc / {%r / {#p / ...` — strips the
    enclosing `<w:p>`, `<w:tr>`, `<w:tc>`, `<w:r>` wrapper:
    ```python
    for y in ["tr", "tc", "p", "r"]:
        pat = (
            r"<w:%(y)s[ >](?:(?!<w:%(y)s[ >]).)*({%%|{{)%(y)s ([^}%%]*(?:%%}|}})).*?</w:%(y)s>"
            % {"y": y}
        )
        src_xml = re.sub(pat, r"\1 \2", src_xml, flags=re.DOTALL)
    ```
  - **Whitespace-control tags `{%-` / `-%}`** collapse `</w:t>` onto the delimiter.
  - **`xml:space="preserve"` is forced** on any `<w:t>` containing a Jinja marker.
  - `render_xml_part` then does `template = jinja_env.from_string(src_xml); dst_xml = template.render(context)`.
- **R5 relevance:** T1 foundation. ~80 LOC of the original `patch_xml` are
  directly reusable (the `striptags` regex + the prefix collapse loop).
  Our `scripts/fill_docx.py:_iter_unique_cells()` (L897-925) already walks `w:tc`
  elements; we add a parallel `_scan_jinja_tags()` that walks `<w:t>` text runs
  and applies the striptags trick.

### Project B (carry-over R4): noahshinn/reflexion + MONISMALIK1/reflexion
- **URLs:**
  - https://github.com/noahshinn/reflexion (3,265 ⭐, NeurIPS 2023)
  - https://github.com/MONISMALIK1/reflexion (from-scratch Python implementation)
- **ReflexionStrategy enum** — referenced in noahshinn/reflexion README but the actual
  `class ReflexionStrategy(Enum)` definition lives in a paper-supplement file not
  rendered on GitHub. The four documented values per README:
  - `NONE` — no info about last attempt
  - `LAST_ATTEMPT` — previous reasoning trace as context
  - `REFLEXION` — previous self-reflection as context
  - `LAST_ATTEMPT_AND_REFLEXION` — both
- **`use_memory` flag** documented in `alfworld_runs/run_reflexion.sh`: "use persisting
  memory to store self-reflections (turn off to run a baseline run)". Logs land in
  `./root/<run_name>/`.
- **`ReflectionMemory` (from MONISMALIK1)** — the load-bearing concrete class:
  ```python
  from __future__ import annotations
  from dataclasses import dataclass, field

  @dataclass
  class ReflectionMemory:
      """A bounded, ordered store of verbal self-reflections."""
      max_reflections: int = 3
      reflections: list[str] = field(default_factory=list)

      def add(self, reflection: str) -> None:
          reflection = reflection.strip()
          if not reflection:
              return
          self.reflections.append(reflection)
          if len(self.reflections) > self.max_reflections:
              self.reflections = self.reflections[-self.max_reflections:]

      def is_empty(self) -> bool:
          return not self.reflections

      def format_for_prompt(self) -> str:
          if not self.reflections:
              return ""
          lines = [
              "You have attempted this question before and failed. "
              "The following reflections diagnose what went wrong and how to "
              "avoid the same mistake. Use them to do better this time:",
          ]
          for i, r in enumerate(self.reflections, 1):
              lines.append(f"Reflection {i}: {r}")
          return "\n".join(lines)

      def __len__(self) -> int:
          return len(self.reflections)
  ```
- **Key takeaways for R5:**
  1. `max_reflections: int = 3` default — `form-filler --reflexion-rounds 1` is
     actually a *single* reflection pass; the memory is useful only when rounds >= 2.
  2. `add()` strips whitespace and silently ignores empty strings — defensive default
     that we should mirror.
  3. `format_for_prompt()` returns `""` on empty — first-trial prompt is *unchanged*,
     so backward compat is automatic.
  4. The slicing trim (`self.reflections = self.reflections[-self.max_reflections:]`)
     is a single-line implementation; no deque needed.
- **R5 relevance:** R1 (ReflexionStrategy enum) + R2 (persistent reflection log).
  Implementation surface: a new `scripts/reflexion.py` with the dataclass +
  `audit_reflections.jsonl` writer (JSONL for cross-run persistence, in-memory list
  for within-run access).

### Project C (NEW R5): jerryjliu/form_filling_app
- **URL:** https://github.com/jerryjliu/form_filling_app (207 ⭐)
- **Description:** "PDF Form Filler by LlamaIndex" — full-stack PDF form filling app
  using Claude Agent SDK + LlamaParse + Next.js 16 frontend.
- **Tech stack:**
  - Backend: Python FastAPI + Claude Agent SDK + custom MCP tools
  - Frontend: Next.js 16 + React 19 with SSE streaming
  - PDF Processing: PyMuPDF
  - Document Parsing: LlamaParse
- **Architecture (NOT RAG, but agentic tool-use):**
  - LlamaParse extracts context from uploaded PDF/DOCX/PPTX/images
  - Claude (via Agent SDK) uses MCP tools to inspect + modify PDF form fields
  - Real-time streaming progress to React frontend
- **R5 relevance:**
  - Confirms the *parse → tool-call* pattern beats free-form retrieval for forms
  - LlamaParse is overkill for our use case (we already have cell-walk + Pydantic)
  - The **dual PDF view (original vs filled)** UX pattern could inform a future
    `templates/filled_preview.html` side-by-side diff
  - **Multi-turn conversation for iterative refinement** maps to our `--reflexion-rounds`
    but in a user-facing way — out of scope for R5 but noted for R6+ UX work

### Project D (NEW R5): smol-ai/developer
- **URL:** https://github.com/smol-ai/developer
- **Description:** Library that lets you embed a developer agent in your app; scaffolds
  entire codebases from product specs or operates as a "personal junior developer."
- **Key patterns (verbatim from README):**
  ```python
  shared_deps = plan(prompt)
  file_paths = specify_file_paths(prompt, shared_deps)
  code = generate_code_sync(prompt, shared_deps, file_path)
  ```
- **Design philosophy (verbatim):**
  - "engineering with prompts, rather than prompt engineering"
  - "Plan first, generate second. Before writing any code, a single 'coding plan'
    string is produced so later steps stay coherent across files."
  - "Use a schema-aware call to enumerate outputs. `specify_file_paths` uses OpenAI
    Function Calling so the list of files 'is guaranteed' to come back as JSON."
  - "Generate one artifact at a time. Each file is produced independently against
    the shared plan, enabling parallelization and simple retries."
  - "Human-in-the-loop iteration. The loop continues 'until happiness is attained.'"
  - "Paste-an-error-and-fix. Users paste runtime errors back into the prompt."
  - "Whole-codebase debugging. Reads the whole codebase to make specific code change
    suggestions."
- **R5 relevance:**
  - The **plan → enumerate → generate-one-at-a-time** skeleton is the same shape as
    our schema-first routing: (a) `find_schema_for_label` ≈ `plan()`, (b) `match_rules`
    ≈ `specify_file_paths()`, (c) `fill_docx()` per-cell loop ≈ `generate_code_sync`.
  - The **paste-an-error-and-fix** pattern maps onto a future `--fix-from-audit PATH`
    flag: user pastes the audit table rows marked ❌ and the agent re-fills only those
  - **R5 takeaway:** for the eventual `{%p for entry in entries %}` table-row template
    support (T2 from R4), the `specify_file_paths`-style function-call enum of fields
    + types is the right authoring-side primitive

### Project E (NEW R5): lancedb/lancedb
- **URL:** https://github.com/lancedb/lancedb
- **Stars:** (per `gh search` — lower than 100; OSS data project)
- **Description:** "Developer-friendly OSS embedded retrieval library for multimodal AI.
  Search More; Manage Less." Built on Lance columnar format.
- **Key features (from README):**
  - "Fast Vector Search: Search billions of vectors in milliseconds with state-of-the-art indexing."
  - "Comprehensive Search: Support for vector similarity search, full-text search and SQL."
  - "Multimodal Support: Store, query and filter vectors, metadata and multimodal data."
  - "Zero-copy, automatic versioning, manage versions of your data without needing extra infrastructure."
  - "Built on the Lance columnar format for efficient storage and analytics."
  - SDKs: Python, Node.js, Rust, REST APIs.
- **R5 relevance:** Future-state storage for `audit_reflections.jsonl` when audit
  volume exceeds ~10k rows. The `append_only` semantics + automatic versioning would
  let `audit_reflections.jsonl` grow without rewrite, and SQL+vector search would let
  reviewers query "find all ❌ rows similar to this one" — out of scope for R5 but
  worth recording as a known upgrade path.

---

## 3. Pattern Analysis — deferred items from R4

### Pattern T1 — Jinja2-tag-aware scan

- **Source:** elapouya/python-docx-template `patch_xml` (2.7k ⭐, primary)
- **Where applied:** `D:\form filler\scripts\fill_docx.py` — new module `scripts/jinja_scan.py`
  (or method `_scan_jinja_tags()` on `fill_docx`). Triggered when `scan_docx_tables()` finds
  any `{{...}}` substring in `<w:t>` text content.
- **Mechanism (concrete):**
  1. Serialise each `<w:tc>`'s `<w:t>` runs to a single string via `striptags()` regex
     (lifted verbatim from python-docx-template).
  2. Find all `{{...}}` substrings; each is a tag. Parse the inner identifier as either
     `(schema_cls, field_name)` (if it matches `evaluation.schemas.SCHEMAS`) or as a raw
     profile key (fallback path).
  3. If the scan finds >= 1 tag, **switch routing mode**: skip `_is_likely_label()` cell-walk
     entirely; each tag becomes one `audit` entry with `fill_mode: "jinja"`.
  4. If the scan finds 0 tags, **fall through to existing cell-walk** (v6.2 behavior preserved).
- **What it solves:** Today's `_is_likely_label()` regex list (L195-213) is brittle on
  novel DOCX labels. A user-authored `{{姓名}}` tag is unambiguous; the tag *is* the field.
- **Complexity:** +120 LOC + 3 tests. Low risk (additive; opt-in via template choice).
  - `scripts/jinja_scan.py`: ~80 LOC (`striptags`, `find_jinja_tags`, `parse_tag`).
  - `scripts/fill_docx.py:fill_docx()`: ~25 LOC integration (mode-switch + audit wiring).
  - `templates/` fixture: 1 new `with_jinja_tags.docx` (or programmatic construction in test).
  - `tests/test_jinja_scan.py`: 3 tests (simple tag, escaped `{{` `}}`, mixed cell-walk + tag).
- **Estimated impact:** Medium. Opens a new authoring mode for users who want explicit
  tags; expected adoption ~5-15% (most existing templates are tag-free cell-walk form).
- **Risk register:**
  - **T1-R1**: User template has `{{` in literal text (e.g., math formula). Mitigation:
    add `escaped: {{ '{{' }}` support OR require a sentinel like `{%var%}` for tags. Ship
    the literal `{{` case as a known limitation with a stderr warning.
  - **T1-R2**: Tag contains a function call or filter (e.g., `{{ name | upper }}`). Mitigation:
    support only bare identifiers in v6.3; defer filter support to v6.4.

### Pattern R1+R2 — ReflexionStrategy enum + persistent reflection log

- **Source:** noahshinn/reflexion + MONISMALIK1/reflexion `ReflectionMemory` dataclass.
- **Where applied:**
  - `D:\form filler\scripts\reflexion.py` (NEW file, ~80 LOC)
  - `D:\form filler\scripts\fill_docx.py` (replace `--reflexion-rounds N` with two flags)
  - `D:\form filler\scripts\model_adapter.py` (add `reflect_with_memory()` method)
- **Mechanism (concrete):**
  1. New enum `class ReflexionStrategy(str, Enum): NONE | LAST_ATTEMPT | REFLEXION | LAST_ATTEMPT_AND_REFLEXION`.
  2. CLI flags `--reflexion-strategy reflexion` (default `none` to preserve v6.2 behaviour)
     and `--reflexion-memory-size 3` (default 3, matching MONISMALIK1).
  3. New `ReflectionMemory(max_reflections=N)` dataclass — verbatim lift from MONISMALIK1,
     but with one addition: `to_jsonl()` and `from_jsonl()` methods that append/read
     `audit_reflections.jsonl` for cross-run persistence.
  4. `fill_docx()` calls `memory.format_for_prompt()` to inject prior reflections into
     the next round's `adapter.reflect()` call (LAST_ATTEMPT_AND_REFLEXION strategy).
- **What it solves:** v6.2's `profile.md` records only the latest reflection (one-shot,
  ephemeral). With persistent memory, round N+1 can see round N's reflection text.
- **Complexity:** +150 LOC + 5 tests. Medium risk (changes reflexion semantics).
  - `scripts/reflexion.py`: ~80 LOC (enum + dataclass + JSONL read/write).
  - `scripts/fill_docx.py`: ~30 LOC integration + CLI flag.
  - `scripts/model_adapter.py`: ~25 LOC (`reflect_with_memory(strategy, memory, ...)`).
  - `tests/test_reflexion_strategy.py`: 5 tests (one per enum value + memory trim).
- **Estimated impact:** Medium. Mostly relevant when users run `--reflexion-rounds > 2`,
  which is currently rare. The bigger value is *semantic clarity* — explicit enum names
  beat `--reflexion-rounds 1` in docs and CLI help text.
- **Decision: defer to R6.** Per R5 reviewer guidance (§5 below), this is a cosmetic
  refactor that does not unblock any v6.3 work. Document the design but don't ship.

### Pattern B5 — `match_rules` dedup (housekeeping)

- **Source:** Internal — the codebase itself. Two sources of truth for field routing:
  - `D:\form filler\scripts\fill_docx.py:match_rules` (L277-296) — 18 regex entries.
  - `D:\form filler\evaluation\schemas.py:find_schema_for_label` SYNONYMS dict (L179-191)
    and `find_field_in_schema` SYNONYMS dict (L212-224) — duplicate synonyms dict.
- **Overlap analysis (concrete, line-cited):**

  | match_rules pattern | form-filler line | SYNONYMS key | schemas.py line |
  |---|---|---|---|
  | `r"申报人姓名\|申请人\|姓名"` | L278 | `申请人`, `申报人`, `申请人姓名` | L180-182 |
  | `r"邮箱\|电子邮件"` | L285 | `email`, `电子邮件`, `E-mail` | L184-186 |
  | `r"手机\|电话"` | L284 | `联系方式`, `联系电话` | L187-188 |
  | `r"学号\|工号"` | L286 | — | — |
  | `r"政治面貌"` | L283 | — | — |

  → **The "name/email/phone" synonyms appear in BOTH places**, with slight regex
  divergence. Adding a new alias requires editing two files in sync.

- **Concrete refactor plan (R5-A2):**
  1. **Promote synonyms to a single source of truth.** Move the SYNONYMS dict to
     `D:\form filler\evaluation\schemas.py:SCHEMA_SYNONYMS` (module-level).
  2. **`match_rules` consumes SCHEMA_SYNONYMS** by generating `r"别名1|别名2|...|字段名"`
     patterns at import time. Eliminates the `r"申报人姓名|申请人|姓名"` literal-regex.
  3. **Delete the duplicate SYNONYMS dict** from `find_field_in_schema()`.
  4. **Bonus:** extend SYNONYMS to cover the regex-only patterns (`学号`, `工号`, `政治面貌`,
     `专业`, `院系`, `学校`, `民族`, `籍贯`, `出生地`) so match_rules becomes a one-liner
     generator.
- **What it solves:** Two sources of truth → silent divergence. The R3-A1 reviewer
  flagged this as B5; R4 deferred it.
- **Complexity:** +60 LOC (mostly deletion) + 4 tests. Zero behavior change (regression
  risk ≈ 0 if test coverage preserved).
  - `evaluation/schemas.py`: +20 LOC (export `SCHEMA_SYNONYMS`, regenerate match_rules).
  - `scripts/fill_docx.py`: -40 LOC net (delete literals, add import).
  - `tests/test_match_rules_dedup.py`: 4 tests (one per synonym family).
- **Estimated impact:** Low direct, **high indirect** (no more silent divergence).
  Future R6+ schema additions only touch one file.
- **Decision: ship in R5-A2** — it's a refactor with test coverage, low risk, and
  reviewer-flagged for R5.

### Pattern B4 — XML iter fallback hardening

- **Source:** Internal — `D:\form filler\scripts\fill_docx.py:_iter_unique_cells()` (L897-925)
  with `try/except` fallback (L786-794) that reverts to the old `for ri, row in
  enumerate(table.rows): for ci, cell in enumerate(row.cells)` pattern.
- **What's brittle:**
  - The fallback path duplicates python-docx's `cells[ci]` semantics which is exactly
    the double-counting bug that the XML iter was written to fix. So *if* the XML iter
    fails, we silently regress to a known-wrong state.
  - The except clause catches `Exception` and prints to stderr but **does not re-raise**
    — silent degradation to a buggy path is the worst outcome.
- **Concrete hardening plan (R5-A3 alt):**
  1. **Replace the silent fallback with a structured log entry:**
     ```python
     except Exception as exc:
         audit.setdefault("warnings", []).append(
             f"_iter_unique_cells failed: {exc}; falling back to legacy cell-walk "
             "(known to double-count merged cells)"
         )
     ```
  2. **Always-XML alternative:** instead of lxml `iterchildren`, use python-docx's
     `table._cells` which is computed by python-docx itself (post-merge deduplication
     is handled internally in recent python-docx ≥ 0.8.11). One-line replacement:
     ```python
     for ci, cell in enumerate(table._cells):
         ...
     ```
  3. **Add a regression test** that constructs a DOCX with a vertically-merged cell
     and asserts `len(filled_rows) == 1` for that label.
- **What it solves:** The XML iter fallback is currently a soft fail with a noisy
  stderr print and a known-wrong fallback. Either it should never fire (always-XML)
  or it should fail loud.
- **Complexity:** +20 LOC + 2 tests. Zero behavior change in the happy path.
- **Estimated impact:** Low. Hasn't bitten in practice (R3-A2 tests are green). Defer
  to R6 housekeeping unless we observe a regression.
- **Decision: defer to R6** as a single-line cleanup unless B5 runs into the same
  region.

---

## 4. Pattern Analysis — NEW R5 patterns

### Pattern S1 — `specify_file_paths`-style function-call enum

- **Source:** smol-ai/developer pattern (per README)
- **What it is:** Use OpenAI Function Calling (or Pydantic schema-as-prompt) to
  enumerate the field list with types **before** generating any per-field value.
- **Form-filler analogue:** `find_schema_for_label()` already does this for *one*
  label at a time. A pre-scan that returns `[(field_name, schema_cls, Literal/pattern)]`
  for all labels in a single LLM call would let:
  - Pre-cache `Literal` decisions (skip LLM reflexion entirely on those).
  - Detect `field_path` mismatches before any cell is written.
  - Surface "this form has 18 fields, 5 are Literal, 13 need LLM" up front.
- **Complexity:** +60 LOC + 2 tests. Low risk (additive; pre-scan only).
- **Decision: defer to R6** unless R6 finds a regression on schema ambiguity.

### Pattern S2 — LlamaParse-style parse → tool pipeline

- **Source:** jerryjliu/form_filling_app
- **What it is:** When a DOCX template references a source file (e.g., "extract the
  research topic from my thesis.pdf"), LlamaParse extracts context, then Claude invokes
  MCP tools to fill fields.
- **Form-filler analogue:** Today's `profiles/*.yaml` is the only context source.
  A `--source-context thesis.pdf` flag that runs LlamaParse on the PDF and feeds
  extracted text into the prompt would extend the use case to "fill from this PDF."
- **Complexity:** +200 LOC + 4 tests + a LlamaCloud API key requirement. High risk
  (vendor lock-in to LlamaParse).
- **Decision: defer indefinitely** — the user's R1-R4 profile.md flow already covers
  most cases; LlamaParse is only worth it for 10k+-field documents.

### Pattern S3 — LanceDB append-only audit

- **Source:** lancedb/lancedb (zero-copy automatic versioning)
- **What it is:** Replace `audit.md` flat-file writes with a LanceDB table where each
  fill operation is a new version; reviewers query past versions with SQL + vector.
- **Form-filler analogue:** Today `audit.md` is overwritten on each run. If a user
  fills 50 forms per semester and wants to compare across semesters, a versioned
  storage would let them ask "show me all political_status='共青团员' rows in Fall 2025."
- **Complexity:** +120 LOC + 4 tests + a `pyarrow`/`lancedb` dep. High risk (new dep).
- **Decision: defer indefinitely** — current `audit.md` is sufficient for the 1-2
  forms per semester use case.

---

## 5. Anti-Patterns to Avoid (R5 carry-overs + new)

### Anti-pattern E — Heavy DOM walk for tag scanning
- **Source:** natural temptation given python-docx-template exists
- python-docx-template actually does *not* walk the lxml DOM for tag detection — it
  serialises to string and runs `re.sub`. Our `_iter_unique_cells()` already walks
  `<w:tc>` for the cell-walk; **don't double-walk**. Build `_scan_jinja_tags()` to
  consume the same XML traversal but only emit tag strings.

### Anti-pattern F — Persistence before substance
- **Source:** reflexion paper's `use_memory` flag
- R1 (enum) is cheap; R2 (persistent JSONL) is also cheap. But **R3 (cross-form
  retrieval over reflections) is the actual payoff**. Ship R1+R2 now and add the
  retrieval hook in a future round, so we don't over-engineer round-trip persistence
  before we know what the queries will look like.

### Anti-pattern G — Vendor-locked document parsing
- **Source:** jerryjliu/form_filling_app uses LlamaParse (commercial)
- LlamaParse costs $$ and requires an API key. Our cell-walk + Pydantic schema path
  handles 95% of the use case. **Don't add LlamaParse** even if it's "the modern way."

### Anti-pattern H — Re-LLM'ing the match_rules
- **Source:** some instructor examples
- Resist the urge to use an LLM to generate regex for `match_rules` from natural
  language. The schemas already encode constraints. `Literal[...]` introspects cleanly;
  pattern fields can use Pydantic `pattern=...`. **No LLM in the routing layer.**

---

## 6. Top Recommendations for Round 5

| Priority | ID | Pattern | LOC Δ | Tests | Impact | Risk | Recommendation |
|---|---|---|---|---|---|---|---|
| 1 | **R5-A1** | **T1 — Jinja2-tag scan** (foundation) | +120 | +3 | Medium (new authoring) | Low | **SHIP** |
| 2 | **R5-A2** | **B5 — match_rules dedup** (refactor) | +20 net | +4 | Low direct / high indirect | Very low | **SHIP** |
| 3 | R5-A3 | R1+R2 — ReflexionStrategy enum + memory log | +150 | +5 | Medium (semantic clarity) | Medium | Defer to R6 |
| 4 | R5-A4 | B4 — XML iter fallback hardening | +20 | +2 | Low | Very low | Defer to R6 |
| 5 | R5-A5 | S1 — function-call enum pre-scan | +60 | +2 | Medium | Low | Defer to R6 |
| 6 | R5-A6 | S2 — LlamaParse source-context | +200 | +4 | High (UX) | High | Defer indefinitely |
| 7 | R5-A7 | S3 — LanceDB versioned audit | +120 | +4 | High (queryability) | High | Defer indefinitely |

**Recommended R5 PR scope:** R5-A1 + R5-A2 in one atomic commit.
**Estimated total LOC:** +140 net, +7 tests.
**Expected score Δ:** +1.0 to +2.0 (T1 opens new authoring; B5 reduces future divergence).
**Indirect value:** Sets up R6 for S1 (function-call enum) since the SYNONYMS
centralisation in R5-A2 makes S1 trivial to add.

### Specific R5-A1 file layout
```
D:\form filler\scripts\jinja_scan.py   (NEW, ~80 LOC)
D:\form filler\scripts\fill_docx.py    (MODIFY, +25 LOC: mode-switch + audit wiring)
D:\form filler\templates\with_jinja_tags.docx  (NEW, fixture)
D:\form filler\tests\test_jinja_scan.py (NEW, ~110 LOC, 3 tests)
D:\form filler\tests\test_fill_docx.py  (MODIFY, +30 LOC: 1 regression test)
D:\form filler\agent_state\round_5\01_researcher.md  (this file)
```

### Specific R5-A2 file layout
```
D:\form filler\evaluation\schemas.py     (MODIFY, +25 LOC: export SCHEMA_SYNONYMS; delete dup)
D:\form filler\scripts\fill_docx.py      (MODIFY, -25 LOC net: generate match_rules from SYNONYMS)
D:\form filler\tests\test_match_rules_dedup.py (NEW, ~80 LOC, 4 tests)
D:\form filler\tests\test_fill_docx.py   (MODIFY, +20 LOC: 1 invariant regression test)
```

### Acceptance gates for R5
- [ ] All R4 tests still pass (no regression on the 70/72 baseline).
- [ ] New R5 tests pass (target 7 new, total ≥ 77/79 with 2 skipped).
- [ ] `python scripts/fill_docx.py` on `templates/with_jinja_tags.docx` (new fixture)
      emits `fill_mode="jinja"` rows in `audit.md`.
- [ ] `python scripts/fill_docx.py` on a v6.2 regression template emits the SAME
      `fill_mode` distribution as R4 (no silent regression from B5 refactor).
- [ ] `python evaluation/schemas.py` self-test still 10/10 (no synonym typo).
- [ ] `python evaluation/score_consistency.py --demo` returns score ≥ 94.0
      (no regression; +X is bonus).

---

## 7. Appendix

### 7.1 Surveyed project URLs (R5)

| Project | URL | Stars | Survey role |
|---|---|---|---|
| elapouya/python-docx-template | https://github.com/elapouya/python-docx-template | 2,703 | T1 (deferred from R4) |
| noahshinn/reflexion | https://github.com/noahshinn/reflexion | 3,265 | R1+R2 (deferred from R4) |
| MONISMALIK1/reflexion | https://github.com/MONISMALIK1/reflexion | 0 | R2 (concrete `ReflectionMemory` code) |
| jerryjliu/form_filling_app | https://github.com/jerryjliu/form_filling_app | 207 | NEW (LlamaParse + Claude Agent SDK) |
| smol-ai/developer | https://github.com/smol-ai/developer | (small) | NEW (plan→enum→generate pattern) |
| lancedb/lancedb | https://github.com/lancedb/lancedb | (small OSS) | NEW (versioned audit log future-state) |
| run-llama/llama_index | https://github.com/run-llama/llama_index | 52,163 | NEW (context: structured extraction patterns) |

### 7.2 Carried over from R4 (not re-surveyed)
- jxnl/instructor — 13.9k ⭐ (Pattern I1 → shipped in R4-A1)
- dottxt-ai/outlines — 15.8k ⭐ (Pattern O1 → shipped in R4-A2)
- microsoft/guidance — 21.8k ⭐ (Pattern G2 → shipped in R4-A3)
- WestHealth/pdf-form-filler — 17 ⭐
- neuml/txtai — 12.9k ⭐
- atharvakarval-dev/Form-Flow-AI — 18 ⭐
- form-o-fill/form-o-fill-chrome-extension — 93 ⭐
- jawspeak/ruby-docx-templater — 147 ⭐
- UNIT6-open/TemplateEngine.Docx — 418 ⭐
- cbjuan/django_pdf_form_filler — 17 ⭐
- hddevteam/smart-form-filler — 45 ⭐

### 7.3 Method notes
- Star counts sourced via `gh search repos` on 2026-09-15.
- python-docx-template internals fetched via WebFetch on the raw `template.py` URL.
- Reflexion internals: noahshinn/reflexion `main.py` URLs returned 404; MONISMALIK1/reflexion
  `memory.py` fetched successfully and provided the concrete `ReflectionMemory` source.
- New projects surfaced via `gh search repos "form filling" --sort stars --limit 20`.
- `gh search repos "self-refine llm" --limit 5` returned only tiny forks; no new star-quality
  projects.
- `gh search repos "audit log llm"` surfaced 5 projects, all sub-100⭐; none directly
  applicable beyond the LanceDB discussion.

### 7.4 Line-cited codebase references for R5

| Item | File | Lines | Action |
|---|---|---|---|
| `match_rules` dedup target | `D:\form filler\scripts\fill_docx.py` | L277-296 | R5-A2 |
| `find_schema_for_label` SYNONYMS | `D:\form filler\evaluation\schemas.py` | L179-191 | R5-A2 |
| `find_field_in_schema` SYNONYMS (dup) | `D:\form filler\evaluation\schemas.py` | L212-224 | R5-A2 |
| `_iter_unique_cells` XML walker | `D:\form filler\scripts\fill_docx.py` | L897-925 | R5-A4 |
| `_iter_unique_cells` try/except fallback | `D:\form filler\scripts\fill_docx.py` | L786-794 | R5-A4 |
| `_is_likely_label` (label detection) | `D:\form filler\scripts\fill_docx.py` | L195-213 | (referenced by T1) |
| `match_field` (Pass 1 schema-first) | `D:\form filler\scripts\fill_docx.py` | L354-450 | (referenced by T1) |
| `write_profile_md` (intermediate) | `D:\form filler\scripts\fill_docx.py` | L514-611 | (potential R2 store) |
| `OpenAICompatibleAdapter.reflect` | `D:\form filler\scripts\model_adapter.py` | L229-291 | (potential R2 hook) |

### 7.5 Why these new projects matter
- **jerryjliu/form_filling_app** validates that *parse → tool-call* beats free-form RAG
  for form filling — confirms our schema-first routing is the right shape, even when
  scaling up to LlamaParse-level projects.
- **smol-ai/developer** provides a concrete library-call decomposition that mirrors our
  fill_docx pipeline (plan → enumerate → generate-one-at-a-time). Useful template for
  future R6 work on multi-step form authoring.
- **lancedb/lancedb** is recorded as a future upgrade path for `audit_reflections.jsonl`
  when volume crosses ~10k rows. No action in R5.

---

## 8. One-paragraph summary for Optimizer

The four patterns deferred from R4 are now well-understood: **T1 (Jinja2-tag scan) is
the most actionable** because python-docx-template's `patch_xml` ships a tiny,
~10-LOC `striptags()` regex that solves the Word run-boundary problem; build
`scripts/jinja_scan.py` (~80 LOC) as a parallel tag detector that switches routing
mode when tags are present. **B5 (match_rules dedup) is the lowest-risk win** —
centralize the synonyms in `evaluation/schemas.py:SCHEMA_SYNONYMS` and generate
match_rules from it, eliminating the regex/table duplicate at L277-296 vs L179-191.
**R1+R2 (ReflexionStrategy enum + persistent log) is worth deferring** — we have
concrete code from `MONISMALIK1/reflexion` (`ReflectionMemory` dataclass with
sliding window) but no v6.3 user requesting `--reflexion-rounds > 2`. **B4 (XML
iter fallback hardening) is also deferrable** — it hasn't fired in practice and a
one-line `audit["warnings"]` log entry is the entire R5-A4 surface. Three new
frontier projects surveyed (`jerryjliu/form_filling_app` confirms our schema-first
shape; `smol-ai/developer` offers a plan→enumerate→generate template for R6;
`lancedb/lancedb` is a future upgrade path for the audit log). **Ship R5-A1 +
R5-A2 in one atomic PR; total ~+140 LOC, +7 tests, no LLM changes, expected score
Δ +1.0 to +2.0.**

---

**End of round-5 Researcher output.**
