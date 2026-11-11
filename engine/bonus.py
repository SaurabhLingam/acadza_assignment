"""Question-level findings that no report covers -> bonus_findings.json.

    python -m engine.bonus            # reads results.json (the main run), writes bonus_findings.json

A code finding is a bonus when it is a definite finding or a signal (not weak) and no report's outcome
covers it:
  - per-occurrence text fixes (spelling, noise, markup_leak) are covered only by a results.json edit that
    fixed that span (for a spelling pair, either spelling): a report naming one typo leaves the others;
  - any other repair is covered when a report on the question claims it (verify.unreported) or a result on
    the question has that repair.
That includes leftovers on reported questions, and findings on questions nobody reported.

docs/bonus-review.json is the human review layer: `add` holds findings the checks miss (each one's
evidence_raw must occur in the stored field, or this fails), `dismiss` drops false positives (each must
match a code finding, or this fails). Every row says where it came from (`source`, `found_by`).

could_auto_apply uses the D-023 bar with no report to lean on: the repair is auto in the taxonomy and
low-risk, the finding is definite (a signal is not a settlement, D-007), and a code-built edit passes the
D-004 guards. High-stakes repairs (D-023, D-024) need two independent sources, which an unreported finding
does not have. Everything else is listed for a confirm (model or faculty) with the reason.
Generic rules only (D-010): question ids live in the review file, never in this code.
"""
from __future__ import annotations

import json

from . import config
from .checks import DEFINITE, SIGNAL, build_vocab, find_word_near, parse_question, run_checks
from .claims import classify
from .edits import code_edit, field_raw, guard, public_edit
from .loader import ROOT, load_questions, load_reports, load_taxonomy
from .parse import locate_raw
from .verify import unreported

OUT = ROOT / "bonus_findings.json"
REVIEW = ROOT / "docs" / "bonus-review.json"
PER_OCCURRENCE = {"spelling", "noise", "markup_leak"}


def _fixed_by(f, qid: str, results: list[dict]) -> str | None:
    """reportId of a result whose edit already covers this finding's raw evidence (or, for a spelling pair,
    the other spelling), if any."""
    own = (f.evidence_raw or "").strip()
    pair = ((f.data or {}).get("suggest") or "").strip().lower() if f.check == "spelling_suspect" else ""
    for r in results:
        e = r.get("edit") or {}
        if r["questionId"] != qid or not isinstance(e.get("find"), str):
            continue
        if (own and e.get("field") == f.field and own in e["find"]) or \
                (pair and pair in e["find"].lower()):     # the other spelling, in any field
            return r["reportId"]
    return None


def _covered(f, qid: str, claims: list, results: list[dict]) -> bool:
    if _fixed_by(f, qid, results):
        return True
    if f.repair in PER_OCCURRENCE:
        return False
    return not unreported([f], claims) or any(r["questionId"] == qid and r["repair"] == f.repair
                                              for r in results)


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


def _manual(m: dict, pq, taxonomy) -> dict:
    """A reviewed finding from docs/bonus-review.json, checked against the stored record."""
    qid, fld = m["questionId"], m["field"]
    raw = pq.q.chapter if fld == "chapter" else field_raw(pq, fld)
    n = (raw or "").count(m["evidence_raw"])
    if not n:
        raise SystemExit(f"bonus-review: evidence_raw for {qid} not found in stored {fld}: {m['evidence_raw']!r}")
    edit, fails = None, []
    if "proposed_replace" in m:
        edit = {"field": fld, "find": m["evidence_raw"], "replace": m["proposed_replace"]}
        fails = guard(edit, m["repair"], pq, taxonomy)
    rep = taxonomy["repairs"].get(m["repair"], {})
    if not rep.get("auto"):
        why = f"{m['repair']} is faculty-only in the taxonomy"
    elif m["repair"] not in config.LOW_RISK_REPAIRS:
        why = f"{m['repair']} is high-stakes (D-023/D-024): needs two independent sources"
    else:
        why = "low-risk, but no code check supports it (D-023); human-found, so apply as a faculty-approved edit"
    if fails:
        why += "; proposed edit fails guards: " + "; ".join(fails)
    return {
        "questionId": qid, "repair": m["repair"], "check": "manual_review", "strength": "manual",
        "field": fld, "detail": m["detail"], "evidence_text": m["evidence_text"],
        "evidence_raw": m["evidence_raw"], "evidence_raw_unique": n == 1, "evidence_raw_count": n,
        "proposed_edit": public_edit(edit) if edit and not fails else None,
        "edit_how": "manual review" if edit else "no single edit",
        "could_auto_apply": False, "why": why,
    }


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
    review = json.loads(REVIEW.read_text(encoding="utf-8")) if REVIEW.exists() else {"add": [], "dismiss": []}
    dismiss = {(d["questionId"], d["check"], d["evidence_text"]): d["reason"] for d in review["dismiss"]}
    used = set()

    out = []
    for qid, pq in parsed.items():
        reps = by_q.get(qid, [])
        claims = [classify(r.comment) for r in reps]
        for f in run_checks(pq, vocab):
            if f.strength not in (DEFINITE, SIGNAL) or _covered(f, qid, claims, results):
                continue
            if (k := (qid, f.check, f.evidence_text)) in dismiss:
                used.add(k)
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
                "source": "code_check",
                "proposed_edit": public_edit(edit) if edit and not fails else None,
                "edit_how": how,
                "could_auto_apply": ok,
                "why": why,
            }
            if f.check == "spelling_suspect":
                row["occurrences"] = _occurrences(pq, [f.data["word"], f.data["suggest"]])
            out.append(row)
    if unused := set(dismiss) - used:
        raise SystemExit(f"bonus-review: dismissals that match no code finding: {sorted(unused)}")
    for m in review["add"]:
        row = _manual(m, parsed[m["questionId"]], taxonomy)
        row["reports_on_question"] = [r.report_id for r in by_q.get(m["questionId"], [])]
        row["source"], row["found_by"] = "manual_review", m["found_by"]
        out.append(row)
    out.sort(key=lambda r: (r["questionId"], r["source"] != "code_check"))
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    rows = run()
    print(f"wrote {OUT.name}: {len(rows)} findings ({sum(r['source'] == 'manual_review' for r in rows)} manual), "
          f"{sum(r['could_auto_apply'] for r in rows)} could auto-apply")
    for r in rows:
        print(f"  {r['questionId'][:8]} {r['repair']:<13} {r['check']:<22} {r['strength']:<8} "
              f"auto={r['could_auto_apply']!s:<5} edit={'y' if r['proposed_edit'] else '-'} {r['evidence_text']!r}")
