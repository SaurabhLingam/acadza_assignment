"""HTML + MathML to clean text, option splitting, answer normalisation.

Standard library only. Rules here are generic: nothing refers to a
specific question or report.
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from html.entities import codepoint2name
from html.parser import HTMLParser

# --------------------------------------------------------------------------
# Tree building
# --------------------------------------------------------------------------

VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "col", "area", "wbr",
             "none", "mprescripts", "malignmark", "maligngroup"}
BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "li", "ul", "ol",
              "table", "tr", "blockquote"}
SKIP_TAGS = {"script", "style"}

ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")


class Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict | None = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list = []


class _TreeBuilder(HTMLParser):
    """Tolerant builder: unclosed tags close at end, stray end tags are ignored."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, {k: (v or "") for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def build_tree(raw: str) -> Node:
    b = _TreeBuilder()
    b.feed(raw or "")
    b.close()
    return b.root


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

DEGREE_MARKS = {"o", "∘", "º", "°", "˚"}
RELATIONS = {"=", "≠", "≈", "≃", "≅", "∝", "<", ">", "≤", "≥", "⇒", "→", "⟹", "⇔",
             "∴", "∵", "⟶", "≡", "~"}
FUNCTION_NAMES = {"sin", "cos", "tan", "cot", "sec", "cosec", "csc", "log", "ln",
                  "exp", "lim", "max", "min", "sinh", "cosh", "tanh", "arcsin",
                  "arccos", "arctan"}
# Combining marks for <mover> accents.
ACCENTS = {
    "∘": "̊", "˚": "̊", "°": "̊", "o": "̊",   # ring: A + ring = Å
    "→": "⃗", "⟶": "⃗", "⇀": "⃗",                    # vector arrow
    "¯": "̅", "‾": "̅", "_": "̅", "―": "̅",      # bar
    "^": "̂", "ˆ": "̂",                                    # hat
    "˙": "̇", ".": "̇",                                    # dot
    "~": "̃", "˜": "̃",                                    # tilde
}

_ATOM = re.compile(r"√?[^\W_]+(?:\.[^\W_]+)?")
_EXP_ATOM = re.compile(r"[+\-−]?√?[^\W_]+(?:\.[^\W_]+)?|[′″]+|[+\-−]")


