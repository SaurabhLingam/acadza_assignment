"""Bake everything the faculty console shows into console/public/data.json.

    python console/scripts/build_data.py        # run from the repo root

Reads data/questions.json, data/reports.json, results.json, the evidence for that run
(logs/runs/<run>/details.jsonl, located via logs/run-summary.json) and bonus_findings.json.
Applies each edit to the stored HTML so the console shows before/after without computing anything,
and works out headline, evidence chips and urgency in one place (here), not in the browser.
No LLM calls, no API keys. Never reads docs/eval-labels.csv.
"""
from __future__ import annotations

import html
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine import config  # noqa: E402
from engine.checks import build_vocab, parse_question, run_checks  # noqa: E402
from engine.loader import load_questions, load_reports  # noqa: E402
from engine.parse import html_to_text  # noqa: E402

OUT = ROOT / "console" / "public" / "data.json"

# Harm: does the defect stop a student getting the right answer?
HARM_BLOCKS = {"answer_key", "stem_data", "unsound", "type_mismatch", "diagram", "wrong_question"}
HARM_MIDDLE = {"solution_fix", "solution_missing", "identical_options", "option_repair"}
HARM_LABEL = {3: "Blocks the right answer", 2: "Wrong solution or options", 1: "Cosmetic", 0: "No defect"}

VERDICT_HEAD = {
    "no_error": "No error", "display_issue": "Display issue, stored content is fine",
    "app_issue": "App issue, not this question", "language_mode": "Language request",
    "already_fixed": "Already fixed in the live record", "not_actionable": "Comment not actionable",
}
REPAIR_HEAD = {
    "unsound": "No correct option as written", "diagram": "Figure missing or wrong",
    "wrong_chapter": "Filed under the wrong chapter", "syllabus": "Outside the syllabus (student claim)",
    "identical_options": "Two options are identical", "wrong_question": "Solution belongs to another question",
    "solution_fix": "Solution has an error", "solution_missing": "Solution missing",
    "option_repair": "An option is missing or blank", "stem_data": "Question is missing data",
    "answer_form": "Answer form not stated", "spelling": "Spelling", "markup_leak": "Raw markup visible",
    "exam_reference": "Exam tag in the question", "noise": "Stray text", "notation": "Notation",
    "type_mismatch": "Wrong question type", "answer_key": "Answer key wrong",
}
MODEL_NAME = {"openai/gpt-oss-120b": "gpt-oss-120b", "openai/gpt-oss-20b": "gpt-oss-20b",
              "deepseek/deepseek-v4-flash": "DeepSeek"}


