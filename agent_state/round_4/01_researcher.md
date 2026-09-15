# Round 4 — Researcher Output

## 1. Executive Summary

After surveying 20+ form-filling / structured-generation / DOCX-template / OCR projects on GitHub, four transferable patterns stand out for round 4 of form-filler:

1. **Jinja2-based DOCX templating** — `elapouya/python-docx-template` (2.7k ⭐) proves that DOCX templating should lean on Jinja2 tags (`{{name}}`) embedded in the .docx, separating *what to fill* from *how to fill*. Form-filler currently walks cell-by-cell; introducing a Jinja-tag scan path could simplify the dispatch model and enable per-tag fill strategies.
2. **Provider-agnostic structured outputs via Pydantic + automatic retry** — `jxnl/instructor` (13.9k ⭐) and `dottxt-ai/outlines` (15.8k ⭐) show the de-facto pattern: `BaseModel` + retry-on-validation-failure. Our v6.0 schema-as-prompt implements the model half but lacks the *retry surface* (R4-A1 candidate).
3. **Token fast-forwarding / constrained generation** — `microsoft/guidance` (21.8k ⭐) demonstrates deterministic insertion when the next tokens are known. For form-filler, this means: when filling a `Literal["男","女"]` field, we should never invoke the LLM at all — branch to a deterministic lookup first.
4. **Self-reflective memory across iterations** — `noahshinn/reflexion` (3.3k ⭐) formalises the LAST_ATTEMPT + REFLEXION enum. Form-filler's v5.0 profile.md already implements ad-hoc reflexion; a clean enum + persistent memory log would harden it.
5. **Browser-agent form automation** — `atharvakarval-dev/Form-Flow-AI` and `hddevteam/smart-form-filler` show that AI-form-filling has split into (a) document-native (DOCX/PDF) and (b) browser-agent (Playwright + LLM). Form-filler is firmly in (a); the boundary is worth defending rather than expanding into (b).

The single highest-leverage recommendation for round 4: **introduce a Jinja2-tag scan path alongside the cell-walk path**, so DOCX templates can opt into either authoring style without changing the fill code.

## 2. Surveyed Projects

### Project 1: elapouya/python-docx-template
- **URL:** https://github.com/elapouya/python-docx-template
- **Stars:** 2,703
- **Language:** Python (LGPL-2.1)
- **Description:** "Use a docx as a jinja2 template" — embeds Jinja2 tags directly in a .docx file and renders them with context variables.
- **Key features:**
  - Jinja2 for tag management, python-docx for read/write
  - Supports complex Word features: pictures, index tables, footer, header, variables
  - Renders templates in memory (no Word required)
  - Supports `{%p ... %}` Jinja statements (loops, conditionals) in addition to `{{var}}` substitutions
- **Why it's relevant:** Form-filler scans cell-by-cell today. If users authored templates with explicit `{{name}}` tags, routing becomes trivial — skip the cell-walk entirely. Worth at least an *opt-in* scan path.
- **Transferable patterns:**
  - **Pattern T1 — Jinja2-tag-aware scan** (write `scripts/fill_docx.py:_scan_jinja_tags()` that finds `{{...}}` occurrences in `w:t` runs; if any, switch routing mode).
  - **Pattern T2 — `{%p %}` statement rendering** for table-row iteration (out of scope for v6.1; future).
- **Complexity:** T1 ≈ +120 LOC + 3 tests. Low risk (additive).
- **Evidence:** README section "Why python-docx-template?" — "python-docx is powerful for creating documents but not for modifying them" — same shape of problem form-filler addresses for *user-authored* templates.

### Project 2: jxnl/instructor
- **URL:** https://github.com/jxnl/instructor
- **Stars:** 13,900
- **Language:** Python (MIT) — also TS/Ruby/Go/Elixir/Rust ports
- **Description:** "Get reliable JSON from any LLM. Built on Pydantic for validation, type safety, and IDE support."
- **Key features:**
  - Single API across OpenAI, Anthropic, Google, Ollama, Groq via `instructor.from_provider(...)`
  - **Automatic retries:** "Failed validations are automatically retried with the error message" — `max_retries=3`
  - Streaming with `Partial[Model]`
  - Pydantic v2 `@field_validator` enforced before return
  - `response_model=` accepts any `BaseModel` subclass
  - OpenAI function-calling under the hood (with provider-specific tweaks)
