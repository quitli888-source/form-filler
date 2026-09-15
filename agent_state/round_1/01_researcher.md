# Round 1 — Researcher Output

## 1. Surveyed Projects (5)

### 1.1 microsoft/guidance — https://github.com/microsoft/guidance
- **Stars:** 21.8k
- **One-line description:** A programming paradigm for steering LLMs that supports constrained generation, JSON schemas, regex/grammar, and interleaved Pythonic control flow.
- **Key architectural ideas observed:**
  - Token-level **fast-forwarding** — when output is constrained, known tokens are inserted without a forward pass (cuts latency/cost).
  - **Offline grammar debugging** via a Mock model (no API calls needed to validate a grammar).
  - **Composable `@guidance` functions** that form a reusable CFG — a DSL for LLM output.
  - **Pydantic-style JSON generation** with structural guarantees, not post-hoc parsing.
- **Source quote:** "Constrained generation... Force model output to match regex patterns, grammar rules, or be selected from a predefined list of options. Generating JSON via Pydantic schemas... fast-forwarding reduces GPU usage and latency."

### 1.2 dottxt-co/Outlines — https://github.com/dottxt-co/Outlines
- **Stars:** 15.8k
- **One-line description:** Library guaranteeing **structured outputs from any LLM** during generation via regex, CFG, JSON/Pydantic, or function-call signatures.
- **Key architectural ideas observed:**
  - **Provider-agnostic** — same code runs against vLLM, Ollama, transformers, llama.cpp, OpenAI (no rewrite to swap models).
  - **Type-as-prompt** — Python type hints (`Literal["A","B","C"]`, Pydantic model) become generation constraints.
  - **Application pattern** — encapsulated prompt template + output type = reusable component.
  - **Multiple output types** unified under one API: regex, JSON, multiple-choice, function-call.
- **Source quote:** "Pass the desired output type directly... Guaranteed valid structure matching Python type hints or Pydantic models. Works with any model across providers."

### 1.3 noahshinn/reflexion — https://github.com/noahshinn/reflexion
- **Stars:** 3.3k (NeurIPS 2023 paper repo)
- **One-line description:** Agents that **verbally self-critique** after each failed attempt and store reflections in persistent memory for the next try.
- **Key architectural ideas observed:**
  - **Last-attempt + self-reflection** appended as context for next trial (vs. only retry).
  - **Persistent memory file** of reflections survives across runs.
  - **Four reflexion strategies** (NONE / LAST_ATTEMPT / REFLEXION / LAST_ATTEMPT_AND_REFLEXION) are first-class knobs.
  - **ReAct trace + reflection log** = auditable iteration history.
- **Source quote:** "Reflexion: Language Agents with Verbal Reinforcement Learning... Self-reflection on the last attempt as context... Persistent memory for self-reflections across trials and resumption of logged runs."

### 1.4 THUDM/LongWriter — https://github.com/THUDM/LongWriter
- **Stars:** 1.9k (ICLR 2025)
- **One-line description:** Method + models + benchmarks for **10,000+ word coherent long-form generation** with explicit length/quality evaluation.
- **Key architectural ideas observed:**
  - **Plan-then-write** decomposition — generate an outline first, then expand each section ("AgentWrite" pipeline).
  - **Two formal benchmarks** (LongBench-Write, LongWrite-Ruler) measure *length compliance* + *quality* — not just one or the other.
  - **LongWriter-6k dataset** = 6k synthetic long-form samples built via the agent pipeline (reusable training data pattern).
  - **Structured per-chunk generation** with global outline state propagated across chunks.
- **Source quote:** "AgentWrite pipeline: an automated data construction pipeline for ultra-long outputs... LongBench-Write (quality + length) and LongWrite-Ruler (maximum output length stress test)... capable of generating 10,000+ words in roughly one minute."

### 1.5 smol-ai/developer — https://github.com/smol-ai/developer
- **Stars:** 12.2k
- **One-line description:** A "junior developer" agent that scaffolds a codebase from a product spec via a **plan → file paths → generate-code** pipeline.
- **Key architectural ideas observed:**
  - **Three-stage pipeline**: (1) write a `shared_dependencies.md` plan, (2) emit JSON file paths via function calling, (3) generate code per file.
  - **`shared_dependencies.md`** — an intermediate, human-readable artifact that all later generation steps reference (kills hallucinated cross-file imports).
  - **Library / Git-Repo / API** three usage modes from one core.
  - **Markdown-as-prompt** — fenced-code blocks inside `.md` carry structured spec into free-text context.
