"""Check a claim against the record and the rule findings; decide the outcome.

Outcomes:
  code_settled  - code can name verdict, repair and route with certainty
  code_routed   - the case goes to faculty whatever an LLM says (auto: false repair
                  whose existence code has confirmed, or a claim only faculty can judge)
  needs_llm     - code cannot decide; the row still carries every signal it found

Rules are generic. In particular:
  * answer_form and spelling hits are signals, never settlements on their own.
    Spelling settles only when the student names the word and the check agrees; answer_form only
    when the student says the unit is missing and the check finds no unit in the stem (D-028).
  * a vague or junk comment is not `not_actionable` when checks found something:
    the verdict then depends on the checks, so it goes to the next tier.
  * a disagreement between the solution and the key never settles: code can see
    the mismatch but not which side is wrong.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .checks import DEFINITE, SIGNAL, Finding, ParsedQuestion, find_word_near, words
from .claims import Claim
from .loader import Report

CODE_SETTLED, CODE_ROUTED, NEEDS_LLM = "code_settled", "code_routed", "needs_llm"

# Which repairs a claim category is about (used for "unreported" findings and relevance).
CLAIM_REPAIRS = {
    "spelling": {"spelling"}, "markup": {"markup_leak"}, "exam_reference": {"exam_reference"},
    "figure": {"diagram"}, "type": {"type_mismatch"}, "option_identical": {"identical_options"},
    "option_missing": {"option_repair"}, "answer_form": {"answer_form"}, "stem_data": {"stem_data"},
    "solution": {"solution_fix", "solution_missing", "wrong_question", None},
    "answer": {"answer_key", "unsound", None}, "syllabus": {"syllabus"}, "wrong_chapter": {"wrong_chapter"},
    "display": {"option_repair", "markup_leak", "diagram"},
}


@dataclass
class Decision:
    outcome: str
    verdict: str = ""
    repair: str = ""
    route: str = ""
    basis: str = ""
    findings_used: list[str] = field(default_factory=list)


# "unit not mentioned", "no unit given", "unit nahi diya": the student says the unit is missing (D-028)
_UNIT_MISSING_CLAIM = re.compile(
    r"\bunits?\b.{0,40}?\b(?:not\s+(?:given|mentioned|stated|provided|specified|written)|missing|nahi|nhi|absent)\b"
    r"|\b(?:no|missing|without)\s+units?\b", re.I)


def _route(repair: str, taxonomy: dict) -> str:
    return "auto_apply" if taxonomy["repairs"][repair]["auto"] else "faculty_review"


def _by(findings: list[Finding], *checks: str, strength: str | None = None) -> list[Finding]:
    return [f for f in findings if f.check in checks and (strength is None or f.strength == strength)]


def _counted(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.strength in (DEFINITE, SIGNAL)]


def _summ(findings: list[Finding]) -> str:
    return "; ".join(f"{f.check}: {f.detail}" for f in findings)


def already_fixed(report: Report, claim: Claim, pq: ParsedQuestion) -> Decision | None:
    """Settles only when the student names the item, a faculty/history entry after the report
    mentions it, and the named item is gone from the live text."""
    later = [h for h in pq.q.error_history if h.at and h.at > report.reported_at]
    if not later or not claim.named_words:
        return None
    text_words = set(words(pq.all_text))
    for w in claim.named_words:
        wl = w.lower()
        hist = [h for h in later if re.search(rf"(?<![A-Za-z]){re.escape(wl)}(?![A-Za-z])", h.note.lower())]
        if hist and wl not in text_words:
            h = hist[0]
            return Decision(
                CODE_SETTLED, "already_fixed", "", "no_change",
                f"Student names '{w}'; history entry '{h.type}' by {h.actor} at {h.at} (after the report at "
                f"{report.reported_at}) mentions it, and '{w}' no longer appears in the live text.")
    return None


def spelling_agreement(claim: Claim, pq: ParsedQuestion, findings: list[Finding], vocab: Counter):
    """Return (field, text_word, named_word) if a named word and the check agree."""
    flagged = {f.data.get("word", "").lower(): f for f in _by(findings, "spelling_suspect", "run_together_words")}
    for w in claim.named_words:
        wl = w.lower()
        for fld, t, d in find_word_near(w, pq):
            tl = t.lower()
            if d == 0 and tl in flagged:
                return fld, t, w, f"the spelling check also flags '{t}' ({flagged[tl].detail})"
            if d > 0 and wl not in set(words(pq.all_text)) and vocab[tl] <= 1:
                return fld, t, w, (f"'{w}' is absent from the text and '{t}' ({d} edit(s) away) appears in no "
                                   "other question")
    return None


def decide(report: Report, claim: Claim, pq: ParsedQuestion, findings: list[Finding],
           vocab: Counter, taxonomy: dict) -> Decision:
    definite = [f for f in findings if f.strength == DEFINITE]
    counted = _counted(findings)
    cats = set(claim.categories)
    p = claim.primary

    fixed = already_fixed(report, claim, pq)
    if fixed:
        return fixed

    if claim.injection:
        return Decision(NEEDS_LLM, basis=(
            "Comment contains instruction-like text; it is treated as data, never followed. "
            "Whether the key is right needs an independent solve."
            + (f" Checks also found: {_summ(counted)}" if counted else "")),
            findings_used=[f.check for f in counted])

    if p in ("junk", "vague") or p == "unclear":
        if not counted and p == "junk":
            return Decision(CODE_SETTLED, "not_actionable", "", "no_change",
                            "Comment is unintelligible and no check found anything on the question.")
        if counted:
            return Decision(NEEDS_LLM, basis=(
                f"Comment is {p}, but checks found something, so the verdict depends on the checks: "
                + _summ(counted)), findings_used=[f.check for f in counted])
        return Decision(NEEDS_LLM, basis=(
            f"Comment is {p}; no rule finding. A blind solve is needed before calling it not_actionable "
            "(a wrong key is invisible to rule checks)."))

    if p == "language":
        if re.search("[ऀ-ॿ]", pq.question_text):
            return Decision(NEEDS_LLM, basis="Student asks for another language, but the question already contains Devanagari text.")
        return Decision(CODE_SETTLED, "language_mode", "", "no_change",
                        "Student asks for another language; the stored question is English-only.")

    if p == "app":
        return Decision(CODE_SETTLED, "app_issue", "", "no_change",
                        "Comment describes platform behaviour (recorded option / app), not the question content.")

    if p == "display":
        content = [f for f in definite if f.repair in CLAIM_REPAIRS["display"]]
        if content:
            return Decision(NEEDS_LLM, basis="Display complaint, but stored content is also defective: " + _summ(content),
                            findings_used=[f.check for f in content])
        return Decision(CODE_SETTLED, "display_issue", "", "no_change",
                        f"Display/loading complaint; stored content is complete ({len(pq.split.letters)} non-blank "
                        "options, no markup leak, no missing figure).")

    if p == "syllabus":
        return Decision(CODE_ROUTED, "defect", "syllabus", "faculty_review",
                        "Syllabus claims are faculty-only (auto: false); question stays live meanwhile.")

    if p == "wrong_chapter":
        return Decision(CODE_ROUTED, "defect", "wrong_chapter", "faculty_review",
                        f"Chapter claim against '{pq.q.subject} / {pq.q.chapter}'; wrong_chapter is faculty-only "
                        "(auto: false), so the route is fixed whatever an LLM says.")

    if p == "spelling":
        agree = spelling_agreement(claim, pq, findings, vocab)
        if agree:
            fld, t, w, why = agree
            return Decision(CODE_SETTLED, "defect", "spelling", _route("spelling", taxonomy),
                            f"Student names '{w}'; {fld} has '{t}'. Check agrees: {why}.",
                            findings_used=["spelling_named_word"])
        sp = [f for f in counted if f.repair == "spelling"]
        return Decision(NEEDS_LLM, basis=(
            "Spelling claim without a named word the check can confirm (signals only, never a settlement)"
            + (f": {_summ(sp)}" if sp else "; no spelling signal found.")),
            findings_used=[f.check for f in sp])

    if p == "markup":
        hits = [f for f in definite if f.repair == "markup_leak"]
        if hits:
            return Decision(CODE_SETTLED, "defect", "markup_leak", _route("markup_leak", taxonomy),
                            "Student reports raw code; check confirms: " + _summ(hits),
                            findings_used=[f.check for f in hits])
        return Decision(NEEDS_LLM, basis="Markup claim, but no raw LaTeX/HTML found in the stored text.")

    if p == "exam_reference":
        hits = _by(definite, "exam_reference")
        if hits:
            return Decision(CODE_SETTLED, "defect", "exam_reference", _route("exam_reference", taxonomy),
                            "Student reports an exam tag; check confirms: " + _summ(hits),
                            findings_used=["exam_reference"])
        return Decision(NEEDS_LLM, basis="Exam-reference claim, but no exam/year tag found in the stored text.")

    if p == "figure":
        hits = _by(definite, "figure_missing")
        if hits:
            return Decision(CODE_ROUTED, "defect", "diagram", "faculty_review",
                            "Stem refers to a figure and no image is stored; diagram repairs are faculty-only. "
                            + _summ(hits), findings_used=["figure_missing"])
        return Decision(NEEDS_LLM, basis="Figure claim, but the stem does not refer to a figure, or an image is stored.")

    if p == "type":
        hits = _by(findings, "mcq_single_answer")
        if hits:
            key = set(hits[0].data.get("normalized", []))
            if not claim.letters or set(claim.letters) == key:
                return Decision(CODE_SETTLED, "defect", "type_mismatch", _route("type_mismatch", taxonomy),
                                "Student says only one option is correct in a multiple-correct question; the stored "
                                "key agrees (" + _summ(hits) + ")", findings_used=["mcq_single_answer"])
        return Decision(NEEDS_LLM, basis="Question-type claim the key does not confirm.")

    if p == "option_identical":
        hits = _by(definite, "identical_options")
        if hits:
            dup = set(hits[0].data.get("letters", []))
            if not claim.letters or set(claim.letters) <= dup:
                return Decision(CODE_ROUTED, "defect", "identical_options", "faculty_review",
                                "Check confirms duplicate options; a new distractor is authored content (auto: false). "
                                + _summ(hits), findings_used=["identical_options"])
        return Decision(NEEDS_LLM, basis="Duplicate-option claim the check does not confirm.")

    if p == "option_missing":
        hits = _by(definite, "option_missing", "option_blank")
        if hits:
            keyed = any(h.data.get("missing_is_keyed") or h.data.get("blank_is_keyed") for h in hits)
            if keyed:
                return Decision(NEEDS_LLM, basis=(
                    "Check confirms a missing/blank option and it is the keyed answer, so the solution should state "
                    "its content; an LLM must extract it before an edit exists. " + _summ(hits)),
                    findings_used=[h.check for h in hits])
            return Decision(CODE_ROUTED, "defect", "option_repair", "faculty_review",
                            "Check confirms a missing/blank distractor; its content is not derivable from the key or "
                            "solution, so there is no source for the edit. " + _summ(hits),
                            findings_used=[h.check for h in hits])
        return Decision(NEEDS_LLM, basis="Missing-option claim, but all options are stored and non-blank (maybe display).")

    if p == "answer_form":
        hits = _by(findings, "unit_not_stated")
        # D-028: like spelling, claim + check settles it. The student must say the *unit* is missing (not
        # rounding or decimal places), and the check must confirm the stem states no unit while the solution
        # works in one.
        if hits and _UNIT_MISSING_CLAIM.search(report.comment or ""):
            return Decision(CODE_SETTLED, "defect", "answer_form", _route("answer_form", taxonomy),
                            "Student says the unit is missing; check agrees: " + _summ(hits),
                            findings_used=["unit_not_stated"])
        return Decision(NEEDS_LLM, basis=(
            "answer_form claim; the unit check is a signal, not a settlement"
            + (f": {_summ(hits)}" if hits else " and it found nothing.")), findings_used=[h.check for h in hits])

    if p in ("stem_data", "solution"):
        rel = [f for f in findings if f.repair in CLAIM_REPAIRS[p] or f.check.startswith("solution")]
        strong = _counted(rel)
        weak = [f for f in rel if f not in strong]
        return Decision(NEEDS_LLM, basis=(
            f"{p} claim; needs reading the solution against the stem. Signals: "
            + (_summ(strong) if strong else "none")
            + (f". Weak hints: {_summ(weak)}" if weak else "")), findings_used=[f.check for f in rel])

    if p == "answer":
        bad = _by(definite, "answer_malformed")
        if bad:
            norm = set(bad[0].data.get("normalized", []))
            if norm and set(claim.letters) == norm and not claim.values:
                return Decision(CODE_SETTLED, "defect", "answer_key", _route("answer_key", taxonomy),
                                "Stored key is malformed and its normalised form equals the student's answer: "
                                + _summ(bad), findings_used=["answer_malformed"])
        sk = [f for f in counted if f.check.startswith("solution")]
        return Decision(NEEDS_LLM, basis=(
            "Answer dispute; code never settles answer values (it can see a solution/key mismatch but not which "
            "side is wrong)." + (f" Signals: {_summ(sk)}" if sk else "")),
            findings_used=[f.check for f in sk])

    return Decision(NEEDS_LLM, basis=f"No rule for claim category '{p}'.")


def unreported(findings: list[Finding], claims: list[Claim]) -> list[Finding]:
    """Definite/signal findings that no report on the question is about."""
    covered: set = set()
    for c in claims:
        for cat in c.categories:
            covered |= CLAIM_REPAIRS.get(cat, set())
    return [f for f in _counted(findings) if f.repair not in covered]
