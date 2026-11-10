"""Edits: built in code where possible (D-004), mapped from clean text where an LLM
proposes one (D-016), and always checked by the per-repair guards before use.

An edit is {"field", "find", "replace"} against the stored record: raw HTML for
question/solution, the stored value for answer/questionType.
"""
from __future__ import annotations

import html
import json
import re

from .checks import DEFINITE, ParsedQuestion
from .parse import locate_raw

MAX_FIND_CHARS = 400
MAX_FIND_SHARE = 0.5          # an edit may not replace more than half of a field
_LATEX_SIMPLE = {
    r"\AA": "Å", r"\times": "×", r"\pi": "π", r"\alpha": "α", r"\beta": "β", r"\gamma": "γ",
    r"\theta": "θ", r"\lambda": "λ", r"\mu": "μ", r"\omega": "ω", r"\Omega": "Ω", r"\Delta": "Δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\phi": "φ", r"\rho": "ρ", r"\sigma": "σ", r"\tau": "τ",
    r"\degree": "°", r"\circ": "°", r"\cdot": "·", r"\infty": "∞", r"\pm": "±", r"\le": "≤", r"\ge": "≥",
}


def field_raw(pq: ParsedQuestion, fld: str):
    return {"question": pq.q.question_html, "solution": pq.q.solution_html,
            "answer": pq.q.answer_raw, "questionType": pq.q.qtype}.get(fld)


# --------------------------------------------------------------------------
# Edits code can build
# --------------------------------------------------------------------------

