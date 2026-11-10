"""Sort a student comment into a claim category and pull out what it asserts.

The comment is untrusted input: it is read for leads, never followed as an
instruction. Keyword lists cover English and common Hinglish. All rules are
generic; nothing here refers to a specific report.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# Priority order: the first matching category becomes `primary`.
CATEGORY_ORDER = (
    "injection", "junk", "language", "app", "display", "syllabus", "wrong_chapter",
    "spelling", "markup", "exam_reference", "figure", "type", "option_identical",
    "option_missing", "answer_form", "stem_data", "solution", "vague", "answer",
)

_INJECTION = [
    r"\bignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|earlier|your)\s+(?:instructions?|prompts?|rules)",
    r"\byou\s+are\s+(?:now\s+)?(?:the|an?|my)\s+[\w\s]{0,20}?(?:bot|assistant|admin|ai|model|system)\b",
    r"\b(?:system\s+prompt|developer\s+mode|jailbreak|dan\s+mode)\b",
    r"\bmark\s+(?:this|the)\s+(?:report|question|case)\s+as\b",
    r"\b(?:disregard|override|bypass)\b.{0,30}\b(?:instructions?|rules|checks?|guards?)\b",
    r"\bact\s+as\s+(?:an?\s+|the\s+)?(?:admin|system|moderator|developer)\b",
    r"</?(?:system|assistant|instructions?)>",
]
_LANGUAGE = r"\b(?:hindi|english|marathi|gujarati|tamil|telugu|bengali|bangla|kannada|malayalam|urdu|odia|punjabi|language|bhasha|translate|translation)\b"
_APP = [
    r"\b(?:clicked|tapped|selected|marked|chose|pressed)\b.{0,30}\b(?:but|and|par|lekin)\b.{0,25}\b(?:saved|recorded|submitted|registered|selected|took|showing|shows|went)\b",
    r"\b(?:app|crash(?:ed|es)?|keyboard|lag(?:ging|gy)?|logged\s+out|timer|not\s+saving|submit\s+button|freez\w*|hang(?:s|ing)?)\b",
]
_DISPLAY = r"\b(?:load(?:ing|s)?|forever|slow|cut(?:\s+off)?|screen|phone|mobile|render(?:ing|ed)?|display(?:ed|ing)?|zoom|overlap\w*|blurry|not\s+visible|font|dikh\s*(?:nahi|nhi)|dikhai)\b"
_SYLLABUS = r"\b(?:syllabus|not\s+in\s+ncert|out\s+of\s+(?:course|ncert)|deleted\s+(?:topic|chapter|portion))\b"
_CHAPTER = r"\b(?:chapter|wrong\s+(?:topic|subject|unit)|why\s+is\s+it\s+in|belongs?\s+to)\b"
_SPELLING = r"\b(?:spell\w*|typo|misspel\w*|galat\s+likha)\b"
_MARKUP = r"(?:\\[a-z]+|\blatex\b|\bcode\b|\bhtml\b|\btags?\b|\bweird\s+(?:symbols?|characters?)|\bgarbage\s+text\b|\$\$)"
_EXAM = r"\b(?:neet|jee|aipmt|aiims|bitsat|kcet|eamcet|cbse)\b.{0,20}\b(?:19|20)\d{2}\b|\b(?:exam\s+name|year\s+(?:written|mentioned))\b"
_FIGURE = r"\b(?:figure|fig|diagram|image|graph|picture|photo|circuit\s+diagram)\b"
_TYPE = r"\b(?:multiple\s+correct|multi[\s-]?correct|single\s+correct|more\s+than\s+one\s+(?:correct|answer)|only\s+one\s+(?:option\s+)?(?:is\s+)?correct|integer\s+type|numerical\s+type|mcq|scq)\b"
_OPTION = r"\boptions?\b"
_IDENTICAL = r"\b(?:same|identical|repeat\w*|duplicate\w*|twice)\b"
_OPTION_MISSING = r"\b(?:missing|blank|empty|khali|nahi\s+(?:hai|di|diya)|not\s+(?:there|given|showing)|only\s+\d|no\s+option)\b"
_UNIT = r"\b(?:unit|units|rounding|round\s+off|decimal\s+places|nearest\s+integer)\b"
_MISSING = r"\b(?:not\s+(?:given|mentioned|provided|stated)|missing|nahi\s+(?:di|diya|hai|he)|nhi\s+(?:di|diya)|how\s+to\s+find|data|incomplete|value\s+(?:is\s+)?not)\b"
_SOLUTION = r"\b(?:solution|sol|explanation|solution\s+me)\b"
# Strong triggers assert something about the answer. Weak ones ("why", "wrong") count
# only when nothing more specific matched or the comment asserts a value.
_ANSWER = [
    r"\b(?:ans|answer|key|answer\s+key|should\s+be|hona\s+chahiye|aana\s+chahiye|aayega|correct\s+answer|marked|got)\b",
    r"\b(?:assertion|reason|statement)\b.{0,25}\b(?:true|false|correct|incorrect|wrong)\b",
]
_ANSWER_WEAK = r"\b(?:galat|wrong|incorrect|kyu|kyun|why)\b"
_VAGUE_WORDS = {"wrong", "galat", "error", "incorrect", "mistake", "bad", "issue", "problem", "question",
                "ques", "q", "is", "hai", "this", "the", "sir", "maam", "please", "pls", "plz", "check"}
_HINGLISH = {"hai", "nahi", "nhi", "kyu", "kyun", "chahiye", "galat", "me", "mein", "ki", "ka", "ke", "toh",
             "karu", "kya", "aa", "raha", "rha", "di", "diya", "hona", "aana", "aayega", "lekin", "par", "bhi"}
_KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")


@dataclass
class Claim:
    comment: str
    primary: str
    categories: list[str]
    injection: bool = False
    hinglish: bool = False
    letters: list[str] = field(default_factory=list)       # option letters the student asserts
    values: list[float] = field(default_factory=list)      # numbers the student asserts as the answer
    disputed: list[float] = field(default_factory=list)    # numbers the student says are wrong ("not 14", "why 130")
    expression: str = ""                                    # non-numeric asserted answer ("tan inverse 2")
    named_words: list[str] = field(default_factory=list)   # words named in a spelling claim
    option_refs: list[str] = field(default_factory=list)   # "option A", "option D is missing"

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "primary", "categories", "injection", "hinglish", "letters", "values", "disputed",
            "expression", "named_words", "option_refs")}


def _any(patterns, text) -> bool:
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(re.search(p, text, re.I) for p in patterns)


def _is_junk(comment: str) -> bool:
    toks = re.findall(r"[A-Za-z]+", comment)
    if not comment.strip():
        return True
    if not toks or re.search(r"\d", comment):
        return False

    def mash(t: str) -> bool:
        t = t.lower()
        if len(t) >= 4 and any(t in row or t[::-1] in row for row in _KEYBOARD_ROWS):
            return True
        return len(t) >= 5 and not re.search(r"[aeiouy]", t)

    return all(mash(t) for t in toks)


def _num(s: str) -> float | None:
    try:
        return float(s.replace("−", "-"))
    except ValueError:
        return None


def _extract_values(comment: str, claim: Claim) -> None:
    c = comment
    low = c.lower()
    # non-numeric asserted forms
    m = re.search(r"\b(tan|sin|cos)\s*(?:inverse|\^?-1|⁻¹)\s*\(?\s*(\d+(?:\.\d+)?)\)?", low)
    if m:
        claim.expression = f"{m.group(1)}^-1({m.group(2)})"
    m_root = re.search(r"(\d+(?:\.\d+)?)\s*(?:root|√)\s*(\d+(?:\.\d+)?)", low)
    ratio = re.search(r"\b(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\b", c)

    disputed_spans = []
    for dm in re.finditer(r"\b(?:not|why|instead\s+of|nahi)\s+(?:the\s+)?([+\-−]?\d+(?:\.\d+)?)", low):
        disputed_spans.append(dm.span(1))
        claim.disputed.append(float(dm.group(1).replace("−", "-")))
    for dm in re.finditer(r"([+\-−]?\d+(?:\.\d+)?)\s*(?:kyu|kyun|kaise)\b", low):
        disputed_spans.append(dm.span(1))
        claim.disputed.append(float(dm.group(1).replace("−", "-")))

    if ratio:
        a, b = float(ratio.group(1)), float(ratio.group(2))
        claim.expression = claim.expression or f"{ratio.group(1)}:{ratio.group(2)}"
        if b:
            claim.values.append(a / b)
        return
    if m_root:
        claim.values.append(float(m_root.group(1)) * math.sqrt(float(m_root.group(2))))
        claim.expression = claim.expression or f"{m_root.group(1)}√{m_root.group(2)}"
        return
    if claim.expression:
        return
    if "=" in c:
        after = re.search(r"=\s*([+\-−]?\d+(?:\.\d+)?)", c[c.rfind("="):])
        if after:
            claim.values.append(float(after.group(1).replace("−", "-")))
            return
    for nm in re.finditer(r"(?<![\w.^])([+\-−]?\d+(?:\.\d+)?)", c):
        if any(a <= nm.start(1) < b for a, b in disputed_spans):
            continue
        v = _num(nm.group(1))
        if v is not None:
            claim.values.append(v)


def _extract_letters(comment: str, claim: Claim) -> None:
    # explicit "option X" references
    for m in re.finditer(r"\boption\s*\(?\s*([a-dA-D])\s*\)?(?![\w])", comment):
        claim.option_refs.append(m.group(1).upper())
    # asserted answer letters: uppercase standalone A-D tokens
    letters = re.findall(r"(?<![\w'’])\(?([A-D])\)?(?![\w'’])", comment)
    claim.letters = list(dict.fromkeys(letters))


def _extract_named_words(comment: str, claim: Claim) -> None:
    quoted = re.findall(r"['‘’\"“”]([A-Za-z][A-Za-z\- ]{1,30}?)['‘’\"“”]", comment)
    pats = [
        r"\bspell(?:ing)?\s+(?:of|for)\s+([A-Za-z]{3,})",
        r"\b([A-Za-z]{3,})\s+(?:ki|ka|ke)?\s*spell(?:ing)?\b",
        r"\b([A-Za-z]{3,})\s+is\s+(?:misspel\w*|spelled\s+wrong)",
        r"\b(?:should\s+be|instead\s+of)\s+['‘’\"“”]?([A-Za-z]{3,})",
    ]
    named = list(quoted)
    for p in pats:
        named += re.findall(p, comment, re.I)
    stop = {"mistake", "error", "the", "this", "option", "wrong", "galat", "spelling", "question", "options"}
    claim.named_words = [w for w in dict.fromkeys(n.strip() for n in named) if w.lower() not in stop]


def classify(comment: str) -> Claim:
    c = (comment or "").strip()
    low = c.lower()
    cats: list[str] = []
    injection = _any(_INJECTION, low)
    if injection:
        cats.append("injection")
    if _is_junk(c):
        cats.append("junk")
    if _any(_LANGUAGE, low):
        cats.append("language")
    if _any(_APP, low):
        cats.append("app")
    if _any(_DISPLAY, low):
        cats.append("display")
    if _any(_SYLLABUS, low):
        cats.append("syllabus")
    if _any(_CHAPTER, low):
        cats.append("wrong_chapter")
    if _any(_SPELLING, low):
        cats.append("spelling")
    if _any(_MARKUP, c):
        cats.append("markup")
    if _any(_EXAM, low):
        cats.append("exam_reference")
    if _any(_FIGURE, low):
        cats.append("figure")
    if _any(_TYPE, low):
        cats.append("type")
    if _any(_OPTION, low) and _any(_IDENTICAL, low):
        cats.append("option_identical")
    if _any(_OPTION, low) and _any(_OPTION_MISSING, low):
        cats.append("option_missing")
    if _any(_UNIT, low):
        cats.append("answer_form")
    if _any(_MISSING, low) and not {"option_missing", "figure", "answer_form"} & set(cats):
        cats.append("stem_data")
    if _any(_SOLUTION, low):
        cats.append("solution")

    claim = Claim(comment=c, primary="", categories=[], injection=injection)
    claim.hinglish = bool(set(re.findall(r"[a-z]+", low)) & _HINGLISH)
    _extract_letters(c, claim)
    _extract_values(c, claim)
    if "spelling" in cats:
        _extract_named_words(c, claim)
    has_assertion = bool(claim.values or claim.letters or claim.expression)
    if _any(_ANSWER, low) or (not cats and (has_assertion or _any(_ANSWER_WEAK, low))):
        cats.append("answer")
    if not cats:
        toks = re.findall(r"[a-z]+", low)
        if toks and all(t in _VAGUE_WORDS for t in toks) and not has_assertion:
            cats.append("vague")
    if "answer" in cats and not has_assertion and len(re.findall(r"[a-z]+", low)) <= 3 \
            and set(re.findall(r"[a-z]+", low)) <= _VAGUE_WORDS | {"ans", "answer", "key"}:
        cats.append("vague")

    cats = list(dict.fromkeys(cats))
    claim.categories = sorted(cats, key=CATEGORY_ORDER.index)
    claim.primary = claim.categories[0] if claim.categories else "unclear"
    return claim
