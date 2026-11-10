"""Per-question rule checks.

Every rule here is generic: it looks at the structure and text of a record,
never at a specific question or report id.

Each finding has a strength:
  definite  - code is certain the defect exists (e.g. a blank option)
  signal    - worth a look, but code cannot decide on its own
              (spelling suspects, answer_form, solution/key disagreement)
  weak      - noisy hint, passed to later tiers but not counted as a finding
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .loader import Question
from .parse import (LETTERS, NormalizedAnswer, SplitQuestion, grow_unique, html_to_text,
                    locate_raw, normalize_answer, split_options)

DEFINITE, SIGNAL, WEAK = "definite", "signal", "weak"


@dataclass
class Finding:
    check: str
    repair: str | None          # taxonomy repair this points at, if any
    strength: str
    field: str                  # question | solution | answer
    detail: str
    evidence_text: str = ""
    evidence_raw: str | None = None
    evidence_raw_unique: bool = False
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {
            "check": self.check, "repair": self.repair, "strength": self.strength,
            "field": self.field, "detail": self.detail,
            "evidence_text": self.evidence_text, "evidence_raw": self.evidence_raw,
            "evidence_raw_unique": self.evidence_raw_unique,
        }
        if self.data:
            d["data"] = self.data
        return d


@dataclass
class ParsedQuestion:
    q: Question
    split: SplitQuestion
    solution_text: str
    answer: NormalizedAnswer
    has_options: bool

    @property
    def question_text(self) -> str:
        return " ".join([self.split.stem_text, *self.split.options_text.values()])

    @property
    def all_text(self) -> str:
        return self.question_text + " " + self.solution_text


def parse_question(q: Question) -> ParsedQuestion:
    has_options = q.qtype in ("scq", "mcq")
    sq = split_options(q.question_html, has_options)
    letters = sq.letters or tuple(LETTERS)
    return ParsedQuestion(
        q=q, split=sq, solution_text=html_to_text(q.solution_html),
        answer=normalize_answer(q.qtype, q.answer_raw, letters), has_options=has_options,
    )


def _field_raw(pq: ParsedQuestion, fld: str) -> str:
    return pq.q.solution_html if fld == "solution" else pq.q.question_html


def _with_raw(f: Finding, pq: ParsedQuestion, region=None, word: bool = False) -> Finding:
    if f.evidence_text and f.field in ("question", "solution"):
        f.evidence_raw, f.evidence_raw_unique = locate_raw(
            _field_raw(pq, f.field), f.evidence_text, region, whole_word=word)
    return f


# --------------------------------------------------------------------------
# Structural checks
# --------------------------------------------------------------------------

def check_options(pq: ParsedQuestion) -> list[Finding]:
    out: list[Finding] = []
    if not pq.has_options:
        return out
    sq, raw = pq.split, pq.q.question_html
    keyed = set(pq.answer.values)
    missing = [L for L in LETTERS if L not in sq.letters]
    if missing:
        f = Finding(
            "option_missing", "option_repair", DEFINITE, "question",
            f"Only {len(sq.letters)} option(s) stored ({', '.join(sq.letters) or 'none'}); "
            f"missing {', '.join(missing)}.",
            data={"missing": missing, "missing_is_keyed": bool(keyed & set(missing))},
        )
        if sq.letters:
            last = sq.letters[-1]
            s, e = sq.option_spans[last]
            f.evidence_text = f"({last}) {sq.options_text[last]}"
            f.evidence_raw, f.evidence_raw_unique = grow_unique(raw, s, e)
        out.append(f)
    for L in sq.letters:
        if not sq.options_text[L].strip():
            s, e = sq.option_spans[L]
            ev, uniq = grow_unique(raw, s, e)
            out.append(Finding(
                "option_blank", "option_repair", DEFINITE, "question",
                f"Option ({L}) is blank" + (" and it is the keyed answer." if L in keyed else "."),
                evidence_text=f"({L})", evidence_raw=ev, evidence_raw_unique=uniq,
                data={"letter": L, "blank_is_keyed": L in keyed},
            ))
    seen: dict[str, str] = {}
    for L in sq.letters:
        key = re.sub(r"\s+", " ", sq.options_text[L]).strip().lower()
        if not key:
            continue
        if key in seen:
            out.append(_with_raw(Finding(
                "identical_options", "identical_options", DEFINITE, "question",
                f"Options ({seen[key]}) and ({L}) are identical: '{sq.options_text[L]}'.",
                evidence_text=sq.options_text[L], data={"letters": [seen[key], L]},
            ), pq, sq.option_spans[L]))
        else:
            seen[key] = L
    return out


def check_answer(pq: ParsedQuestion) -> list[Finding]:
    a, q = pq.answer, pq.q
    raw_repr = json.dumps(q.answer_raw, ensure_ascii=False)  # the stored value, exactly
    flags = set(a.flags)
    if q.qtype == "mcq" and len(a.values) == 1 and flags <= {"empty_element"}:
        # A multiple-correct question can legitimately have one answer, so this is a signal.
        return [Finding(
            "mcq_single_answer", "type_mismatch", SIGNAL, "answer",
            f"Stored as multiple-correct but the key has one answer ({a.values[0]})"
            + (" plus an empty element" if "empty_element" in flags else "") + f": {raw_repr}.",
            evidence_text=raw_repr, evidence_raw=raw_repr, evidence_raw_unique=True,
            data={"normalized": list(a.values), "flags": sorted(flags)},
        )]
    if flags:
        return [Finding(
            "answer_malformed", "answer_key", DEFINITE, "answer",
            f"Stored answer {raw_repr} is malformed ({', '.join(sorted(flags))}); "
            f"normalised: {list(a.values)}.",
            evidence_text=raw_repr, evidence_raw=raw_repr, evidence_raw_unique=True,
            data={"normalized": list(a.values), "flags": sorted(flags)},
        )]
    return []


# --------------------------------------------------------------------------
# Text checks
# --------------------------------------------------------------------------

_LATEX = re.compile(r"\\[A-Za-z]+(?:\{[^{}]*\})*")
_VISIBLE_TAG = re.compile(r"</?(?:sup|sub|span|br|p|div|b|i|math|mi|mn|mo)\b[^>]*>", re.I)
_LONE_AMP = re.compile(r"<(m[ion]|mtext)\b[^>]*>\s*(?:&amp;|&)\s*</\1>")


def check_markup(pq: ParsedQuestion) -> list[Finding]:
    out: list[Finding] = []
    for fld, text in (("question", pq.question_text), ("solution", pq.solution_text)):
        for m in _LATEX.finditer(text):
            out.append(_with_raw(Finding(
                "latex_in_text", "markup_leak", DEFINITE, fld,
                f"Raw LaTeX visible in {fld}: {m.group(0)}", evidence_text=m.group(0)), pq))
        for m in _VISIBLE_TAG.finditer(text):
            out.append(_with_raw(Finding(
                "html_tag_in_text", "markup_leak", DEFINITE, fld,
                f"Escaped HTML tag visible in {fld}: {m.group(0)}", evidence_text=m.group(0)), pq))
        raw = _field_raw(pq, fld)
        amps = list(_LONE_AMP.finditer(raw))
        if amps:
            ev, uniq = grow_unique(raw, amps[0].start(), amps[0].end())
            out.append(Finding(
                "alignment_marker_leak", "markup_leak", DEFINITE, fld,
                f"{len(amps)} lone '&' token(s) in {fld} MathML (LaTeX alignment markers); "
                f"a browser shows them as a visible '&'.",
                evidence_text="&", evidence_raw=ev, evidence_raw_unique=uniq, data={"count": len(amps)},
            ))
    return out


_EXAM = re.compile(
    r"[\(\[]?\s*(?:JEE\s*(?:Main|Mains|Advanced|Adv\.?)?|NEET(?:\s*UG)?|AIPMT|AIIMS|BITSAT|"
    r"KCET|MHT[\s-]*CET|EAMCET|WBJEE|CBSE|COMEDK|VITEEE)\b[^()\[\]\n]{0,25}?(?:19|20)\d{2}"
    r"[^()\[\]\n]{0,25}?[\)\]]?", re.I)


def check_exam_reference(pq: ParsedQuestion) -> list[Finding]:
    out = []
    for fld, text in (("question", pq.question_text), ("solution", pq.solution_text)):
        for m in _EXAM.finditer(text):
            tag = m.group(0).strip()
            out.append(_with_raw(Finding(
                "exam_reference", "exam_reference", DEFINITE, fld,
                f"Exam/source tag in {fld}: {tag}", evidence_text=tag), pq))
    return out


_FIGURE = re.compile(
    r"\b(?:as shown|shown in (?:the )?(?:figure|fig|diagram|graph)|(?:given|following|adjacent|above|below) "
    r"(?:figure|fig|diagram|graph|circuit)|in (?:the )?(?:figure|fig\.?|diagram)|see (?:the )?figure|"
    r"figure (?:shows|below|above))\b", re.I)


def check_diagram(pq: ParsedQuestion) -> list[Finding]:
    has_image = bool(pq.q.ques_images) or "<img" in pq.q.question_html.lower()
    m = _FIGURE.search(pq.question_text)
    if m and not has_image:
        return [_with_raw(Finding(
            "figure_missing", "diagram", DEFINITE, "question",
            f"Stem refers to a figure ('{m.group(0)}') but the question has no image.",
            evidence_text=m.group(0)), pq)]
    return []


def check_solution_present(pq: ParsedQuestion) -> list[Finding]:
    n = len(pq.solution_text.strip())
    if n == 0:
        return [Finding("solution_empty", "solution_missing", DEFINITE, "solution", "Solution is empty.")]
    if n < 40:
        return [Finding("solution_very_short", "solution_missing", WEAK, "solution",
                        f"Solution is only {n} characters: '{pq.solution_text}'.",
                        evidence_text=pq.solution_text)]
    return []


# --------------------------------------------------------------------------
# answer_form (signal only)
# --------------------------------------------------------------------------

UNITS = {
    "m", "cm", "mm", "km", "nm", "μm", "um", "s", "sec", "second", "seconds", "ms", "min", "minute",
    "minutes", "hr", "hour", "hours", "day", "days", "year", "years", "n", "newton", "newtons", "j",
    "joule", "joules", "ev", "kev", "mev", "w", "watt", "watts", "kw", "v", "volt", "volts", "mv", "kv",
    "a", "ma", "μa", "amp", "ampere", "ω", "ohm", "ohms", "k", "kelvin", "°c", "°", "degree", "degrees",
    "hz", "khz", "kg", "g", "mg", "mol", "pa", "kpa", "atm", "d", "dioptre", "dioptres", "diopter",
    "diopters", "rad", "radian", "radians", "t", "tesla", "c", "coulomb", "μc", "f", "μf", "farad", "h",
    "mh", "henry", "l", "litre", "litres", "ml", "%", "percent", "m/s", "km/h", "m/s^2", "rad/s",
    "mm^3", "cm^3", "m^3", "m^2", "cm^2", "n/m", "n/m^2", "kg/m^3", "j/k", "cal", "kcal",
}
_UNIT_STATED = re.compile(
    r"\(\s*in\s+[^)]{1,25}\)"                                                       # (in cm)
    r"|\bin\s+(?:the\s+)?(?:SI\s+units?|units?\s+of\s+\S+|[A-Za-zμΩ°%][\w/^°Ω\-]*)"  # in cm / in units of
    r"|_{2,}\s*[A-Za-zμΩ°%]"                                                        # ____ mm^3
    r"|\b(?:nearest|rounded|round off|decimal|significant)\b", re.I)
_DIMENSIONLESS_ASK = re.compile(
    r"\b(?:value of\s+['‘’\"]?\s*\w{1,3}\s*['‘’\"]?(?:\s|$|[.?])|ratio|how many|number of|the integer)", re.I)
_NUM_UNIT = re.compile(r"(?<![\^_\w.])\d+(?:\.\d+)?\s*([A-Za-zμΩ°%][\w/^°]*)")


def _stated_unit(text: str) -> bool:
    for m in _UNIT_STATED.finditer(text):
        s = m.group(0).lower()
        if s.startswith(("(", "_")) or "unit" in s or re.search(
                r"nearest|rounded|round off|decimal|significant", s):
            return True
        if re.sub(r"^in\s+(?:the\s+)?", "", s).strip() in UNITS:
            return True
    return False


def check_answer_form(pq: ParsedQuestion) -> list[Finding]:
    if pq.q.qtype != "integerQuestion":
        return []
    stem = pq.split.stem_text
    if _stated_unit(stem) or _DIMENSIONLESS_ASK.search(stem):
        return []
    sol_units = [m.group(1) for m in _NUM_UNIT.finditer(pq.solution_text) if m.group(1).lower() in UNITS]
    if not sol_units:
        return []
    tail = stem[-60:]
    return [_with_raw(Finding(
        "unit_not_stated", "answer_form", SIGNAL, "question",
        f"Integer question does not state the unit or form of the answer; the solution works in "
        f"'{Counter(sol_units).most_common(1)[0][0]}'.",
        evidence_text=tail, data={"solution_units": sorted(set(sol_units))}), pq)]


# --------------------------------------------------------------------------
# Spelling (signal only)
# --------------------------------------------------------------------------

_WORD = re.compile(r"(?<![\w^_])[A-Za-z][a-z]+(?![\w^_])")
# Words that get glued to a neighbour ("ofleaf", "riceis"). Prefix-like words such as
# "in", "a", "be" are left out: "incorrect", "inactivation", "below" are real words.
FUNCTION_WORDS = {"of", "to", "is", "the", "and"}


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Optimal-string-alignment distance, early exit above cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
        if min(prev) > cap:
            return cap + 1
    return prev[-1]


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def build_vocab(parsed: list[ParsedQuestion]) -> Counter:
    """Dataset-level vocabulary: word -> number of questions that use it."""
    c: Counter = Counter()
    for pq in parsed:
        c.update(set(words(pq.all_text)))
    return c


def _variant(a: str, b: str) -> bool:
    """Inflection or derivation of one word (produce/produced, activation/inactivation)."""
    return a.startswith(b) or b.startswith(a) or a.endswith(b) or b.endswith(a)


def near_words(w: str, candidates, cap: int = 1) -> list[tuple[str, int]]:
    out = []
    for v in candidates:
        if v == w or abs(len(v) - len(w)) > cap or _variant(v, w):
            continue
        d = edit_distance(w, v, cap)
        if d <= cap:
            out.append((v, d))
    return sorted(out, key=lambda x: (x[1], x[0]))


def check_spelling(pq: ParsedQuestion, vocab: Counter) -> list[Finding]:
    """Signal only. Without a dictionary the dataset itself is the reference, so the
    rule is narrow: a word used nowhere else in the dataset that is one edit away from
    a word in the same question, or a function word glued to a word that the same
    question also uses on its own."""
    out: list[Finding] = []
    own = Counter(words(pq.all_text))
    flagged: set[str] = set()
    for fld, text in (("question", pq.question_text), ("solution", pq.solution_text)):
        for orig in _WORD.findall(text):
            w = orig.lower()
            if w in flagged or len(w) < 5 or vocab[w] > 1:
                continue
            near = near_words(w, [v for v in own if len(v) >= 5])
            if near:
                v = near[0][0]
                sv, sw = (own[v], vocab[v]), (own[w], vocab[w])
                if sv < sw or (sv == sw and v < w):
                    continue  # the other spelling is the suspect; reported from its side
                flagged.add(w)
                detail = (f"'{orig}' and '{v}' differ by one edit; one is likely misspelled." if sv == sw
                          else f"'{orig}' looks like a misspelling of '{v}' (one edit).")
                out.append(_with_raw(Finding(
                    "spelling_suspect", "spelling", SIGNAL, fld, detail,
                    evidence_text=orig, data={"word": orig, "suggest": v}), pq, word=True))
                continue
            for i in range(2, len(w) - 1):
                a, b = w[:i], w[i:]
                if ((a in FUNCTION_WORDS and len(b) >= 3 and own[b] >= 1) or
                        (b in FUNCTION_WORDS and len(a) >= 3 and own[a] >= 1)):
                    flagged.add(w)
                    out.append(_with_raw(Finding(
                        "run_together_words", "spelling", SIGNAL, fld,
                        f"'{orig}' looks like two words run together: '{a} {b}'.",
                        evidence_text=orig, data={"word": orig, "suggest": f"{a} {b}"}), pq, word=True))
                    break
    return out


def find_word_near(word: str, pq: ParsedQuestion, cap: int = 2) -> list[tuple[str, str, int]]:
    """Words in the question's text equal or close to `word`: (field, text word, distance)."""
    w = word.lower()
    hits = []
    for fld, text in (("question", pq.question_text), ("solution", pq.solution_text)):
        for orig in set(_WORD.findall(text)):
            o = orig.lower()
            if o == w:
                hits.append((fld, orig, 0))
            elif abs(len(o) - len(w)) <= cap and not _variant(o, w) and (d := edit_distance(o, w, cap)) <= cap:
                hits.append((fld, orig, d))
    return sorted(hits, key=lambda h: h[2])


