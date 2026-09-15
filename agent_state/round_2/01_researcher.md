# Round 2 — Researcher Output

> Focus: deep-dive on **Pattern A (Schema-as-Prompt)** and **Pattern F (Provider-Agnostic Adapter)**, plus a curated set of *new* projects that didn't surface in Round 1 (which surveyed guidance / Outlines / Reflexion / LongWriter / smol-developer). Round 1 shipped v5.0 with Reflexion + profile.md + audit-table render + 9-rule score harness + validate_rules.py. This round's job is to introduce the **structured-output substrate** that makes Round 1's reflexion loop and audit-table rendering structurally correct instead of probabilistically repaired.

## 1. Surveyed Projects (5 NEW — distinct from Round 1)

### 1.1 jxnl/instructor — https://github.com/jxnl/instructor
- **Stars:** ~13.9k
- **One-line description:** Python library that turns any LLM into a *reliable structured-output generator* by wrapping it with Pydantic validation + an automatic retry-with-error-feedback loop.
- **Key architectural ideas observed:**
  - **`from_provider("openai/gpt-4o")` factory** — one call, 100+ providers (OpenAI, Anthropic, Gemini, Ollama, Cohere, Groq, Mistral, etc.). The same `client.chat.completions.create(response_model=..., messages=...)` API across all of them.
  - **`max_retries=3` parameter** — on Pydantic validation failure, the library automatically re-sends the request with the previous validation error appended to the prompt. This is the *defining* pattern.
  - **`Partial[T]` streaming** — yields incrementally-validated partial objects as the model produces tokens, with each partial guaranteed to be a valid `T` so far.
  - **Provider-agnostic through mode tags** — `Mode.TOOL_CALL`, `Mode.JSON`, `Mode.MD_JSON`, `Mode.PARALLEL_TOOLS`, `Mode.GEMINI_JSON` — library picks the best per provider.
- **Source quote:** "reliable JSON from any LLM ... focused on one thing—structured extraction. It's lighter, faster, and easier to debug." And: `client = instructor.from_provider("openai/gpt-4o-mini"); user = client.chat.completions.create(response_model=User, messages=[...], max_retries=3)`.
- **Why not in Round 1:** Round 1 surveyed `outlines-dev/outlines` and `microsoft/guidance`, both of which use **constrained decoding** (the model physically cannot emit a bad token). Instructor is the complementary *post-hoc validation + retry* approach — works on every model including those with no constrained-output support (most local models today). It's the *adapter-friendly* cousin of Outlines.

### 1.2 pydantic/pydantic-ai — https://github.com/pydantic/pydantic-ai
- **Stars:** ~12k+
- **One-line description:** Pydantic-AI is the *agent* framework from the Pydantic team, built on top of `instructor`'s patterns but extended with first-class agent loops, dependency injection, and a managed gateway for cost tracking.
- **Key architectural ideas observed:**
  - **"Typed end to end"** — `Agent('openai:gpt-5.6', output_type=Sentiment)` returns a `RunResult[Sentiment]`. The static type system, the IDE, and the LLM *all agree* on the returned shape. Validation errors are caught before user code sees them.
  - **`output_type` is a first-class Pydantic model** — `Literal`, `Field(ge=, le=, max_length=, regex=)`, `Optional`, unions, nested models all become generation constraints. The library constructs a JSON schema and feeds it to the model, then validates the response.
  - **Pydantic AI Gateway** — managed proxy that fronts many providers with **failover and cost monitoring built in**. One credential covers all providers.
  - **Composition over monoliths** — tools, instructions, hooks are reusable units. Function signatures + docstrings become the tool schema automatically.
  - **Tagline mantra** — "Any model, one Python API" + "Measured, not vibes" + "No flagship feature is locked to one vendor".
- **Source quote:** "Give the agent an output type and tools, and every run comes back validated and typed ... the run is guaranteed to return a Sentiment ... moving whole classes of errors from runtime to write-time."
- **Why not in Round 1:** Round 1 surveyed `outlines-dev/outlines` and `microsoft/guidance` (constrained decoding libraries), but skipped the *agent-runtime* layer where Pydantic-AI lives. It is what you build *on top of* a structured-output backend, and the patterns there (DI, gateway, composable tools) are reusable in form-filler even without using the agent loop itself.

### 1.3 andrewyng/aisuite — https://github.com/andrewyng/aisuite
- **Stars:** ~12k+
- **One-line description:** Andrew Ng's lightweight Python library that exposes a single `chat.completions.create(model="provider:model", ...)` interface across ~10+ providers, designed for **swapping providers by changing one string** with zero refactoring.
- **Key architectural ideas observed:**
  - **Convention-based provider discovery** — `providers/<provider>_provider.py` containing a class `<Provider>Provider` (capitalized) is auto-loaded. Adding a new provider is *one file, one class*.
  - **Tiny API surface** — `client = ai.Client(); client.chat.completions.create(model=..., messages=...)` with `stream=True`, `temperature=`, `max_turns=` (for auto tool execution). Async via `aclient.chat.completions.acreate(...)`.
  - **Agents layer (newer)** — `Agent(name=..., model=..., instructions=..., tools=[...])` + `Runner.run(agent, prompt)`. Toolkits include `ai.toolkits.files(root=".")`, `ai.toolkits.git(root=".")`. State stores: in-memory, file, Postgres.
