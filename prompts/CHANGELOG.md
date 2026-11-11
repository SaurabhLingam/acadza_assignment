# Prompt changelog

One entry for each new prompt version. Prompt files live in this folder as `<name>_v<N>.md` and are never edited after they are used in a logged run. To change one, create the next version.

<!-- Template
## <name>_v<N>: YYYY-MM-DD
- **What changed:**
- **Why:**
- **Evidence:** (report IDs, log lines from logs/llm-calls.jsonl, eval-label mismatches)
-->

## solver_v1: 2026-11-10 (not yet run)
- **What changed:** First version. Blind solve: sees only the question type, clean stem and options; never the key, the stored solution or the comment (D-002). Answers in the unit the question asks for, as a calculator expression that code evaluates safely and matches to options numerically (with unit conversion). `missing_information` and `question_issues` are extra signals.
- **Why:** Independent check of the key without anchoring on it. Used by two model families (solver_1 on Groq gpt-oss-120b, solver_2 on OpenRouter deepseek-v4-flash).
- **Evidence:** Pending the 6-report test run.

## extract_v1: 2026-11-10 (not yet run)
- **What changed:** First version. Purely factual: what the stored solution ends on (value, unit, option named, final statement). It does not judge the solution or look for problems.
- **Why:** Code's regex extraction misses symbolic finals. Judgement about the solution lives in `solution_audit_v1`, so this call stays a cheap fact read (gpt-oss-20b).
- **Evidence:** Pending the 6-report test run.

## solution_audit_v1: 2026-11-10 (not yet run)
- **What changed:** First version, split out of the extract draft at the user's request. Three yes/no judgements with quoted evidence: values the solution uses that the question never gives (stem_data), internal contradiction (unsound / solution_fix), part of the solution about another question (solution_fix / wrong_question). No key shown.
- **Why:** These are judgements, not facts, so they run on the stronger gpt-oss-120b and stay separate from extraction.
- **Evidence:** Pending the 6-report test run.

## option_check_v1: 2026-11-10 (not yet run)
- **What changed:** First version. Judges one option (or, for integer questions, one candidate answer) at a time, with no key shown; statement options are judged part by part. The same prompt is the tie-breaker on the other model family.
- **Why:** Called only where a key change is on the table (a solver or the solution differs from the key, the student disputes the key, or the key is malformed), to keep calls down.
- **Evidence:** Pending the 6-report test run.

## triage_v1: 2026-11-10 (not yet run)
- **What changed:** First version. Code decides the verdict wherever the signals settle it, and the task block tells triage exactly what is left: the verdict (only where code cannot decide), the repair from a code-given shortlist (e.g. solution_fix vs wrong_question), or a blank option's content. Where code already decided, triage states what it believes so code can detect a contradiction and route to faculty. Edits are proposed in clean text; code maps them to raw HTML. No confidence and no route in the output (D-001).
- **Why:** The first design let triage choose every verdict, contradicting D-001 (`docs/ai-mistakes.md` M-002).
- **Evidence:** Pending the 6-report test run.

## reply_v1: 2026-11-10 (not yet run)
- **What changed:** First version. 1–3 sentences; credits the student when the disputed item was defective (D-015); promises only what the route allows; replies in Hinglish to Hinglish comments; uses only the facts code supplies. Code validates the reply and falls back to a template on failure.
- **Why:** The student reply is scored, and a reply that says "fixed" when the case is only routed to faculty would be false.
- **Evidence:** Pending the 6-report test run.

## prompt_guard_v1: 2026-11-10 (not yet run)
- **What changed:** First version. The student comment verbatim as the only message to Groq's `meta-llama/llama-prompt-guard-2-86m` classifier, with no instructions added. Its score is an injection signal alongside the regex detector in `engine/claims.py`.
- **Why:** A second, independent injection detector. The reply format (score or label) is parsed defensively and logged raw, to be confirmed in the first test run.
- **Evidence:** Pending the 6-report test run.

## Pre-run review: 2026-11-10 (solver_v2, option_check_v2, value_check_v1, solution_audit_v2, reply_v2)
The user reviewed the v1 prompts before any of them ran. The v1 files are kept unchanged; none of them has been used in a logged run.

### solver_v2
- **What changed:** If the answer matches no option, `chosen_options` stays empty and `question_issues` says so; the solver never picks the closest option. Trigonometric functions take radians, and degrees are converted with pi/180. `missing_information` is null when nothing is missing.
- **Why:** A closest-option pick would look like agreement with a key, or with another solver, when it is not. A degree value inside sin() would evaluate wrongly in the code evaluator.
- **Evidence:** Pre-run review by the user. Code enforces the same rule: an evaluated value that matches no numeric option maps to no letters (`engine/tiers.py`).

### option_check_v2
- **What changed:** The model first works out its own answer (`own_answer`), then writes `parts` and `reason`, and gives `verdict` last.
- **Why:** If the verdict comes first in the JSON, the reasoning is written after the judgement and only justifies it.
- **Evidence:** Pre-run review by the user.

