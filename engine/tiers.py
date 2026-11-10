"""LLM tier calls. Each returns *signals*; nothing here decides a verdict or a route."""
from __future__ import annotations

import json
import re

from . import config
from .checks import DEFINITE, SIGNAL, ParsedQuestion
from .decide import OptionVerdict, SolverSig
from .llm import Client
from .mathexpr import ExprError, evaluate, match_integer_key, match_option, parse_quantity, unit_info
from .prompts import load_prompt

_PROMPTS: dict = {}


def prompt_for(role: str):
    _, _, name, version, _ = config.ROLES[role]
    if (name, version) not in _PROMPTS:
        _PROMPTS[(name, version)] = load_prompt(name, version)
    return _PROMPTS[(name, version)]


def family(role: str) -> str:
    return config.FAMILY.get(config.ROLES[role][1], config.ROLES[role][1].split("/")[0])


# --------------------------------------------------------------------------
# Shared inputs
# --------------------------------------------------------------------------

def options_block(pq: ParsedQuestion) -> str:
    if not pq.has_options:
        return "No options: this is an integer-answer question."
    return "Options:\n" + "\n".join(f"({L}) {t}" for L, t in pq.split.options_text.items())


_ASKED = [re.compile(r"\(\s*in\s+([^)]{1,20})\)", re.I),
          re.compile(r"_{2,}\s*([A-Za-zμΩÅ°%][\w/^°]*)"),
          re.compile(r"\bin\s+(?:units?\s+of\s+)?([A-Za-zμΩÅ°%][\w/^°]*)", re.I)]


def asked_unit(stem: str) -> str:
    """The unit the question asks the answer in, if it states one."""
    for pat in _ASKED:
        for m in pat.finditer(stem):
            u = m.group(1).strip().rstrip(".,")
            if unit_info(u):
                return u
    return ""


def _value(expr) -> float | None:
    if expr in (None, "", "null"):
        return None
    try:
        return evaluate(str(expr))
    except ExprError:
        return None


# --------------------------------------------------------------------------
# Tiers
# --------------------------------------------------------------------------

def run_guard(client: Client, report_id: str, comment: str) -> dict:
    p = prompt_for("guard")
    msgs = p.render(comment=(comment or "")[: config.GUARD_MAX_CHARS] or "(empty)")
    r = client.call("guard", p, msgs, stage="guard", tier=1, subject=report_id, json_mode=False, temperature=None)
    raw = (r.content or "").strip()
    score, label = None, ""
    m = re.search(r"[-+]?\d*\.\d+(?:e[-+]?\d+)?|[-+]?\d+(?:e[-+]?\d+)?", raw)
    if re.search(r"malicious|jailbreak|injection|unsafe", raw, re.I):
        label, score = "malicious", 1.0
    elif re.search(r"benign|safe", raw, re.I):
        label, score = "benign", 0.0
    elif m:
        try:
            score = float(m.group(0))
            label = "score"
        except ValueError:
            pass
    flag = score is not None and score >= config.GUARD_THRESHOLD
    return {"score": score, "label": label or "unparsed", "flag": flag, "raw": raw[:80],
            "model_answered": r.model_answered}