- **Source quote:** "Model names use the format `<provider>:<model-name>`; aisuite routes the call to the right provider with the right parameters ... Swap providers by changing one string."
- **Why not in Round 1:** Round 1 surveyed Outlines (provider-agnostic) but didn't surface the *swappable-adapter* pattern at the API level. aisuite is the simplest possible *hand-rolled reference implementation* — if we choose Pattern F as a minimal adapter (~150 LOC), aisuite's naming convention (`provider:model`) is the right one to copy.

### 1.4 simonw/llm — https://github.com/simonw/llm
- **Stars:** ~9k
- **One-line description:** CLI + Python library by Simon Willison that wraps OpenAI / Anthropic / Gemini / Ollama / OpenRouter / local-model endpoints behind one interface, with **every prompt and response persisted to SQLite** as a built-in feature.
- **Key architectural ideas observed:**
  - **Plugin-based architecture** — `llm install llm-gemini`, `llm install llm-anthropic`, `llm install llm-ollama` add new providers; the core is provider-agnostic.
  - **SQLite as the default storage layer** — every prompt, response, embedding, model ID, token count is logged by default. This is what makes A/B testing, regression detection, and audit trivial — the data already exists.
  - **Fragments + templates** — `llm fragment set myprompt "..."` and `llm -t myprompt "..."` (think of these as versioned prompt templates keyed by name, stored in SQLite).
  - **Schemas-as-first-class** — `llm --schema 'name, age int, bio' "Extract from bio.txt"` produces a CSV/JSON table directly; the schema is a Pydantic-shaped spec.
- **Source quote:** "Run prompts from the command-line ... Store prompts and responses in SQLite ... Generate and store embeddings ... Extract structured content from text and images."
- **Why not in Round 1:** Round 1 surveyed long-form generation projects (LongWriter, smol-developer). The `llm` library is a **developer-experience reference for how a minimal provider-agnostic tool with built-in logging should look**. The "every prompt is in SQLite" pattern is what makes regression detection *free*.

### 1.5 mangiucugna/json_repair — https://github.com/mangiucugna/json_repair
- **Stars:** ~2k+
- **One-line description:** A library that takes malformed JSON output from an LLM (missing brackets, unquoted strings, trailing commas, mixed prose) and **parses it following a BNF grammar + heuristics** to return a valid JSON string or Python object.
- **Key architectural ideas observed:**
  - **BNF-grammar parse, not regex fix** — walks `<json> ::= <primitive> | <container>` and applies structural fixes (missing closing brackets, missing quotes, line-break normalization).
  - **Schema-guided repair** — `repair_json(bad, schema=Payload, skip_json_loads=True)` — when given a Pydantic model, the repairer uses the schema to fill in default values for missing fields.
  - **Stream-stable mode** — `stream_stable=True` allows repairing partial JSON output mid-stream.
  - **CLI + library** — `json_repair -h` exposes the same logic on the command line; useful for piping.
- **Source quote:** "repair_json parses JSON that may be malformed ... by following a BNF definition ... applies heuristics ... adding missing brackets/parentheses, quoting strings, adjusting whitespace, removing stray prose."
- **Why not in Round 1:** Round 1 deferred Pattern A but didn't research the *fallback layer* below it. When constrained decoding isn't available (most local models, many cloud models in JSON mode), the only thing standing between a malformed LLM response and a hard error is a smart JSON repair step. json_repair is the **reference implementation of that fallback**.

### 1.6 (bonus) confident-ai/deepeval — https://github.com/confident-ai/deepeval
- **Stars:** ~8k+
- **One-line description:** A Pytest-style LLM evaluation framework with 50+ metrics (Hallucination, Faithfulness, Tool Correctness, Task Completion, JSON Correctness, Bias, Toxicity, Prompt Alignment) and trajectory tracing for agents.
- **Why it matters:** **"Trajectory tracing"** — `@observe()` decorators on each component let you record every step (LLM call, tool use, retrieval, sub-agent handoff) and run metrics against the *full* trace, not just the final output. form-filler's audit table is essentially a single-step trace; deepeval shows what a multi-step trace looks like.

---

## 2. Deep-Dive on Pattern A — Schema-as-Prompt

### 2.1 How mature projects handle the four corner cases

#### (a) When the model violates the schema

| Library | Strategy | Code / Quote |
|---|---|---|
| **Outlines** | **Prevent** — compiled regex/CFG/JSON-schema is turned into a token-level mask at every generation step. The model *physically cannot* emit a token that would violate the schema. | "Guaranteed valid structure - No more parsing headaches or broken JSON." |
| **Guidance** | **Prevent + fast-forward** — same token-mask approach as Outlines, plus when the constraint pins tokens (e.g., the next char is known to be `"`), those tokens are inserted without a forward pass. | "fast-forwarding of tokens. The constraints imposed by a grammar often mean that some tokens are known in advance." |
| **Pydantic-AI** | **Prevent via JSON schema prompt + validate-and-retry** — constructs a JSON schema from the Pydantic model and includes it in the system prompt. On validation failure, the error message is fed back to the model for one retry. | "every run comes back validated and typed ... the run is guaranteed to return a Sentiment" |
| **Instructor** | **Validate-and-retry (no prevention)** — sends the prompt as a tool-call or JSON-mode request, validates with Pydantic, and on failure re-sends with the validation error appended to the conversation. `max_retries=N` controls depth. | `client.chat.completions.create(response_model=User, messages=[...], max_retries=3)` |
| **json_repair** | **Repair** — after a model produces malformed JSON (e.g., a model without JSON mode), repair_json parses BNF + heuristics to fix it. Schema-guided mode uses a Pydantic model to fill defaults. | `repair_json('{"value": "1", "tags": }', schema=Payload, return_objects=True)` |