# --------------------------------------------------------------------------
# Solution vs key (signal only: code cannot tell which side is wrong)
# --------------------------------------------------------------------------

_SCI = (r"(?<![\^_\w.])([+\-−]?\d+(?:\.\d+)?)(?:\s*[x×]\s*10\^\(?([+\-−]?\d+)\)?)?"
        r"(?:\s*√\(?(\d+(?:\.\d+)?))?")
_NUMBER = re.compile(_SCI)
_VALUE_AT_START = re.compile(r"\s*" + _SCI + r"(?:\s*/\s*(\d+(?:\.\d+)?))?")
# After a stated value: an optional unit, then end / punctuation / a space not followed by an operator.
_AFTER_VALUE = re.compile(r"\s*(?:[A-Za-zμΩ°%][A-Za-z°/]*(?:\^[−\-]?\d)?)?\s*(?:$|[.,;:)]|\s+(?![\d×*/^+\-−(√]))")
_RELATION = re.compile(r"[=≈⇒→∴]")
_OPTION_FN_PREFIX = re.compile(r"\s*(?:[a-z]{2,6}\^?[−\-]?1?\()?(?=[+\-−]?\d)")
_SOL_LETTER = re.compile(
    r"(?:correct\s+(?:answer|option|choice)\s+is|answer\s*(?:is)?\s*[:.]?|ans\.?\s*[:.]?|option|"
    r"solution\s*:|hence,?)\s*\(\s*([a-dA-D])\s*\)", re.I)


