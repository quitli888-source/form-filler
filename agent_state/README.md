# Multi-Agent Optimization Loop State

This directory tracks the iterative optimization of the `form-filler` project.

## Loop Architecture

```
                    ┌──────────────────────────────────────────────────┐
                    │              Main Agent (Orchestrator)           │
                    │  - Tracks round number, reads all phase outputs  │
                    │  - Decides: continue / terminate / commit+push    │
                    └──────────────────────────────────────────────────┘
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              ▼                               ▼                               ▼
   ┌────────────────────┐         ┌────────────────────┐         ┌────────────────────┐
   │ 01_researcher      │  ────►  │ 02_reviewer        │  ────►  │ 03_optimizer       │
   │ Search high-star   │         │ Evaluate vs        │         │ Apply changes      │
   │ novel-gen projects │         │ previous code      │         │ to SKILL.md/       │
   │ on GitHub, write   │         │ write action plan  │         │ scripts/templates  │
   │ transferable ideas │         │                    │         │                    │
   └────────────────────┘         └────────────────────┘         └────────────────────┘
              ▲                                                                │
              │                                                                ▼
   ┌────────────────────┐                                          ┌────────────────────┐
   │ 05_main_judgment   │  ◄─── feedback ───                        │ 04_tester          │
   │ Quality gate,      │                                          │ Run scripts,       │
   │ terminate decision │                                          │ validate YAML,     │
   │ commit + push      │                                          │ write report       │
   └────────────────────┘                                          └────────────────────┘
```

## Communication Protocol

Each sub-agent writes its output to `agent_state/round_N/<phase>.md`.
The Main Agent reads these files and feeds the content into the next phase's prompt.

## Why "novel generation" projects?

Novel generation projects share deep structural similarities with form filling:
- **Long-form generation with constraints** → self-recommendation letter with word limits
- **Character consistency** → form field consistency
- **Structured output (JSON/scenes)** → form templates with `{{fields}}`
- **Quality scoring & validation** → form consistency checks
- **Iterative refinement** → multi-pass form filling
- **Style/voice control** → tone of generated content

Cross-domain inspiration is a known source of novel optimizations.

## Files

- `loop_config.json` — global loop configuration and termination criteria
- `round_N/01_researcher.md` — research output (Phase 1)
- `round_N/02_reviewer.md` — review and prioritized action items (Phase 2)
- `round_N/03_optimizer.md` — change log (Phase 3)
- `round_N/04_tester.md` — test report (Phase 4)
- `round_N/05_main_judgment.md` — termination decision (Phase 5)

## Evaluation harness (v4.1)

After `python scripts/fill_docx.py --template T.docx --profile-dir ./profiles --output O.docx` produces `O_audit.md`, run `python evaluation/score_consistency.py --audit O_audit.md --profiles ./profiles` to get a JSON score (0–100) — the baseline metric the Darwin loop measures each round against.