**The form-filler implication:** Outlines/Guidance give the strongest guarantees but require the model to support logit masking (vLLM, llama.cpp, some Anthropic/Google modes — not OpenAI cloud as of v5.0). Instructor works on **every** model including OpenAI/Anthropic/Claude/local. The Round-2-v5.x recommendation is **Instructor + json_repair as a fallback layer** — Instructor handles schema-violation retries, json_repair handles the "model output isn't even valid JSON" edge case.

#### (b) Streaming / partial outputs

| Library | Approach |
|---|---|
| **Instructor** | `Partial[T]` wrapper around `response_model` produces a generator yielding incrementally-validated partial objects: `User(name=None, age=None) → User(name="John", age=None) → User(name="John", age=25)`. Each partial is valid-against-schema-so-far. |
| **Outlines** | Partial regex/JSON streaming supported but you only get raw tokens; you re-validate downstream. |
| **Guidance** | Native token-streaming with named captures (`lm["bp"]` extracts a substring the grammar accepted); you consume the buffer directly. |
| **Pydantic-AI** | Streaming returns string deltas; structured output happens at the end. |

**The form-filler implication:** form-filler's `fill_docx()` writes one cell at a time per field, so we don't *need* per-token streaming — per-field is enough. But for AI-generated long text (self-recommendation letter, 500–1500 chars), Instructor `Partial` streaming would let `fill_docx.py` show the user a live progress bar of the response being built. That's a UX win, not a correctness win, so defer if budget is tight.

#### (c) Local-model vs API-model parity

| Library | Local support | API support | Parity story |
|---|---|---|---|
| **Outlines** | First-class (vLLM, llama.cpp, transformers, MLX) | First-class (OpenAI, Anthropic) | "Works with any model - Same code runs across OpenAI, Ollama, vLLM, and more." |
| **Guidance** | First-class (transformers, llama.cpp) | Limited (OpenAI only via `guidance.models.OpenAI`; no Anthropic adapter in core) | Local-first |
| **Instructor** | First-class (`ollama/llama3.2` via `from_provider`) | First-class (all major APIs) | Best parity for our use case |
| **Pydantic-AI** | First-class via model string (`ollama:llama3.2`) | First-class | "Virtually every model and provider ... swappable with a string" |

**The form-filler implication:** The user is filling a Chinese university scholarship form. Privacy matters (bank info, ID number). A local Ollama/llama.cpp model is desirable. **Outlines + Instructor both offer full parity; Instructor is the path of least resistance** because it requires no model-side logit-mask support and works on whatever Ollama serves.

#### (d) Cost / latency tracking