### value_check_v1 (new prompt)
- **What changed:** The integer-question counterpart of option_check: is this candidate value the correct answer? Same structure (`own_answer`, then `reason`, then `verdict`). It is run on the key's value and on each solver value that differs from the key, on gpt-oss-120b (`value_check`), with deepseek-v4-flash as the tie-breaker (`value_tiebreak`).
- **Why:** Option checks need options, so an integer question could never reach answer_key. `engine/decide.py` uses value checks the same way it uses option checks.
- **Evidence:** Pre-run review by the user.

### solution_audit_v2
- **What changed:** Values that appear in the options count as given, so they are not listed under `values_not_in_question`.
- **Why:** A solution that plugs in an option value (e.g. to verify it) would otherwise be flagged as using unstated stem data.
- **Evidence:** Pre-run review by the user.

### reply_v2
- **What changed:** For syllabus reports, the question stays live while a teacher checks it; the reply never says it was or will be removed. Code also adds this to the facts, and `check_reply` rejects a syllabus reply that mentions removal.
- **Why:** The taxonomy says syllabus claims are faculty-only and the question stays live meanwhile.
- **Evidence:** Pre-run review by the user; `data/taxonomy.json` (repair `syllabus`).

## Review of the first 6-report test: 2026-11-10 (solver_v3, solution_audit_v3, reply_v3, triage_v2)
The v2 prompts (and triage_v1) were used in run `20261110T161819Z` and stay unchanged.

### solver_v3
- **What changed:** `final_expression` is null only when the answer is a statement; a number or ratio is always given as an expression, even if it matches no option or a letter is also picked. Code also records when a solver's answer is only its picked letter (`from_letter`) and uses that letter as its answer.
- **Why:** gpt-oss-120b returned `final_expression: null` for numeric answers, so code could not compare its value or apply the never-the-closest-option rule.
- **Evidence:** Run `20261110T161819Z`: R011 (ratio 1:1, null expression), R027 (5.7e-5, null expression, letter A only).

### solution_audit_v3
- **What changed:** Standard data (the density of water, atmospheric pressure, the speed of sound) and pure numbers that belong to a formula (the 3 in γ = 3α) are no longer listed as values the question never gives.
- **Why:** False positives would wrongly support a stem_data verdict.
- **Evidence:** Run `20261110T161819Z`: R016 flagged "1 g/cm^3 density of water", R027 flagged the factor 3 in γ = 3α.

### reply_v3
- **What changed:** If the student proposed no answer, the reply states the right answer and the key step neutrally and never says their answer was wrong. If no option is correct, the reply never names an option or value as the answer. It names an option letter or value only if it appears in the facts. The Hinglish rule is stronger and has an example. Code now supplies the key step (the working of a blind solver whose answer code matched to the correct one), the post-edit content of a repaired option, and an explicit "no option is correct" fact. `check_reply` rejects option letters or values not in the facts, an English reply to a Hinglish comment, and "your answer was wrong" when the student proposed none; a failure falls back to a code-built template (English or Hinglish). Letters in a comment flagged as an injection are not treated as the student's answer.
- **Why:** M-003 (R034 told "the correct answer is B" with no correct option); R004 and R011 answered in English to Hinglish comments; R027 told "Your answer was not correct" although the student gave no answer; replies had no real key step because the facts contained none.
- **Evidence:** Run `20261110T161819Z`, reports R004, R011, R027, R029, R034.

### triage_v2
- **What changed:** When the task says the stored solution ends at a wrong value and gives the agreed value, triage proposes the minimal solution_fix edit: the shortest unique span around the wrong final value, with only that value changed. Code puts the wrong and agreed values in the task block only when the key, both solver families and the option/value check all agree.
- **Why:** In R016 triage chose solution_fix but returned `"edit": null` with no reason (the cached response confirms it). The task block made the edit optional ("only if the repair needs one") and never told triage which value to change, so the case went to faculty for want of an edit.
- **Evidence:** Run `20261110T161819Z`, R016; cached triage response for that call.

## reply_v4: 2026-11-10
- **What changed:** The reply never opens with "your answer is not correct" or anything like it; it opens by acknowledging the student's effort or with the right answer, then gives the key step. A differing student answer may be mentioned gently after the key step. `check_reply` rejects a reply whose first sentence tells the student they were wrong (fallback: the code template, which now also gives the key step). Code also now supplies a "what was wrong with the question" fact for every defect, including reports code settled on its own.
- **Why:** User review of run `20261110T172651Z`: R029 opened "Your answer of 0.4 is not correct". R021's reply invented a "negative sign" explanation because code-settled reports got no answer or what-changed facts.
- **Evidence:** Run `20261110T172651Z`, R021, R029 (R020 also explained physics not in its facts).

