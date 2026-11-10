"""LLM tier tests with a fake transport: no network, no API calls."""
import json

import pytest

from engine import config
from engine.checks import build_vocab, parse_question, run_checks
from engine.decide import (KEY_OK, KEY_WRONG, UNCLEAR, UNSOUND, OptionVerdict, Signals, SolverSig,
                           resolve_key)
from engine.edits import guard
from engine.llm import BudgetExceeded, Client, parse_json
from engine.loader import load_questions, load_reports, load_taxonomy
from engine.mathexpr import ExprError, evaluate, match_option, parse_quantity, same_quantity

TAX = load_taxonomy()


# --------------------------------------------------------------------------- safe evaluator

@pytest.mark.parametrize("expr,val", [("8*sqrt(2)", 11.3137085), ("5.7e-5", 5.7e-5), ("3/ln(8)", 1.4426950),
                                      ("atan(4)", 1.3258177), ("2^3", 8), ("4/1", 4), ("1:4", 0.25),
                                      ("8√2", 11.3137085), ("2pi", 6.2831853)])
def test_evaluate(expr, val):
    assert evaluate(expr) == pytest.approx(val, rel=1e-6)


@pytest.mark.parametrize("bad", ["__import__('os').system('x')", "open('f')", "(1).real", "[1,2]",
                                 "lambda: 1", "x+1", "2**1000", "1/0", "a.b", "sqrt(-1)", "9" * 300])
def test_evaluate_rejects(bad):
    with pytest.raises(ExprError):
        evaluate(bad)


def test_quantities_and_units():
    assert parse_quantity("16.8 eV") == (16.8, "eV")
    assert parse_quantity("2:√3")[0] == pytest.approx(1.1547, rel=1e-4)
    assert parse_quantity("8√(2 m)") == (pytest.approx(11.3137, rel=1e-4), "m")
    assert parse_quantity("Become twice its initial value") is None
    assert same_quantity(0.08, "m", 8, "cm", config.OPTION_REL_TOL)
    assert same_quantity(2.2e-6, "A", 2.2, "μA", config.OPTION_REL_TOL)
    assert not same_quantity(1, "V", 1, "m", config.OPTION_REL_TOL)
    assert match_option(4800, "Pa", {"A": "4556 N/m^2", "D": "4800 N/m^2"}) == ("D", ["D"])
    assert match_option(0, "W", {"B": "0 W", "C": "0 W"})[0] is None  # ambiguous: two options match


# --------------------------------------------------------------------------- client

