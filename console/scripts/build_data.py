"""Bake everything the faculty console shows into console/public/data.json.

    python console/scripts/build_data.py        # run from the repo root (npm run data)

Reads data/questions.json, data/reports.json, data/taxonomy.json, results.json, the evidence of the run that
produced it (logs/runs/<run>/details.jsonl, located via logs/run-summary.json) and bonus_findings.json.

One queue item per question per route (the reports on it share an outcome), plus one per bonus finding.
Each item carries a view model the browser only renders:
  sentence  - what's wrong, one plain sentence
  sure      - how sure, one line computed from the same counts as the evidence grid (so it cannot claim more
              than the grid shows)
  grid      - for answer cases: options x sources (solver 1, solver 2, option check, stored solution, key)
  change    - before/after HTML with the edit applied, the answer change, or a suggestion / "nothing changes"
No LLM calls, no API keys. Never reads docs/eval-labels.csv.
"""
from __future__ import annotations

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
from engine.loader import load_questions, load_reports, load_taxonomy  # noqa: E402
from engine.parse import html_to_text, locate_raw  # noqa: E402

OUT = ROOT / "console" / "public" / "data.json"

TIER_BLOCKS = {"answer_key", "stem_data", "unsound", "type_mismatch", "diagram", "wrong_question"}
TIER_SOLUTION = {"solution_fix", "solution_missing", "identical_options", "option_repair"}
TIER_CLASS = {"wrong_chapter", "syllabus"}
CERT_RANK = {"strong": 0, "partial": 1, "weak": 2}
MODEL_NAME = {"openai/gpt-oss-120b": "gpt-oss-120b", "openai/gpt-oss-20b": "gpt-oss-20b",
              "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash"}
NUM_WORD = {0: "No", 1: "One", 2: "Both", 3: "Three"}


_SUP = str.maketrans("0123456789+-−=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿ")
_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def pretty(s):
    """Clean-text notation (10^−2, m^2, L_0) as a reader sees it (10⁻², m², L₀), for display strings."""
    if not isinstance(s, str):
        return s
    s = re.sub(r"\^(?:\(([+\-−]?[0-9n]+)\)|([+\-−]?[0-9n]+))", lambda m: (m[1] or m[2]).translate(_SUP), s)
    s = re.sub(r"(?<=[A-Za-z])_(?:\(([0-9]+)\)|([0-9]+))", lambda m: (m[1] or m[2]).translate(_SUB), s)
    return s


def opt_letter(findings) -> str | None:
    for f in findings:
        if f.repair == "option_repair" and f.data:
            return f.data.get("letter") or (f.data.get("missing") or [None])[0]
    return None


