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
