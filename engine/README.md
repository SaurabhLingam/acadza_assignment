# engine/

Python triage engine. So far: the code-only tier (data profiler). Standard library only; Python 3.10+.

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

Rules are generic: no question or report IDs (D-010, enforced by `tests/test_project_rules.py`).

Conventions (see `CLAUDE.md`): prompts are loaded from `../prompts/` (never inline), and every LLM call is logged to `../logs/llm-calls.jsonl`, with a run summary in `../logs/run-summary.json`.