def clip(s, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


NBSP = "\u00a0"
_HEAD_MAX = 110


def _cut_ok(s: str, i: int) -> bool:
    """True if s[:i] closes every bracket and quote it opens (so a cut there is not inside a value)."""
    pre = s[:i]
    return (pre.count("(") == pre.count(")") and pre.count("[") == pre.count("]") and pre.count("“") == pre.count("”")
            and pre.count('"') % 2 == 0 and len(re.findall(r"(?<![A-Za-z])'|'(?![A-Za-z])", pre)) % 2 == 0)


def shorten(s: str, n: int = _HEAD_MAX) -> str:
    """A headline short enough to read at a glance: drop spaced asides "( … )", then cut at a clause boundary."""
    if len(s) <= n:
        return s
    t = re.sub(r" \([^()]*\)", "", s)
    if len(t) > n:
        cuts = [m.start() for m in re.finditer(r"[,;] ", t) if m.start() < n and _cut_ok(t, m.start())]
        if cuts:
            t = t[:cuts[-1]] + "."
    return t


def keep_values(s: str) -> str:
    """Non-breaking spaces inside values, so a line never breaks in "a = 20 cm", "C (130 V)" or a short quote."""
    if not isinstance(s, str):
        return s
    s = re.sub(r"(?<=\S) = (?=\S)", NBSP + "=" + NBSP, s)                                  # a = 20
    s = re.sub(r"(?<=[0-9\u2070\u00b9\u00b2\u00b3\u2074-\u2079]) (?=[A-Za-z\u03a9\u03bc\u00b0%/][^\s,.;:]{0,5}(?:[\s,.;:)\u201d'\u2019]|$))",
               NBSP, s)                                                                    # 20 cm, 130 V
    s = re.sub(r"\b([A-H]) \(([^()]{1,28})\)",
               lambda m: m[1] + NBSP + "(" + m[2].replace(" ", NBSP) + ")", s)            # C (130 V)
    s = re.sub(r"(?<=[0-9]) ([x×]) (?=[0-9])", NBSP + r"\1" + NBSP, s)              # 5.7 x 10
    short = lambda m: m[1] + m[2].replace(" ", NBSP) + m[3]
    s = re.sub(r"(\u201c)([^\u201c\u201d]{1,30})(\u201d)", short, s)                       # “short quote”
    s = re.sub(r"((?:^|(?<=[\s(]))')([^']{1,30})('(?=[\s,.;:)]|$))", short, s)              # 'short quote'
    return s


def model_of(role: str) -> str:
    m = config.ROLES[role][1]
    return MODEL_NAME.get(m, m.split("/")[-1])


def tier_of(verdict: str, repair: str | None, pq, findings) -> tuple[int, str]:
    if verdict != "defect":
        return 0, "No defect"
    if repair in TIER_CLASS:
        return 1, "Classification"
    if repair == "option_repair":
        if any(f.data.get("missing_is_keyed") or f.data.get("letter") in pq.answer.values
               for f in findings if f.repair == "option_repair" and f.data):
            return 3, "Blocks the right answer"
        return 2, "Wrong solution or option"
    if repair in TIER_BLOCKS:
        return 3, "Blocks the right answer"
    if repair in ("solution_fix", "solution_missing"):
        return 2, "Wrong solution"
    if repair in TIER_SOLUTION:
        return 2, "Wrong solution or option"
    return 1, "Cosmetic"


# --------------------------------------------------------------------------- HTML marking

def _in_math(raw: str, i: int):
    s = raw.rfind("<math", 0, i + 1)
    if s < 0 or raw.rfind("</math>", 0, i) > s:
        return None
    e = raw.find("</math>", i)
    return (s, e + len("</math>")) if e >= 0 else None


def _whole_elements(seg: str) -> bool:
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
    """raw with raw[i:i+n] replaced by `new` (None = keep) and the span marked. Inside MathML an <mrow> wraps
    whole elements (else the whole <math>); in HTML <u>/<s>, which the parser repairs across tag boundaries.
    The browser has a TypeScript port of this (src/edit.ts) for edits made in the console."""
    seg = raw[i:i + n] if new is None else new
    out = raw[:i] + seg + raw[i + n:]
    m = _in_math(out, i)
    if m and _whole_elements(seg):
        return out[:i] + f'<mrow class="{cls}">' + seg + "</mrow>" + out[i + len(seg):]
    if m:
        s, e = m
        return out[:s] + f'<span class="{cls} whole-math">' + out[s:e] + "</span>" + out[e:]
    tag = "s" if cls == "del" else "u"
    if not seg.strip():
        return out[:i] + f'<{tag} class="{cls} caret"></{tag}>' + out[i:]
    return out[:i] + f'<{tag} class="{cls}">' + seg + f"</{tag}>" + out[i + len(seg):]


def field_raw(q, fld: str) -> str:
    return q.solution_html if fld == "solution" else q.question_html


def diff_of(q, edit: dict | None) -> dict | None:
    if not edit or edit.get("field") not in ("question", "solution"):
        return None
    raw = field_raw(q, edit["field"])
    i = raw.find(edit["find"])
    if i < 0:
        return {"field": edit["field"], "error": "The text to replace is no longer in the stored record."}
    n = len(edit["find"])
    return {"field": edit["field"], "before": mark(raw, i, n, None, "del"),
            "after": mark(raw, i, n, edit["replace"], "ins"),
            "findText": html_to_text(edit["find"]), "replaceText": html_to_text(edit["replace"])}


def flag_spans(raw: str, quotes: list[str]) -> str | None:
    """raw with each quoted clean-text span marked as flagged (unique locations only)."""
    hits = []
    for qt in quotes:
        sub, uniq = locate_raw(raw, qt) if qt else (None, False)
        if sub and uniq:
            hits.append((raw.find(sub), len(sub)))
    if not hits:
        return None
    for i, n in sorted(hits, reverse=True):
        raw = mark(raw, i, n, None, "flag")
    return raw


_TRAIL = re.compile(r"(?:\s|&nbsp;|<br\s*/?>|</[a-zA-Z0-9]+>)*$")
_LEAD = re.compile(r"(?:\s|&nbsp;|</?(?:p|span|div|br)\b[^>]*>)*")


def tag_options(pq, tags: dict[str, str]) -> str:
    """Question HTML with a small tag (KEY / NEW / OLD KEY) after the given options' text."""
    raw = pq.q.question_html
    spots = []
    for L, label in tags.items():
        if L not in pq.split.option_spans:
            continue
        s, e = pq.split.option_spans[L]
        cut = s + _TRAIL.search(raw[s:e]).start()
        if _in_math(raw, cut):
            continue
        cls = {"KEY": "tag-key", "NEW": "tag-new", "OLD KEY": "tag-old"}[label]
        vs = e - len(pq.split.options_raw[L])
        vs += _LEAD.match(raw, vs, cut).end() - vs
        spots.append((cut, f' <span class="opt-tag {cls}">{label}</span>', vs if label == "OLD KEY" else None))
    for cut, t, vs in sorted(spots, key=lambda x: x[0], reverse=True):
        raw = raw[:cut] + t + raw[cut:]
        if vs is not None and vs < cut:          # the old key's value is struck through, not the tag
            raw = mark(raw, vs, cut - vs, None, "del")
    return raw


# --------------------------------------------------------------------------- answers

def letters_of(x) -> list[str]:
    if isinstance(x, list):
        x = ",".join(map(str, x))
    return sorted({p.strip().upper() for p in str(x or "").replace(" ", ",").split(",") if p.strip()})


def opt_label(pq, L: str) -> str:
    t = pq.split.options_text.get(L, "")
    return f"{L} ({clip(t, 26)})" if t else f"{L} (blank)"


def show_answer(pq, value) -> str:
    if pq.q.qtype == "integerQuestion":
        return str(value[0] if isinstance(value, list) and value else value)
    ls = letters_of(value)
    if ls and all(L in pq.split.options_text for L in ls):
        return ", ".join(opt_label(pq, L) for L in ls)
    return json.dumps(value, ensure_ascii=False)


def key_text(pq) -> str:
    return show_answer(pq, pq.q.answer_raw) if pq.answer.values else json.dumps(pq.q.answer_raw, ensure_ascii=False)


def num_eq(a, b) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=config.INTEGER_REL_TOL, abs_tol=config.INTEGER_ABS_TOL)
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- evidence grid