def run_solver(client: Client, role: str, pq: ParsedQuestion, stem_text: str | None = None) -> tuple[SolverSig, dict]:
    """Blind solve. `stem_text` replaces the stem for a re-solve of an edited question (D-021)."""
    p = prompt_for(role)
    resolve = stem_text is not None
    msgs = p.render(question_type=pq.q.qtype, question_text=stem_text if resolve else pq.split.stem_text,
                    options_block=options_block(pq))
    r = client.call(role, p, msgs, stage="resolve" if resolve else "solve",
                    tier=4 if resolve else (1 if role == "solver_1" else 2),
                    subject=f"{pq.q.id}:resolve" if resolve else pq.q.id)
    d = r.data or {}
    sig = SolverSig(role=role, family=family(role), ok=bool(r.data), missing=_missing(d.get("missing_information")),
                    issues=tuple(d.get("question_issues") or ()), unit=str(d.get("unit") or ""))
    if not r.data:
        sig.error = "no valid JSON"
        return sig, d
    sig.working = str(d.get("working") or "")[:300]
    sig.value = _value(d.get("final_expression"))
    if d.get("final_expression") not in (None, "", "null") and sig.value is None:
        sig.error = f"unevaluable expression: {str(d.get('final_expression'))[:60]}"
    chosen = tuple(sorted({str(x).strip().upper()[:1] for x in (d.get("chosen_options") or [])}
                          & set(pq.split.letters)))
    if pq.has_options:
        numeric = None
        if sig.value is not None:
            unit = sig.unit or asked_unit(pq.split.stem_text)
            numeric, hits = match_option(sig.value, unit, pq.split.options_text)
        numeric_options = all(parse_quantity(t) for t in pq.split.options_text.values() if t)
        if numeric:
            sig.letters = (numeric,)
            if chosen and chosen != (numeric,):
                sig.issues = sig.issues + (f"chosen {chosen} but value matches ({numeric}); code uses the value",)
        elif sig.value is not None and numeric_options:
            # never the closest option: a value that matches no option (or several) maps to no letter
            sig.letters = tuple(x for x in chosen if x in hits) if len(hits) > 1 else ()
            if chosen and not sig.letters:
                sig.issues = sig.issues + (f"chosen {chosen} but value {sig.value:g} {sig.unit} matches no option; "
                                           "code ignores the pick",)
        else:
            # no usable expression (or statement options): the picked letter is this solver's answer
            sig.letters = chosen
            sig.from_letter = bool(chosen) and sig.value is None
    return sig, d


_NONE_WORDS = {"", "none", "null", "n/a", "na", "nothing", "no", "nil", "none.", "nothing is missing"}


def _missing(x) -> str | None:
    """missing_information, with the model's ways of saying 'nothing' mapped to None."""
    if x is None:
        return None
    t = str(x).strip()
    return None if t.lower().rstrip(".") in _NONE_WORDS else t


def integer_match(sig: SolverSig, pq: ParsedQuestion) -> bool | None:
    if sig.value is None or not pq.answer.values:
        return None
    try:
        key = float(pq.answer.values[0])
    except ValueError:
        return None
    asked = asked_unit(pq.split.stem_text)
    return match_integer_key(sig.value, sig.unit or asked, key, asked or sig.unit)


def run_extract(client: Client, pq: ParsedQuestion) -> dict:
    p = prompt_for("extract")
    msgs = p.render(question_text=pq.split.stem_text, options_block=options_block(pq),
                    solution_text=pq.solution_text or "(no solution stored)")
    r = client.call("extract", p, msgs, stage="extract", tier=2, subject=pq.q.id)
    d = r.data or {}
    out = {"ok": bool(r.data), "value": _value(d.get("final_expression")), "unit": str(d.get("unit") or ""),
           "option_named": (str(d.get("option_named") or "").strip().upper()[:1] or None),
           "statement": str(d.get("final_statement") or "")[:160], "letters": None, "shown": ""}
    if not r.data:
        return out
    if pq.has_options:
        if out["option_named"] in pq.split.letters:
            out["letters"] = (out["option_named"],)
            out["shown"] = f"({out['option_named']})"
        elif out["value"] is not None:
            L, _ = match_option(out["value"], out["unit"] or asked_unit(pq.split.stem_text), pq.split.options_text)
            if L:
                out["letters"], out["shown"] = (L,), f"{out['value']:g} {out['unit']} = ({L})".strip()
            else:
                out["letters"], out["shown"] = ("?",), f"{out['value']:g} {out['unit']} (no option)".strip()
    elif out["value"] is not None:
        sig = SolverSig("extract", "", True, out["value"], out["unit"])
        m = integer_match(sig, pq)
        out["letters"] = (pq.answer.values[0],) if m else (f"{out['value']:g}",)
        out["shown"] = f"{out['value']:g} {out['unit']}".strip()
    return out


def run_audit(client: Client, pq: ParsedQuestion) -> dict:
    p = prompt_for("audit")
    msgs = p.render(question_text=pq.split.stem_text, options_block=options_block(pq),
                    solution_text=pq.solution_text or "(no solution stored)")
    r = client.call("audit", p, msgs, stage="audit", tier=2, subject=pq.q.id)
    d = r.data or {}
    vals = d.get("values_not_in_question") or []
    return {"ok": bool(r.data),
            "values_not_in_question": [v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in vals],
            "contradiction": bool(d.get("contradiction")), "contradiction_quote": d.get("contradiction_quote") or "",
            "about_other_question": bool(d.get("about_other_question")),
            "other_question_quote": d.get("other_question_quote") or ""}


