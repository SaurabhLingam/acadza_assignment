# Claude Code prompts

Every prompt typed into Claude Code in this project, verbatim. Appended automatically by `.claude/hooks/log_prompt.py` (UserPromptSubmit hook). Raw copy: `logs/claude-code-prompts.jsonl`.

---

### 2026-11-10T18:05:09+05:30

session: `42ec5436-b3d9-445f-882c-ac70a16e4dcc` · source: manual backfill (prompt sent before hook existed)

```text
You're setting up the repo for my Acadza AI intern assignment. Read README.md and everything in data/ first so you understand the task. DO NOT build the triage engine or the console yet. This step is only scaffolding and record-keeping.

Context: I'm on Windows (PowerShell). Engine will be Python. LLMs: Groq (main) and OpenRouter (tie-breaker), both free tier, via their OpenAI-compatible APIs. The console will be a static site added later.

1. FOLDER STRUCTURE
- data/: the given files. Treat as read-only; never modify them.
- engine/: Python triage engine (empty for now, just a placeholder README)
- prompts/: every LLM prompt used by the product, one file per prompt per version (e.g. solver_v1.md). Prompts must never be written inline in code.
- prompts/CHANGELOG.md: for each new prompt version: what changed, why, and what evidence prompted it
- console/: empty placeholder
- docs/: record-keeping (below)
- logs/: run outputs (below)

2. AUTOMATIC PROMPT LOGGING (most important)
Set up a Claude Code UserPromptSubmit hook in this project's .claude/settings.json that appends every prompt I type to docs/claude-code-prompts.md with a timestamp and session id, verbatim, nothing truncated. Also keep a raw JSONL copy in logs/claude-code-prompts.jsonl. Write the hook script in Python so it works on Windows. Test it, and tell me exactly what I need to do (restart, approve in /hooks, etc.) for it to take effect. This prompt itself won't be captured by the hook, so add it manually as the first entry.

3. RECORD-KEEPING FILES (create with short templates)
- docs/ai-mistakes.md: each entry: date, what the AI did wrong, how I caught it, what I changed.
- docs/decisions.md: each entry: decision, alternatives considered, why, evidence. Pre-fill these decisions from planning:
  a) LLM only produces signals; code decides verdict, confidence and route.
  b) The student comment is treated as an untrusted claim. The solver never sees the comment or the answer key.
  c) Tiered pipeline: code checks first, then a cheap solve, then escalation. BUT for this assignment we run every tier on every report in "shadow mode" and log what early exit would have decided, to measure whether early exit is safe rather than assume it.
  d) Edits are built in code wherever possible; LLM-written edits must pass per-repair guards from taxonomy.json (allowed fields, find appears exactly once, additive-only for answer_form, no digit/symbol changes for spelling, stem untouched for option_repair).
  e) Built on free-tier models on purpose. The harness must keep wrong auto-applies at zero even with a weak model; we'll prove it by swapping in a small model.
  f) The console reads precomputed results.json; no LLM calls or API keys in the frontend.
- docs/eval-labels.csv: empty with headers reportId, questionId, my_verdict, my_repair, my_answer, notes (my hand-labelled ground truth).

4. ENGINE RUN LOGGING (conventions only, implement later)
Record in CLAUDE.md that every LLM call the engine makes must log: timestamp, stage/tier, model id, prompt file + version, input hash, tokens in/out, latency, cache hit, retries. That goes to logs/llm-calls.jsonl, plus a run summary in logs/run-summary.json (total time, tokens, calls per tier, cases settled per tier, routed-to-faculty count, shadow-mode early-exit disagreements).

5. CLAUDE.md (project rules you must follow in every future session)
- Everything in sections 1 to 4 above.
- When I write "mistake: ...", append it to docs/ai-mistakes.md. When I write "decision: ...", append it to docs/decisions.md. Keep my words; only format them.
- If you make a significant design choice yourself, propose it to me as a decisions.md entry. Don't write it silently.
- Keep changes scoped to what I ask. No speculative features.

6. HYGIENE
- .gitignore: .env, caches, __pycache__, node_modules, logs/llm-calls.jsonl (too large)
- .env.example with GROQ_API_KEY and OPENROUTER_API_KEY placeholders
- git init, no commit yet

When done: list every file you created, show me the hook config, and prove the hook works by telling me what it logged.
```