def evidence_grid(pq, det) -> dict | None:
    """Rows = options (or candidate values), columns = sources. Cells: 'y' picked / judged right, 'n' judged
    wrong, 'mixed' checks disagree, '' no signal. None when no answer evidence was gathered."""
    solvers = [s for s in (det.get("solvers") or []) if s.get("role") in ("solver_1", "solver_2")]
    checks = det.get("option_checks") or {}
    ex = det.get("extract") or {}
    if not solvers and not checks:
        return None
    is_int = pq.q.qtype == "integerQuestion"
    cols = []
    for i, sv in enumerate(solvers):
        title = f"{model_of(sv['role'])}, blind solve (never saw the key, the solution or the comment)"
        if sv.get("missing"):
            title += f"; reported missing data: {clip(sv['missing'], 80)}"
        elif not sv.get("ok"):
            title += "; gave no answer"
        cols.append({"id": f"s{i + 1}", "label": f"Solver {i + 1}", "title": title})
    chk_models = sorted({model_of(v["role"]) for vs in checks.values() for v in vs})
    if checks:
        cols.append({"id": "check", "label": "Value check" if is_int else "Option check",
                     "title": "Each option judged on its own by " + " and ".join(chk_models)})
    cols.append({"id": "sol", "label": "Stored solution", "title": "Where the stored worked solution ends"})
    cols.append({"id": "key", "label": "Key", "title": "The stored answer key"})

    def check_cell(vs):
        marks = {v.get("verdict") for v in vs}
        if marks == {"correct"}:
            return "y"
        if marks == {"incorrect"}:
            return "n"
        if marks <= {"cannot_tell"}:
            return ""
        return "mixed"

    def check_note(vs):
        return "; ".join(f"{model_of(v['role'])}: {v['verdict']}" + (f" ({clip(v.get('reason'), 140)})" if v.get("reason") else "")
                         for v in vs)

    rows = []
    if not is_int:
        for L in pq.split.letters:
            cells, notes = {}, {}
            for i, sv in enumerate(solvers):
                ok = sv.get("ok") and not sv.get("missing")
                cells[f"s{i + 1}"] = "y" if ok and L in (sv.get("letters") or []) else ""
            if checks:
                vs = checks.get(L) or []
                cells["check"] = check_cell(vs) if vs else ""
                if vs:
                    notes["check"] = check_note(vs)
                    notes["checkCount"] = len(vs)
            cells["sol"] = "y" if ex.get("ok") and L in (ex.get("letters") or []) else ""
            cells["key"] = "y" if L in pq.answer.values else ""
            rows.append({"id": L, "label": L, "text": clip(pq.split.options_text.get(L, "") or "(blank)", 44),
                         "cells": cells, "notes": notes})
    else:
        vals = []
        if pq.answer.values:
            vals.append(("key", float(pq.answer.values[0])))
        for cand, (v, _u) in (det.get("value_candidates") or {}).items():
            if not any(num_eq(v, x) for _, x in vals):
                vals.append((cand, v))
        for cand, v in vals:
            cells, notes = {}, {}
            for i, sv in enumerate(solvers):
                ok = sv.get("ok") and not sv.get("missing")
                cells[f"s{i + 1}"] = "y" if ok and num_eq(sv.get("value"), v) else ""
            if checks:
                vs = checks.get(cand) or []
                cells["check"] = check_cell(vs) if vs else ""
                if vs:
                    notes["check"] = check_note(vs)
                    notes["checkCount"] = len(vs)
            cells["sol"] = "y" if ex.get("ok") and num_eq(ex.get("value"), v) else ""
            cells["key"] = "y" if cand == "key" else ""
            rows.append({"id": cand, "label": f"{v:g}", "text": "", "cells": cells, "notes": notes})
    return {"cols": cols, "rows": rows}