## triage_v3: 2026-11-11
- **What changed:** `replace` must be written the way a student reads it: plain text, values with their usual unit symbol ("95.5 mH"). The prompt explains that the clean text it is shown writes formatting as `^` and `_`, and that those (and `_{`, `\`, LaTeX) would render literally. A new edit guard (`engine/edits.py`, `_LITERAL_NOTATION`) rejects any question/solution edit whose visible text adds `^`, `\` or `_{`, so the prompt is the first line and the guard the hard stop.
- **Why:** M-004: in the gpt-oss-20b robustness run, triage copied the clean-text notation into a stem_data edit, "an inductance of 95.5×10^−3 H", which passed every guard and auto-applied (the value was right, the caret would have shown to students).
- **Evidence:** Run `20261111T012802Z-swap-gpt-oss-20b`, R007. The main run's edit for the same report was "inductance of 95.5 mH". Re-checked every edit in both runs and in `bonus_findings.json` against the new guard: only that R007 edit fails.
- **Check after the change:** run `20261111T015454Z-swap-gpt-oss-20b` (R006-R008, gpt-oss-20b swap, triage_v3): R008 wrote "an inductance of 95.5 mH" and auto-applied after the re-solve check; R006 auto-applied ("solid copper cube of side length 10 cm"); R007's triage proposed no edit this time, so it went to faculty. The main `results.json` was produced with triage_v2 and is not regenerated here.

## triage_v4: 2026-11-11
- **What changed:** a `stem_data` edit is now stated as expected whenever the stored solution states the missing value, written the way a student reads it and inserted next to the quantity it belongs to. The notation rule is cut to one line (code's `_LITERAL_NOTATION` guard enforces it anyway). A new output field `no_edit_reason` is required when a defect gets no edit; code records it in the case's edit note. Examples use neutral values (a capacitor, 2.2 μF) rather than values from the dataset.
- **Why:** M-005: triage_v3's longer warning about notation made gpt-oss-120b stop proposing stem_data edits at all, and it gave no reason.
- **Evidence:** Full run `20261111T044652Z` (triage_v3): R006, R007, R008 triage returned `edit: null` with no reason in `evidence`, so all three went from auto-apply (triage_v2, run `20261110T182626Z`: "inductance of 95.5 mH", "solid copper cube of side 10 cm", both re-solve checked) to faculty review.

## Data-free examples: 2026-11-11 (triage_v5, solver_v4, extract_v2, reply_v5)
- **What changed:** every example value or phrase that came from `data/` is replaced by a neutral one. Nothing else changed in any of the four prompts.
  - triage_v5: solution-fix example "a = 40 cm" → "a = 20 cm" becomes "x = 6.4 mm" → "x = 7.3 mm"; value examples "2.2 μF", "15 cm", "2.2×10^−6 F" become "4.7 μF", "0.36 m", "4.7×10^−6 F".
  - solver_v4: scientific-notation example "5.7e-5" becomes "7.3e-4".
  - extract_v2: named-answer example "the correct answer is (d)" becomes "so option (b) is the answer".
  - reply_v5: Hinglish example "Sahi answer (D) 4800 N/m² hai, kyunki P = ⅓ρv² lagta hai" becomes "Sahi answer (B) 7.3 m/s hai, kyunki v = u + at lagta hai".
- **Why:** an example taken from the data gives the model the answer to a real report, so a correct result could come from the prompt rather than the pipeline.
- **Evidence:** "a = 40 cm" → "a = 20 cm" is R016's exact fix; 4800 N/m² is R004's key; 5.7×10⁻⁵ is R027's key; "the correct answer is (d)" appears verbatim in stored solutions; 2.2 and "15 cm" occur in the data. Found by `tests/test_prompt_data_leak.py`, which now fails if any prompt the engine loads contains a decimal or 3-digit number, a value with a unit, a quoted example with a digit, or a 5-word phrase from `data/questions.json` or `data/reports.json`. Retired versions (triage_v2–v4, solver_v1–v3, reply_v3–v4, extract_v1) contain the same examples and are left as they were used in logged runs.

## solver_v5, triage_v6: 2026-11-11
- **What changed:** solver_v5: `missing_information` means only a value the question needs and does not give; standard constants (g, water density, …) and a blank or absent option are not missing. triage_v6: `find_clean` is a short plain-text phrase (for stem_data, the phrase naming the quantity), never a span with a formula, an exponent or a number in notation. Code (`engine/decide.py`, `excuse_noticed_defect`): a solver whose `missing_information` only names a defect code already found (a blank/missing option, a missing figure) still counts as evidence; the text is kept as `noticed`.
- **Why:** in run `20261111T054141Z` (solver_v4, triage_v5) three auto-applies dropped to faculty without anything being wrong: R016's solver 1 listed "assumed water density ρ = 1 g/cm³" as missing and R011's solver 1 listed "Option C is missing", so neither solve counted; R006's triage chose a `find_clean` containing "7×10^6", which has no unique raw-HTML match, so no edit could be built.
- **Evidence:** run `20261111T054141Z`, details for R006, R011, R016 (`solvers[].missing`, `edit_how`, `route_why`).
