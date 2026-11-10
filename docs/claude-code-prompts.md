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

---

### 2026-11-10T19:38:02+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text


<pasted_content id="5d75">
Next: the LLM part of the engine, for the 26 needs_llm reports. Propose the design and the prompt drafts first, then wait for my go-ahead.

First, call the Groq and OpenRouter model-list endpoints with my .env keys and tell me which models are actually available right now. Don't assume names.

What I have in mind:
- One client for both providers: rate limiting, retries with backoff, a response cache, and the call logging described in CLAUDE.md.
- Solver: sees only the clean question. No key, no comment, no stored solution. Two different model families. The model gives its final value as a math expression, code evaluates it safely (no exec/eval of arbitrary code) and matches it to an option numerically.
- An extraction call to pull the final answer out of the stored solution.
- Per-option checks only where a key change is on the table, to keep calls down.
- A triage call that sees all the signals and picks verdict + repair from the taxonomy only, plus the edit where code can't build it. The edit must pass the guards.
- A reply writer on a small model.
- Routing and confidence decided in code from how many signals agree, never by the model.
- Shadow mode: run every tier on every report, and log what early exit would have decided.
- Output results.json in the exact README format.

OpenRouter: I have $2.58 of paid credit, so paid models are allowed, not just :free ones. The model-list endpoint returns pricing. Use it to propose a cheap but strong model from a different family than the Groq solver, for solver #2 and the tie-breaker, and estimate the cost of one full run before running anything. Add a hard spend cap to the client (default $0.50 per run) that stops the run cleanly if it would be exceeded, and log the actual cost of every call. Every call must log which provider and model actually answered.

Prompts go in prompts/ as v1 files. Plan to test on 5 reports first before any full run.
</pasted_content id="5d75">

```

---

### 2026-11-10T19:40:13+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
try again
```

---

### 2026-11-10T19:46:36+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text


<pasted_content id="5d75">
mistake: the LLM-tier design had the triage model choosing the verdict, which contradicts D-001 (the LLM produces signals, code decides). Caught while reviewing the design.

Go ahead and build it, with these changes:
- Code decides the verdict wherever signals settle it. For answer disputes, solver + option-check agreement with or against the key gives no_error / answer_key / unsound. Triage chooses the verdict only where code can't (e.g. solution_fix vs wrong_question, missing stem data). If triage contradicts the signals, route to faculty.
- Keep extraction purely factual. Move the stem_data, contradiction and wrong-question flags to a separate check on gpt-oss-120b.
- Solver answers in the unit the question asks for; numeric matching uses a stated tolerance and handles unit conversion.
- Add Groq's prompt-guard model as an extra injection signal alongside the regex.
- Test set: add R034, so 6 reports.
- Restore .env.example.
- Add your three decisions to decisions.md, plus one for the verdict split.

Don't make any API calls yet. When it's built, show me all the prompt files verbatim so I can review them before the 6-report test.
</pasted_content id="5d75">

```

---

### 2026-11-10T21:43:16+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text


<pasted_content id="5d75">
Reviewed the prompts. Make these changes as v2 files with a CHANGELOG entry "pre-run review", keeping v1 as it is:

1. Integer questions can never reach answer_key, because option checks need options. Add a value check for integerQuestion (is this value correct?) for both the key's value and the solvers' value, and let decide.py use it the same way it uses option checks.
2. solver: if your answer matches no option, leave chosen_options empty and say so in question_issues; never pick the closest option. Convert degrees with pi/180.
3. decide.py: a solve whose missing_information is not empty doesn't count as independent agreement.
4. option_check: put parts and reason before verdict in the JSON, and tell it to work out the answer itself before judging the option.
5. solution_audit: values that appear in the options count as given.
6. evidence in results.json: for verdicts code decided, build the evidence string in code from the signals (which model said what, what the stored solution says, what the key says). Add triage's evidence only where triage decided.
7. reply: for syllabus reports, the question stays live while a teacher checks it; never say it was removed.
8. Log the prompt-guard flag rate in the run summary.

Then run the tests, commit, and run the 6-report test. Show me for each report: the signals, the final verdict/repair/route, the evidence, the reply, plus the total cost and time.
</pasted_content id="5d75">

```