def latex_to_text(cmd: str) -> str | None:
    m = re.fullmatch(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", cmd)
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        wrap = lambda x: x if re.fullmatch(r"[\w.]+", x) else f"({x})"
        return f"{wrap(a)}/{wrap(b)}"
    m = re.fullmatch(r"\\sqrt\{([^{}]*)\}", cmd)
    if m:
        return f"√({m.group(1)})" if not re.fullmatch(r"[\w.]+", m.group(1)) else f"√{m.group(1)}"
    return _LATEX_SIMPLE.get(cmd)


def answer_edit(pq: ParsedQuestion, new_answer) -> dict:
    """Key change or key normalisation. Keeps the stored shape: str for scq/integer, list for mcq."""
    stored = pq.q.answer_raw
    if pq.q.qtype == "mcq":
        new = sorted(new_answer)
    else:
        new = new_answer[0] if isinstance(new_answer, (list, tuple)) else new_answer
    return {"field": "answer", "find": stored, "replace": new}


def code_edit(repair: str, pq: ParsedQuestion, findings: list, *, new_answer=None, named_word=None,
              option_content=None) -> tuple[dict | None, str]:
    """(edit, how) for repairs code can build; (None, reason) otherwise."""
    raw_q = pq.q.question_html
    if repair == "answer_key" and new_answer:
        return answer_edit(pq, new_answer), "code: key change/normalisation"
    if repair == "type_mismatch":
        target = "scq" if pq.q.qtype == "mcq" and len(pq.answer.values) == 1 else None
        if target:
            return {"field": "questionType", "find": pq.q.qtype, "replace": target}, "code: single-answer mcq -> scq"
        return None, "no type change derivable"
    if repair == "exam_reference":
        f = next((x for x in findings if x.check == "exam_reference" and x.evidence_raw_unique), None)
        if f:
            raw = field_raw(pq, f.field)
            find = f.evidence_raw
            i = raw.find(find)
            if i >= 0 and raw[i + len(find): i + len(find) + 1] == " " and raw.count(find + " ") == 1:
                find += " "
            return {"field": f.field, "find": find, "replace": ""}, "code: remove exam tag"
        return None, "no unique exam tag"
    if repair == "markup_leak":
        f = next((x for x in findings if x.check == "latex_in_text" and x.evidence_raw_unique), None)
        if f:
            rep = latex_to_text(f.evidence_text)
            if rep is not None:
                return {"field": f.field, "find": f.evidence_raw, "replace": html.escape(rep, quote=False)}, \
                    "code: LaTeX to text"
        return None, "markup not convertible by code"
    if repair == "spelling" and named_word:
        from .checks import find_word_near
        for fld, t, d in find_word_near(named_word, pq):
            if 0 < d <= 2:
                raw, uniq = locate_raw(field_raw(pq, fld), t, whole_word=True)
                if raw and uniq:
                    good = named_word if not t[:1].isupper() else named_word[:1].upper() + named_word[1:]
                    return {"field": fld, "find": raw, "replace": raw.replace(t, good)}, "code: named word"
        return None, "named word not located"
    if repair == "option_repair" and option_content:
        f = next((x for x in findings if x.check == "option_blank" and x.strength == DEFINITE), None)
        if f and f.evidence_raw_unique:
            L = f.data["letter"]
            s, e = pq.split.option_spans[L]
            marker_raw = raw_q[s:e][: len(raw_q[s:e]) - len(pq.split.options_raw[L])]
            find = f.evidence_raw
            if marker_raw and marker_raw in find:
                rep = find.replace(marker_raw, marker_raw + " " + html.escape(option_content.strip(), quote=False), 1)
                return {"field": "question", "find": find, "replace": rep}, "code: fill blank option"
        return None, "blank option not located"
    return None, f"code builds no edit for {repair}"


# --------------------------------------------------------------------------
# LLM edit in clean text -> raw edit
# --------------------------------------------------------------------------

def map_clean_edit(pq: ParsedQuestion, e: dict) -> tuple[dict | None, str]:
    fld = (e or {}).get("field")
    find_clean = (e or {}).get("find_clean") or ""
    replace = (e or {}).get("replace")
    if fld not in ("question", "solution") or not find_clean or replace is None:
        if fld in ("answer", "questionType") and replace is not None:
            return {"field": fld, "find": field_raw(pq, fld), "replace": replace}, "llm: value edit"
        return None, "incomplete edit"
    raw, uniq = locate_raw(field_raw(pq, fld), find_clean)
    if not raw or not uniq:
        return None, "find_clean not located uniquely in the raw field"
    return {"field": fld, "find": raw, "replace": html.escape(str(replace), quote=False),
            "_find_clean": find_clean}, "llm: mapped from clean text"


# --------------------------------------------------------------------------
# Guards (D-004)
# --------------------------------------------------------------------------

def guard(edit: dict | None, repair: str, pq: ParsedQuestion, taxonomy: dict) -> list[str]:
    """Return the list of failed guards ([] = passes)."""
    if not edit:
        return ["no edit"]
    fails = []
    fld = edit.get("field")
    allowed = taxonomy["repairs"].get(repair, {}).get("fields", [])
    if fld not in allowed:
        fails.append(f"field '{fld}' not allowed for {repair} (allowed: {allowed})")
    find, rep = edit.get("find"), edit.get("replace")
    if fld in ("question", "solution"):
        raw = field_raw(pq, fld) or ""
        if not isinstance(find, str) or not find:
            fails.append("empty find")
        else:
            n = raw.count(find)
            if n != 1:
                fails.append(f"find occurs {n} times (must be exactly once)")
            if len(find) > MAX_FIND_CHARS or len(find) > MAX_FIND_SHARE * max(len(raw), 1):
                fails.append("edit too large (not surgical)")
            if re.search(r"</?m(?:row|i|n|o|frac|sup|sub|sqrt|text|style|ath)\b", find) and \
                    not re.search(r"</?m(?:row|i|n|o|frac|sup|sub|sqrt|text|style|ath)\b", str(rep)):
                fails.append("edit would replace MathML with plain text")
        if not isinstance(rep, str):
            fails.append("replace must be text")
        elif isinstance(find, str):
            if repair == "answer_form" and (find not in rep or len(rep) <= len(find)):
                fails.append("answer_form edits must be additive (find kept intact)")
            if repair == "spelling":
                strip = lambda x: re.sub(r"[A-Za-z\s]", "", html.unescape(re.sub(r"<[^>]*>", "", x)))
                if strip(find) != strip(rep):
                    fails.append("spelling edit changes digits or symbols")
            if repair == "option_repair" and fld == "question":
                first = min((sp[0] for sp in pq.split.option_spans.values()), default=None)
                at = raw.find(find)
                if first is None or at < first:
                    fails.append("option_repair edit touches the stem")
    elif fld == "answer":
        if find != pq.q.answer_raw:
            fails.append("answer edit must find the stored answer exactly")
        letters = set(pq.split.letters)
        if pq.q.qtype == "integerQuestion":
            if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", str(rep)):
                fails.append("integer key must be a number")
        elif pq.q.qtype == "scq":
            if not (isinstance(rep, str) and rep in letters):
                fails.append("scq key must be one existing option letter")
        elif pq.q.qtype == "mcq":
            if not (isinstance(rep, list) and rep and set(rep) <= letters):
                fails.append("mcq key must be a list of existing option letters")
        if json.dumps(rep) == json.dumps(find):
            fails.append("answer edit changes nothing")
    elif fld == "questionType":
        if rep not in ("scq", "mcq", "integerQuestion") or rep == pq.q.qtype:
            fails.append("invalid question type change")
    return fails


def public_edit(edit: dict | None) -> dict | None:
    """The edit as written to results.json (internal keys dropped)."""
    if not edit:
        return None
    return {"field": edit["field"], "find": edit["find"], "replace": edit["replace"]}
