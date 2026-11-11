# AI mistakes log

Times the AI (coding assistant or in-product LLM) got something wrong. Add entries by writing `mistake: ...` in Claude Code; the user's words are kept and only formatted.

<!-- Template
## M-NNN: <short title>
- **Date:** YYYY-MM-DD
- **What the AI did wrong:**
- **How I caught it:**
- **What I changed:**
-->

## M-001: Throwaway MathML converter dropped HTML `<sup>`
- **Date:** 2026-11-10
- **What the AI did wrong:** the throwaway MathML converter dropped HTML `<sup>`, so `10<sup>-5</sup>` became "10-5" and it nearly got reported as a broken exponent.
- **How I caught it:** Caught while reviewing the survey.
- **What I changed:** the real parser must keep sup/sub.

## M-002: LLM-tier design had the triage model choosing the verdict
- **Date:** 2026-11-10
- **What the AI did wrong:** the LLM-tier design had the triage model choosing the verdict, which contradicts D-001 (the LLM produces signals, code decides).
- **How I caught it:** Caught while reviewing the design.
- **What I changed:** Code decides the verdict wherever signals settle it. For answer disputes, solver + option-check agreement with or against the key gives no_error / answer_key / unsound. Triage chooses the verdict only where code can't (e.g. solution_fix vs wrong_question, missing stem data). If triage contradicts the signals, route to faculty.

## M-003: Reply writer invented a correct answer on a question with no correct option
- **Date:** 2026-11-10
- **What the AI did wrong:** the reply writer told the R034 student "the correct answer is B" on a question with no correct option. Code gave it no correct-answer fact, so it made one up.
- **How I caught it:** Caught reviewing the 6-report test.
- **What I changed:** Approved fixes: for an unsound question the facts state that no option is correct as written, and the reply check rejects any option or value the facts don't contain (falling back to a template); reply_v3.

## M-004: Triage wrote an inserted value in caret notation that would render literally
- **Date:** 2026-11-11
- **What the AI did wrong:** the 20b run would have put "95.5×10^−3 H" live. In R007's stem_data edit, triage copied the clean-text notation it is shown (`^` for superscripts) into the replacement; the value was right, but HTML would show the caret. It passed every guard and auto-applied.
- **How I caught it:** found by the robustness test (D-005): `eval/compare_runs.py` lists auto-applied edits that differ from the main run, and R007's read "an inductance of 95.5×10^−3 H" where the main run had "inductance of 95.5 mH".
- **What I changed:** an edit guard: inserted text must not contain characters that would render literally (^, \, _{, raw LaTeX); values are written the way a student reads them (e.g. "95.5 mH"). The guard checks visible text only and blocks additions (`engine/edits.py`, test `test_guard_blocks_notation_that_renders_literally`); triage_v3 tells the model the same.

## M-005: triage_v3's notation warning stopped stem_data edits altogether
- **Date:** 2026-11-11
- **What the AI did wrong:** triage_v3's warning about notation made the model stop proposing stem_data edits at all (R006–R008 went from auto-apply to faculty).
- **How I caught it:** Caught by re-running all 44 rather than only the changed cases.
- **What I changed:** triage_v4: states plainly that a missing-value fix is expected when the solution states the value, written the way a student reads it; the notation rule is one short line (code enforces it anyway); if triage declines an edit it must say why (`no_edit_reason`).

## M-006: The injection regex fit R027's wording and missed the held-out phrasings
- **Date:** 2026-11-11
- **What the AI did wrong:** the injection regex was written against R027's wording and missed all three new phrasings in the held-out set (H07-H09); H08 auto-applied from an injection report.
- **How I caught it:** Caught by a held-out set I built, not by the 44.
- **What I changed:** D-030. A detector built on what the comment does (five families, English and Hinglish), and any guard score >= 0.5 now blocks auto-apply.