def picks(grid, col) -> list[str]:
    return [r["label"] for r in grid["rows"] if r["cells"].get(col) == "y"]


def sure_from_grid(grid, target: list[str] | None, old: list[str] | None, unsound: bool) -> str:
    """One line built only from what the grid shows."""
    if not grid:
        return ""
    s_cols = [c["id"] for c in grid["cols"] if re.fullmatch(r"s\d", c["id"])]
    has_check = any(c["id"] == "check" for c in grid["cols"])
    rows = {r["label"]: r for r in grid["rows"]}
    fmt = lambda ls: " and ".join(ls) if ls else "nothing"
    if unsound:
        checked = [r for r in grid["rows"] if r["cells"].get("check")]
        wrong = [r for r in checked if r["cells"]["check"] == "n"]
        twice = [r["label"] for r in wrong if r["notes"].get("checkCount", 0) >= 2]
        line = ("Every option was checked and marked wrong" if checked and len(wrong) == len(grid["rows"])
                else f"{len(wrong)} of {len(grid['rows'])} options were checked and marked wrong")
        if twice:
            line += f" ({fmt(twice)} by two different models)"
        extra = []
        sol = picks(grid, "sol")
        if sol:
            extra.append(f"the stored solution picks {fmt(sol)}")
        s_picks = sorted({p for c in s_cols for p in picks(grid, c)})
        n_pick = sum(1 for c in s_cols if picks(grid, c))
        if s_picks:
            extra.append(f"{'one AI solver picks' if n_pick == 1 else 'the AI solvers pick'} {fmt(s_picks)}")
        return line + (f"; {', and '.join(extra)}, which the checks reject." if extra else ".")
    tgt = target or []
    agree = [c for c in s_cols if picks(grid, c) == tgt]
    sol_ok = bool(tgt) and picks(grid, "sol") == tgt
    others = sorted({p for c in s_cols if c not in agree for p in picks(grid, c)})
    if len(s_cols) == 2:
        who = {2: "Both AI solvers (two different models)", 1: "One of the two AI solvers", 0: "Neither AI solver"}[len(agree)]
    else:
        who = f"{len(agree)} of {len(s_cols)} AI solvers"
    if agree:
        parts = [who + (" and the stored solution" if sol_ok else "") + (" give " if len(agree) > 1 or sol_ok else " gives ") + fmt(tgt)]
    elif sol_ok:
        parts = [f"The stored solution gives {fmt(tgt)}; neither AI solver does"]
    else:
        parts = [f"Neither AI solver gives {fmt(tgt)}"]
    if others:
        parts.append(f"the other solver gives {fmt(others)}" if len(agree) == 1 else f"they give {fmt(others)}")
    if has_check and tgt:
        t_ok = all(rows[t]["cells"].get("check") == "y" for t in tgt if t in rows)
        o_bad = bool(old) and all(rows[o]["cells"].get("check") == "n" for o in old if o in rows)
        if t_ok and o_bad:
            parts.append(f"the option check marks {fmt(tgt)} right and {fmt(old)} wrong")
        elif t_ok:
            parts.append(f"the {'value' if not rows.get(tgt[0], {}).get('text', 'x') else 'option'} check agrees")
        elif any(rows[t]["cells"].get("check") == "n" for t in tgt if t in rows):
            parts.append(f"but the check marks {fmt(tgt)} wrong")
    if agree and not sol_ok and picks(grid, "sol"):
        parts.append(f"the stored solution ends at {fmt(picks(grid, 'sol'))}")
    line = "; ".join(parts) + "."
    return line[0].upper() + line[1:]


def certainty_rank(det) -> str:
    if det.get("injection_blocks_auto_apply") or det.get("triage_contradicts") or det.get("against", 0) > 0:
        return "weak"
    if det.get("decided_by") == "triage":
        return "partial"
    return "strong"


# --------------------------------------------------------------------------- sentences

def audit_values(det) -> list[dict]:
    out = []
    for v in (det.get("audit") or {}).get("values_not_in_question") or []:
        try:
            out.append(json.loads(v) if isinstance(v, str) else v)
        except ValueError:
            pass
    return out