def clip(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# --------------------------------------------------------------------------- edits -> before/after HTML

def _in_math(raw: str, i: int) -> tuple[int, int] | None:
    """Bounds of the <math> element containing position i, if any."""
    s = raw.rfind("<math", 0, i + 1)
    if s < 0 or raw.rfind("</math>", 0, i) > s:
        return None
    e = raw.find("</math>", i)
    return (s, e + len("</math>")) if e >= 0 else None


def _whole_elements(seg: str) -> bool:
    """True if seg is a sequence of complete elements (balanced tags, no stray text at the edges),
    so it can be wrapped in an <mrow> without breaking the MathML tree."""
    seg = seg.strip()
    if not (seg.startswith("<") and seg.endswith(">")) or seg.startswith("</"):
        return False
    depth = 0
    for t in re.finditer(r"<(/?)([a-zA-Z][\w:-]*)[^>]*?(/?)>", seg):
        if t.group(3):
            continue
        depth += -1 if t.group(1) else 1
        if depth < 0:
            return False
    return depth == 0


def mark(raw: str, i: int, n: int, new: str | None, cls: str) -> str:
    """raw with raw[i:i+n] replaced by `new` (None = keep) and the change highlighted.
    Inside MathML the whole <math> element is wrapped (an HTML tag inside MathML would not render);
    elsewhere <u>/<s> are used because the HTML parser repairs them across tag boundaries."""
    seg = raw[i:i + n] if new is None else new
    out = raw[:i] + seg + raw[i + n:]
    m = _in_math(out, i)
    if m and _whole_elements(seg):
        return out[:i] + f'<mrow class="{cls} chg-mrow">' + seg + "</mrow>" + out[i + len(seg):]
    if m:
        s, e = m
        return out[:s] + f'<span class="{cls} chg-math">' + out[s:e] + "</span>" + out[e:]
    tag = "s" if cls == "chg-del" else "u"
    if not seg.strip():
        return out[:i] + f'<{tag} class="{cls} chg-empty"></{tag}>' + out[i:]
    return out[:i] + f'<{tag} class="{cls}">' + seg + f"</{tag}>" + out[i + len(seg):]


def field_html(q, fld: str) -> str:
    return q.solution_html if fld == "solution" else q.question_html


def before_after(q, edit: dict | None) -> dict | None:
    if not edit or edit.get("field") not in ("question", "solution"):
        return None
    raw = field_html(q, edit["field"])
    i = raw.find(edit["find"])
    if i < 0:
        return {"field": edit["field"], "error": "find not located in the stored field"}
    n = len(edit["find"])
    return {
        "field": edit["field"],
        "before": mark(raw, i, n, None, "chg-del"),
        "after": mark(raw, i, n, edit["replace"], "chg-ins"),
        "find_text": html_to_text(edit["find"]),
        "replace_text": html_to_text(edit["replace"]),
    }


def flagged(q, fld: str, ev: str | None) -> dict | None:
    """Highlight a bonus finding's evidence in place (no edit)."""
    if fld not in ("question", "solution") or not ev:
        return None
    raw = field_html(q, fld)
    i = raw.find(ev)
    return None if i < 0 else {"field": fld, "flagged": mark(raw, i, len(ev), None, "chg-flag")}


# --------------------------------------------------------------------------- answers

def letters_of(x) -> list[str]:
    if isinstance(x, list):
        x = ",".join(map(str, x))
    return sorted({p.strip().upper() for p in str(x or "").replace(" ", ",").split(",") if p.strip()})


def show_answer(pq, value) -> dict:
    """{'short': 'C', 'long': 'C (130 V)'} for an answer value."""
    if pq.q.qtype == "integerQuestion":
        v = str(value[0] if isinstance(value, list) and value else value)
        return {"short": v, "long": v}
    ls = letters_of(value)
    opt = pq.split.options_text
    if ls and all(L in opt for L in ls):
        return {"short": ", ".join(ls),
                "long": ", ".join(f"{L} ({clip(opt[L], 28) or 'blank'})" for L in ls)}
    return {"short": json.dumps(value, ensure_ascii=False), "long": json.dumps(value, ensure_ascii=False)}


def key_letters(pq) -> list[str]:
    return list(pq.answer.values)


# --------------------------------------------------------------------------- headline, chips, urgency

def harm_of(verdict: str, repair: str | None, pq, findings) -> int:
    if verdict != "defect":
        return 0
    if repair == "option_repair":
        lets = {f.data.get("letter") for f in findings if f.repair == "option_repair" and f.data}
        return 3 if lets & set(key_letters(pq)) else 2
    if repair in HARM_BLOCKS:
        return 3
    if repair in HARM_MIDDLE:
        return 2
    return 1


def certainty(res: dict, det: dict) -> tuple[str, str]:
    """(short phrase, tone) for how sure the evidence is."""
    if det.get("injection_blocks_auto_apply"):
        return "injection attempt flagged", "bad"
    if det.get("triage_contradicts"):
        return "model disagrees with the checks", "bad"
    t0 = (det.get("tier0") or {}).get("outcome")
    if det.get("against", 0) > 0:
        return "sources disagree", "warn"
    if det.get("decided_by") == "triage":
        return "model judgement, one code check", "warn"
    if t0 in ("code_settled", "code_routed") and det.get("settled_tier") == 0:
        return "decided by a code check", "ok"
    if det.get("agree", 0) >= 2:
        return "all sources agree", "ok"
    return "limited evidence", "warn"


def headline(res: dict, pq, ba: dict | None) -> str:
    v, rep, e = res["verdict"], res["repair"], res.get("edit") or {}
    if v != "defect":
        h = VERDICT_HEAD.get(v, v)
        if v == "no_error" and key_letters(pq):
            h += f": key {show_answer(pq, pq.q.answer_raw)['short']} confirmed"
        return h
    if rep == "answer_key" and e.get("field") == "answer":
        a, b = show_answer(pq, e["find"]), show_answer(pq, e["replace"])
        if letters_of(e["find"]) == letters_of(e["replace"]):
            return f"Answer key format fixed: {json.dumps(e['find'], ensure_ascii=False)} → {b['short']}"
        return f"Answer key {a['short']} → {b['short']}"
    if rep == "type_mismatch" and e.get("field") == "questionType":
        return f"Question type {e['find']} → {e['replace']}"
    if ba and "find_text" in ba:
        f, r = ba["find_text"].strip(), ba["replace_text"].strip()
        if r.startswith(f) and len(r) > len(f):
            return f"{REPAIR_HEAD.get(rep, rep)}: added “{clip(r[len(f):].strip(), 40)}”"
        if not r:
            return f"{REPAIR_HEAD.get(rep, rep)}: removed “{clip(f, 40)}”"
        return f"{REPAIR_HEAD.get(rep, rep)}: “{clip(f, 30)}” → “{clip(r, 30)}”"
    return REPAIR_HEAD.get(rep, rep or "Defect")


def _model(role_or_model: str) -> str:
    m = config.ROLES.get(role_or_model, (None, role_or_model))[1]
    return MODEL_NAME.get(m, m.split("/")[-1])


def chips(res: dict, det: dict, pq) -> list[dict]:
    """Evidence chips: tone ok = supports the decision, bad = against it / the defect, neutral = no answer."""
    out = []
    e = res.get("edit") or {}
    target = None
    if e.get("field") == "answer":
        target = letters_of(e["replace"]) if pq.has_options else [str(e["replace"])]
    elif res["verdict"] == "no_error" or det.get("key_status") == "key_ok":
        target = key_letters(pq)
    is_int = pq.q.qtype == "integerQuestion"

    def agrees(letters, value):
        if not target:
            return None
        if is_int:
            try:
                return value is not None and math.isclose(float(value), float(target[0]),
                                                          rel_tol=config.INTEGER_REL_TOL,
                                                          abs_tol=config.INTEGER_ABS_TOL)
            except (TypeError, ValueError):
                return None
        return sorted(letters or []) == sorted(target) if letters else None

    for sv in det.get("solvers") or []:
        name = _model(sv["role"])
        if not sv.get("ok"):
            out.append({"tone": "neutral", "label": f"{name} → no answer"})
            continue
        if sv.get("missing"):
            out.append({"tone": "warn", "label": f"{name} → needs data", "title": sv["missing"]})
            continue
        val = f"{sv['value']:g} {sv.get('unit') or ''}".strip() if sv.get("value") is not None else ""
        shown = "".join(sv.get("letters") or []) or val or "?"
        if sv.get("letters") and val and not is_int:
            shown = f"{''.join(sv['letters'])} ({clip(val, 14)})"
        a = agrees(sv.get("letters"), sv.get("value"))
        out.append({"tone": "neutral" if a is None else ("ok" if a else "bad"), "label": f"{name} → {shown}",
                    "title": clip(sv.get("working") or "", 300)})
    ex = det.get("extract") or {}
    if ex.get("ok") and ex.get("shown"):
        lets = [x for x in (ex.get("letters") or []) if x and x != "?"]
        a = agrees(lets, ex.get("value"))
        out.append({"tone": "neutral" if a is None else ("ok" if a else "bad"),
                    "label": f"stored solution → {clip(ex['shown'], 22)}", "title": clip(ex.get("statement", ""), 300)})
    for cand, vs in (det.get("option_checks") or {}).items():
        for v in vs:
            lab = f"({cand})" if not is_int else ("key value" if cand == "key" else cand[1:])
            verdict = v.get("verdict")
            if verdict == "cannot_tell":
                tone = "neutral"
            elif res["repair"] == "unsound":
                tone = "ok" if verdict == "incorrect" else "bad"     # every option incorrect is the finding
            elif target is None:
                tone = "neutral"
            else:
                if not is_int:
                    is_target = cand in target
                else:
                    vc = (det.get("value_candidates") or {}).get(cand)
                    v_cand = pq.answer.values[0] if cand == "key" and pq.answer.values else (vc[0] if vc else None)
                    is_target = agrees(None, v_cand) is True
                tone = "ok" if (verdict == "correct") == is_target else "bad"
            out.append({"tone": tone, "label": f"{_model(v['role'])} check {lab}: {verdict}",
                        "title": clip(v.get("reason") or "", 300)})
    if e.get("field") == "answer" and pq.has_options:
        out.append({"tone": "bad", "label": f"key says {show_answer(pq, e['find'])['short']}"})
    tr = det.get("triage") or {}
    if tr.get("verdict"):
        same = tr.get("verdict") == res["verdict"] and (tr.get("repair") or None) == (res["repair"] or None)
        out.append({"tone": "ok" if same else "bad",
                    "label": f"triage → {tr['verdict']}{'/' + tr['repair'] if tr.get('repair') else ''}",
                    "title": clip(tr.get("evidence") or "", 300)})
    t0 = det.get("tier0") or {}
    if t0.get("outcome") in ("code_settled", "code_routed"):
        out.append({"tone": "ok", "label": "code check settled it", "title": clip(t0.get("basis", ""), 300)})
    if det.get("injection_regex") or (det.get("guard") or {}).get("flag"):
        out.append({"tone": "bad", "label": "injection attempt flagged",
                    "title": f"prompt-guard score {(det.get('guard') or {}).get('score', 0):.3f}; "
                             f"regex {'yes' if det.get('injection_regex') else 'no'}"})
    return out


# --------------------------------------------------------------------------- build

def main():
    summary = json.loads((ROOT / "logs" / "run-summary.json").read_text(encoding="utf-8"))
    run_dir = (ROOT / summary["results_file"]).parent
    results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    run_results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    if run_results != results:
        raise SystemExit(f"results.json does not match {run_dir.name}/results.json; evidence would not line up")
    details = {d["reportId"]: d for d in
               (json.loads(x) for x in (run_dir / "details.jsonl").read_text(encoding="utf-8").splitlines() if x)}
    bonus = json.loads((ROOT / "bonus_findings.json").read_text(encoding="utf-8"))
    qs = load_questions()
    reports = {r.report_id: r for r in load_reports()}
    parsed = {k: parse_question(q) for k, q in qs.items()}
    vocab = build_vocab(list(parsed.values()))
    findings = {k: run_checks(pq, vocab) for k, pq in parsed.items()}

    reach = {}
    for r in reports.values():
        reach.setdefault(r.question_id, set()).add(r.student_id)

    cases = []
    for res in results:
        qid, rid = res["questionId"], res["reportId"]
        pq, det, rep = parsed[qid], details.get(rid, {}), reports[rid]
        ba = before_after(pq.q, res.get("edit"))
        e = res.get("edit") or {}
        h = harm_of(res["verdict"], res["repair"], pq, findings[qid])
        cert, cert_tone = certainty(res, det)
        n = len(reach.get(qid, ()))
        det_trim = {k: v for k, v in det.items() if k not in ("solver_raw",)}
        cases.append({
            "reportId": rid, "questionId": qid, "studentId": rep.student_id,
            "source": getattr(rep, "source", ""), "reportedAt": getattr(rep, "reported_at", ""),
            "comment": rep.comment,
            "verdict": res["verdict"], "repair": res["repair"], "route": res["route"],
            "confidence": res["confidence"], "edit": res.get("edit"), "evidence": res["evidence"],
            "reply": res["student_reply"],
            "headline": headline(res, pq, ba), "harm": h, "harmLabel": HARM_LABEL[h],
            "certainty": cert, "certaintyTone": cert_tone, "reach": n,
            "why": f"{HARM_LABEL[h]} · {n} reporter{'s' if n != 1 else ''} · {cert} ({res['confidence']:.2f})",
            "chips": chips(res, det, pq),
            "diff": ba,
            "answerChange": ({"from": show_answer(pq, e["find"]), "to": show_answer(pq, e["replace"])}
                             if e.get("field") == "answer" else None),
            "typeChange": ({"from": e["find"], "to": e["replace"]} if e.get("field") == "questionType" else None),
            "routeWhy": det.get("route_why") or [],
            "basis": det.get("basis") or [],
            "notes": det.get("notes") or [],
            "details": det_trim,
        })

    bonus_out = []
    for i, b in enumerate(bonus):
        q = parsed[b["questionId"]].q
        rep = b["repair"]
        h = 3 if rep in HARM_BLOCKS else 2 if rep in HARM_MIDDLE else 1
        ba = before_after(q, b.get("proposed_edit"))
        bonus_out.append({
            "id": f"B{i + 1:03d}", **{k: b.get(k) for k in (
                "questionId", "repair", "check", "strength", "field", "detail", "evidence_text", "evidence_raw",
                "proposed_edit", "could_auto_apply", "why", "source", "found_by", "reports_on_question", "occurrences")},
            "harm": h, "harmLabel": HARM_LABEL[h],
            "headline": f"{REPAIR_HEAD.get(rep, rep)}: “{clip(b['evidence_text'], 40)}”",
            "diff": ba, "flag": None if ba else flagged(q, b["field"], b.get("evidence_raw")),
        })

    questions = {}
    for qid, pq in parsed.items():
        q = pq.q
        questions[qid] = {
            "id": qid, "type": q.qtype, "subject": q.subject, "chapter": q.chapter,
            "concept": q.raw.get("concept", ""), "questionHtml": q.question_html, "solutionHtml": q.solution_html,
            "answerRaw": q.answer_raw, "answer": show_answer(pq, q.answer_raw) if pq.answer.values else
            {"short": json.dumps(q.answer_raw, ensure_ascii=False), "long": json.dumps(q.answer_raw, ensure_ascii=False)},
            "stem": clip(pq.split.stem_text, 140),
        }

    data = {
        "meta": {"runId": summary["run_id"], "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "reports": len(cases), "questions": len(questions), "bonus": len(bonus_out),
                 "note": "Precomputed results, no live AI calls."},
        "questions": questions, "cases": cases, "bonus": bonus_out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(cases)} cases, {len(bonus_out)} bonus findings, "
          f"{len(questions)} questions, {OUT.stat().st_size // 1024} KB (run {summary['run_id']})")


if __name__ == "__main__":
    main()
