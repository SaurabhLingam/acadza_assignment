"""Decision rules on synthetic records (no dataset ids)."""
from collections import Counter

from engine.checks import build_vocab, parse_question, run_checks
from engine.claims import classify
from engine.loader import Question, Report, load_taxonomy
from engine.verify import CODE_SETTLED, NEEDS_LLM, decide


def _q(html: str) -> Question:
    return Question(id="q", qtype="scq", subject="Physics", chapter="X", question_html=html,
                    solution_html="F = 99 N", answer_raw="C", ques_images=(), solution_images=(),
                    error_history=(), updated_at="", raw={})


def _decide(html: str, comment: str):
    pq = parse_question(_q(html))
    vocab: Counter = build_vocab([pq])
    fs = run_checks(pq, vocab)
    r = Report("r", "q", "s", "android", "2026-01-01T00:00:00Z", comment)
    return decide(r, classify(comment), pq, fs, vocab, load_taxonomy())


CUT = "options are cut on my phone screen"


def test_cut_options_settle_as_display_only_when_all_options_exist():
    d = _decide("Force?<br/>(A) 100 N<br/>(B) 121 N<br/>(C) 99 N<br/>(D) None", CUT)
    assert d.outcome == CODE_SETTLED and d.verdict == "display_issue"


def test_cut_options_with_missing_option_is_not_display_issue():
    d = _decide("Force?<br/>(A) 100 N<br/>(B) 121 N<br/>(C) 99 N", CUT)
    assert d.outcome == NEEDS_LLM and d.verdict == ""


def test_cut_options_with_blank_option_is_not_display_issue():
    d = _decide("Force?<br/>(A) 100 N<br/>(B) <br/>(C) 99 N<br/>(D) None", CUT)
    assert d.outcome == NEEDS_LLM and d.verdict == ""