def report_view(res, pq, det, findings) -> dict:
    v, rep, e = res["verdict"], res["repair"], res.get("edit") or {}
    t0 = det.get("tier0") or {}
    key = list(pq.answer.values)
    grid = evidence_grid(pq, det)
    diff = diff_of(pq.q, res.get("edit"))
    kind, sentence, sure, title = "faculty", "", "", ""
    answer_change = type_change = suggestion = nothing = None
    tags = {}
    sol_flags, sol_open = [], False

    if e.get("field") == "answer":
        kind = "answer"
        new = letters_of(e["replace"]) if pq.has_options else [str(e["replace"])]
        was = letters_of(e["find"]) if pq.has_options else [str(e["find"])]
        if new == was:  # malformed key normalised
            title = "Key format fixed"
            sentence = (f"The answer key is stored as {json.dumps(e['find'], ensure_ascii=False)}, one string instead "
                        f"of separate answers, so correct answers are marked wrong.")
            sure = "A format check found it; split into separate answers, the key matches what the student entered."
            answer_change = {"from": json.dumps(e["find"], ensure_ascii=False), "to": ", ".join(new)}
            tags = {L: "KEY" for L in new}
        else:
            a, b = show_answer(pq, e["find"]), show_answer(pq, e["replace"])
            title = f"Answer key {', '.join(was)} → {', '.join(new)}"
            sentence = f"The answer key says {a}, but the correct answer is {b}."
            answer_change = {"from": a, "to": b}
            sure = sure_from_grid(grid, new, was, False)
            tags = {**{L: "OLD KEY" for L in was}, **{L: "NEW" for L in new}} if pq.has_options else {}
    elif e.get("field") == "questionType":
        kind = "type"
        title = f"Type {e['find']} → {e['replace']}"
        sentence = (f"Stored as multiple-correct, but only {opt_label(pq, key[0]) if key else 'one option'} is correct, "
                    f"so marking does not work.")
        sure = "The stored key has a single answer, and the student says only one option is correct."
        type_change = {"from": e["find"], "to": e["replace"]}
        tags = {L: "KEY" for L in key}
    elif diff:
        kind = "text"
        f, r = diff.get("findText", "").strip(), diff.get("replaceText", "").strip()
        where = "question" if diff["field"] == "question" else "worked solution"
        if rep == "stem_data":
            av = audit_values(det)
            what = av[0]["what"] if av else "a value"
            title = f"Missing {clip(what, 26)}"
            sentence = f"The question leaves out the {what}, which it needs to be solved."
            n_missing = sum(1 for s in det.get("solvers") or [] if s.get("missing"))
            resolve = next((n for n in det.get("notes") or [] if n.startswith("Re-solve")), "")
            sure = (f"{NUM_WORD.get(n_missing, n_missing)} AI solver{'s' if n_missing != 1 else ''} reported the "
                    f"data missing; the stored solution uses {av[0]['value'] if av else 'a value'}"
                    + ("; re-solving with it added reproduces the key in both models." if "reproduces the key" in resolve else "."))
        elif rep == "option_repair":
            L = opt_letter(findings) or "?"
            title = f"Option {L} blank"
            sentence = f"Option {L} is blank, and it is the keyed answer." if L in key else f"Option {L} is blank."
            note = next((n for n in det.get("notes") or [] if n.startswith("Content")), "")
            m = re.search(r"agreed by (\d+) independent sources: (.*)", note)
            if m:
                srcs = m.group(2).replace("deepseek-v4-flash", "DeepSeek").replace(" blind solve", "")
                sure = f"{NUM_WORD.get(int(m.group(1)), m.group(1))} independent sources give the same value for it ({srcs})."
            else:
                sure = note
            tags = {L: "KEY"} if L in key else {}
        elif rep == "solution_fix":
            title = "Solution's final value"
            lhs = re.match(r"\s*([^=]{1,12}?)\s*=\s*", str(r))
            r_val = str(r)[lhs.end():] if lhs and str(f).strip().startswith(lhs.group(1)) else r
            sentence = f"The solution ends at {f}, but the answer is {r_val}."
            base = sure_from_grid(grid, key, None, False)
            sure = (base.rstrip(".") + f"; the stored solution says {f}.") if base else f"Every check gives {r}."
            tags = {L: "KEY" for L in key} if pq.has_options else {}
            sol_open = True
        else:
            if rep == "exam_reference":
                title = "Exam tag in question"
                sentence = f"The question carries an exam tag, “{f}”."
            elif rep == "markup_leak":
                title = "Raw code in question" if diff["field"] == "question" else "Raw code in solution"
                sentence = f"The {where} shows raw code, “{f}”, instead of formatted text."
            elif rep == "answer_form":
                title = "Unit not stated"
                sentence = "The question does not say what unit the answer should be in."
            elif r.replace(" ", "") == f.replace(" ", "") and r.count(" ") > f.count(" "):
                title = f"Spelling: {clip(f, 18)}"
                sentence = f"The {where} has “{f}”, two words run together."
            else:
                title = f"Spelling: {clip(f, 18)}"
                sentence = f"The {where} has “{f}”, which should read “{r}”."
            if t0.get("outcome") == "code_settled":
                sure = "A text check confirmed it in the stored record" + (
                    ", and it is the word the student named." if rep == "spelling" else ".")
            elif det.get("decided_by") == "triage":
                sure = "A text check flagged it; the AI triage chose this fix and the edit guards passed. No second source."
            else:
                sure = "A text check flagged it, the AI triage agreed, and the edit guards passed."
            sol_open = diff["field"] == "solution"
    elif v != "defect":
        kind = "nochange" if v in ("no_error", "already_fixed") else "platform"
        if v == "no_error":
            title = f"Key {', '.join(key)} is right" if key else "No error"
            sentence = f"Checked: the stored key, {key_text(pq)}, is right."
            if det.get("injection_regex") or (det.get("guard") or {}).get("flag"):
                sentence = f"The comment tried to change the key and was ignored; the key, {key_text(pq)}, is right."
            sure = sure_from_grid(grid, key, None, False) or "The checks found nothing wrong."
            nothing = "Nothing changes: the key and the question are correct as stored."
            tags = {L: "KEY" for L in key} if pq.has_options else {}
        elif v == "already_fixed":
            title = "Already fixed"
            sentence = "Already fixed: a faculty edit after this report removed the problem."
            sure = clip(re.sub(r"(\d{4})-(\d\d)-(\d\d)T[\d:]+Z", lambda m: datetime(int(m[1]), int(m[2]), int(m[3])).strftime("%d %b").lstrip("0"),
                               t0.get("basis", "")), 240) + (" The AI triage disagreed, so give it a look."
                                                     if det.get("triage_contradicts") else "")
            nothing = "Nothing changes: the live record is already correct."
        else:
            title = {"display_issue": "Display issue", "app_issue": "App issue", "language_mode": "Language request",
                     "not_actionable": "Not actionable"}[v]
            sentence = {"display_issue": "The student reported a display problem; the question content is fine.",
                        "app_issue": "The student reported an app problem; the question content is fine.",
                        "language_mode": "The student asked for another language; the question content is fine.",
                        "not_actionable": "The comment can't be acted on, and the checks found nothing wrong with the question."}[v]
            sure = {"display_issue": "A code check found the stored question complete: every option present, no raw code, no missing figure.",
                    "app_issue": "The comment describes how the app behaved (what was recorded), not the question's content.",
                    "language_mode": "The stored question exists only in English, so there is nothing to switch to.",
                    "not_actionable": "The comment is unreadable, and no check found anything wrong with the question."}[v]
            nothing = "Nothing changes: this is not a problem with the stored question."
    else:
        kind = "faculty"
        tags = {L: "KEY" for L in key}
        if rep == "unsound":
            title = "No option is correct"
            sentence = "No option is correct as written."
            sure = sure_from_grid(grid, None, None, True)
            tr = det.get("triage") or {}
            if tr.get("evidence"):
                suggestion = {"text": "Rewrite the options so exactly one is correct, or change the question.",
                              "detail": f"AI triage's reading: {clip(tr['evidence'], 300)}"}
        elif rep == "identical_options":
            fd = next((x for x in findings if x.check == "identical_options"), None)
            m = re.search(r"Options \((\w)\) and \((\w)\) are identical: '([^']*)'", fd.detail if fd else "")
            title = f"Options {m.group(1)} and {m.group(2)} identical" if m else "Identical options"
            sentence = (f"Options {m.group(1)} and {m.group(2)} are identical (“{m.group(3)}”)." if m
                        else "Two options are identical.")
            both = grid and all(len(picks(grid, c["id"])) == 2 for c in grid["cols"] if re.fullmatch(r"s\d", c["id"]))
            sure = "A text check confirmed it in the stored question." + (" Both AI solvers pick both of them." if both else "")
            suggestion = {"text": f"Write a new distractor to replace option {m.group(2) if m else 'one of them'}.",
                          "detail": "New options are authored content, so this can't be applied automatically."}
        elif rep == "option_repair":
            L = opt_letter(findings) or "?"
            title = f"Option {L} missing"
            stored = f"{pq.split.letters[0]}–{pq.split.letters[-1]}" if pq.split.letters else "the others"
            sentence = (f"Option {L} is missing; only {stored} are stored." if L not in pq.split.letters
                        else f"Option {L} is blank.")
            sure = "A structure check confirmed it. Nothing in the key or the solution says what the option should be."
            suggestion = {"text": f"Write option {L}.", "detail": "It is a distractor, so there is no source to copy it from."}
        elif rep == "diagram":
            title = "Figure missing"
            sentence = "The question refers to a figure that isn't there."
            fd = next((x for x in findings if x.check == "figure_missing"), None)
            sure = f"The stem says “{fd.evidence_text}” and no image is stored." if fd else "No image is stored."
            suggestion = {"text": "Add the figure, or rewrite the stem so it doesn't need one.", "detail": ""}
        elif rep in ("wrong_chapter", "syllabus"):
            tags = {}
            title = "Wrong chapter?" if rep == "wrong_chapter" else "Outside syllabus?"
            sentence = (f"A student says this is filed under the wrong chapter (now: {pq.q.chapter})."
                        if rep == "wrong_chapter" else "A student says this is outside the syllabus.")
            sure = "This is the student's claim; no check can confirm it. The question stays live meanwhile."
        elif rep in ("solution_fix", "wrong_question", "solution_missing"):
            av = audit_values(det)
            title = "Solution doesn't fit" if av else "Solution problem"
            sentence = (f"The worked solution uses a {av[0]['what']} of {av[0]['value']}, which the question never gives."
                        if av else "The worked solution has a problem.")
            base = sure_from_grid(grid, key, None, False) if grid else ""
            sure = (base.rstrip(".") + "; the key is not in doubt, only the solution.") if base else "The solution audit flagged it."
            sol_flags = [x.get("quote", "") for x in av]
            sol_open = True
            te = (det.get("triage") or {}).get("edit") or {}
            if te.get("find_clean") and any(q and q in te["find_clean"] for q in sol_flags):
                suggestion = {"text": f"Replace “{te['find_clean']}” with “{te.get('replace', '')}”.",
                              "detail": "The AI triage's edit. The edit guards did not pass it, so it was not applied."}
        else:
            title = (rep or "defect").replace("_", " ").capitalize()
            sentence = clip(t0.get("basis") or res["evidence"], 200)
            sure = clip("; ".join(det.get("basis") or []), 240)

    if grid:
        for r in grid["rows"]:
            r["text"] = pretty(r["text"])
    title, sentence, sure = pretty(title), keep_values(shorten(pretty(sentence))), keep_values(pretty(sure))
    if answer_change:
        answer_change = {k: pretty(x) for k, x in answer_change.items()}
    if suggestion:
        suggestion = {k: pretty(x) for k, x in suggestion.items()}
    q_html = tag_options(pq, tags) if tags and pq.has_options else pq.q.question_html
    sol_html = flag_spans(pq.q.solution_html, sol_flags) if sol_flags else None
    return {"kind": kind, "title": title, "sentence": sentence, "sure": sure, "grid": grid,
            "diff": diff, "answerChange": answer_change, "typeChange": type_change,
            "suggestion": suggestion, "nothing": nothing, "questionHtml": q_html,
            "solutionHtml": sol_html, "solutionOpen": sol_open or bool(sol_html),
            "certainty": certainty_rank(det)}


