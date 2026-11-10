# engine/

Python triage engine: the code-only tier (data profiler) and the LLM tiers. Standard library only; Python 3.10+.

```powershell
python -m engine.profile          # writes logs/profile/{reports.csv, questions.csv, summary.md}
python -m eval.evaluate_profile   # compares code-decided rows with the hand labels (eval/ only)
python -m pytest tests            # parser tests + project-rule guards
```

| Module | Role |
|---|---|
| `loader.py` | Read-only loading of `data/` into typed records. |
| `parse.py` | HTML + MathML (incl. HTML `sup`/`sub`) → clean text; option splitting on markers outside `<math>` (or a `<math>` that is only a marker); answer normalisation with malformation flags; exact raw-substring evidence. |
| `checks.py` | Per-question rule checks. Each finding is `definite`, `signal` or `weak`, with raw + clean evidence. |
| `claims.py` | Sorts a comment into a claim category (English + Hinglish) and extracts asserted letters/values/words; injection detector. |
| `verify.py` | Claim × record × findings → `code_settled` / `code_routed` / `needs_llm` (see `docs/decisions.md` D-007). |
| `profile.py` | Runs all of the above and writes the profile. |
| `config.py` | Model per role, tolerances, spend cap, confidence constants. |
| `llm.py` | One client for Groq + OpenRouter: pacing, rate-limit headers, retries, cache, call log, cost, hard spend cap. |
| `prompts.py` | Loads `prompts/<name>_v<N>.md` and renders `{{vars}}` (fails on missing/unused). |
| `mathexpr.py` | Safe `ast`-whitelist evaluator (no eval/exec), units → SI, option/answer quantity matching with stated tolerances. |
| `tiers.py` | LLM calls → signals: guard, solvers, extract, audit, option checks (value checks for integer questions), triage, reply. |
| `decide.py` | Code decides verdict / repair / route / confidence from the signals (D-016); shadow-mode per-tier decisions. |
| `edits.py` | Code-built edits, clean-text → raw mapping for LLM edits (D-019), D-004 guards. |
| `run.py` | `python -m engine.run [--reports a,b] [--cap 0.5] [--offline]`: full pipeline, `results.json`, run summary. |

Rules are generic: no question or report IDs (D-010, enforced by `tests/test_project_rules.py`).

Conventions (see `CLAUDE.md`): prompts are loaded from `../prompts/` (never inline), and every LLM call is logged to `../logs/llm-calls.jsonl`, with a run summary in `../logs/run-summary.json`.
