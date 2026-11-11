# engine/

Python triage engine: the code-only tier (data profiler) and the LLM tiers. Standard library only; Python 3.10+.

```powershell
python -m engine.profile          # writes logs/profile/{reports.csv, questions.csv, summary.md}
python -m eval.evaluate_profile   # compares code-decided rows with the hand labels (eval/ only)
python -m pytest tests            # parser tests + project-rule guards
python -m engine.bonus            # question-level findings no report covers -> bonus_findings.json
python -m engine.run --swap-model openai/gpt-oss-20b    # D-005 robustness run -> logs/runs/<id>-swap-*/ only
python -m eval.compare_runs logs/runs/<main> logs/runs/<swap>   # accuracy, routes, wrong auto-applies
```

| Module | Role |
|---|---|
| `loader.py` | Read-only loading of `data/` into typed records. |
| `parse.py` | HTML + MathML (incl. HTML `sup`/`sub`) → clean text; option splitting on markers outside `<math>` (or a `<math>` that is only a marker); answer normalisation with malformation flags; exact raw-substring evidence. |
| `checks.py` | Per-question rule checks. Each finding is `definite`, `signal` or `weak`, with raw + clean evidence. |
| `claims.py` | Sorts a comment into a claim category (English + Hinglish) and extracts asserted letters/values/words; injection detector (D-030: five families, English + Hinglish; a state-change request alone is logged only). |
| `verify.py` | Claim × record × findings → `code_settled` / `code_routed` / `needs_llm` (see `docs/decisions.md` D-007). |
| `profile.py` | Runs all of the above and writes the profile. |
| `config.py` | Model per role, tolerances, spend cap, confidence constants. |
| `llm.py` | One client for Groq + OpenRouter: pacing, rate-limit headers, retries, cache, call log (with the provider that answered), cost, hard spend cap; same-model OpenRouter fallback after 60 s of Groq rate limiting (D-022). |
| `prompts.py` | Loads `prompts/<name>_v<N>.md` and renders `{{vars}}` (fails on missing/unused). |
| `mathexpr.py` | Safe `ast`-whitelist evaluator (no eval/exec), units → SI, option/answer quantity matching with stated tolerances. |
| `tiers.py` | LLM calls → signals: guard, solvers, extract, audit, option checks (value checks for integer questions), triage, reply. |
| `decide.py` | Code decides verdict / repair / route / confidence from the signals (D-016); shadow-mode per-tier decisions. |
| `edits.py` | Code-built edits, clean-text → raw mapping for LLM edits (D-019), D-004 guards. |
| `run.py` | `python -m engine.run [--reports a,b] [--cap 0.5] [--offline] [--swap-model M]`: full pipeline, `results.json`, run summary. `--swap-model` puts M in solver #1 and the checks (audit, option and value checks) and writes only under `logs/runs/`. |
| `bonus.py` | Question-level findings no report's outcome covers → `bonus_findings.json`: code findings (spelling/noise/markup_leak count as covered only if a `results.json` edit fixed that span) merged with the human review in `docs/bonus-review.json` (`add`: missed findings, each verified against the stored HTML; `dismiss`: false positives). Each row: evidence, a guarded edit where possible, and whether it could auto-apply under D-023. |

Rules are generic: no question or report IDs (D-010, enforced by `tests/test_project_rules.py`).

Conventions (see `CLAUDE.md`): prompts are loaded from `../prompts/` (never inline), and every LLM call is logged to `../logs/llm-calls.jsonl`, with a run summary in `../logs/run-summary.json`.