# --------------------------------------------------------------------------- build

def main():
    summary = json.loads((ROOT / "logs" / "run-summary.json").read_text(encoding="utf-8"))
    run_dir = (ROOT / summary["results_file"]).parent
    results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    if json.loads((run_dir / "results.json").read_text(encoding="utf-8")) != results:
        raise SystemExit(f"results.json does not match {run_dir.name}/results.json; evidence would not line up")
    details = {d["reportId"]: d for d in
               (json.loads(x) for x in (run_dir / "details.jsonl").read_text(encoding="utf-8").splitlines() if x)}
    bonus = json.loads((ROOT / "bonus_findings.json").read_text(encoding="utf-8"))
    taxonomy = load_taxonomy()
    qs = load_questions()
    reports = {r.report_id: r for r in load_reports()}
    parsed = {k: parse_question(q) for k, q in qs.items()}
    vocab = build_vocab(list(parsed.values()))
    findings = {k: run_checks(pq, vocab) for k, pq in parsed.items()}
    res_by = {r["reportId"]: r for r in results}

    students = {}
    for r in reports.values():
        students.setdefault(r.question_id, set()).add(r.student_id)

    def report_rows(qid, ids):
        rows = []
        for rid, r in sorted(reports.items(), key=lambda kv: (kv[0] not in ids, kv[1].reported_at)):
            if r.question_id != qid:
                continue
            res = res_by[rid]
            rows.append({"reportId": rid, "studentId": r.student_id, "source": r.source, "reportedAt": r.reported_at,
                         "comment": r.comment, "reply": res["student_reply"], "verdict": res["verdict"],
                         "repair": res["repair"], "route": res["route"], "inThisCase": rid in ids})
        return rows

    items = []
    groups: dict = {}
    for res in results:
        groups.setdefault((res["questionId"], res["route"]), []).append(res)
    for (qid, route), rs in groups.items():
        pq = parsed[qid]
        views = []
        for res in rs:
            det = details.get(res["reportId"], {})
            t, tl = tier_of(res["verdict"], res["repair"], pq, findings[qid])
            views.append((res, det, t, tl, report_view(res, pq, det, findings[qid])))
        views.sort(key=lambda x: (-x[2], CERT_RANK[x[4]["certainty"]], -x[0]["confidence"], x[0]["reportId"]))
        res, det, t, tl, view = views[0]
        ids = [x[0]["reportId"] for x in views]
        n = len(students.get(qid, ()))
        cert_txt = {"strong": "evidence agrees", "partial": "one source plus a check", "weak": "evidence is mixed"}
        items.append({
            "key": f"{route}:{qid}", "source": "report", "route": route, "questionId": qid, "reportIds": ids,
            "tier": t, "tierLabel": tl, "reach": n, "confidence": res["confidence"],
            "why": f"{tl} · {n} student{'s' if n != 1 else ''} reported it · {cert_txt[view['certainty']]}",
            "verdict": res["verdict"], "repair": res["repair"], "edit": res.get("edit"),
            "rawEvidence": [{"reportId": x[0]["reportId"], "evidence": x[0]["evidence"]} for x in views],
            "routeWhy": det.get("route_why") or [], "decidedBy": det.get("decided_by", ""),
            "reports": report_rows(qid, set(ids)), **view,
        })

    for i, b in enumerate(bonus):
        qid = b["questionId"]
        pq = parsed[qid]
        rep = b["repair"]
        if rep in TIER_BLOCKS:
            t, tl = 3, "Blocks the right answer"
        elif rep in TIER_CLASS:
            t, tl = 1, "Classification"
        elif rep in ("solution_fix", "solution_missing"):
            t, tl = 2, "Wrong solution"
        elif rep in TIER_SOLUTION:
            t, tl = 2, "Wrong solution or option"
        else:
            t, tl = 1, "Cosmetic"
        edit = b.get("proposed_edit")
        diff = diff_of(pq.q, edit)
        flagged = None
        if not diff and b["field"] in ("question", "solution") and b.get("evidence_raw"):
            raw = field_raw(pq.q, b["field"])
            j = raw.find(b["evidence_raw"])
            flagged = mark(raw, j, len(b["evidence_raw"]), None, "flag") if j >= 0 else None
        src = ("found in manual review" if b["source"] == "manual_review" else
               f"found by a {'definite' if b['strength'] == 'definite' else 'suspect-word'} code check")
        if b["source"] == "manual_review":
            sure = "A reviewer confirmed it against the stored record."
        elif b["strength"] == "definite":
            sure = "A code check confirmed it in the stored record."
        else:
            sure = "A code check flagged it as a suspect; nobody has confirmed it yet."
        if b.get("occurrences"):
            sure += " In the record: " + ", ".join(f"“{o['text']}” ({o['field']})" for o in b["occurrences"]) + "."
        items.append({
            "key": f"bonus:{qid}:{i}", "source": "bonus", "route": "bonus", "questionId": qid,
            "reportIds": [], "tier": t, "tierLabel": tl, "reach": 0, "confidence": 0,
            "why": f"{tl} · no student reported it · {src}", "verdict": "defect", "repair": rep, "edit": edit,
            "rawEvidence": [{"reportId": "", "evidence": f"{b['detail']} Evidence: “{b['evidence_text']}”. {b['why']}"}],
            "routeWhy": [b["why"]], "decidedBy": b["source"], "reports": report_rows(qid, set()),
            "kind": "text" if diff else "faculty",
            "title": "Wrong chapter" if rep == "wrong_chapter" else pretty(clip(b["evidence_text"], 28)),
            "sentence": keep_values(shorten(pretty(re.split(r"(?<=[.!?])\s", b["detail"])[0]))),
            "sure": keep_values(pretty(sure)), "grid": None, "diff": diff, "answerChange": None, "typeChange": None,
            "suggestion": None if diff else {"text": "Fix by hand.", "detail": b["why"]},
            "nothing": None,
            "questionHtml": flagged if b["field"] == "question" and flagged else pq.q.question_html,
            "solutionHtml": flagged if b["field"] == "solution" and flagged else None,
            "solutionOpen": b["field"] == "solution" and not diff,
            "certainty": "partial" if b["strength"] == "signal" else "strong",
            "couldAutoApply": b["could_auto_apply"],
        })

    questions = {}
    for qid, pq in parsed.items():
        q = pq.q
        questions[qid] = {"id": qid, "type": q.qtype, "subject": q.subject, "chapter": q.chapter,
                          "questionHtml": q.question_html, "solutionHtml": q.solution_html,
                          "answerRaw": q.answer_raw, "key": pretty(key_text(pq)),
                          "letters": list(pq.split.letters) if pq.has_options else [],
                          "optionStart": min((s for s, _ in pq.split.option_spans.values()), default=None)}

    data = {
        "meta": {"runId": summary["run_id"], "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "reports": len(results), "items": len(items),
                 "repairFields": {k: v["fields"] for k, v in taxonomy["repairs"].items()}},
        "questions": questions, "items": items,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(items)} items, {OUT.stat().st_size // 1024} KB (run {summary['run_id']})")


if __name__ == "__main__":
    main()
