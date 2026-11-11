# PRODUCT.md

## Who loses most when a question is broken

- **The student who meets a broken question the night before an exam.** A wrong key doesn't just cost a
  mark; it teaches the wrong concept, and the student trusts it.
- **The student who reported correctly and gets brushed off.** They stop reporting, and the next broken
  question stays broken for everyone.

How the design responds:
- **Blocking defects come first.** The faculty queue is ordered by harm (blocks the right answer > wrong
  solution or option > cosmetic or classification), then by how many students reported it, then by certainty
  (D-026).
- **Fast auto-fix when the evidence is strong.** A wrong key confirmed by two independent model families and
  the option checks goes live without waiting for a human (D-016, D-023).
- **Every reporter is credited.** The verdict follows whether the thing they disputed is defective, not
  whether their own answer is right. The reply thanks them for the real problem and gently corrects their
  answer (D-015).

## What never auto-applies

The bar depends on the risk of the repair (D-023):
- **Low risk** (spelling, noise, exam_reference, markup_leak, answer_form): auto-applies when its structural
  guard passes and a code check supports it. The guards box in the harm: spelling edits can't change a digit
  or symbol, answer_form edits only add, and exam_reference and markup_leak edits are code-built.
- **High stakes** (answer_key, stem_data, option_repair, solution_fix, type_mismatch, notation,
  solution_missing): need two independent sources (D-023, D-024).

These never auto-apply:
- **An answer-key change without two independent model families agreeing**, confirmed by the option or value
  checks (D-016).
- **Anything from an injection-flagged report**, however strong the evidence (D-017, D-030, D-032).
- **New authored content:**
  - a missing distractor goes to faculty, because there is no source for its text (D-013)
  - figures are faculty-only (`diagram`, `auto: false`)
  - a blank option's content needs two agreeing sources (D-020)
  - a whole new solution needs two independent sources (D-024)
- **Classification and syllabus calls** (`wrong_chapter`, `syllabus`, faculty-only; D-011).
- **Anything that changes how past attempts were scored without re-grading them.** This is a product rule;
  re-grading isn't built here.

And a reply never states an answer the engine hasn't confirmed (D-031, D-032):
- A reply that names a different answer, or claims an action that didn't happen, is replaced by a code-built
  one.
- A flagged report sent to faculty gets a neutral reply that names no answer.

## The week-1 metric

**The undo rate on auto-applied edits:** the share of auto-applied edits that faculty reverse. It measures
directly whether "auto" can be trusted. The target is near zero; if it rises, tighten the bar for the repair
types being undone.

**Secondary:** the time from first report to fix for blocking defects (a wrong key, missing data, no correct
option).

## The idea to pitch: catch broken keys before anyone reports them

- Attempt data already holds the signal. If strong students overwhelmingly pick an option the key calls
  wrong, the key is probably wrong.
- Feed those questions into the same verification pipeline (blind solves by two model families, option
  checks, code deciding), with no student comment needed.
- Run it across the whole 8-lakh corpus as well. On the 43 questions here, the bonus pass found 21
  question-level issues that no report's outcome covered, on 13 questions: 8 from code checks and 13 added in
  manual review (`bonus_findings.json`).