def _num(groups) -> float | None:
    base, exp, root = groups[0], groups[1], groups[2]
    try:
        v = float(base.replace("−", "-"))
        if exp:
            v *= 10 ** float(exp.replace("−", "-"))
        if root:
            v *= math.sqrt(float(root))
        return v
    except ValueError:
        return None


def option_value(text: str) -> float | None:
    """Numeric value of an option, only if the option *is* a number (optionally inside f^-1(...))."""
    m = _OPTION_FN_PREFIX.match(text)
    if not m:
        return None
    n = _NUMBER.match(text, m.end())
    return _num(n.groups()) if n else None


def stated_values(text: str) -> list[float]:
    """Values a solution states as results: '= 50 V', '≈ 1.44min', '= 4/1'.
    A relation followed by more expression ('= 1/8 2q/ε') is not a result."""
    rels = [m.start() for m in _RELATION.finditer(text)]
    out = []
    for i, pos in enumerate(rels):
        if text[pos] not in "=≈":
            continue
        seg = text[pos + 1: rels[i + 1] if i + 1 < len(rels) else len(text)]
        m = _VALUE_AT_START.match(seg)
        if not m or not _AFTER_VALUE.match(seg, m.end()):
            continue
        v = _num(m.groups()[:3])
        if v is not None and m.group(4):
            d = float(m.group(4))
            v = v / d if d else None
        if v is not None:
            out.append(v)
    return out


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=5e-3, abs_tol=1e-9)


