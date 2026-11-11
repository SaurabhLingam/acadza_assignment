"""Question-level findings that no report covers -> bonus_findings.json.

    python -m engine.bonus            # reads results.json (the main run), writes bonus_findings.json

A finding is a bonus when it is a definite finding or a signal (not weak) and:
  - none of the question's reports makes a claim about that repair (verify.unreported), and
  - no edit in results.json already fixes it (e.g. R-report on a vague comment fixed one of two typos).
That includes leftovers on reported questions, and findings on questions nobody reported.

could_auto_apply uses the D-023 bar with no report to lean on: the repair is auto in the taxonomy and
low-risk, the finding is definite (a signal is not a settlement, D-007), and a code-built edit passes the
D-004 guards. High-stakes repairs need two independent sources, which an unreported finding does not have.
Everything else is listed for a confirm (model or faculty) with the reason it cannot auto-apply.
Generic rules only (D-010).
"""
from __future__ import annotations

import json

from . import config
from .checks import DEFINITE, build_vocab, find_word_near, parse_question, run_checks
from .claims import classify
from .edits import code_edit, field_raw, guard, public_edit
from .loader import ROOT, load_questions, load_reports, load_taxonomy
from .parse import locate_raw
from .verify import unreported

OUT = ROOT / "bonus_findings.json"


def _fixed_by(f, qid: str, results: list[dict]) -> str | None:
    """reportId of a result whose edit already covers this finding's raw evidence, if any."""
    for r in results:
        e = r.get("edit") or {}
        if r["questionId"] == qid and e.get("field") == f.field and f.evidence_raw and \
                isinstance(e.get("find"), str) and f.evidence_raw.strip() in e["find"]:
            return r["reportId"]
    return None


def _occurrences(pq, words: list[str]) -> list[dict]:
    """Every field occurrence of each word (exact clean text and raw substring), for spelling pairs where
    code cannot tell which side is the misspelling."""
    out = []
    for w in words:
        for fld, t, d in find_word_near(w, pq, cap=0):
            raw, uniq = locate_raw(field_raw(pq, fld), t, whole_word=True)
            out.append({"field": fld, "text": t, "raw": raw, "raw_unique": uniq})
    return out


def _edit(f, pq) -> tuple[dict | None, str]:
    """A code-built edit for the finding, or (None, why not)."""
    if f.check == "run_together_words" and f.evidence_raw_unique:
        a = f.data["suggest"].split(" ", 1)[0]
        raw = f.evidence_raw
        if raw.lower().startswith(a.lower()):
            return {"field": f.field, "find": raw, "replace": raw[:len(a)] + " " + raw[len(a):]}, \
                "code: split run-together words"
        return None, "run-together words not split at the raw start"
    if f.check == "spelling_suspect":
        if "differ by one edit" in f.detail:
            return None, "two spellings of one word appear the same number of times; code cannot tell which " \
                         "is the misspelling"
        return None, "code suggests a nearby word, but both may be real words; needs a confirm"
    return code_edit(f.repair, pq, [f])


def _auto(f, edit, fails, taxonomy) -> tuple[bool, str]:
    rep = taxonomy["repairs"].get(f.repair or "", {})
    if not rep.get("auto"):
        return False, f"{f.repair} is faculty-only in the taxonomy"
    if f.repair not in config.LOW_RISK_REPAIRS:
        return False, f"{f.repair} is high-stakes (D-023/D-024): needs two independent sources"
    if f.strength != DEFINITE:
        return False, "signal only: low-risk, but needs one confirm (model or faculty) before it can auto-apply"
    if edit is None:
        return False, "definite and low-risk, but code builds no edit for this check yet"
    if fails:
        return False, "code-built edit fails guards: " + "; ".join(fails)
    return True, "definite, low-risk (D-023), code-built edit passes the guards"


def run() -> list[dict]:
    taxonomy = load_taxonomy()
    questions = load_questions()
    reports = load_reports()
    results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    parsed = {qid: parse_question(q) for qid, q in questions.items()}
    vocab = build_vocab(list(parsed.values()))
    by_q: dict[str, list] = {}
    for r in reports:
        by_q.setdefault(r.question_id, []).append(r)

    out = []
    for qid, pq in parsed.items():
        reps = by_q.get(qid, [])
        for f in unreported(run_checks(pq, vocab), [classify(r.comment) for r in reps]):
            if _fixed_by(f, qid, results):
                continue
            edit, how = _edit(f, pq)
            fails = guard(edit, f.repair, pq, taxonomy) if edit else []
            ok, why = _auto(f, edit, fails, taxonomy)
            row = {
                "questionId": qid,
                "repair": f.repair,
                "check": f.check,
                "strength": f.strength,
                "field": f.field,
                "detail": f.detail,
                "evidence_text": f.evidence_text,
                "evidence_raw": f.evidence_raw,
                "evidence_raw_unique": f.evidence_raw_unique,
                "reports_on_question": [r.report_id for r in reps],
                "proposed_edit": public_edit(edit) if edit and not fails else None,
                "edit_how": how,
                "could_auto_apply": ok,
                "why": why,
            }
            if f.check == "spelling_suspect":
                row["occurrences"] = _occurrences(pq, [f.data["word"], f.data["suggest"]])
            out.append(row)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    rows = run()
    print(f"wrote {OUT.name}: {len(rows)} findings, {sum(r['could_auto_apply'] for r in rows)} could auto-apply")
    for r in rows:
        print(f"  {r['questionId'][:8]} {r['repair']:<12} {r['check']:<22} {r['strength']:<8} "
              f"auto={r['could_auto_apply']!s:<5} {r['evidence_text']!r}")