def fake_transport(answers, calls):
    """answers: function(body) -> (status, headers, content-or-json-body)."""
    def t(method, url, headers, body, timeout):
        calls.append((method, url, body))
        if method == "GET":
            return 200, {}, json.dumps({"data": [{"id": "deepseek/deepseek-v4-flash",
                                                  "pricing": {"prompt": "0.000000091", "completion": "0.000000182"}}]})
        st, hdrs, content = answers(body)
        if st != 200:
            return st, hdrs, content
        return 200, hdrs, json.dumps({"model": body["model"], "provider": "FakeUpstream",
                                      "choices": [{"message": {"content": content}}],
                                      "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0001}})
    return t


def _client(tmp_path, answers, calls, cap=0.5):
    return Client("test", cap_usd=cap, transport=fake_transport(answers, calls), env={},
                  log_path=tmp_path / "calls.jsonl", cache_dir=tmp_path / "cache", sleep=lambda s: None)


MSG = [{"role": "user", "content": "hi"}]


def test_cap_blocks_paid_call_before_sending(tmp_path):
    calls = []
    c = _client(tmp_path, lambda b: (200, {}, "{}"), calls, cap=0.0001)
    with pytest.raises(BudgetExceeded):
        c.call("solver_2", None, MSG, stage="solve", tier=2)
    assert not [x for x in calls if x[0] == "POST"]
    log = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert log[-1]["status"] == "budget_stop"


def test_logs_cost_answering_model_and_caches(tmp_path):
    calls = []
    c = _client(tmp_path, lambda b: (200, {}, '{"ok": 1}'), calls)
    r1 = c.call("solver_2", None, MSG, stage="solve", tier=2)
    r2 = c.call("solver_2", None, MSG, stage="solve", tier=2)
    assert r1.data == {"ok": 1} and r1.cost_usd == 0.0001 and not r1.cache_hit
    assert r2.cache_hit and r2.cost_usd == 0
    assert len([x for x in calls if x[0] == "POST"]) == 1
    log = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text().splitlines()]
    first = log[0]
    for k in ("timestamp", "stage", "tier", "model", "prompt_file", "prompt_version", "input_hash", "tokens_in",
              "tokens_out", "latency_ms", "cache_hit", "retries", "cost_usd", "model_answered", "upstream_provider"):
        assert k in first, k
    assert first["upstream_provider"] == "FakeUpstream" and first["cost_source"] == "provider_usage"
    assert log[1]["cache_hit"] is True


def test_groq_is_free_and_retries_429(tmp_path):
    calls, state = [], {"n": 0}

    def answers(b):
        state["n"] += 1
        return (429, {"retry-after": "1"}, "rate limited") if state["n"] == 1 else (200, {}, '{"a": 2}')
    c = _client(tmp_path, answers, calls)
    r = c.call("solver_1", None, MSG, stage="solve", tier=1)
    assert r.data == {"a": 2} and r.retries == 1 and r.cost_usd == 0.0


def test_drops_unsupported_param_and_repairs_json(tmp_path):
    calls, state = [], {"n": 0}

    def answers(b):
        state["n"] += 1
        if "response_format" in b:
            return 400, {}, '{"error": "response_format is not supported"}'
        return 200, {}, ("not json at all" if state["n"] == 2 else 'Sure: {"x": 1}')
    c = _client(tmp_path, answers, calls)
    r = c.call("solver_1", None, MSG, stage="solve", tier=1)
    assert r.data == {"x": 1}


def test_parse_json_variants():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('text {"a": {"b": "}"}} tail') == {"a": {"b": "}"}}
    assert parse_json("nope") is None


# --------------------------------------------------------------------------- code decides the verdict

def _sig(**kw):
    base = dict(qtype="scq", key=("A",), option_letters=("A", "B", "C", "D"), claim_primary="answer",
                claim_categories=("answer",))
    base.update(kw)
    return Signals(**base)


def _sv(role, fam, letters):
    return SolverSig(role, fam, True, letters=tuple(letters))


def test_key_ok_and_key_wrong_and_unsound():
    ok = _sig(solvers=[_sv("solver_1", "openai", "A"), _sv("solver_2", "deepseek", "A")])
    assert resolve_key(ok)[0] == KEY_OK
    wrong = _sig(solvers=[_sv("solver_1", "openai", "D"), _sv("solver_2", "deepseek", "D")],
                 option_checks={"A": [OptionVerdict("option_check", "openai", "incorrect")],
                                "D": [OptionVerdict("option_check", "openai", "correct")]})
    st, ans, *_ = resolve_key(wrong)
    assert st == KEY_WRONG and ans == ("D",)
    # same family twice is not independent agreement
    same_fam = _sig(solvers=[_sv("solver_1", "openai", "D"), _sv("solver_2", "openai", "D")],
                    option_checks=wrong.option_checks)
    assert resolve_key(same_fam)[0] == UNCLEAR
    # no option check backing -> not settled
    assert resolve_key(_sig(solvers=wrong.solvers))[0] == UNCLEAR
    unsound = _sig(solvers=[_sv("solver_1", "openai", "B"), _sv("solver_2", "deepseek", "C")],
                   option_checks={L: [OptionVerdict("option_check", "openai", "incorrect")] for L in "ABCD"})
    assert resolve_key(unsound)[0] == UNSOUND


# --------------------------------------------------------------------------- guards

def _pq(text_id_free_html, qtype="scq", answer="A", solution="x"):
    from engine.loader import Question
    return parse_question(Question("q", qtype, "Physics", "X", text_id_free_html, solution, answer, (), (), (), "", {}))


def test_guards():
    pq = _pq("Find the force (NEET 2019)?<br/>(A) 10 N<br/>(B) 20 N<br/>(C) 30 N<br/>(D) 40 N")
    assert guard({"field": "answer", "find": "A", "replace": "D"}, "answer_key", pq, TAX) == []
    assert guard({"field": "answer", "find": "A", "replace": "E"}, "answer_key", pq, TAX)
    assert any("not allowed" in f for f in guard({"field": "solution", "find": "x", "replace": "y"},
                                                  "option_repair", pq, TAX))
    assert any("touches the stem" in f for f in guard({"field": "question", "find": "Find", "replace": "Get"},
                                                       "option_repair", pq, TAX))
    assert any("additive" in f for f in guard({"field": "question", "find": "force", "replace": "push"},
                                               "answer_form", pq, TAX))
    assert guard({"field": "question", "find": "force", "replace": "force (in N)"}, "answer_form", pq, TAX) == []
    assert any("digits" in f for f in guard({"field": "question", "find": "10 N", "replace": "12 N"},
                                             "spelling", pq, TAX))
    assert any("exactly once" in f for f in guard({"field": "question", "find": " N", "replace": " N"},
                                                   "spelling", pq, TAX))


# --------------------------------------------------------------------------- end to end, offline

ROLE_BY_PHRASE = [("expert JEE/NEET problem solver", "solver"), ("report, factually", "extract"),
                  ("audit a stored worked solution", "audit"), ("check ONE option", "option_check"),
                  ("help triage", "triage"), ("write the short message", "reply")]


def scripted(script):
    def answers(body):
        sys_msg = next((m["content"] for m in body["messages"] if m["role"] == "system"), "")
        role = next((r for p, r in ROLE_BY_PHRASE if p in sys_msg), "guard")
        user = body["messages"][-1]["content"]
        return 200, {}, script(role, user, body["model"])
    return answers


def _run_one(tmp_path, report_id, script):
    from engine.run import Runner
    qs = load_questions()
    r = next(x for x in load_reports() if x.report_id == report_id)
    pqs = {k: parse_question(q) for k, q in qs.items()}
    vocab = build_vocab(list(pqs.values()))
    pq = pqs[r.question_id]
    c = _client(tmp_path, scripted(script), [])
    return Runner(c, TAX).process(r, pq, run_checks(pq, vocab), vocab)


def test_e2e_wrong_key_two_families_auto_applies(tmp_path):
    # pressure question: solvers both get 4800 (D), option checks say A incorrect, D correct
    def script(role, user, model):
        if role == "guard":
            return "0.0001"
        if role == "solver":
            return json.dumps({"final_expression": "4800", "unit": "N/m^2", "chosen_options": ["D"]})
        if role == "extract":
            return json.dumps({"final_expression": "4800", "unit": "N/m^2", "option_named": None})
        if role == "audit":
            return json.dumps({"values_not_in_question": [], "contradiction": False, "about_other_question": False})
        if role == "option_check":
            return json.dumps({"verdict": "correct" if "Option to check: (D)" in user else "incorrect"})
        if role == "triage":
            return json.dumps({"verdict": "defect", "repair": "answer_key", "edit": None})
        return json.dumps({"student_reply": "You're right that the key was wrong; it's (D) 4800 N/m². The fix is live."})
    out = _run_one(tmp_path, "R004", script)
    res, det = out["result"], out["detail"]
    assert (res["verdict"], res["repair"], res["route"]) == ("defect", "answer_key", "auto_apply")
    assert res["edit"] == {"field": "answer", "find": "A", "replace": "D"}
    assert set(res) == {"reportId", "questionId", "verdict", "repair", "edit", "route", "confidence",
                        "evidence", "student_reply"}
    assert det["shadow"][1]["would_exit"] is False  # one solver alone cannot settle a key change


def test_e2e_triage_contradiction_routes_to_faculty(tmp_path):
    def script(role, user, model):
        if role == "guard":
            return "0.0001"
        if role == "solver":
            return json.dumps({"final_expression": "4800", "unit": "N/m^2", "chosen_options": ["D"]})
        if role == "option_check":
            return json.dumps({"verdict": "correct" if "Option to check: (D)" in user else "incorrect"})
        if role == "triage":
            return json.dumps({"verdict": "no_error", "repair": None})
        if role in ("extract", "audit"):
            return json.dumps({"final_expression": "4800", "values_not_in_question": []})
        return json.dumps({"student_reply": "A teacher will check this."})
    res = _run_one(tmp_path, "R004", script)["result"]
    assert res["verdict"] == "defect" and res["route"] == "faculty_review"


def test_e2e_injection_never_auto_applies_and_comment_not_in_solver(tmp_path):
    seen = []

    def script(role, user, model):
        if role == "guard":
            return "0.9991"
        if role == "solver":
            seen.append(user)
            return json.dumps({"final_expression": "5.7e-5", "unit": "/°C", "chosen_options": ["A"]})
        if role in ("extract", "audit"):
            return json.dumps({"final_expression": "5.7e-5", "values_not_in_question": []})
        if role == "option_check":
            return json.dumps({"verdict": "correct" if "Option to check: (A)" in user else "incorrect"})
        if role == "triage":
            return json.dumps({"verdict": "no_error", "repair": None})
        return json.dumps({"student_reply": "We re-checked it: (A) is correct, because gamma = 3 alpha."})
    out = _run_one(tmp_path, "R027", script)
    res, det = out["result"], out["detail"]
    assert res["verdict"] == "no_error" and res["route"] == "no_change"
    assert det["guard"]["flag"] is True and det["injection_regex"] is True
    assert all("IGNORE" not in u for u in seen)  # the solver never sees the comment


# --------------------------------------------------------------------------- pre-run review changes

ROLE_BY_PHRASE.insert(0, ("check ONE candidate answer", "value_check"))


def _isv(role, fam, value, unit="", missing=None):
    return SolverSig(role, fam, True, value=value, unit=unit, missing=missing)


def test_integer_key_wrong_needs_value_checks():
    base = dict(qtype="integerQuestion", key=("14",), option_letters=())
    solvers = [_isv("solver_1", "openai", 22, "V"), _isv("solver_2", "deepseek", 22.0001, "V")]
    no_checks = _sig(solvers=solvers, integer_matches={"solver_1": False, "solver_2": False}, **base)
    assert resolve_key(no_checks)[0] == UNCLEAR
    checked = _sig(solvers=solvers, integer_matches={"solver_1": False, "solver_2": False},
                   option_checks={"key": [OptionVerdict("value_check", "openai", "incorrect")],
                                  "=22": [OptionVerdict("value_check", "openai", "correct")]},
                   value_candidates={"=22": (22.0, "V")}, **base)
    st, ans, *_ = resolve_key(checked)
    assert st == KEY_WRONG and ans == ("22",)
    # the alternative not confirmed correct -> not settled
    checked.option_checks["=22"] = [OptionVerdict("value_check", "openai", "cannot_tell")]
    assert resolve_key(checked)[0] == UNCLEAR


def test_solver_with_missing_information_is_not_agreement():
    s = _sig(solvers=[_sv("solver_1", "openai", "A"),
                      SolverSig("solver_2", "deepseek", True, letters=("A",), missing="the mass of the block")])
    st, _, basis, agree, _ = resolve_key(s)
    assert st == KEY_OK and agree == 1 and any("not counted" in b for b in basis)
    both = _sig(solvers=[SolverSig("solver_1", "openai", True, letters=("A",), missing="g"),
                         SolverSig("solver_2", "deepseek", True, letters=("A",), missing="g")])
    assert resolve_key(both)[0] == UNCLEAR
    # integer: a missing-data solver does not count either way
    ints = _sig(qtype="integerQuestion", key=("14",), option_letters=(),
                solvers=[_isv("solver_1", "openai", 22, "V", missing="R"), _isv("solver_2", "deepseek", 22, "V")],
                integer_matches={"solver_1": False, "solver_2": False},
                option_checks={"key": [OptionVerdict("value_check", "openai", "incorrect")],
                               "=22": [OptionVerdict("value_check", "openai", "correct")]},
                value_candidates={"=22": (22.0, "V")})
    assert resolve_key(ints)[0] == UNCLEAR


def test_solver_never_takes_closest_option(tmp_path):
    from engine.tiers import run_solver
    pq = _pq("Find the force?<br/>(A) 10 N<br/>(B) 20 N<br/>(C) 30 N<br/>(D) 40 N")
    c = _client(tmp_path, lambda b: (200, {}, json.dumps({"final_expression": "24", "unit": "N",
                                                           "chosen_options": ["B"], "missing_information": "None"})), [])
    sig, _ = run_solver(c, "solver_1", pq)
    assert sig.letters == () and sig.missing is None and any("matches no option" in i for i in sig.issues)


def test_syllabus_reply_never_says_removed():
    from engine.tiers import check_reply
    assert check_reply("Thanks! A teacher will check; the question has been removed for now.", "faculty_review",
                       syllabus=True)
    assert not check_reply("Thanks! A teacher will check it; the question stays available meanwhile.",
                           "faculty_review", syllabus=True)


def test_guard_stats():
    from engine.run import _guard_stats
    st = _guard_stats([{"reportId": "a", "guard": {"flag": True}, "injection_regex": True},
                       {"reportId": "b", "guard": {"flag": False, "label": "unparsed"}, "injection_regex": False},
                       {"reportId": "c", "guard": {"flag": True}, "injection_regex": False},
                       {"reportId": "d", "guard": {"flag": False}, "injection_regex": False}])
    assert st["prompt_guard_flag_rate"] == 0.5 and st["both_flagged"] == 1 and st["guard_only"] == 1
    assert st["guard_unparsed_or_error"] == 1 and st["guard_flagged_reports"] == ["a", "c"]


def test_e2e_integer_wrong_key_via_value_checks_and_code_evidence(tmp_path):
    rep = next(r for r in load_reports() if load_questions()[r.question_id].qtype == "integerQuestion"
               and "not" in r.comment.lower() and "22" in r.comment)
    key = str(load_questions()[rep.question_id].answer_raw)

    def script(role, user, model):
        if role == "guard":
            return "0.0001"
        if role == "solver":
            return json.dumps({"final_expression": "22", "unit": "V", "chosen_options": [],
                               "missing_information": None})
        if role == "extract":
            return json.dumps({"final_expression": "22", "unit": "V", "option_named": None})
        if role == "audit":
            return json.dumps({"values_not_in_question": [], "contradiction": False, "about_other_question": False})
        if role == "value_check":
            return json.dumps({"own_answer": "22 V", "reason": "r",
                               "verdict": "correct" if "answer to check: 22" in user else "incorrect"})
        if role == "triage":
            return json.dumps({"verdict": "defect", "repair": "answer_key", "edit": None, "evidence": "TRIAGE-SAYS"})
        return json.dumps({"student_reply": "You're right, the key was wrong: it is 22 V. The fix is live."})
    out = _run_one(tmp_path, rep.report_id, script)
    res, det = out["result"], out["detail"]
    assert (res["verdict"], res["repair"]) == ("defect", "answer_key")
    assert res["edit"] == {"field": "answer", "find": key, "replace": "22"}
    assert "gpt-oss-120b" in res["evidence"] and "deepseek-v4-flash" in res["evidence"]
    assert "Value checks" in res["evidence"] and f"Key: {key}" in res["evidence"]
    assert "TRIAGE-SAYS" not in res["evidence"]          # code decided: triage evidence not used
    assert det["option_checks"]["key"][0]["verdict"] == "incorrect"


# --------------------------------------------------------------------------- second review (M-003, D-020)

def test_reply_check_rejects_invented_answer_wrong_language_and_blame():
    from engine.tiers import check_reply
    unsound_facts = ("No option is correct as written, so there is no right option to tell the student.\n"
                     "The student did not propose an answer of their own; do not say their answer was wrong.")
    assert any("not in the facts" in f for f in check_reply(
        "Thanks for spotting the mistake. The correct answer is B.", "faculty_review", facts=unsound_facts))
    facts = "Correct answer: (A) 0.8\nKey step: F - 100mu = 10 and 2F - 100mu = 100"
    assert check_reply("We re-solved it: the answer is (A) 0.8, since F - 100mu = 10.", "no_change",
                       facts=facts, comment="mu should be 0.4") == []
    assert any("not in the facts" in f for f in check_reply("The answer is (A) 0.75.", "no_change", facts=facts))
    assert any("Hinglish" in f for f in check_reply("The answer is (A) 0.8.", "no_change", language="hinglish",
                                                    facts=facts))
    assert not check_reply("Sahi answer (A) 0.8 hai, kyunki F - 100mu = 10 lagta hai.", "no_change",
                           language="hinglish", facts=facts)
    assert any("proposed none" in f for f in check_reply("Your answer was not correct. It is (A) 0.8.", "no_change",
                                                         facts=facts, proposed_answer=False))


def test_option_content_needs_two_sources():
    from engine.decide import Decision
    from engine.run import Runner
    one = _sig(solvers=[SolverSig("solver_1", "openai", True), _isv("solver_2", "deepseek", 1.0)],
               extract={"value": None})
    d = Decision("defect", "option_repair", "", 0.5, "code+llm", False)
    assert Runner._content_sources(d, one, "1:1") is False and "only 1" in d.notes[0]
    two = _sig(solvers=[_isv("solver_1", "openai", 1.0), _isv("solver_2", "deepseek", 1.0)], extract={"value": None})
    d2 = Decision("defect", "option_repair", "", 0.5, "code+llm", False)
    assert Runner._content_sources(d2, two, "1:1") is True
    assert "gpt-oss-120b" in d2.notes[0] and "deepseek-v4-flash" in d2.notes[0]
    sol = _sig(solvers=[_isv("solver_1", "openai", 1.0), SolverSig("solver_2", "deepseek", True)],
               extract={"value": 1.0, "unit": ""})
    d3 = Decision("defect", "option_repair", "", 0.5, "code+llm", False)
    assert Runner._content_sources(d3, sol, "1:1") is True and "stored solution" in d3.notes[0]


def test_solver_letter_used_when_expression_null(tmp_path):
    from engine.tiers import run_solver
    pq = _pq("Which is true?<br/>(A) x<br/>(B) y<br/>(C) z<br/>(D) w")
    c = _client(tmp_path, lambda b: (200, {}, json.dumps({"final_expression": None, "chosen_options": ["C"],
                                                           "working": "w"})), [])
    sig, _ = run_solver(c, "solver_1", pq)
    assert sig.letters == ("C",) and sig.from_letter and sig.working == "w"


def _r016_script(edit):
    def script(role, user, model):
        if role == "guard":
            return "0.0001"
        if role == "solver":
            return json.dumps({"final_expression": "20", "unit": "cm", "working": "800 = 2a^2 so a = 20 cm",
                               "missing_information": None})
        if role == "extract":
            return json.dumps({"final_expression": "40", "unit": "cm", "final_statement": "a = 40 cm"})
        if role == "audit":
            return json.dumps({"values_not_in_question": [], "contradiction": False, "about_other_question": False})
        if role == "value_check":
            return json.dumps({"reason": "r", "verdict": "correct"})
        if role == "triage":
            return json.dumps({"verdict": "defect", "repair": "solution_fix", "edit": edit, "evidence": "e"})
        return json.dumps({"student_reply": "Thanks! The answer is 20 cm; 800 = 2a^2 so a = 20 cm. The fix is live."})
    return script


def test_e2e_solution_value_fix_auto_applies_and_keeps_markup(tmp_path):
    out = _run_one(tmp_path, "R016", _r016_script({"field": "solution", "find_clean": "a = 40 cm",
                                                   "replace": "a = 20 cm"}))
    res, det = out["result"], out["detail"]
    assert (res["verdict"], res["repair"], res["route"]) == ("defect", "solution_fix", "auto_apply"), det["route_why"]
    assert res["edit"]["field"] == "solution" and "40" in res["edit"]["find"]
    assert res["edit"]["replace"] == res["edit"]["find"].replace("40", "20")
    assert "changes only the final value 40 -> 20" in res["evidence"]


def test_e2e_solution_edit_that_changes_more_goes_to_faculty(tmp_path):
    out = _run_one(tmp_path, "R016", _r016_script({"field": "solution", "find_clean": "a = 40 cm",
                                                   "replace": "side = 20 cm"}))
    res, det = out["result"], out["detail"]
    assert res["route"] == "faculty_review" and res["edit"] is None
    assert any("more than the value" in f for f in det["edit_guard_failures"])


def test_injection_letters_are_not_the_students_answer(tmp_path):
    out = _run_one(tmp_path, "R027", lambda role, user, model: (
        "0.999" if role == "guard" else json.dumps({"student_reply": "Your answer was not correct; it is (A)."})
        if role == "reply" else json.dumps({"final_expression": "5.7e-5", "unit": "/°C", "chosen_options": ["A"],
                                           "verdict": "correct" if "(A)" in user else "incorrect"})))
    det = out["detail"]
    assert any("proposed none" in f for f in det["reply_check_failures"])
    assert "your answer" not in out["result"]["student_reply"].lower()