def solution_letter(text: str) -> str | None:
    hits = _SOL_LETTER.findall(text)
    return hits[-1].upper() if hits else None


def check_solution_vs_key(pq: ParsedQuestion) -> list[Finding]:
    sol = pq.solution_text
    keyed = set(pq.answer.values)
    if not sol or not keyed:
        return []
    if pq.has_options:
        letter = solution_letter(sol)
        if letter:
            if letter in keyed:
                return [Finding("solution_supports_key", None, WEAK, "solution",
                                f"Solution names the keyed option ({letter}).", data={"solution_letter": letter})]
            return [_with_raw(Finding(
                "solution_names_other_option", None, SIGNAL, "solution",
                f"Solution names option ({letter}); key is {sorted(keyed)}.",
                evidence_text=f"({letter.lower()})", data={"solution_letter": letter}), pq)]
        vals = stated_values(sol)
        if not vals:
            return []
        fv = vals[-1]
        matches = [L for L, t in pq.split.options_text.items()
                   if (ov := option_value(t)) is not None and close(ov, fv)]
        if len(matches) == 1 and matches[0] not in keyed:
            return [Finding(
                "solution_value_matches_other_option", None, SIGNAL, "solution",
                f"Solution's final value {fv:g} matches option ({matches[0]}), not the key {sorted(keyed)}.",
                evidence_text=f"{fv:g}", data={"solution_value": fv, "solution_letter": matches[0]})]
        if len(matches) == 1:
            return [Finding("solution_supports_key", None, WEAK, "solution",
                            f"Solution's final value {fv:g} matches the keyed option ({matches[0]}).",
                            data={"solution_value": fv, "solution_letter": matches[0]})]
        return []
    # integer question: the key counts as supported if the solution states it as a result anywhere
    try:
        key = float(next(iter(keyed)))
    except ValueError:
        return []
    vals = stated_values(sol)
    if not vals:
        return []
    if any(close(v, key) for v in vals):
        return [Finding("solution_supports_key", None, WEAK, "solution",
                        f"Solution states the key value {key:g} as a result.", data={"solution_values": vals})]
    return [Finding(
        "solution_value_differs_from_key", None, SIGNAL, "solution",
        f"Solution never states the key {key:g}; its last stated value is {vals[-1]:g} (could be a wrong "
        f"key, a wrong solution step, or a unit/form conversion).",
        evidence_text=f"{vals[-1]:g}", data={"solution_values": vals, "key": key})]


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUMBER.finditer(text):
        s = m.group(1).replace("−", "-").lstrip("+-")
        if s == "10" and text[m.end(1):m.end(1) + 1] == "^":
            continue  # base of a power of ten
        out.add(s.rstrip("0").rstrip(".") if "." in s else s)
    return out


