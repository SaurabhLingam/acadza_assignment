"""Prompts must not carry values or phrasing from the dataset (data/questions.json, data/reports.json).

An example taken from the data hands the model the answer to a real report (e.g. a solution-fix example that is
the exact fix for one question), so a good result could come from the prompt rather than the pipeline.

Checked for every prompt version the engine loads (engine/config.py ROLES); retired versions stay as they were
used in logged runs. A prompt fails if, after removing its {{placeholders}} and front matter, it contains any of:
  1. a decimal number, or an integer >= 100, that occurs in the data (180 is allowed: degrees to radians);
  2. a "<number> <unit>" pair that occurs in the data ("40 cm");
  3. a quoted example containing a digit that occurs in the data ("a = 40 cm");
  4. a run of 5 words that occurs in the data ("the correct answer is (d)").
Small integers (counts, limits, "max 20 words") are structure, not data, and are not checked on their own.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

from engine import config
from engine.parse import html_to_text

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_NUMBERS = {"180"}
NUM = r"\d+(?:\.\d+)?"
UNIT = r"[A-Za-zμΩ°%][A-Za-zμΩ°/²³]{0,5}"


@lru_cache(maxsize=1)
def corpus() -> tuple[str, set[str], set[tuple[str, ...]]]:
    texts: list[str] = []

    def walk(x):
        if isinstance(x, str):
            texts.append(html_to_text(x) if "<" in x else x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8")))
    walk([r["comment"] for r in json.loads((ROOT / "data" / "reports.json").read_text(encoding="utf-8"))])
    text = " ".join(" ".join(texts).split()).lower()
    words = _words(text)
    return text, set(re.findall(NUM, text)), {tuple(words[i:i + 5]) for i in range(len(words) - 4)}


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z]+(?:'[a-z]+)?", s.lower())


def _body(path: Path) -> str:
    t = path.read_text(encoding="utf-8")
    t = re.sub(r"\A---.*?---", "", t, flags=re.S)
    return re.sub(r"\{\{[^}]*\}\}", " ", t)


def leaks(text: str) -> list[str]:
    data, nums, grams = corpus()
    found = []
    for n in re.findall(rf"(?<![\w.]){NUM}(?![\d.])", text):          # 5.7 in "5.7e-5" counts
        if n in nums and n not in ALLOWED_NUMBERS and ("." in n or int(n) >= 100):
            found.append(f"number {n}")
    for m in re.finditer(rf"(?<![\w.])({NUM})\s+({UNIT})(?![\w/])", text):
        pair = f"{m[1]} {m[2]}".lower()
        if re.search(rf"(?<![\w.]){re.escape(pair)}(?![\w/])", data):
            found.append(f"value '{pair}'")
    for q in re.findall(r"[\"“]([^\"”\n]{3,80})[\"”]", text):
        if re.search(r"\d", q) and " ".join(q.split()).lower() in data:
            found.append(f"quote '{q}'")
    w = _words(text)
    for i in range(len(w) - 4):
        if tuple(w[i:i + 5]) in grams:
            found.append(f"phrase '{' '.join(w[i:i + 5])}'")
    return sorted(set(found))


ACTIVE = sorted({ROOT / "prompts" / f"{name}_v{ver}.md" for _, _, name, ver, _ in config.ROLES.values()})


@pytest.mark.parametrize("path", ACTIVE, ids=lambda p: p.name)
def test_active_prompt_has_nothing_from_the_data(path):
    assert leaks(_body(path)) == []


def test_detector_catches_known_leaks():
    assert leaks('e.g. "a = 40 cm" -> "a = 20 cm"')                  # a solution fix from the data
    assert leaks("Sahi answer (D) 4800 N/m² hai")                       # a key value from the data
    assert leaks("such as 5.7e-5")                                       # a key value from the data
    assert not leaks('e.g. "x = 6.4 mm", max 20 words, sin(30*pi/180)')  # neutral example, structure