---

### 2026-11-10T18:22:52+05:30

session: `42ec5436-b3d9-445f-882c-ac70a16e4dcc` · source: manual backfill (hook not loaded in this session)

```text
Next up: a profiler. No LLM calls at all. I want to actually measure how many reports code alone can settle, instead of assuming most are easy.

Before building anything, look through data/ and tell me:
- how questions, options, answers and MathML are actually stored (show me 3 MathML samples converted to plain text like 1/√3)
- what the reports look like: duplicates, Hinglish, anything that smells like a trap or injection
- anything that already looks broken

Then propose a plan and wait for my go-ahead.

Roughly what I have in mind (push back if the data says otherwise):
- parse each question into clean stem / options / answer / solution text without losing symbols
- run rule-based checks on all 43 questions, mapped to taxonomy repairs, with the exact offending text as evidence
- sort each comment into a rough category and pull out what it's claiming ("option D missing", "answer is 50")
- check that claim against the actual record
- give a verdict only when code is certain; otherwise mark it needs_llm

Output a per-report CSV, a per-question CSV (flag questions with problems but no reports, since those are bonus finds), and a short summary with the counts.

Build it as reusable modules in engine/; the real engine will use them later.
```

---

### 2026-11-10T18:34:12+05:30

session: `42ec5436-b3d9-445f-882c-ac70a16e4dcc` · source: manual backfill (hook not loaded in this session)

```text
mistake: the throwaway MathML converter dropped HTML <sup>, so 10<sup>-5</sup> became "10-5" and it nearly got reported as a broken exponent. Caught while reviewing the survey; the real parser must keep sup/sub.

Before I restart: save your whole survey (sections 1–4, including the tables) to docs/data-survey.md exactly as you wrote it. Also draft docs/eval-labels.csv from your hand-solves, with an extra label_source column set to claude_draft. I'll verify each row myself.
```

---

### 2026-11-10T18:44:36+05:30

session: `42ec5436-b3d9-445f-882c-ac70a16e4dcc` · source: manual backfill (hook not loaded in this session)

```text
Also update CLAUDE.md: Claude may draft eval-labels.csv rows marked claude_draft, but only I mark them verified, and the engine must never read that file except in the evaluation script.
```

---

### 2026-11-10T18:48:47+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
Hi, testing this hook
```

---

### 2026-11-10T18:49:40+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text


<pasted_content id="5d75">
Read docs/data-survey.md. That's the data survey and profiler plan from my last session. Go ahead and build it as proposed, with the three outcomes and the parser tests, plus these changes:

- Generic rules only. No question IDs or report IDs anywhere in engine logic. You've seen the answers; don't let that leak into the rules.
- answer_form and spelling hits are signals, not settlements. Spelling only settles when the student names the word and the check agrees.
- A vague comment on a question where checks found something is not not_actionable. The verdict depends on the checks too.
- Put the evaluation script in a top-level eval/ folder, not in engine/, so nothing in engine/ ever opens eval-labels.csv. Update CLAUDE.md to match.

Write the three decisions you proposed into decisions.md, and add one for "generic rules only, no IDs".
</pasted_content id="5d75">

```

---

### 2026-11-10T19:14:51+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
Yes, add all four judgment calls to decisions.md. For the display/app/language one, confirm the claim check means an "options cut off" report only settles as display_issue if all options actually exist in the record. Then commit everything so far with a clear message.
```

---

### 2026-11-10T19:21:43+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
decision: the verdict depends on whether the thing the student disputes (the key, an option, the text) is actually defective, not on whether their proposed alternative is right. R004/R034 pattern: student says the key is wrong and it is, but their own answer is also wrong → defect, and the reply credits them and corrects them. If what they dispute is fine (e.g. "change it to C" when the key is right) → no_error for that report, and any unrelated defect checks find goes on the question-level findings list instead. Only when the comment disputes nothing specific ("wrong") do the checks decide the verdict.

Also rename the branch from master to main and commit.
```

---

### 2026-11-10T19:26:36+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
Before pushing: confirm .env is gitignored and has never been committed (check git history too), and that no API key appears anywhere in tracked files, including the prompt logs. Only if all of that is clean, add https://github.com/SaurabhLingam/acadza_assignment.git as origin, commit the D-015 edit, and push main.
```
