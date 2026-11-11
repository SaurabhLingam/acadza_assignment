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

---

### 2026-11-10T22:47:00+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text


<pasted_content id="5d75">
mistake: the reply writer told the R034 student "the correct answer is B" on a question with no correct option. Code gave it no correct-answer fact, so it made one up. Caught reviewing the 6-report test.

decision: option_repair can auto-apply when two independent sources agree on the missing content, and the stored solution counts as one source. The evidence must say exactly which sources agreed.

Approve your fixes 1–4, 6, 7, 8 (reply_v3, solver_v3, solution_audit_v3, plus code changes). Also:
- R027's reply says "Your answer was not correct", but that student gave no answer. When the comment proposes no answer, the reply just states the right answer and the key step, neutrally.
- solver: if final_expression is null but chosen_options is set, code uses the letter as that solver's answer.
- R016: triage should propose a minimal solution_fix edit (e.g. "a = 40 cm" → "a = 20 cm") when the key, both solvers and the value check agree on the value. If it passes the guards and all signals agree, auto_apply. Find out why triage didn't propose it this time.
- Fix the R011 evidence wording.

Also: docs/eval-labels.csv is now verified. Set label_source to user_verified on all 44 rows, and add a line at the top of the file: "Drafted by Claude Code; independently re-solved in a separate Claude session; traps and disputed cases reviewed by me."

Then rerun the same 6 (cached solves make it cheap), plus 6 new ones that exercise untested paths: R005 (integer, wrong key), R020 (malformed mcq key), R021 (type_mismatch), R007 (stem_data), R001 (duplicate group), R039 (Hinglish language request). Same per-report summary as before, plus a score against eval-labels.csv. Commit, and keep logs/runs in git.
</pasted_content id="5d75">

```

---

### 2026-11-10T23:04:29+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
<task-notification>
<task-id>be5xg9m15</task-id>
<tool-use-id>toolu_01BPfxft26dwTsVgvHt6bEDp</tool-use-id>
<output-file>C:\Users\saura\AppData\Local\Temp\claude\ebefd33da09cf696\3fa27d9c-9c89-4801-bd05-2c41bbce6651\tasks\be5xg9m15.output</output-file>
<status>completed</status>
<summary>Background command "PYTHONIOENCODING=utf-8 python -m engine.run --reports R004,R011,R016,R027,R029,R034,R005,R020,R021,R007,R001,R039 --cap 0.50 &gt; /c/Users/saura/AppData/Local/Temp/claude/ebefd33da09cf696/3fa27d9c-9c89-4801-bd05-2c41bbce6651/scratchpad/run2.log 2&gt;&amp;1" completed (exit code 0)</summary>
</task-notification>
```

---

### 2026-11-10T23:09:08+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text


<pasted_content id="5d75">
decision: stem_data only auto-applies if a re-solve with the inserted value reproduces the keyed answer. Otherwise faculty_review. Same principle as D-020: two independent sources must agree before content goes into a question.

Go ahead with fixes 1–3 and the R007 re-solve check. Also:
- reply tone: never open with "your answer is not correct". Start by acknowledging their effort or with the right answer, then the key step. reply_v4 with a CHANGELOG entry.
- remove the stale "UNSURE" note on R034 in eval-labels.csv (verified).

Then rerun the 12 to confirm nothing regressed. If all 12 still match, do the full run on all 44 reports and write results.json at the repo root. Score it with eval/evaluate_run.py, and also list: every auto_apply with its edit, every reply that fell back to a template, and the shadow-mode disagreements. Commit and push.
</pasted_content id="5d75">

```

---

### 2026-11-10T23:12:41+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
<task-notification>
<task-id>b1mvk81ah</task-id>
<tool-use-id>toolu_01B3RQG81Z2VWTdUi1F4KfgW</tool-use-id>
<output-file>C:\Users\saura\AppData\Local\Temp\claude\ebefd33da09cf696\3fa27d9c-9c89-4801-bd05-2c41bbce6651\tasks\b1mvk81ah.output</output-file>
<status>completed</status>
<summary>Background command "PYTHONIOENCODING=utf-8 python -m engine.run --reports R004,R011,R016,R027,R029,R034,R005,R020,R021,R007,R001,R039 --cap 0.50 &gt; /c/Users/saura/AppData/Local/Temp/claude/ebefd33da09cf696/3fa27d9c-9c89-4801-bd05-2c41bbce6651/scratchpad/run3.log 2&gt;&amp;1" completed (exit code 0)</summary>
</task-notification>
```