def _is_wrapped(s: str) -> bool:
    if not (s.startswith("(") and s.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(s):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and i < len(s) - 1:
            return False
    return True


def _wrap(s: str, exp: bool = False) -> str:
    s = s.strip()
    if not s:
        return s
    pat = _EXP_ATOM if exp else _ATOM
    if pat.fullmatch(s) or _is_wrapped(s):
        return s
    return f"({s})"


def _token_text(node: Node) -> str:
    return re.sub(r"\s+", " ", "".join(_flat_text(node))).strip()


def _flat_text(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    out: list[str] = []
    for c in node.children:
        out.extend(_flat_text(c))
    return out


def _elements(node: Node) -> list[Node]:
    return [c for c in node.children if isinstance(c, Node)]


def _concat_math(parts: list[tuple[str, str]]) -> str:
    """Join rendered math siblings; parts are (rendered, tag)."""
    out = ""
    prev_tag = ""
    prev = ""
    for text, tag in parts:
        if not text:
            continue
        if out and text[:1].isalnum() and (
                (prev_tag == "mi" and prev.strip() in FUNCTION_NAMES) or prev_tag == "mfrac"):
            out += " "
        out += text
        prev, prev_tag = text, tag
    return out


def _render_math(node, in_table: bool = False) -> str:
    if isinstance(node, str):
        return node
    tag = node.tag
    kids = _elements(node)

    if tag in ("mi", "mn", "ms"):
        t = _token_text(node)
        return "" if t == "&" else t  # lone '&' is a leaked alignment marker
    if tag == "mo":
        t = _token_text(node)
        if t == "&":
            return ""
        if t in RELATIONS:
            return f" {t} "
        if t == ",":
            return ", "
        return t
    if tag == "mtext":
        t = re.sub(r"\s+", " ", "".join(_flat_text(node)).replace("\xa0", " "))
        if t.strip() == "&":
            return ""
        return t
    if tag in ("mphantom", "annotation", "annotation-xml", "none", "mprescripts",
               "malignmark", "maligngroup"):
        return ""
    if tag == "semantics":
        return _render_math(kids[0], in_table) if kids else ""
    if tag == "mspace":
        inner = _render_children(node, in_table)
        return ("\n" if node.attrs.get("linebreak") == "newline" else " ") + inner

    r = [(_render_math(k, in_table).strip() if k.tag != "mspace" else _render_math(k, in_table))
         for k in kids]

    if tag == "mfrac" and len(r) >= 2:
        return f"{_wrap(r[0])}/{_wrap(r[1])}"
    if tag == "msqrt":
        return "√" + _wrap(_render_children(node, in_table).strip())
    if tag == "mroot" and len(r) >= 2:
        return f"{_wrap(r[0])}^(1/{r[1]})"
    if tag == "msup" and len(r) >= 2:
        if r[1] in DEGREE_MARKS:
            return r[0] + "°"
        return f"{r[0]}^{_wrap(r[1], exp=True)}"
    if tag == "msub" and len(r) >= 2:
        return f"{r[0]}_{_wrap(r[1])}"
    if tag == "msubsup" and len(r) >= 3:
        return f"{r[0]}_{_wrap(r[1])}^{_wrap(r[2], exp=True)}"
    if tag == "mover" and len(r) >= 2:
        mark = ACCENTS.get(r[1])
        if mark and r[0]:
            return unicodedata.normalize("NFC", r[0] + mark)
        return f"{r[0]}^{_wrap(r[1], exp=True)}"
    if tag == "munder" and len(r) >= 2:
        return f"{r[0]}_{_wrap(r[1])}"
    if tag == "munderover" and len(r) >= 3:
        return f"{r[0]}_{_wrap(r[1])}^{_wrap(r[2], exp=True)}"
    if tag == "mfenced":
        op = node.attrs.get("open", "(")
        cl = node.attrs.get("close", ")")
        sep = node.attrs.get("separators", ",").strip() or ","
        return op + f"{sep} ".join(r) + cl
    if tag == "mtable":
        rows = []
        for row in kids:
            rows.append(_render_math(row, True).strip())
        return "\n".join(x for x in rows if x)
    if tag in ("mtr", "mlabeledtr"):
        return " ".join(_render_math(c, True).strip() for c in kids)
    return _render_children(node, in_table)


def _render_children(node: Node, in_table: bool = False) -> str:
    parts = []
    for c in node.children:
        if isinstance(c, str):
            # whitespace between MathML elements is not content
            if c.strip():
                parts.append((c.strip(), "#text"))
            continue
        parts.append((_render_math(c, in_table), c.tag))
    return _concat_math(parts)


def _render_html(node) -> str:
    if isinstance(node, str):
        return node
    tag = node.tag
    if tag in SKIP_TAGS:
        return ""
    if tag == "math":
        return _render_children(node)
    if tag == "br":
        return "\n"
    if tag == "img":
        return ""
    inner = "".join(_render_html(c) for c in node.children)
    if tag == "sup":
        s = _normalize_inline(inner)
        if s in DEGREE_MARKS:
            return "°"
        return "^" + _wrap(s, exp=True) if s else ""
    if tag == "sub":
        s = _normalize_inline(inner)
        return "_" + _wrap(s) if s else ""
    if tag == "mspace":  # MathML element left open outside <math>
        return ("\n" if node.attrs.get("linebreak") == "newline" else " ") + inner
    if tag in BLOCK_TAGS:
        return "\n" + inner + "\n"
    return inner


def _normalize_inline(s: str) -> str:
    s = ZERO_WIDTH.sub("", s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def normalize_text(s: str, keep_lines: bool = False) -> str:
    s = ZERO_WIDTH.sub("", s)
    s = s.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    s = unicodedata.normalize("NFC", s)
    lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    lines = [ln for ln in lines if ln]
    s = ("\n" if keep_lines else " ").join(lines)
    s = re.sub(r" +([.,;:?!])(?=\s|$)", r"\1", s)
    s = re.sub(r"\( +", "(", s)
    s = re.sub(r" +\)", ")", s)
    return s.strip()


def html_to_text(raw: str, keep_lines: bool = False) -> str:
    """Render production HTML (with inline MathML) to clean plain text."""
    return normalize_text(_render_html(build_tree(raw)), keep_lines=keep_lines)


# --------------------------------------------------------------------------
# Option splitting
# --------------------------------------------------------------------------

LETTERS = "ABCD"
_MARKER = re.compile(r"\(\s*([A-D])\s*\)")
_MATH_SPAN = re.compile(r"<math\b.*?</math>", re.S | re.I)
_TAG_SPAN = re.compile(r"<[^>]*>")


@dataclass(frozen=True)
class Marker:
    letter: str
    start: int
    end: int


@dataclass
class SplitQuestion:
    stem_raw: str
    stem_text: str
    options_raw: dict = field(default_factory=dict)    # letter -> raw HTML slice (marker excluded)
    options_text: dict = field(default_factory=dict)   # letter -> clean text
    option_spans: dict = field(default_factory=dict)   # letter -> (start, end) in raw, marker included
    letters: tuple = ()


def find_markers(raw: str) -> list[Marker]:
    """Option markers outside <math>, plus <math> blocks whose whole text is a marker."""
    math_spans = [(m.start(), m.end()) for m in _MATH_SPAN.finditer(raw)]
    tag_spans = [(m.start(), m.end()) for m in _TAG_SPAN.finditer(raw)]
    found: list[Marker] = []
    for s, e in math_spans:
        inner = html.unescape(re.sub(r"<[^>]*>", "", raw[s:e]))
        m = _MARKER.fullmatch(_normalize_inline(inner))
        if m:
            found.append(Marker(m.group(1), s, e))

    def inside(pos, spans):
        return any(a <= pos < b for a, b in spans)

    for m in _MARKER.finditer(raw):
        if inside(m.start(), math_spans) or inside(m.start(), tag_spans):
            continue
        found.append(Marker(m.group(1), m.start(), m.end()))
    found.sort(key=lambda x: x.start)
    return found


def _choose_chain(markers: list[Marker]) -> list[Marker]:
    """Pick the option chain: the last (A) that is followed by a (B), then the
    first (B), (C), (D) after it in order. An earlier (A) followed by no (B)
    before the next (A) (e.g. 'Assertion (A)') is part of the stem."""
    a_idx = [i for i, m in enumerate(markers) if m.letter == "A"]
    chosen_start = None
    for i in reversed(a_idx):
        if any(m.letter == "B" for m in markers[i + 1:]):
            chosen_start = i
            break
    if chosen_start is None:
        return [markers[a_idx[0]]] if a_idx else []
    chain = [markers[chosen_start]]
    want = 1
    for m in markers[chosen_start + 1:]:
        if want < len(LETTERS) and m.letter == LETTERS[want]:
            chain.append(m)
            want += 1
    return chain


def split_options(raw: str, has_options: bool = True) -> SplitQuestion:
    raw = raw or ""
    if not has_options:
        return SplitQuestion(stem_raw=raw, stem_text=html_to_text(raw))
    chain = _choose_chain(find_markers(raw))
    if not chain:
        return SplitQuestion(stem_raw=raw, stem_text=html_to_text(raw))
    sq = SplitQuestion(stem_raw=raw[: chain[0].start], stem_text=html_to_text(raw[: chain[0].start]))
    for i, m in enumerate(chain):
        end = chain[i + 1].start if i + 1 < len(chain) else len(raw)
        body = raw[m.end:end]
        sq.options_raw[m.letter] = body
        sq.options_text[m.letter] = html_to_text(body)
        sq.option_spans[m.letter] = (m.start, end)
    sq.letters = tuple(m.letter for m in chain)
    return sq


# --------------------------------------------------------------------------
# Answer normalisation
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class NormalizedAnswer:
    values: tuple          # normalised: letters for scq/mcq, a number string for integer
    flags: tuple           # e.g. ("empty_element", "combined_string", "not_a_letter")


_NUM = re.compile(r"[+-]?\d+(?:\.\d+)?")


def normalize_answer(qtype: str, raw, option_letters: tuple = LETTERS) -> NormalizedAnswer:
    flags: list[str] = []
    if qtype == "integerQuestion":
        s = str(raw if raw is not None else "").strip()
        if not _NUM.fullmatch(s):
            flags.append("not_numeric")
            return NormalizedAnswer((), tuple(flags))
        return NormalizedAnswer((s,), ())

    elements = raw if isinstance(raw, list) else [raw]
    if qtype == "scq" and isinstance(raw, list):
        flags.append("list_for_scq")
    if qtype == "mcq" and not isinstance(raw, list):
        flags.append("string_for_mcq")
    letters: list[str] = []
    for el in elements:
        s = str(el if el is not None else "").strip()
        if not s:
            flags.append("empty_element")
            continue
        parts = [p for p in re.split(r"[\s,;/&]+|AND", s.upper()) if p]
        if len(parts) > 1:
            flags.append("combined_string")
        for p in parts:
            if len(p) == 1 and p in LETTERS:
                letters.append(p)
            else:
                flags.append("not_a_letter")
    for x in letters:
        if x not in option_letters:
            flags.append("letter_without_option")
    if len(set(letters)) != len(letters):
        flags.append("duplicate_letter")
    if qtype == "scq" and len(set(letters)) > 1:
        flags.append("multiple_letters_for_scq")
    if not letters:
        flags.append("no_answer")
    return NormalizedAnswer(tuple(sorted(set(letters))), tuple(dict.fromkeys(flags)))


# --------------------------------------------------------------------------
# Raw evidence
# --------------------------------------------------------------------------

def _char_pattern(ch: str) -> str:
    if ch.isspace():
        return r"(?:\s|&nbsp;|&#160;|&#x0*a0;|<[^>]*>)+"
    alts = [re.escape(ch), re.escape(html.escape(ch, quote=False))]
    cp = ord(ch)
    alts.append(rf"&#x0*{cp:x};")
    alts.append(rf"&#0*{cp};")
    if cp in codepoint2name:
        alts.append(rf"&{codepoint2name[cp]};")
    return "(?:" + "|".join(dict.fromkeys(alts)) + ")"


def _tolerant_pattern(needle: str) -> re.Pattern:
    gap = r"(?:<[^>]*>|[​﻿])*"
    chars = [c for c in re.sub(r"\s+", " ", needle.strip())]
    return re.compile(gap.join(_char_pattern(c) for c in chars), re.I)


def grow_unique(raw: str, s: int, e: int, max_extend: int = 120) -> tuple[str, bool]:
    """Grow raw[s:e] outwards one character per side until it occurs exactly once in raw."""
    for _ in range(max_extend):
        sub = raw[s:e]
        if raw.count(sub) == 1:
            return sub, True
        s, e = max(0, s - 1), min(len(raw), e + 1)
    return raw[s:e], raw.count(raw[s:e]) == 1


def _inside_tag(raw: str, pos: int) -> bool:
    lt, gt = raw.rfind("<", 0, pos + 1), raw.rfind(">", 0, pos)
    return lt > gt


def locate_raw(raw: str, needle: str, region: tuple[int, int] | None = None,
               whole_word: bool = False) -> tuple[str | None, bool]:
    """Find the exact raw-HTML substring for a clean-text needle.

    Matches inside tag markup (attributes) are skipped. Entities and tags between
    characters are tolerated. Returns (substring, unique): the substring is grown
    outwards until it occurs exactly once in `raw`; `unique` is False if that failed.
    """
    if not needle or not needle.strip():
        return None, False
    lo, hi = region if region else (0, len(raw))
    seg = raw[lo:hi]
    wb_l, wb_r = (r"(?<![A-Za-z])", r"(?![A-Za-z])") if whole_word else ("", "")
    for pat in (re.compile(wb_l + re.escape(needle) + wb_r),
                re.compile(wb_l + _tolerant_pattern(needle).pattern + wb_r, re.I)):
        for m in pat.finditer(seg):
            if not _inside_tag(raw, lo + m.start()):
                return grow_unique(raw, lo + m.start(), lo + m.end())
    return None, False