def run_option_check(client: Client, role: str, pq: ParsedQuestion, cand: str, text: str) -> OptionVerdict:
    p = prompt_for(role)
    msgs = p.render(question_text=pq.split.stem_text, options_block=options_block(pq), option_letter=cand,
                    option_text=text)
    r = client.call(role, p, msgs, stage="option_check" if role == "option_check" else "tiebreak",
                    tier=3, subject=f"{pq.q.id}:{cand}")
    d = r.data or {}
    v = str(d.get("verdict") or "").strip().lower()
    return OptionVerdict(role, family(role), v if v in ("correct", "incorrect", "cannot_tell") else "cannot_tell",
                         str(d.get("reason") or "")[:200], str(d.get("own_answer") or "")[:160])


def run_value_check(client: Client, role: str, pq: ParsedQuestion, cand: str, value_text: str) -> OptionVerdict:
    """integerQuestion counterpart of run_option_check: is this value the correct answer?"""
    p = prompt_for(role)
    msgs = p.render(question_text=pq.split.stem_text, candidate_value=value_text)
    r = client.call(role, p, msgs, stage="value_check" if role == "value_check" else "tiebreak",
                    tier=3, subject=f"{pq.q.id}:{cand}")
    d = r.data or {}
    v = str(d.get("verdict") or "").strip().lower()
    return OptionVerdict(role, family(role), v if v in ("correct", "incorrect", "cannot_tell") else "cannot_tell",
                         str(d.get("reason") or "")[:200], str(d.get("own_answer") or "")[:160])


def run_triage(client: Client, pq: ParsedQuestion, report, task: str, taxonomy: dict, signals_text: dict) -> dict:
    p = prompt_for("triage")
    verdicts = "\n".join(f"- {k}: {v}" for k, v in taxonomy["verdicts"].items())
    repairs = "\n".join(f"- {k}: fields={v['fields']}, auto={str(v['auto']).lower()}. {v['label']}"
                        for k, v in taxonomy["repairs"].items())
    msgs = p.render(task_block=task, verdicts_block=verdicts, repairs_block=repairs, question_type=pq.q.qtype,
                    question_text=pq.split.stem_text, options_block=options_block(pq),
                    stored_answer=json.dumps(pq.q.answer_raw, ensure_ascii=False),
                    solution_text=pq.solution_text or "(no solution stored)", comment=report.comment or "(empty)",
                    **signals_text)
    r = client.call("triage", p, msgs, stage="triage", tier=4, subject=report.report_id)
    d = r.data or {}
    v = d.get("verdict") if d.get("verdict") in taxonomy["verdicts"] else None
    rep = d.get("repair") if d.get("repair") in taxonomy["repairs"] else None
    return {"ok": bool(r.data), "verdict": v, "repair": rep, "edit": d.get("edit") if isinstance(d.get("edit"), dict) else None,
            "option_content": d.get("option_content") or None, "disputed_item": d.get("disputed_item"),
            "other_problems": d.get("other_problems") or [], "evidence": str(d.get("evidence") or "")[:300],
            "invalid_keys": [k for k in ("verdict", "repair") if d.get(k) not in (None, "", "null")
                             and d.get(k) not in (taxonomy["verdicts"] if k == "verdict" else taxonomy["repairs"])]}


_INTERNAL = re.compile(r"\b(verdict|repair|taxonomy|faculty_review|auto_apply|no_change|signal|triage)\b", re.I)
_CLAIMS_FIX = re.compile(r"\b(fixed|corrected|updated|changed|ho gaya|kar diya)\b", re.I)


_REMOVED = re.compile(r"\b(remov\w*|delet\w*|hidden|hide|taken down|hata\w*)\b", re.I)


_LETTER_PATS = [re.compile(r"\(([A-E])\)"), re.compile(r"\boption\s+([A-E])\b", re.I),
                re.compile(r"\banswer\s+(?:is\s+|hai\s+)?\(?([A-E])\b(?!\w)")]
_NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_HINGLISH_MARKERS = {"hai", "nahi", "nhi", "kyu", "kyun", "kyunki", "chahiye", "galat", "mein", "ki", "ka", "ke",
                     "toh", "kya", "raha", "rha", "diya", "hona", "lekin", "bhi", "aapka", "aapne", "sahi", "tha",
                     "thi", "hain", "karo", "karein", "dhyan", "hoga", "lagta", "liye", "abhi", "yeh", "ye", "woh"}
_YOUR_ANSWER_WRONG = re.compile(r"\b(?:your|aapka|tumhara)\s+(?:answer|ans|attempt|jawab)\b(?:[^.!?]|\.(?=\d))*"
                                r"\b(?:not|wrong|incorrect|galat|nahi)\b", re.I)
_CORRECT_IS = re.compile(r"\bcorrect\s+(?:answer|option)\s+(?:is|hai)\s*\(?([A-E])\b(?!\w)", re.I)


def _letters(text: str) -> set:
    return {m.group(1).upper() for p in _LETTER_PATS for m in p.finditer(text or "")}


def _numbers(text: str) -> list[float]:
    return [float(x) for x in _NUM.findall(text or "")]


def check_reply(text: str, route: str, syllabus: bool = False, *, language: str = "english", facts: str = "",
                comment: str = "", proposed_answer: bool = True) -> list[str]:
    """Code checks on the student reply. Any failure -> the caller uses a code-built template instead."""
    fails = []
    if syllabus and _REMOVED.search(text or ""):
        fails.append("syllabus reply mentions removal (the question stays live)")
    if facts:
        extra = _letters(text) - _letters(facts)
        if extra:
            fails.append(f"names option(s) {sorted(extra)} not in the facts")
        allowed = _numbers(facts) + _numbers(comment)
        stray = [n for n in _numbers(text) if not any(abs(n - a) <= 1e-9 * max(1.0, abs(a)) for a in allowed)]
        if stray:
            fails.append(f"states value(s) {stray[:3]} not in the facts")
        correct = {m.group(1).upper() for m in re.finditer(r"Correct answer: \(([A-E])\)", facts)}
        wrong = {m.group(1).upper() for m in _CORRECT_IS.finditer(text or "")} - correct
        if wrong:
            fails.append(f"calls {sorted(wrong)} correct, which the facts do not")
    if language == "hinglish":
        words = set(re.findall(r"[a-z]+", (text or "").lower()))
        if len(words & _HINGLISH_MARKERS) < 2:
            fails.append("reply should be in Hinglish")
    if not proposed_answer and _YOUR_ANSWER_WRONG.search(text or ""):
        fails.append("says the student's answer was wrong, but they proposed none")
    first = re.split(r"(?<=[.!?;])\s+", (text or "").strip(), maxsplit=1)[0]
    if _YOUR_ANSWER_WRONG.match(first.strip()) or re.match(r"\s*(?:that'?s|this is|it'?s)\s+(?:not\s+correct|wrong|"
                                                               r"incorrect)", first, re.I):
        fails.append("opens by telling the student their answer is wrong")
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if x]
    if not text or not text.strip():
        fails.append("empty")
    if len(sentences) > 3:
        fails.append("more than 3 sentences")
    if _INTERNAL.search(text or ""):
        fails.append("internal label")
    if route != "auto_apply" and _CLAIMS_FIX.search(text or "") and not re.search(
            r"\b(will|teacher|faculty|check|review)\b", text or "", re.I):
        fails.append("claims a fix that is not live")
    return fails


def run_reply(client: Client, report, language: str, verdict: str, route: str, facts: str,
              syllabus: bool = False, proposed_answer: bool = True) -> tuple[str, list]:
    p = prompt_for("reply")
    msgs = p.render(comment=report.comment or "(empty)", language=language, verdict=verdict, route=route,
                    outcome_facts=facts)
    r = client.call("reply", p, msgs, stage="reply", tier=4, subject=report.report_id, temperature=0.3)
    text = str((r.data or {}).get("student_reply") or "").strip()
    return text, check_reply(text, route, syllabus, language=language, facts=facts, comment=report.comment or "",
                             proposed_answer=proposed_answer)


def findings_text(findings) -> str:
    rows = [f"- [{f.strength}] {f.check}: {f.detail}" for f in findings if f.strength in (DEFINITE, SIGNAL)]
    return "\n".join(rows) or "- none"
