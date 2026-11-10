"""Data profiler: run the code-only tier over every report and write what it can and cannot settle.

    python -m engine.profile

Writes:
  logs/profile/reports.csv    one row per report: claim, outcome, verdict/repair/route if decided, signals
  logs/profile/questions.csv  one row per question: parse results, findings, unreported_findings flag
  logs/profile/summary.md     counts and the unreported findings list

No LLM calls. Reads only data/; the hand labels are read only by eval/.
"""
from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter, defaultdict

from .checks import DEFINITE, SIGNAL, WEAK, build_vocab, parse_question, run_checks
from .claims import classify
from .loader import ROOT, load_questions, load_reports, load_taxonomy
from .verify import CODE_ROUTED, CODE_SETTLED, NEEDS_LLM, decide, unreported

OUT_DIR = ROOT / "logs" / "profile"


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def run() -> dict:
    t0 = time.perf_counter()
    taxonomy = load_taxonomy()
    questions = load_questions()
    reports = sorted(load_reports(), key=lambda r: r.report_id)

    parsed = {qid: parse_question(q) for qid, q in questions.items()}
    vocab = build_vocab(list(parsed.values()))
    findings = {qid: run_checks(pq, vocab) for qid, pq in parsed.items()}

    by_q = defaultdict(list)
    rows = []
    for r in reports:
        pq = parsed.get(r.question_id)
        claim = classify(r.comment)
        if pq is None:
            rows.append({"reportId": r.report_id, "questionId": r.question_id, "comment": r.comment,
                         "claim_primary": claim.primary, "outcome": "needs_llm",
                         "basis": "questionId not found in questions.json"})
            continue
        by_q[r.question_id].append(claim)
        fs = findings[r.question_id]
        d = decide(r, claim, pq, fs, vocab, taxonomy)
        rows.append({
            "reportId": r.report_id,
            "questionId": r.question_id,
            "comment": r.comment,
            "claim_primary": claim.primary,
            "claim_categories": "|".join(claim.categories),
            "claim_detail": _j({k: v for k, v in claim.as_dict().items()
                                if k not in ("primary", "categories") and v}),
            "injection": int(claim.injection),
            "hinglish": int(claim.hinglish),
            "duplicates_on_question": sum(1 for x in reports if x.question_id == r.question_id),
            "outcome": d.outcome,
            "verdict": d.verdict,
            "repair": d.repair,
            "route": d.route,
            "basis": d.basis,
            "definite_findings": "|".join(sorted({f.check for f in fs if f.strength == DEFINITE})),
            "signals": "|".join(sorted({f.check for f in fs if f.strength == SIGNAL})),
            "weak_signals": "|".join(sorted({f.check for f in fs if f.strength == WEAK})),
        })

    qrows = []
    unreported_all = []
    for qid, pq in parsed.items():
        fs = findings[qid]
        un = unreported(fs, by_q.get(qid, []))
        unreported_all += [(qid, f) for f in un]
        q = pq.q
        qrows.append({
            "questionId": qid,
            "type": q.qtype,
            "subject": q.subject,
            "chapter": q.chapter,
            "report_count": len(by_q.get(qid, [])),
            "option_letters": "".join(pq.split.letters),
            "blank_options": "".join(L for L in pq.split.letters if not pq.split.options_text[L]),
            "answer_raw": _j(q.answer_raw),
            "answer_normalized": "|".join(pq.answer.values),
            "answer_flags": "|".join(pq.answer.flags),
            "math_blocks_stem": len(re.findall(r"<math\b", q.question_html)),
            "math_blocks_solution": len(re.findall(r"<math\b", q.solution_html)),
            "has_images": int(bool(q.ques_images or q.solution_images)),
            "error_history": _j([h.__dict__ for h in q.error_history]) if q.error_history else "",
            "definite_findings": "|".join(f.check for f in fs if f.strength == DEFINITE),
            "signals": "|".join(f.check for f in fs if f.strength == SIGNAL),
            "unreported_findings": int(bool(un)),
            "unreported_detail": "; ".join(f"{f.check}: {f.detail}" for f in un),
            "findings_json": _j([f.as_dict() for f in fs if f.strength != WEAK]),
            "weak_json": _j([f.as_dict() for f in fs if f.strength == WEAK]),
            "stem_text": pq.split.stem_text,
            "options_text": _j(pq.split.options_text),
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(OUT_DIR / "reports.csv", rows)
    _write_csv(OUT_DIR / "questions.csv", qrows)
    summary = _summary(rows, qrows, unreported_all, time.perf_counter() - t0)
    (OUT_DIR / "summary.md").write_text(summary, encoding="utf-8")
    return {"reports": rows, "questions": qrows}


def _write_csv(path, rows):
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _summary(rows, qrows, unreported_all, secs) -> str:
    oc = Counter(r["outcome"] for r in rows)
    by_cat = defaultdict(Counter)
    for r in rows:
        by_cat[r["claim_primary"]][r["outcome"]] += 1
    lines = [
        "# Profiler summary",
        "",
        "Generated by `python -m engine.profile` (code-only tier, no LLM calls). "
        "Counts are only counts until compared with the hand labels by `python -m eval.evaluate_profile`.",
        "",
        f"- Reports: {len(rows)} on {len({r['questionId'] for r in rows})} questions "
        f"({len(qrows)} questions in data; {sum(1 for q in qrows if not q['report_count'])} unreported)",
        f"- Run time: {secs:.2f}s",
        "",
        "## Outcomes",
        "",
        "| Outcome | Reports |",
        "|---|---|",
    ]
    for k in (CODE_SETTLED, CODE_ROUTED, NEEDS_LLM):
        lines.append(f"| `{k}` | {oc.get(k, 0)} |")
    lines += ["", "## By claim category", "", "| Claim | settled | routed | needs_llm |", "|---|---|---|---|"]
    for cat in sorted(by_cat):
        c = by_cat[cat]
        lines.append(f"| {cat} | {c.get(CODE_SETTLED, 0)} | {c.get(CODE_ROUTED, 0)} | {c.get(NEEDS_LLM, 0)} |")
    lines += ["", "## Per report", "", "| Report | Claim | Outcome | Verdict | Repair | Route |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['reportId']} | {r['claim_primary']} | {r['outcome']} | {r.get('verdict', '')} | "
                     f"{r.get('repair', '')} | {r.get('route', '')} |")
    lines += ["", "## Findings no report is about", "",
              "Definite findings and signals on a question that none of its reports' claims cover "
              "(bonus candidates; signals are not confirmed defects).", "",
              "| Question | Strength | Check | Detail |", "|---|---|---|---|"]
    for qid, f in unreported_all:
        lines.append(f"| `{qid[:8]}` | {f.strength} | {f.check} | {f.detail.replace('|', '/')} |")
    lines += ["", "## Parse stats", ""]
    lines.append(f"- Option counts: {dict(Counter(len(q['option_letters']) for q in qrows if q['type'] != 'integerQuestion'))}")
    lines.append(f"- Malformed / flagged answers: {sum(1 for q in qrows if q['answer_flags'])}")
    lines.append(f"- Questions with MathML: {sum(1 for q in qrows if q['math_blocks_stem'] or q['math_blocks_solution'])}")
    lines.append(f"- Questions with images: {sum(q['has_images'] for q in qrows)}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    out = run()
    oc = Counter(r["outcome"] for r in out["reports"])
    print(f"wrote {OUT_DIR}: " + ", ".join(f"{k}={oc.get(k, 0)}" for k in (CODE_SETTLED, CODE_ROUTED, NEEDS_LLM)))