- **Source quote:** "Uses an intermediate shared_dependencies.md planning step to keep cross-file references coherent, addressing hallucinated cross-file dependencies... Function Calling API to reliably return JSON file paths."

---

## 2. Transferable Patterns (8 ideas)

### Pattern A — Schema-as-Prompt (Pydantic / JSON constrained generation)
- **Source project:** Outlines (also: guidance)
- **What it is:** Define each form field as a typed slot (Pydantic model with `Literal`, `Field(min_length=...)`, `Field(max_length=...)`, regex pattern) and pass the schema to the LLM so generation is *constrained by the type system* instead of post-validated. Word-count limits, "must be one of: A/B/C", date format, email regex all become type constraints.
- **Why it applies to form-filler:** The current SKILL.md re-asks the user for word counts and validators on every run. If `field.py` declares `recommendation_letter: str = Field(min_length=200, max_length=400)` (and the script calls a structured-output backend), the LLM *cannot* return 600 words for a "≤400" field. This kills a whole class of inconsistency errors before the audit-table step even runs.
- **Estimated effort:** medium (need to add an Outlines/guidance layer, define Pydantic models for each form template)
- **Estimated impact:** high

### Pattern B — Plan → Outline → Expand (AgentWrite-style decomposition)
- **Source project:** LongWriter
- **What it is:** For long self-recommendation letters / statements of purpose, first generate a structured outline (sections + target word count per section), then expand each section independently, stitching the result. The outline is kept as a first-class artifact for review.
- **Why it applies to form-filler:** A 1500-word motivation letter today is generated as one shot — exceeding word limits and drifting in coherence. Decomposing into "Section 1 (~200w: opening), Section 2 (~400w: research fit)..." with a per-section budget mirrors the way `fill_docx.py` already decomposes the form into fields, but at the *content* level inside long fields.
- **Estimated effort:** medium (add an outline-pass to SKILL.md step 3)
- **Estimated impact:** high

### Pattern C — Reflexion Loop (self-critique on each filled field)
- **Source project:** Reflexion
- **What it is:** After each generated field, the agent asks itself "does this contradict any other field? Does it violate the prompt? Did I hallucinate a number/name?" and appends a short reflection. On the next pass, prior reflections are injected into context to avoid repeating the same mistake.
- **Why it applies to form-filler:** form-filler already has a "consistency check" stage but it works on the *output*. Reflexion flips this: a self-critique before the audit step dramatically reduces audit failures. The audit table (`templates/audit_table.md`) becomes the persistent memory file.
- **Estimated effort:** small (one extra LLM call per field, audit table extended with a `reflections:` column)
- **Estimated impact:** high

### Pattern D — Intermediate Spec Artifact (shared_dependencies.md)
- **Source project:** smol-developer
- **What it is:** Before any generation, write a single human-readable markdown artifact listing all entities, names, dates, and cross-references that will appear. Every later step reads this artifact. It is the source of truth for *consistency*.
- **Why it applies to form-filler:** form-filler's progressive profile collection *already* gathers this data, but the profile lives in scattered user messages, not one consolidated doc. Promoting `profile.md` to a first-class artifact (with a versioned checksum) and making every prompt explicitly include `@profile.md` would eliminate "John Smith" / "Jon Smith" mismatches between fields.
- **Estimated effort:** small (add `profile.md` writer + a prompt-side `@include` convention to SKILL.md)
- **Estimated impact:** high

### Pattern E — Offline Grammar / Field-Rule Debugging (Mock-model validation)
- **Source project:** guidance
- **What it is:** Define each field's grammar/rule once; test it offline against sample strings without paying for LLM calls. Catch "this regex never matches" / "this word-limit is unreachable" before the user runs the tool.
- **Why it applies to form-filler:** A common failure mode today is discovering at runtime that a field's constraint is unachievable (e.g., "200 words describing research interests" when the source doc only has 30 words of relevant material). A `validate_rules.py --mock` pre-flight check would catch this in CI.
- **Estimated effort:** small (add a test fixtures dir + a mock-runner to `scripts/fill_docx.py`)
- **Estimated impact:** medium

### Pattern F — Provider-Agnostic Model Adapter
- **Source project:** Outlines (also: guidance, LMFlow)
- **What it is:** A thin interface (`generate(prompt, schema) -> structured`) with multiple backends (OpenAI, Claude, local vLLM, llama.cpp). Users pick model once; the rest of the pipeline doesn't change.
- **Why it applies to form-filler:** SKILL.md currently bakes in assumptions about a single LLM provider. A `model_adapter` abstraction lets users run form-filler offline (local model for sensitive docs like recommendation letters) vs. cloud (for speed). It also lets the *Reviewer* test changes against multiple model strengths.
- **Estimated effort:** medium (refactor SKILL.md to call `model_adapter.generate(...)` instead of direct API calls)
- **Estimated impact:** medium