def check_solution_grounding(pq: ParsedQuestion) -> list[Finding]:
    """Weak hints: does the solution use the stem's given values, and values the stem never gives?"""
    out: list[Finding] = []
    stem_nums = {n for n in _numbers(pq.split.stem_text) if n not in {"0", "1", "2"}}
    sol_nums = _numbers(pq.solution_text)
    if stem_nums and len(sol_nums) >= 2 and not (stem_nums & sol_nums):
        out.append(Finding(
            "solution_ignores_stem_values", "solution_fix", WEAK, "solution",
            f"Solution uses none of the stem's given values {sorted(stem_nums)}.",
            data={"stem_values": sorted(stem_nums), "solution_values": sorted(sol_nums)}))
    unexplained = sorted(n for n in sol_nums - _numbers(pq.question_text)
                         if n not in {"0", "1", "2", "3", "4", "10"})
    if unexplained:
        out.append(Finding(
            "solution_values_not_in_stem", "stem_data", WEAK, "solution",
            f"Solution uses values not given in the stem: {unexplained[:8]} (many are intermediate results).",
            data={"values": unexplained}))
    return out


# --------------------------------------------------------------------------

def run_checks(pq: ParsedQuestion, vocab: Counter) -> list[Finding]:
    findings: list[Finding] = []
    for fn in (check_options, check_answer, check_markup, check_exam_reference, check_diagram,
               check_solution_present, check_answer_form, check_solution_vs_key,
               check_solution_grounding):
        findings.extend(fn(pq))
    findings.extend(check_spelling(pq, vocab))
    return findings