| Library | Built-in cost tracking? |
|---|---|
| **Outlines** | No (the library is generation-only) |
| **Instructor** | No at the library level (it relies on the provider's response.usage) |
| **LiteLLM** | Yes — full cost-tracking per call, per user, per team (it tracks $0.002/1k input tokens etc. across 100+ providers) |
| **Pydantic-AI Gateway** | Yes — managed cost monitoring built-in |
| **Portkey** | Yes — "40+ production-critical metrics" including cost per request |

**The form-filler implication:** None of the structured-output libraries track cost natively. Cost/latency tracking is a **separate concern** that Pattern F (provider adapter) should own. The adapter wraps the structured-output call and records `(tokens_in, tokens_out, latency_ms, estimated_cost_usd, model)` per call — visible in the audit table.

### 2.2 Recommended form-filler Pattern A implementation (concrete recipe)

**Step 1.** Add `pydantic>=2` to dependencies (already implied by `python-docx` ecosystem, not currently a hard dep). Do *not* add `instructor` — it's only ~150 LOC and we'd be importing a transitive `openai` dep that we don't otherwise need. **Hand-roll a minimal Instructor equivalent** (Pattern A + Pattern F together, see §3.2).

**Step 2.** Create `templates/schemas/` directory. One file per form template:

```python
# templates/schemas/excellent_youth_league.py
from typing import Literal
from pydantic import BaseModel, Field, field_validator
import re

class ExcellentYouthLeagueForm(BaseModel):
    name: str = Field(min_length=2, max_length=20,
                       description="申请人姓名（与身份证一致）")
    gender: Literal["男", "女"]
    birth_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$",
                             description="出生日期 YYYY-MM-DD")
    phone: str = Field(pattern=r"^1\d{10}$", description="11位手机号")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    political_status: Literal["共青团员", "中共党员", "预备党员",
                                "入党积极分子", "群众"]
    application_category: Literal["优秀团员", "优秀团干"]
    self_statement: str = Field(min_length=300, max_length=800,
                                  description="个人事迹材料（300–800字）")

    @field_validator("self_statement")
    @classmethod
    def _word_count_in_range(cls, v):
        # Chinese-char count, not Unicode codepoints
        chinese = len(re.findall(r"[\u4e00-\u9fff]", v))
        if not (300 <= chinese <= 800):
            raise ValueError(f"self_statement 字数 {chinese} 超出 [300, 800]")
        return v
```

**Step 3.** Hand-roll a minimal schema-aware generator in `scripts/schema_gen.py` (~80 LOC):

```python
# scripts/schema_gen.py — v5.x
import json
from typing import Type, get_args, get_origin
from pydantic import BaseModel, Field

def schema_to_prompt(model: Type[BaseModel]) -> str:
    """Convert Pydantic model → system-prompt JSON schema spec."""
    schema = model.model_json_schema()
    fields = []
    for name, spec in schema.get("properties", {}).items():
        bits = [f"  - {name} ({spec.get('type', 'any')})"]
        if "pattern" in spec:
            bits.append(f"    pattern: {spec['pattern']}")
        if "enum" in spec:
            bits.append(f"    one of: {spec['enum']}")
        if "minLength" in spec or "maxLength" in spec:
            bits.append(f"    length: [{spec.get('minLength','-')}, {spec.get('maxLength','-')}]")
        if "minimum" in spec or "maximum" in spec:
            bits.append(f"    range: [{spec.get('minimum','-')}, {spec.get('maximum','-')}]")
        if desc := spec.get("description"):
            bits.append(f"    desc: {desc}")
        fields.append("\n".join(bits))
    return "Output ONLY valid JSON matching this schema:\n" + "\n".join(fields)

def generate_structured(
    prompt: str,
    schema: Type[BaseModel],
    model_adapter,            # Pattern F — see §3
    max_retries: int = 3,
) -> BaseModel:
    """Generate → validate → retry with error feedback. Instructor-lite."""
    sys_prompt = schema_to_prompt(schema)
    last_err = None
    for attempt in range(max_retries + 1):
        user_msg = prompt
        if last_err is not None:
            user_msg += f"\n\n[previous attempt failed validation: {last_err}\nFix the JSON to satisfy the schema.]"
        raw = model_adapter.generate(
            system=sys_prompt, user=user_msg,
            response_format={"type": "json_object"}  # OpenAI json mode
        )
        try:
            return schema.model_validate_json(raw)
        except Exception as e:
            last_err = str(e)
    raise ValueError(f"Schema violation after {max_retries} retries: {last_err}")
```

**Step 4.** Wire into `fill_docx.py`:

```python
# scripts/fill_docx.py — new
from schema_gen import generate_structured
from templates.schemas.excellent_youth_league import ExcellentYouthLeagueForm

# Replace:
#   result = match_field(text, profiles)
#   ...
#   if value_cell and result["value"]:
#       value_cell.paragraphs[0].text = str(result["value"])
# With:
#   if "<AI-gen>" in result["source"]:   # long-form field
#       validated = generate_structured(
#           prompt=f"基于 profile.md 生成个人事迹材料 ({label})",
#           schema=ExcellentYouthLeagueForm,
#           model_adapter=model_adapter,
#       )
#       value = validated.self_statement if label == "个人事迹材料" else ...
```

**Step 5.** New evaluation rules to score the win (see §7).

---

## 3. Deep-Dive on Pattern F — Provider-Agnostic Adapter

### 3.1 Compare 3 mature libraries

| Dimension | **LiteLLM** | **aisuite** | **simonw/llm** |
|---|---|---|---|
| Providers | **100+** (OpenAI, Anthropic, Gemini, Bedrock, Azure, Vertex, vLLM, Nvidia NIM, Cohere, Mistral, Groq, Together, Ollama, Huggingface, Replicate, Databricks, IBM Watsonx, plus A2A agents like LangGraph, Pydantic AI) | **~10** (OpenAI, Anthropic, Google, Mistral, Hugging Face, AWS, Cohere, Ollama, OpenRouter, Requesty + OpenAI-compatible endpoints) | **~30** via plugins (OpenAI, Anthropic, Gemini, Qwen, Gemma, Kimi, DeepSeek, Mistral + plugins for Ollama, LM Studio, etc.) |
| Adding a new provider | Add a transformer class in `litellm/llms/<provider>.py` + register config; ~50–200 LOC; the codebase has dedicated per-provider files | One file `providers/<provider>_provider.py` containing `<Provider>Provider`; auto-discovered; ~30 LOC | Install a PyPI plugin (`llm install llm-XXX`) or write a Python package implementing the `Model` interface; ~50–100 LOC |
| Structured output | Inherits from the underlying provider (no unified schema-aware layer); `response_format` parameter passed through | Inherits from provider; no unified layer | Native `llm --schema` + Python `llm.structured(prompt, schema)` |
| Function calling / tools | Yes — full OpenAI tool-call format with MCP bridge | Yes — `max_turns=` for auto multi-turn | Yes — `llm --functions` or `llm --functions-def` |
| Local models | `ollama/llama3`, `hosted_vllm/...`, `openai/...` (custom base_url) | `ollama:<model>` | `ollama` plugin; `openai endpoint http://localhost:1234/v1 -m ...` |
| API surface | Sync `completion()` + async `acompletion()`; streaming; full Pydantic-typed responses | Sync `client.chat.completions.create()` + async `aclient.chat.completions.acreate()`; streaming | Sync + async; CLI + Python |
| Deployment modes | **Both**: embedded Python SDK *and* standalone OpenAI-compatible Proxy server (port 4000) with cost tracking, virtual keys, rate limits | Embedded Python SDK only | CLI tool + embedded Python; SQLite storage is its standout |
| Logging / observability | First-class — success/failure logs, spend tracking, callbacks, Langfuse/Datadog/OpenTelemetry hooks | None at the library level | **SQLite-by-default** — every prompt + response persisted, queryable via `llm logs` |
| License | MIT (with some provider SDK deps) | MIT | Apache-2.0 |
| Stars | ~30k | ~12k | ~9k |

**Key observation:** All three libraries converge on the **`<provider>:<model>` model-string convention**. This is now the de facto standard — see also LangChain, Pydantic-AI, OpenRouter, Portkey.

### 3.2 Recommended form-filler Pattern F implementation

**Constraint:** form-filler is a **zero-new-deps Python tool** used in a privacy-sensitive context. Adding `litellm` pulls ~30 transitive deps (openai, anthropic, boto3, google-cloud-aiplatform, ...) that we don't need. Adding `aisuite` pulls `openai`. Adding `simonw/llm` pulls `openai` + `anthropic` + click + sqlite.

**Verdict:** **Hand-roll a ~120 LOC minimal adapter** modeled on aisuite's convention. Reasons:
1. form-filler only needs **2 providers initially**: OpenAI-compatible (covers OpenAI, OpenRouter, Azure-OpenAI, vLLM-served, Ollama-served) and Anthropic (optional, for Claude quality on long-form fields).
2. The user picks a provider via `--provider openai-compatible --model llama3.2 --base-url http://localhost:11434/v1` CLI flags.
3. **No new pip deps required** — `urllib.request` + `json` does the whole thing.
4. aisuite's naming convention (`<provider>:<model>`) is the public API we should copy.

**Concrete recipe:**

```python
# scripts/model_adapter.py — v5.x (~120 LOC, stdlib only)

import json, os, urllib.request, urllib.error
from typing import Optional, Type
from pydantic import BaseModel

class ModelAdapter:
    """Provider-agnostic LLM call. Same API for cloud + local."""

    def __init__(self, provider: str, model: str, base_url: Optional[str] = None,
                 api_key: Optional[str] = None):
        self.provider = provider
        self.model = model
        self.base_url = base_url or self._default_base_url(provider)
        self.api_key = api_key or self._default_api_key(provider)

    def _default_base_url(self, p):
        return {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "openai-compatible": os.environ.get("OPENAI_BASE_URL",
                "http://localhost:11434/v1"),  # Ollama default
        }.get(p, "")

    def _default_api_key(self, p):
        return {
            "openai": os.environ.get("OPENAI_API_KEY", ""),
            "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
            "openai-compatible": os.environ.get("OPENAI_API_KEY", "ollama"),
        }.get(p, "")

    def generate(self, system: str, user: str,
                 response_format: Optional[dict] = None,
                 max_retries: int = 3) -> str:
        """Returns the assistant's text. Raises on hard failure."""
        if self.provider == "anthropic":
            return self._anthropic_call(system, user, max_retries)
        return self._openai_call(system, user, response_format, max_retries)

    def _openai_call(self, system, user, response_format, max_retries):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        if response_format:
            body["response_format"] = response_format
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read())
                    return data["choices"][0]["message"]["content"]
            except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"LLM call failed after {max_retries} retries: {e}")
        # unreachable

    def _anthropic_call(self, system, user, max_retries):
        body = {"model": self.model,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "max_tokens": 4096}
        req = urllib.request.Request(
            f"{self.base_url}/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={"x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
        )
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read())
                    return data["content"][0]["text"]
            except (urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"LLM call failed after {max_retries} retries: {e}")
        # unreachable

    def cost_log(self) -> dict:
        """Return {model, provider, latency_ms, tokens_in, tokens_out} — stub,
        real impl tracks via SQLite (Pattern L below)."""
        return {"model": self.model, "provider": self.provider}
```

**Wire-in:**
```python
# scripts/fill_docx.py — new flags
parser.add_argument("--provider", default="openai-compatible",
                    choices=["openai", "anthropic", "openai-compatible"])
parser.add_argument("--model", default="llama3.2",
                    help="Model name (with provider prefix: openai:gpt-4o, anthropic:claude-...)")
parser.add_argument("--base-url", default=None)
parser.add_argument("--api-key", default=None)
```

**Why this fits form-filler:**
- 0 new pip deps (urllib is stdlib).
- Works against **Ollama locally** (the most common privacy-first setup for Chinese users filling forms with PII) — set `--base-url http://localhost:11434/v1 --model llama3.2`.
- Works against **any OpenAI-compatible endpoint** (vLLM, LM Studio, OpenRouter, Azure-OpenAI, DeepSeek, Qwen) — just change the base URL.
- One method (`generate()`) is the single seam where all future model-specific features (structured output, function calling) get added.

---

## 4. New Patterns Discovered (5 NEW — distinct from Round 1's A–H)

### Pattern I — Validation-Repair-Retry Loop (from **instructor**)
- **What it is:** When the LLM output fails Pydantic validation, automatically re-send the prompt with the validation error message appended, up to `max_retries` times. The model "learns" from its mistake within the conversation.
- **Why it applies to v5.0:** Round 1's `_stub_reflect` re-sends the entire prompt to ask "is this OK?" — that wastes a turn. A targeted "the field 'phone' failed: '1381234' is not 11 digits, please retry with a valid phone number" is much cheaper and converges in 1–2 retries.
- **Effort:** S (reuses Pattern A's `generate_structured()`; one extra parameter).
- **Impact:** High (turns every regex/regex-violation into a recoverable self-correction).
- **Risk:** Low. Max-retries=3 caps the cost.

### Pattern J — Schema-Guided JSON Repair (from **json_repair**)
- **What it is:** When an LLM produces *malformed* JSON (missing bracket, trailing comma, unquoted key), parse it against a BNF grammar and apply heuristic fixes. With a Pydantic schema, fill in defaults for missing fields.
- **Why it applies to v5.0:** Even with Instructor's retry loop, a misbehaving local model may produce text that *isn't even JSON*. Currently `fill_docx.py` would silently fail. A repair layer catches the last 5–10% of cases.
- **Effort:** S (one helper function wrapping `repair_json` from json_repair, or ~30 LOC of hand-rolled equivalent).
- **Impact:** Medium (small % of failures, but eliminates a hard-error path).
- **Risk:** Low. json_repair is ~50KB of pure-Python stdlib code.

### Pattern K — Trajectory Tracing (from **deepeval**)
- **What it is:** Every component in an agent loop is wrapped in `@observe()` which records `{input, output, latency, tokens}` for that step. After the run, metrics are run against the full trajectory, not just the final output.
- **Why it applies to v5.0:** Round 1's audit table records *final* per-field status. Trajectory tracing would record *which step* decided each field's value: `match_field() → _compute_grade() → fill_cell() → reflect()`. If a step misfired, you can replay it.
- **Effort:** M (requires refactoring `fill_docx()` to emit structured trace events; new `traces/` directory).
- **Impact:** Medium-High (debuggability win for the next 3 rounds of the loop).
- **Risk:** Low (additive; trace files are derivable from existing audit data).

### Pattern L — CLI-first + SQLite Logging (from **simonw/llm**)
- **What it is:** Every LLM call — prompt, response, model ID, tokens, latency, timestamp — is *automatically* persisted to a local SQLite database. The DB is the source of truth for A/B testing, regression detection, cost analysis, and prompt versioning. No opt-in; the storage is the default.
- **Why it applies to v5.0:** The form-filler loop currently has *zero* persistent record of what the LLM generated. Every round, we re-run the same prompts from scratch and compare only the final filled DOCX. With SQLite logging, every round's `(prompt, response, score)` triple is queryable; a future round can ask "which prompt change made field 'X' start hallucinating?" by joining `prompt_log × audit_log`.
- **Effort:** S (stdlib `sqlite3`; ~50 LOC; one new flag `--log-db PATH`).
- **Impact:** High (this is the *measurement layer* the next 3 rounds need).
- **Risk:** Low. SQLite file is gitignored.

### Pattern M — Provider Failover Chains (from **portkey**, **litellm**)
- **What it is:** Configure a primary + fallback list of `(provider, model)` pairs. If the primary call fails (rate limit, timeout, schema-violation-retries-exhausted), automatically try the next. Log the failover so the audit knows which model produced the value.
- **Why it applies to v5.0:** The user's `--provider openai --model gpt-4o` call may fail mid-run because of API rate limits; the form is half-filled. With failover, the same call falls back to `--model gpt-4o-mini` or `--provider anthropic --model claude-haiku` and continues. The audit table records `source: gpt-4o (primary) → gpt-4o-mini (fallback after 429)`.
- **Effort:** M (config schema + retry loop in `model_adapter.py`).
- **Impact:** Medium (production reliability, not correctness).
- **Risk:** Low. Disabled by default; opt-in via `--fallback-models gpt-4o-mini,claude-haiku-3`.

### Pattern N — JSON Repair Stream (bonus, from **json_repair** `stream_stable` mode)
- **What it is:** Repair partial JSON as it streams in, so the consumer gets a valid JSON object as soon as the producer's buffer is repairable, without waiting for the full response.
- **Why it applies to v5.0:** UX win for long-form fields (self-recommendation letter, 800 chars) — the user sees the response being built live.
- **Effort:** M (requires streaming + partial-validation pipeline).
- **Impact:** Low (UX, not correctness). Defer past Round 2 if budget tight.

---

## 5. Top 3 Recommendations for Round 2

### Recommendation 1 — Pattern A: Schema-as-Prompt via Pydantic (the structural fix)

**Why this round:** Highest payoff in the deferred set. With `profile.md` (R1) as the substrate and `_stub_reflect` (R1) ready to be hooked, Pattern A is now unblocked. Every regex/regex-violation in score_consistency becomes *ungoogleable-by-LLM* by construction.

**Concrete implementation recipe (4 steps):**

1. **Add `pydantic>=2.0` as a soft dep** (no install-time hard requirement; the script falls back to current behavior if missing).
2. **Create `templates/schemas/`** with one Pydantic model per form template (start with `excellent_youth_league.py` since that's the demo profile). Each field is annotated with `Literal[...]`, `Field(min_length=, max_length=, pattern=, ge=, le=)`. The model is the *spec* for what the LLM must emit.
3. **Add `scripts/schema_gen.py`** (~80 LOC) with `schema_to_prompt(model)` and `generate_structured(prompt, schema, adapter, max_retries)`. The latter implements the validate-and-retry pattern (Pattern I). On final failure, optionally apply json_repair (Pattern J) once before raising.
4. **Wire into `fill_docx.py`** — for each `<AI-gen>` field (long-form fields like `个人事迹材料`, `自荐信`), call `generate_structured(prompt, schema_for_field, adapter)`. For non-AI fields (姓名, 性别, 籍贯, etc.), keep the existing `match_field()` path — schema-as-prompt is wasted on fields that come straight from the YAML.

**Effort:** M (1.5–2 days of focused work: schemas + adapter + wiring).
**Expected measurable delta:** +5 (new rules R10/R11/R12 — see §7).
**Risk:** Pydantic adds a dep (mitigated: soft import). Long-form fields may need 2–3 retries on weak local models (mitigated: max_retries=2 cap).

### Recommendation 2 — Pattern F: Provider-Agnostic Adapter (hand-rolled, ~120 LOC, stdlib-only)

**Why this round:** Without a model adapter, Pattern A's `generate_structured()` has no caller, and `_stub_reflect` (R1) remains a stub. The adapter is the *seam* where every future Round-3/4/5 feature plugs in.

**Concrete implementation recipe (3 steps):**

1. **Create `scripts/model_adapter.py`** (~120 LOC) — see §3.2 for the full file. Handles `openai`, `anthropic`, `openai-compatible` (covers Ollama, vLLM, LM Studio, OpenRouter, DeepSeek, Qwen, Azure-OpenAI).
2. **Add CLI flags to `fill_docx.py`** — `--provider`, `--model`, `--base-url`, `--api-key`. Default `--provider openai-compatible --model llama3.2 --base-url http://localhost:11434/v1` (the privacy-first Ollama setup).
3. **Replace `_stub_reflect`'s TODO** — make `fill_docx(_reflect_impl=...)` default to a new `_real_reflect(prompt, adapter)` that calls `adapter.generate(...)`. If `--no-llm` is passed, fall back to the stub (preserves v5.0 behavior + the test fixture).

**Effort:** S–M (1 day).
**Expected measurable delta:** +2 (new rule R13 — see §7).
**Risk:** Adds CLI surface (mitigated: backward-compat defaults). Network errors on cloud providers (mitigated: max_retries=3 in adapter).

### Recommendation 3 — Pattern L: SQLite Logging (the measurement substrate)

**Why this round (over Recommendation 3 alternatives):** Without per-call logs, the Round-3 Reviewer can only compare `(audit_before, audit_after)` — not *why* a field changed. With SQLite logging, the Reviewer can query "show me every prompt sent for field '个人事迹材料' in Round 1 vs Round 2" and see exactly what the LLM was asked and what it returned. **This is the precondition for Round 3 to do attribution-style scoring** instead of black-box before/after.

**Concrete implementation recipe (3 steps):**

1. **Add `scripts/prompt_log.py`** (~50 LOC, stdlib `sqlite3`) — `init(db_path)`, `log(db, prompt, response, model, tokens_in, tokens_out, latency_ms, schema)`, `query(db, where_clause)`. Schema: `CREATE TABLE IF NOT EXISTS llm_calls (id INTEGER PRIMARY KEY, ts TEXT, model TEXT, prompt TEXT, response TEXT, schema TEXT, tokens_in INT, tokens_out INT, latency_ms INT, fill_run_id TEXT)`.
2. **Wire into `model_adapter.generate()`** — every call writes a row to the DB before returning. Pass `fill_run_id` as a UUID generated once per `fill_docx()` invocation.
3. **Add `--log-db` flag** to `fill_docx.py` (default `./profiles/llm_log.sqlite`, gitignored). Add a sibling `scripts/dump_log.py` that prints the last 20 calls for a given `fill_run_id`.

**Effort:** S (0.5 day).
**Expected measurable delta:** +1 (new rule R14 — see §7).
**Risk:** SQLite WAL on Windows requires no special handling; small DB growth (≈ 50KB per fill run).

---

## 6. Anti-patterns to Avoid (Round 2)

### Anti-pattern 1 — Pulling in LiteLLM's 30-transitive-dep blast radius
LiteLLM is the most-featured provider router, but `pip install litellm` brings `openai`, `anthropic`, `boto3`, `google-cloud-aiplatform`, `tiktoken`, `jinja2`, `fastapi`, `uvicorn`, `httpx`, `tiktoken`, ... — and we currently depend on `python-docx + pyyaml` only. **For a privacy-sensitive form-filling tool, the supply-chain risk is non-trivial.** Hand-rolling a 120-LOC adapter (Pattern F as scoped above) gives us 80% of the value at 5% of the cost.

### Anti-pattern 2 — Constrained decoding as the *only* schema-enforcement path
Outlines/Guidance-style token-mask constrained generation is the strongest guarantee but requires the model to expose logit-mask hooks. **OpenAI cloud, Anthropic cloud, and most local Ollama-served models don't support this.** If we go all-in on Outlines and skip Instructor-style validate-and-retry, we'll lock form-filler into vLLM (a heavy infra dep) or shut out the privacy-first Ollama path. **Mix the two**: Instructor-style retry for OpenAI/Anthropic/Ollama, Outlines-style constrained decoding only when vLLM is available.

### Anti-pattern 3 (carryover from Round 1, still relevant) — Massive context stuffing
Promptfoo and LangSmith both illustrate workflows that *dump entire conversation history into every prompt* for "completeness". For form-filler with 50+ fields and a long-form profile.md, this explodes the context. Stick to Pattern D (small versioned `profile.md` + per-field schema) — see Round 1 §Anti-pattern 2.

---

## 7. Measurability Check

For each Top-3 recommendation, can `evaluation/score_consistency.py` measure the improvement? **Yes, with the following new rules added to the existing 9 (R1–R9).**

### Recommendation 1 — Pattern A: Schema-as-Prompt

| New rule | Verdict condition | Severity |
|---|---|---|
| **R10_schema_compliance** | For every detail row with `source: AI-gen`, the value MUST round-trip through its declared Pydantic schema (re-validate against `templates/schemas/<form>.py`). Schema import is soft — if missing, skip with `pass`. | `fail` if invalid; `pass` if valid; `warn` if schema missing |
| **R11_word_limit_within_field_type** | For each row where the schema declares `min_length`/`max_length` (in chars), the value's char count must fall in `[min, max]`. Differs from R8 (which uses a 2000-char hard ceiling) by being *per-field-typed*. | `fail` |
| **R12_literal_enum_compliance** | For each row where the schema declares `Literal[...]`, the value MUST be one of the literals. Catches "性别 = 男性 / 性别 = female" when the schema says `Literal["男","女"]`. | `fail` |

These three rules **cannot be measured today** because `details[]` doesn't carry the schema reference. Adding `"schema_ref": "templates/schemas/excellent_youth_league.py:ExcellentYouthLeagueForm.self_statement"` to the audit dict (when `--write-profile` is on) gives the harness the missing link.

**Predicted score impact:** R10 fails on every AI-gen field in v5.0 (since v5.0 generates free text); R11 fails on the long-form fields that exceed 800 chars; R12 fails on any field the model colorizes with a near-synonym. The score will drop ~10–15 points before the Optimizer applies Pattern A; after Pattern A lands it should return to ≥95. This is the *measurable* delta the loop needs.

### Recommendation 2 — Pattern F: Provider-Agnostic Adapter

| New rule | Verdict condition | Severity |
|---|---|---|
| **R13_provider_log_present** | Every AI-generated detail row must have a `model_id` field (e.g., `gpt-4o`, `llama3.2:8b`, `claude-3-5-sonnet`). Currently 0% of rows carry this; after Pattern F + Pattern L, 100% do. | `warn` (not blocking — model-agnostic is a quality-of-life win, not a correctness one) |

`score_consistency.py` should additionally expose `--profile-dir ./profiles --llm-log ./profiles/llm_log.sqlite` and emit a *secondary* metric: `model_diversity_score` = number of distinct `model_id`s used across the last 10 fill runs (0 = always-same-model = good for reproducibility; >3 = experimentation). This is a *meta* metric that signals how much the optimizer is exercising the adapter.

### Recommendation 3 — Pattern L: SQLite Logging

| New rule | Verdict condition | Severity |
|---|---|---|
| **R14_log_correlation** | Every filled DOCX must have a corresponding `llm_calls` row in `llm_log.sqlite` linked by `fill_run_id` (a UUID in `audit.md` frontmatter). If `llm_log.sqlite` is missing or the row is missing, the rule warns. | `warn` (informational; turns on when Pattern F is in use) |

**Predicted score impact:** R13 + R14 together contribute ~–2 to a *baseline* v5.0 score (because v5.0 has no model_id and no log), but ~0 once both ship. They are *gating* rules: their presence in the harness proves that the underlying capability exists; their absence (or warn state) flags a regression.

### Summary of the measurability story

After Pattern A + F + L, the harness grows from 9 to 14 rules. The **score delta** between (v5.0 with R10–R14 added) and (v5.x with Patterns A+F+L implemented) is **direct evidence of structural improvement** — not a coverage-only score. This is the apples-to-apples comparison the Round-1 Tester §5 flagged as missing.

---

## 8. Cross-reference back to Round 1 backlog (`agent_state/round_1/05_main_judgment.md`)

| Round 1 backlog item | Where Round 2 handles it |
|---|---|
| 1. Pattern A — Schema-as-Prompt (Pydantic) | Recommendation 1 (§5.1) — concrete recipe in §2.2 |
| 2. Real `reflect()` LLM hook | Subsumed by Recommendation 2 (Pattern F). The hook is `model_adapter.generate()` — `_stub_reflect` becomes `_real_reflect` once the adapter exists. |
| 3. Pattern F — Provider adapter | Recommendation 2 (§5.2) — concrete recipe in §3.2 |
| 4. Cosmetic: `evaluate()` → `score()` | Not a Round-2 priority. Defer. |
| 5. Privacy: redact PII in audit.md | Not in this Round 2 scope; could slot in as Pattern O (Audit Redaction, from `confident-ai/deepeval`'s redaction conventions). Defer to Round 3 if budget allows. |

## 9. Round 2 readiness self-check

- **Concrete enough for Optimizer?** Yes — every recommendation includes file paths, line counts, API sketches, and back-compat notes.
- **Concrete enough for Tester?** Yes — new rules R10–R14 have explicit `verdict`/`severity` definitions.
- **Concrete enough for Main Agent?** Yes — each Top-3 has an effort estimate (S/M), risk rating, and a measurable Δ (number of points expected).
- **No new high-priority risks** beyond the 2 anti-patterns already in §6.
- **No conflict with Round-1 deferred patterns B (LongWriter) and G (Fast-Forwarding)** — both remain deferred. Pattern G specifically *depends* on Pattern A (per Round 1 Researcher §3), so Round 2's Pattern A naturally enables Round 3's Pattern G.