### Pattern G — Token Fast-Forwarding / Cost & Latency Budgeting
- **Source project:** guidance (also: LMFlow with speculative decoding)
- **What it is:** When the constraint pins tokens (e.g., a date field starts with "20", or a country is one of 5 options), insert the known tokens without a model forward pass. Track per-field cost/latency and surface them.
- **Why it applies to form-filler:** Form-filler currently makes a full LLM call per field. With ~20–50 fields per form, even cheap calls add up. Fast-forwarding structured ones (dropdown selections, date formats) reduces cost and lets the budget stretch toward the long-text fields where the model actually adds value.
- **Estimated effort:** medium (requires structured-output backend; partly piggybacks on Pattern A)
- **Estimated impact:** medium

### Pattern H — Evaluation Harness (per-field scoring)
- **Source project:** LongWriter (LongBench-Write, LongWrite-Ruler)
- **What it is:** Formal benchmarks measuring (a) length compliance, (b) quality, (c) factual consistency — with reusable scoring scripts in `evaluation/`.
- **Why it applies to form-filler:** The current `audit_table.md` is a manual rubric. A `eval/` directory with automated scorers (length check, regex check, cross-field consistency check, tone classifier) would let the multi-agent loop measure whether each round's improvements actually moved the needle.
- **Estimated effort:** medium-large (scoring rubric + CI integration)
- **Estimated impact:** medium-high (this is the *measurement* that makes the optimization loop work)

---

## 3. Top 3 Recommendations

### 1. Pattern D — Intermediate Spec Artifact (`profile.md`) — **do this first**
- **Why first:** Smallest effort, biggest near-term win for consistency. It's a documentation/convention change to SKILL.md, not a code refactor.
- **Concrete deliverable:**
  - Add `profile.md` as a first-class output of step 2 (semantic field mapping).
  - Every prompt template in step 3+ includes `@profile.md` as a top-of-context reference.
  - Versioned (e.g., `profile_v3.md`) so the audit table can diff versions and explain *why* field X changed.
- **Risk:** none — additive change.

### 2. Pattern C — Reflexion Loop on each filled field — **do this second**
- **Why second:** Builds on Pattern D (reflections go *into* the audit table next to the field). Adds one LLM call per field, but the audit-step failures should drop dramatically.
- **Concrete deliverable:**
  - New step in SKILL.md between "fill" and "audit": `3.5 self-critique`.
  - Extend `audit_table.md` with a `reflection:` column.
  - `fill_docx.py` adds a `--reflexion-rounds N` flag (default 1).
- **Risk:** doubles LLM cost; mitigate with Pattern G later.

### 3. Pattern A — Schema-as-Prompt for field-level constraints — **do this third**
- **Why third:** Highest payoff (kills whole error classes) but biggest code change. Requires choosing a structured-output backend (Outlines is Pythonic and model-agnostic — best fit).
- **Concrete deliverable:**
  - Define a Pydantic model per form template in `templates/schemas/`.
  - `fill_docx.py` calls an Outlines (or guidance) session with the field schema.
  - Word-limit, "one of A/B/C", date-format, and email-regex constraints become *ungoogleable-by-LLM* generation rules.
- **Risk:** some local LLMs don't support structured output — needs a fallback path (Pattern F / provider abstraction).

These three together form a coherent narrative: **D** gathers ground truth, **C** self-corrects against it, **A** makes the next pass structurally correct by construction.

---

## 4. Anti-patterns to avoid

### Anti-pattern 1 — Free-form prose generation for short fields
Projects like AI-Writer and LongWriter are tuned for *long, flowing* output. form-filler must **not** adopt "let the model ramble then trim" for fields like "city of birth" or "graduation year". These fields need Pattern A (constrained generation), not LongWriter-style expansion. Importing a "writing-quality" prompt into a date field will add cost, hallucinate, and break the audit. **Mitigation:** keep field-type → generation-strategy mapping explicit; do not unify them.

### Anti-pattern 2 — Massive context stuffing (full-form dump into every prompt)
Some novel projects (and early smol-developer forks) bundle the entire spec into every prompt "for safety". For form-filler with 50+ fields, this blows the context window and *hurts* consistency because the model re-derives facts each time. Prefer Pattern D (a small, versioned `profile.md` + per-field schema from Pattern A) over a 10k-token single-prompt approach. The novel-gen world's "more context = better" instinct does not transfer.