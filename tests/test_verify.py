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


def _decide_int(stem: str, comment: str):
    q = Question(id="q", qtype="integerQuestion", subject="Physics", chapter="X", question_html=stem,
                 solution_html="f = mg = 20 N", answer_raw="20", ques_images=(), solution_images=(),
                 error_history=(), updated_at="", raw={})
    pq = parse_question(q)
    vocab: Counter = build_vocab([pq])
    r = Report("r", "q", "s", "android", "2026-01-01T00:00:00Z", comment)
    return decide(r, classify(comment), pq, run_checks(pq, vocab), vocab, load_taxonomy())


def test_answer_form_settles_when_student_says_unit_missing_and_check_agrees():  # D-028
    d = _decide_int("A block of mass 2 kg is held against a wall. The friction force is equal to", "unit not mentioned in question")
    assert d.outcome == CODE_SETTLED and (d.verdict, d.repair) == ("defect", "answer_form")


def test_answer_form_does_not_settle_when_stem_states_the_unit():
    d = _decide_int("A block of mass 2 kg is held against a wall. The friction force (in N) is", "unit not mentioned in question")
    assert d.outcome == NEEDS_LLM


def test_answer_form_does_not_settle_on_a_rounding_claim():
    d = _decide_int("A block of mass 2 kg is held against a wall. The friction force is equal to", "rounding not mentioned")
    assert d.outcome == NEEDS_LLM