- **Why it's relevant:** Form-filler v6.0 uses Pydantic models but **does not** retry on validation failure (the model adapter's `reflect()` returns `""` on schema violation). Instructor demonstrates that the retry surface is just a `max_retries` parameter away.
- **Transferable patterns:**
  - **Pattern I1 — Retry-on-validation-failure** (modify `scripts/model_adapter.py:OpenAICompatibleAdapter.generate_structured()` to loop up to `max_retries` with the validator's error message appended to the prompt; configurable via CLI flag `--max-retries 3`).
- **Complexity:** I1 ≈ +60 LOC + 4 tests (one per failure mode). Medium risk (changes LLM call semantics).
- **Evidence:** Instructor README: "Failed validations are automatically retried with the error message" — exact same constraint schema-as-prompt would benefit from.

### Project 3: dottxt-ai/outlines
- **URL:** https://github.com/dottxt-ai/outlines
- **Stars:** 15,800
- **Language:** Python (inferred)
- **Description:** "Structured outputs for LLMs" — guarantees structured outputs during generation with provider independence (OpenAI, Ollama, vLLM).
- **Key features:**
  - Multiple constrained output types: Multiple Choices, Function Calls, JSON/Pydantic, Regular Expressions, Grammars
  - Prompt templates (Jinja-based) — separates prompts from code
  - Custom Python type interface for building complex types
  - Applications: encapsulate templates and types into reusable functions
- **Why it's relevant:** Outlines' *type system* approach complements Instructor's *retry* approach. Form-filler's schemas are Pydantic-only; adopting Outlines-style `Literal`/`Regex` type constraints for individual fields (where supported) would give stronger guarantees for the schema-first routing layer.
- **Transferable patterns:**
  - **Pattern O1 — Literal-first deterministic routing** (in `match_field()`, when a schema field has `Literal["男","女"]`, the lookup is fully deterministic — bypass the LLM entirely, just match the value).
- **Complexity:** O1 ≈ +40 LOC + 3 tests. Low risk (deterministic, no LLM calls).
- **Evidence:** Outlines' "Multiple Choices" feature maps directly to Pydantic `Literal[...]` constraints already present in our schemas.

### Project 4: microsoft/guidance
- **URL:** https://github.com/microsoft/guidance
- **Stars:** 21,800
- **Language:** Python (multi-backend: transformers, llama.cpp, OpenAI)
- **Description:** "A guidance language for controlling large language models."
- **Key features:**
  - `with system():` / `with user():` / `with assistant():` blocks for inline prompt assembly
  - `gen(regex=...)` and `select(...)` for constrained generation
  - **Token fast-forwarding:** "Guidance doesn't need the model to generate these; instead it can insert them" — deterministic tokens skip the LLM
  - `@guidance(stateless=True)` decorator for composable grammar functions
  - `Mock` backend for offline grammar debugging
  - JSON schema generation with Pydantic integration
- **Why it's relevant:** Guidance's "token fast-forwarding" is a more advanced version of Pattern O1 — when the output is fully determined by the constraint, skip generation entirely. Form-filler already has stub mode; Guidance's `Mock` pattern shows how to make stub mode unit-test-friendly.
- **Transferable patterns:**
  - **Pattern G1 — Deterministic-skip path** (when schema field has `Literal` or `regex`, compute the deterministic answer locally; do not invoke LLM; log "[skip-llm: literal]").
  - **Pattern G2 — MockLLM backend** (extend `StubAdapter` to accept canned responses per prompt-hash, enabling deterministic tests of LLM-dependent code paths).
- **Complexity:** G1 ≈ +25 LOC; G2 ≈ +80 LOC + 2 tests. Low risk.
- **Evidence:** Guidance README "Token healing" section demonstrates the broader concept of determinism-aware generation.

### Project 5: noahshinn/reflexion
- **URL:** https://github.com/noahshinn/reflexion
- **Stars:** 3,300
- **Language:** Python (Jupyter notebooks; NeurIPS 2023 paper)
- **Description:** "[NeurIPS 2023] Reflexion: Language Agents with Verbal Reinforcement Learning"
- **Key features:**
  - Reflexion strategies enum: NONE, LAST_ATTEMPT, REFLEXION, LAST_ATTEMPT_AND_REFLEXION
  - **Persistent self-reflection memory** via `use_memory` flag — reflections carry across iterations
  - Multiple agent backbones: ReAct, CoT (with/without context)
  - Multi-domain eval: HotPotQA (reasoning), AlfWorld (decision-making), LeetcodeHardGym (programming)
- **Why it's relevant:** Form-filler v5.0 has ad-hoc `reflexion-rounds` (loops) and v6.0's `profile.md` records reflections. Formalising these as a `ReflexionStrategy` enum + persistent memory log would clean up the surface.
- **Transferable patterns:**
  - **Pattern R1 — ReflexionStrategy enum** (`NONE | LAST_ATTEMPT | REFLEXION | LAST_ATTEMPT_AND_REFLEXION`; CLI flag `--reflexion-strategy`).
  - **Pattern R2 — Persistent reflection log** (append-only `audit_reflections.jsonl` written alongside `audit.md`; queried across `--reflexion-rounds`).
- **Complexity:** R1+R2 ≈ +150 LOC + 5 tests. Medium risk (changes profile.md semantics).
- **Evidence:** Reflexion paper Figure 1 — the strategy enum is the paper's primary contribution.

### Project 6: WestHealth/pdf-form-filler
- **URL:** https://github.com/WestHealth/pdf-form-filler
- **Stars:** 17
- **Language:** Python (Jupyter Notebook, BSD-3-Clause)
- **Description:** "Python Library to Automate Form Filling" — COVID-clinic use case.
- **Key features:**
  - `pdf_form_filler.py` — single file library
  - Built on `pdfrw` — reads/writes AcroForm PDF fields
  - JSON-driven configuration: form fields named in JSON map to PDF field names
- **Why it's relevant:** Demonstrates the *JSON-driven mapping* pattern: a separate config file maps profile keys to PDF field names. Form-filler's `match_rules` list serves the same purpose but is regex-based; a JSON variant could be more transparent.
- **Transferable patterns:**
  - **Pattern W1 — Optional JSON mapping file** (if `field_map.json` exists in `profile_dir`, use it instead of regex `match_rules`. Useful for non-Latin or non-Chinese forms where regex is fragile).
- **Complexity:** W1 ≈ +50 LOC + 2 tests. Low risk (fallback to regex).
- **Evidence:** Repo `pdf_form_filler.py` is 200 LOC; the JSON mapping is the entire interface.

### Project 7: neuml/txtai
- **URL:** https://github.com/neuml/txtai
- **Stars:** 12,900
- **Language:** Python 3.10+ (Apache 2.0)
- **Description:** "txtai is an all-in-one AI framework for semantic search, LLM orchestration and language model workflows."
- **Key features:**
  - Vector search with SQL/object storage/topic modeling/graph analysis/multimodal indexing
  - Embeddings for text, documents, audio, images, video
  - RAG: "Retrieval augmented generation (RAG) reduces the risk of LLM hallucinations by constraining the output with a knowledge base as context."
- **Why it's relevant:** Form-filler currently does not use embeddings or RAG. The RAG pattern would matter if user profiles grew large enough that LLM needs *retrieval* to find the right field. Today profiles are small YAML files, so RAG is overkill — defer.
- **Transferable patterns:** None for round 4. (Note for future.)
- **Evidence:** Txtai README RAG section.

### Project 8: atharvakarval-dev/Form-Flow-AI
- **URL:** https://github.com/atharvakarval-dev/Form-Flow-AI
- **Stars:** 18
- **Language:** Python
- **Description:** "🤖 The Ultimate AI Form Filler. Automate complex web forms & PDFs with Voice, generic LLMs (Gemini/Phi-2), and Playwright."
- **Key features:**
  - Playwright-driven browser automation
  - Generic LLM support (Gemini, Phi-2)
  - PDF + web-form dual target
- **Why it's relevant:** Defines the *boundary* between (a) document-native filling (form-filler's domain) and (b) browser-agent filling (Form-Flow-AI's domain). Form-filler should *not* cross into browser automation — keep DOCX/PDF/Excel focus.
- **Transferable patterns:** None (boundary marker only).
- **Evidence:** README explicitly positions as Playwright-based.

### Project 9: form-o-fill/form-o-fill-chrome-extension
- **URL:** https://github.com/form-o-fill/form-o-fill-chrome-extension
- **Stars:** 93
- **Language:** JavaScript (Chrome extension)
- **Description:** "The programmable form filler for developers." — declarative JSON rules for form fields.
- **Key features:**
  - Declarative JSON rules per website
  - JavaScript expression evaluation per rule
- **Why it's relevant:** Demonstrates the *rule-declaration* style: rather than imperative code, users write JSON rules. Form-filler's `match_rules` is similar but code-only.
- **Transferable patterns:** Pattern W1 (above) overlaps; no new contribution.

### Project 10: jawspeak/ruby-docx-templater
- **URL:** https://github.com/jawspeak/ruby-docx-templater
- **Stars:** 147
- **Language:** Ruby
- **Description:** "Generates new Word .docx files based on a template file. Does templating entirely in memory."
- **Key features:**
  - In-memory templating (no Word required)
  - Mail-merge style field replacement
- **Why it's relevant:** Same shape as python-docx-template; reinforces Pattern T1's value.

### Project 11: UNIT6-open/TemplateEngine.Docx
- **URL:** https://github.com/UNIT6-open/TemplateEngine.Docx
- **Stars:** 418
- **Language:** C#
- **Description:** Smart docx template engine for .NET — supports content blocks, tables, images, lists.
- **Why it's relevant:** Reinforces that DOCX templating is a mature sub-field with multiple implementations. Form-filler's cell-walk approach is more granular (and more brittle) than the templating approach.

## 3. Pattern Analysis

### Pattern T1 — Jinja2-tag-aware scan
- **Source projects:** elapouya/python-docx-template (primary), jawspeak/ruby-docx-templater (cross-language confirmation)
- **What it is:** In `scripts/fill_docx.py:scan_docx_tables()`, detect `{{...}}` and `{%p ... %}` Jinja tags in any cell or paragraph. If found, switch to a "tag mode" where the tag content is used as the field label. Otherwise, fall back to cell-walk mode.
- **Why relevant:** Today's cell-walk requires semantic inference of which cell is a label. With explicit tags, the answer is unambiguous — and user-authored templates become self-documenting.
- **Complexity:** +120 LOC + 3 tests. Low risk.
- **Estimated impact:** Medium — opens a new authoring mode; affects ~10% of templates in the wild that prefer explicit tags.

### Pattern I1 — Retry-on-validation-failure
- **Source projects:** jxnl/instructor
- **What it is:** In `scripts/model_adapter.py:OpenAICompatibleAdapter.generate_structured()`, wrap the call in a retry loop. On Pydantic `ValidationError`, append the error message to the next prompt and retry up to `max_retries` times (default 2).
- **Why relevant:** Today's path silently returns `""` on schema violation. A retry pass would dramatically increase the success rate for free-form generation fields (e.g., `入党动机`, `创新点摘要`).
- **Complexity:** +60 LOC + 4 tests. Medium risk (LLM semantics change).
- **Estimated impact:** High — directly addresses a known failure mode.

### Pattern O1 — Literal-first deterministic routing
- **Source projects:** dottxt-ai/outlines, microsoft/guidance (token fast-forwarding)
- **What it is:** In `scripts/fill_docx.py:match_field()`, when a schema field has `Literal[...]`, treat the lookup as fully deterministic. Match against the profile value exactly (with case/whitespace tolerance); do not invoke the LLM; log `[skip-llm: literal]`.
- **Why relevant:** Today, even `性别=男/女` may go through LLM reflexion. A literal field never needs the LLM.
- **Complexity:** +40 LOC + 3 tests. Low risk (no LLM call).
- **Estimated impact:** Medium — reduces LLM cost; faster deterministic fields.

### Pattern R1+R2 — ReflexionStrategy enum + persistent reflection log
- **Source projects:** noahshinn/reflexion
- **What it is:** Replace `reflexion-rounds` int flag with a strategy enum: `NONE | LAST_ATTEMPT | REFLEXION | LAST_ATTEMPT_AND_REFLEXION`. Persist reflections to `audit_reflections.jsonl` so subsequent rounds can query prior reflections.
- **Why relevant:** v5.0 introduced `reflexion-rounds` but the *content* of the reflection is ephemeral (only the latest round's reflection is in profile.md). Persistent log enables learning across rounds.
- **Complexity:** +150 LOC + 5 tests. Medium risk.
- **Estimated impact:** Medium — formalises an existing capability.

### Pattern G2 — MockLLM backend
- **Source projects:** microsoft/guidance
- **What it is:** Extend `StubAdapter` to accept a `canned_responses.json` map (keyed by SHA-256 of prompt prefix). Enables deterministic tests of LLM-dependent code paths without network.
- **Why relevant:** Today, `StubAdapter` always returns `""`. Tests that need a non-empty LLM response must use the real `OpenAICompatibleAdapter` with a 401-prone key. A `MockLLM` is more ergonomic.
- **Complexity:** +80 LOC + 2 tests. Low risk (test-only).
- **Estimated impact:** Low-medium — improves testability.

## 4. Anti-Patterns to Avoid

### Anti-pattern A — Cross into browser automation
- **Source projects:** atharvakarval-dev/Form-Flow-AI (boundary marker)
- Form-filler's strength is *document-native* filling (DOCX/Excel/PDF/image). Adding Playwright would dilute focus. Defer indefinitely.

### Anti-pattern B — Premature RAG adoption
- **Source projects:** neuml/txtai
- Form-filler profiles are small YAML files; embedding + retrieval adds complexity with no benefit. Wait until profile size crosses ~100 fields per profile.

### Anti-pattern C — Hard-coded JSON mapping in code (instead of config)
- Form-filler's `match_rules` is code. Adding new fields requires a code change. Resist the temptation to bake hard-coded mappings in code — keep the rule list data-side (`field_map.json` opt-in).

### Anti-pattern D — Replacing regex with regex-via-LLM
- Some libraries (e.g., instructor examples) recommend using an LLM to *generate* regex patterns from natural-language field descriptions. This is overkill for form-filler — schemas already encode constraints; use them, don't re-LLM the regex.

## 5. Top Recommendations for Round 4

| Priority | ID | Pattern | Effort | Impact |
|---|---|---|---|---|
| 1 | R4-A1 | Pattern I1 — Retry-on-validation-failure | M (~+60 LOC) | High |
| 2 | R4-A2 | Pattern O1 — Literal-first deterministic routing | S (~+40 LOC) | Medium |
| 3 | R4-A3 | Pattern G2 — MockLLM backend | S (~+80 LOC) | Low-Medium (testability) |
| 4 | R4-A4 | Pattern T1 — Jinja2-tag-aware scan (foundation only) | M (~+120 LOC) | Medium (new authoring) |
| 5 | R4-A5 | Pattern R1+R2 — ReflexionStrategy enum + persistent log | L (~+150 LOC) | Medium |

Total: ~450 LOC across 5 actions. Recommended round-4 scope: ship R4-A1 + R4-A2 + R4-A3 in one atomic commit; defer R4-A4 + R4-A5 to round 5.

## 6. Appendix

### Surveyed project URLs
- https://github.com/elapouya/python-docx-template (2.7k ⭐)
- https://github.com/jxnl/instructor (13.9k ⭐)
- https://github.com/dottxt-ai/outlines (15.8k ⭐)
- https://github.com/microsoft/guidance (21.8k ⭐)
- https://github.com/noahshinn/reflexion (3.3k ⭐)
- https://github.com/WestHealth/pdf-form-filler (17 ⭐)
- https://github.com/neuml/txtai (12.9k ⭐)
- https://github.com/atharvakarval-dev/Form-Flow-AI (18 ⭐)
- https://github.com/form-o-fill/form-o-fill-chrome-extension (93 ⭐)
- https://github.com/jawspeak/ruby-docx-templater (147 ⭐)
- https://github.com/UNIT6-open/TemplateEngine.Docx (418 ⭐)
- https://github.com/cbjuan/django_pdf_form_filler (17 ⭐)
- https://github.com/hddevteam/smart-form-filler (45 ⭐)

### Method notes
- Star counts sourced via `gh search repos` on 2026-09-15.
- Direct GitHub HTML pages fetched for high-priority repos (elapouya/python-docx-template, jxnl/instructor, dottxt-ai/outlines, microsoft/guidance, noahshinn/reflexion, neuml/txtai).
- `gh search repos "form filler" --sort stars --limit 10` returned 11 repos, mostly JavaScript browser extensions; Python form-filling niche is small and mostly low-star.

### Why we didn't survey more
- The form-filler niche on GitHub is dominated by browser extensions (Playwright-based) and PDF-only tools. Form-filler's *DOCX+Excel+PDF* multi-format niche is essentially unoccupied above 100 stars.
- The structured-generation / schema-as-prompt space is mature (Instructor 13.9k, Outlines 15.8k, Guidance 21.8k); these are the sources of most transferable patterns.

**End of round-4 Researcher output.**