---

### 2026-11-10T23:25:02+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
ETA?
```

---

### 2026-11-10T23:32:44+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
done?
```

---

### 2026-11-10T23:41:46+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
how much more time?
```

---

### 2026-11-10T23:43:28+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text


<pasted_content id="5d75">
Stop the run. Groq's daily limit is the bottleneck and I don't want degraded reports in results.json.

decision: amend D-018. When Groq is rate-limited for more than 60 s, fall back to the same model on OpenRouter (openai/gpt-oss-120b, and gpt-oss-20b for the small jobs), still under the per-run spend cap. Same model, so solver independence is unaffected. Evidence: the full run stalled at report 35 with an 11-minute wait on triage after Groq's daily token limit ran out.

Implement that, log which provider actually answered each call, and keep the cache working so the 35 finished reports aren't redone. Then resume the full run, score it, and report as planned: score vs eval-labels, every auto_apply with its edit, template fallbacks, shadow-mode disagreements, total cost. Commit and push.
</pasted_content id="5d75">

```

---

### 2026-11-10T23:49:47+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text
<task-notification>
<task-id>bxsco1xdy</task-id>
<tool-use-id>toolu_01UDr4hFNSmCyzFFFETh6yq9</tool-use-id>
<output-file>C:\Users\saura\AppData\Local\Temp\claude\ebefd33da09cf696\3fa27d9c-9c89-4801-bd05-2c41bbce6651\tasks\bxsco1xdy.output</output-file>
<status>completed</status>
<summary>Background command "PYTHONIOENCODING=utf-8 python -u -m engine.run --cap 0.50 &gt; /c/Users/saura/AppData/Local/Temp/claude/ebefd33da09cf696/3fa27d9c-9c89-4801-bd05-2c41bbce6651/scratchpad/run_full2.log 2&gt;&amp;1" completed (exit code 0)</summary>
</task-notification>
```

---

### 2026-11-10T23:53:06+05:30

session: `3fa27d9c-9c89-4801-bd05-2c41bbce6651`

```text


<pasted_content id="5d75">
decision: auto-apply bar depends on repair risk. Low-risk repairs (spelling, noise, exam_reference, markup_leak, answer_form) auto-apply when their guard passes and at least one code check supports them; the guards already limit the harm structurally. High-stakes repairs (answer_key, stem_data, option_repair, solution_fix, type_mismatch) keep the two-independent-sources rule.

