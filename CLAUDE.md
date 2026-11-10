# CLAUDE.md: project rules (follow in every session)

Acadza AI intern assignment: a "Report → Fix" triage engine (Python) plus a faculty review console (static site). See `README.md` for the brief.

Stack: Python engine. LLMs are Groq (main) and OpenRouter (tie-breaker), both free tier, called through their OpenAI-compatible APIs. Keys come from `.env` (`GROQ_API_KEY`, `OPENROUTER_API_KEY`); see `.env.example`. The user works on Windows (PowerShell).

## 1. Folder structure

| Path | Purpose |
|---|---|
| `data/` | Given files (`questions.json`, `reports.json`, `taxonomy.json`). **Read-only. Never modify.** |
| `engine/` | Python triage engine. Never reads `docs/eval-labels.csv`. |
| `eval/` | Evaluation scripts. **The only code allowed to read `docs/eval-labels.csv`.** |
| `tests/` | pytest tests (parser, project-rule guards). Run with `python -m pytest tests`. |
| `prompts/` | Every LLM prompt the product uses. One file per prompt per version, e.g. `solver_v1.md`, `solver_v2.md`. **Never write prompts inline in code.** Code loads them from here by name and version. |
| `prompts/CHANGELOG.md` | For each new prompt version: what changed, why, and the evidence that prompted it. |
| `console/` | Faculty review console (static site). |
| `docs/` | Record-keeping (see section 3). |
| `logs/` | Run outputs (see section 4). |

## 2. Automatic prompt logging

A `UserPromptSubmit` hook (`.claude/settings.json` → `.claude/hooks/log_prompt.py`) appends every user prompt verbatim, with a timestamp and session id, to `docs/claude-code-prompts.md`, and a raw copy to `logs/claude-code-prompts.jsonl`. Don't edit, reformat or truncate those files. Don't disable the hook.

## 3. Record-keeping

- `docs/ai-mistakes.md`: when the user writes **`mistake: ...`**, append an entry (date, what the AI did wrong, how they caught it, what they changed). Keep their words; only format them.
- `docs/decisions.md`: when the user writes **`decision: ...`**, append an entry (decision, alternatives considered, why, evidence). Keep their words; only format them.
- If you make a significant design choice yourself, **propose it to the user as a `decisions.md` entry**. Don't write it there silently; wait for approval.
- `docs/eval-labels.csv`: the user's hand-labelled ground truth.
  - Claude may draft rows, always with `label_source = claude_draft`.
  - Only the user marks a row verified (`label_source = user_verified`). Claude never sets or changes that value.
  - Nothing in `engine/` may read this file. Only scripts in `eval/` may read it, so ground truth can't leak into triage decisions.

## 4. Engine run logging (convention; implement with the engine)

Every LLM call the engine makes must append one JSON line to `logs/llm-calls.jsonl` with:
`timestamp`, `stage` / tier, `model` id, `prompt_file` + `prompt_version`, `input_hash`, `tokens_in`, `tokens_out`, `latency_ms`, `cache_hit`, `retries`.

Each engine run also writes `logs/run-summary.json` with: total time, total tokens, calls per tier, cases settled per tier, count routed to faculty, and shadow-mode early-exit disagreements (cases where early exit would have decided differently from the full pipeline).

## 5. Working rules

- Keep changes scoped to what the user asks. No speculative features.
- `data/` is read-only.
- Nothing in `engine/` may open `docs/eval-labels.csv`; only `eval/` may. `tests/test_project_rules.py` enforces this.
- Generic rules only: no question IDs or report IDs anywhere in engine logic. Rules must follow from the structure and text of a record, not from knowing the answers. `tests/test_project_rules.py` enforces this.
- Prompts live only in `prompts/`, versioned, with a CHANGELOG entry per new version.
- Never put API keys or LLM calls in `console/`; it reads precomputed `results.json`.
