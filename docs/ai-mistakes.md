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