Fix 1 (vague comment with no named answer counts as nothing_specific, so the checks decide; clear R040's UNSURE note) and 2 (replies use corrected option text). Also:
- prompt-guard alone only blocks auto-apply at score >= 0.9, unless the regex also flags; log everything below. Tell me R009's score.
- the reply check shouldn't flag "fixed" for already_fixed reports.

Rerun only what's affected (cache the rest), rescore, commit and push. Give me a short summary.
</pasted_content id="5d75">

```

---

### 2026-11-11T06:55:13+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text


<pasted_content id="8dee">
Fresh session. Before anything, read CLAUDE.md, docs/decisions.md, engine/README.md and the latest logs/run-summary.json so you know where the project stands.

Then three small things, then a test.

1. Clear R026's "UNSURE" note in eval-labels.csv (verified as defect/syllabus).
2. decision: notation and solution_missing count as high-stakes repairs under D-023. notation can change what a value means, and solution_missing writes new content, so both need two independent sources.
3. Collect every question-level finding no report covers into bonus_findings.json at the repo root: question id, repair type, exact evidence text, and whether it could auto-apply. Include the leftovers on reported questions too (like "Canolla" in R040's question).

Then the weak-model robustness test (decision e): rerun all 44 with gpt-oss-20b instead of gpt-oss-120b as solver #1 and for the checks, writing only to logs/runs/, never the root results.json. Compare it to the main run: accuracy vs eval-labels, how many cases moved to faculty, and above all the number of wrong auto_applies. Run it in the background and report when done. Commit and push.
</pasted_content id="8dee">

```

---

### 2026-11-11T07:14:24+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text


<pasted_content id="8dee">
Cross-check bonus_findings.json against this list from my manual review. For each one, look at the raw HTML in data/questions.json first and confirm it's a real defect in the stored content, not an artifact of our parser. Add the real ones if they're missing; tell me which you dropped and why.

- 68f21caf: radioactivity question filed under chapter "Mathematics in physics" (wrong_chapter)
- 66fe9dbe: solution says insulin and glucagon "work synergistically" (they're antagonistic); option C is missing its dash
- 6956d7e9: options write the unit inside the root, √(2 m)
- 61ee6c9d: "prominant" and "Maceus" in the solution
- 68dea657: garbled subscripts P_eqcu / P_eqch in the solution
- 6062ec84: solution units showing as "/AC", "/CC"
- 6264197: "producebeta-carotene" in the solution (mark as a manual finding)

Also remove the inhibit/inhibin and abaxial/adaxial false positives.
</pasted_content id="8dee">

```

---

### 2026-11-11T07:18:28+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text
<task-notification>
<task-id>b6q12fn8v</task-id>
<tool-use-id>toolu_01L3gtBv25zky6oueqzu6YsX</tool-use-id>
<output-file>C:\Users\saura\AppData\Local\Temp\claude\ebefd33da09cf696\77f3d0e8-4bb1-44c9-8f08-2d117cd48778\tasks\b6q12fn8v.output</output-file>
<status>completed</status>
<summary>Background command "Run all 44 reports with gpt-oss-20b swapped in" completed (exit code 0)</summary>
</task-notification>
```

---

### 2026-11-11T07:22:19+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text


<pasted_content id="8dee">
decision: approve D-025.

Also add an edit guard: inserted text must not contain characters that would render literally (^, \, _{, raw LaTeX). Write values the way a student reads them (e.g. "95.5 mH"). The 20b run would have put "95.5×10^−3 H" live. Note it in ai-mistakes as found by the robustness test. Commit and push.

Then the faculty console, in console/. Design is below; build it in stages and stop after stage 1 so I can look at it.

Stack: React + Vite + TypeScript, static build for Vercel. A build script bakes data/questions.json, results.json, the evidence and bonus_findings.json into one data file, with the "after" HTML pre-computed by applying each edit. No backend, no API keys. Small banner: "Precomputed results, no live AI calls."

Who it's for: a tired faculty member at 10 PM checking dozens of these. They must see in two seconds what changed and why, act in one keystroke, and trust what they see. Dark mode by default, light toggle. Calm and dense, Linear-style. Make it look deliberately designed, not like a default template.

Layout:
- Top bar: progress (x of y reviewed), counts per route, link to the audit log.
- Left: queue grouped by question. Tabs: Needs you / Auto-applied (with undo) / No change (spot-check) / Bonus findings. Each row: urgency dot, topic, number of reporters, one-line reason.
- Centre, for the selected case:
  - Headline, e.g. "Answer key C → A · 3 students · all sources agree".
  - Evidence as chips: ✓ gpt-oss → A, ✓ DeepSeek → A, ✓ stored solution → A, ✗ key says C. Raw evidence one click away.
  - The question rendered properly (native MathML), changed part highlighted.
  - Before/after diff side by side, rendered not raw, changes marked. Answer-key changes as a pill: "C (130 V) → A (50 V)".
  - Every student comment for this question, each with its reply preview, editable.
- Fixed action bar: Approve (A), Edit (E: edit the replacement inline, guards re-run, invalid edits blocked), Reject (R: quick reason chips). J/K to move between cases. Undo toast after every action.

Urgency order = harm × reach × certainty. Harm: defects that stop a student getting the right answer (wrong key, missing data, unsound, blank keyed option) first, wrong solution middle, cosmetic last. Reach: distinct reporters. Certainty: agreeing evidence first, since those are quick wins. Show "why it's here" on each item.

Audit log: every action records time, reviewer (asked once), case, action, before/after, reason. Stored in localStorage, with export to JSON. Say honestly in the UI that it's stored in this browser.

Safety: sanitize all question HTML and student comments (allow MathML, strip scripts and handlers).

Stage 1: the data build script, the layout with real data, the queue and case view with rendered questions. No actions yet. Tell me how to run it locally.
</pasted_content id="8dee">

```

---

### 2026-11-11T07:25:08+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text
<task-notification>
<task-id>bx5r0xk0n</task-id>
<tool-use-id>toolu_01JjZr6WXT3AJoC4gz6C9aLG</tool-use-id>
<output-file>C:\Users\saura\AppData\Local\Temp\claude\ebefd33da09cf696\77f3d0e8-4bb1-44c9-8f08-2d117cd48778\tasks\bx5r0xk0n.output</output-file>
<status>completed</status>
<summary>Background command "Rerun R006-R008 with 20b swap and triage_v3" completed (exit code 0)</summary>
</task-notification>
```

---

### 2026-11-11T07:46:07+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text


<pasted_content id="8dee">
/design Redesign the faculty review console in console/ from scratch. Keep the data pipeline (public/data.json) and the sanitization; replace the UI. Stage 1 showed everything at once; this version must be simple.

WHO AND WHY
A faculty member, tired, at 10 PM, clearing dozens of student error reports on JEE/NEET questions. For each case they must see in 2 seconds what is wrong and what will change, trust it, and act with one keystroke. Every design choice serves that. When in doubt, show less.

PRINCIPLES
- One case at a time, inbox-style.
- Every case answers three questions, top to bottom: What's wrong? How sure are we? What changes?
- Primary actions always in the same place.
- Everything else is secondary and collapsed by default.
- Never show a claim the evidence below contradicts.
- Restrained visuals: one accent colour; red/green only for diffs and pass/fail marks; generous spacing; no pill soup.

LAYOUT
- Top bar (thin): product name, "Precomputed results, no live AI calls" as subtle text, progress "3 of 10 need you", Audit log, theme toggle.
- Left: slim, collapsible queue (toggle with \). Two tabs: "Needs you" (default) and "Done". An "Other" menu holds Auto-applied, No change and Bonus findings. Rows: urgency dot, short title ("Answer key C → A"), topic, reporter count. Nothing more.
- Centre: the case.
- Bottom: fixed action bar.

THE CASE VIEW, top to bottom
1. Small context line: harm tier ("Blocks the right answer" / "Wrong solution" / "Cosmetic" / "Classification"), subject · chapter, number of students.
2. WHAT'S WRONG: one plain sentence as the headline, e.g. "The answer key says C (130 V), but the correct answer is A (50 V)." or "No option is correct as written." or "Option C is blank, and it is the keyed answer."
3. HOW SURE: one honest line, e.g. "Two independent AI solvers and the stored solution all give A." or "Every option was checked wrong by two models, and the solution contradicts itself." Then a "Show evidence" toggle.
   - For answer cases, the evidence is a compact grid: rows = options, columns = Solver 1, Solver 2, Option check, Stored solution, Key. Cells ✓ / ✗ / –. Model names as column tooltips.
   - Below the grid, a "Raw evidence" link with the exact evidence string from results.json.
4. WHAT CHANGES: the rendered question (native MathML, serif) with a before/after diff:
   - Text edits: side-by-side Before | After, changed spans highlighted red/green.
   - Answer-key edits: a single clear line "Answer: C (130 V) → A (50 V)" above the question; the keyed option tagged KEY in the question, the new one tagged NEW.
   - Faculty-only repairs (no edit): no diff; show "Suggested fix (AI suggestion, not applied): …" when the evidence supports one.
   - No-change cases: "Nothing changes", with why.
5. Secondary sections, collapsed by default, each one line when closed:
   - Stored solution (auto-expanded when the solution is the evidence, with flagged spans highlighted).
   - Student reports: each comment as plain text, with its reply preview underneath (editable in Edit mode).
   - Details: report ids, route, confidence, repair type.

ACTIONS (bottom bar, always in the same place)
- Edits that will go live: Approve (A) · Edit (E) · Reject (R).
- Faculty-only repairs: Confirm defect (A) · Not a defect (R).
- Auto-applied items: Keep (A) · Undo (U).
- No-change items: Looks right (A) · Flag (R).
- Edit opens inline editing of the replacement text and the reply. Re-run the browser-side guards (allowed fields, find text unique, no literal ^ \ _{ markup, spelling edits can't change digits or symbols, answer_form edits additive only) and block invalid edits with a one-line reason.
- Reject / Not a defect / Flag ask for a reason: quick chips ("AI is wrong", "Needs a rewrite", "Not a defect", "Other") plus an optional note.
- After any action: small undo toast for 5 seconds, then the next case loads automatically.
- Keyboard: J/K next/previous, A/E/R/U actions, \ toggles queue, ? shows shortcuts.

AUDIT LOG
- Ask the reviewer's name once (small dialog, remembered).
- Every action records: time, reviewer, question id, report ids, action, before/after, reason/note.
- A drawer lists entries newest first, with Export JSON.
- State plainly in the drawer: "Stored in this browser."

QUEUE ORDER
Harm first, then reach (distinct reporters), then certainty, as in D-026. Show one muted "Why it's here" line on the case, not in the list.

OTHER STATES
- Empty "Needs you": a calm "All caught up" message with counts of what was done.
- Bonus findings: same case layout; the headline is the finding, the diff is the proposed edit when one exists, marked "found without a student report".
- Display / app / language reports: headline says what the student reported and that the question content is fine; actions Looks right / Flag.

VISUAL STYLE
Dark by default, light toggle. Calm, dense where it helps, generous elsewhere, Linear-like restraint. Sans-serif UI, serif for question text, monospace only for ids. Readable at 100% zoom on a laptop. Visible focus states for keyboard use.

CONSTRAINTS
Static site (React + Vite + TS), no backend, no API keys. Sanitize all HTML (allow MathML, strip scripts and handlers); comments as plain text only. Must deploy on Vercel with root directory console.

When done: run it, check it with headless screenshots, fix anything broken, then commit and push. Show me screenshots of 695ee00b (R034, no option correct), 60f744b3 (answer key C → A), 6263d75b (solution fix), and the empty "Needs you" state. Then give me exact Vercel deploy steps.
</pasted_content id="8dee">

```

---

### 2026-11-11T07:55:02+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text
<task-notification>
<task-id>bjll0caek</task-id>
<tool-use-id>toolu_01V8NsiNvuQM7PoBMHi5MPT1</tool-use-id>
<output-file>C:\Users\saura\AppData\Local\Temp\claude\ebefd33da09cf696\77f3d0e8-4bb1-44c9-8f08-2d117cd48778\tasks\bjll0caek.output</output-file>
<status>completed</status>
<summary>Background command "Install Playwright in a scratch virtualenv" completed (exit code 0)</summary>
</task-notification>
```

---

### 2026-11-11T08:00:19+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text
<task-notification>
<task-id>brueq297g</task-id>
<tool-use-id>toolu_01Rf38KxxeMkGSNAqTWs6rDc</tool-use-id>
<output-file>C:\Users\saura\AppData\Local\Temp\claude\ebefd33da09cf696\77f3d0e8-4bb1-44c9-8f08-2d117cd48778\tasks\brueq297g.output</output-file>
<status>failed</status>
<summary>Background command "Serve built console on port 4173" failed with exit code 1</summary>
</task-notification>
```

---

### 2026-11-11T08:05:43+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text
<task-notification>
<task-id>bpw127m2q</task-id>
<tool-use-id>toolu_01WYVqrFYjkjjzWdrTEFq9Vi</tool-use-id>
<output-file>C:\Users\saura\AppData\Local\Temp\claude\ebefd33da09cf696\77f3d0e8-4bb1-44c9-8f08-2d117cd48778\tasks\bpw127m2q.output</output-file>
<status>failed</status>
<summary>Background command "Serve built console on port 4173" failed with exit code 127</summary>
</task-notification>
```

---

### 2026-11-11T08:19:33+05:30

session: `77f3d0e8-4bb1-44c9-8f08-2d117cd48778`

```text
Yes, add D-026 and D-027 to decisions.md. Commit and push.
```
