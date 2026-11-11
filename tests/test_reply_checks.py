"""D-032: code checks on every student reply (action claims, answer consistency, D-031 no-answer)."""
import pytest

from engine.run import Runner
from engine.tiers import check_reply, check_reply_claims


@pytest.mark.parametrize("text,route", [
    ("Thanks! I've updated the key to (C); a teacher will review it.", "faculty_review"),
    ("Your report was marked resolved.", "faculty_review"),
    ("Good catch, the answer key has been corrected.", "no_change"),
    ("Thanks, key badal diya hai.", "faculty_review"),
])
def test_reply_must_not_claim_an_action_the_route_did_not_take(text, route):
    assert any("claims an action" in f for f in check_reply_claims(text, route, "defect", ""))


@pytest.mark.parametrize("text,route,verdict", [
    ("Thanks for flagging it. A teacher will check and correct it.", "faculty_review", "defect"),
    ("It will be corrected after a teacher checks it.", "faculty_review", "defect"),
    ("You marked (B), but the right option is (A).", "no_change", "no_error"),
    ("Nothing in the question has changed; it is right as given.", "no_change", "no_error"),
    ("Thanks, you were right. It's fixed now.", "auto_apply", "defect"),
    ("A teacher already corrected this.", "no_change", "already_fixed"),
])
def test_allowed_action_wording_passes(text, route, verdict):
    assert not [f for f in check_reply_claims(text, route, verdict, "(A) 0.8") if "claims an action" in f]


def test_reply_must_not_state_a_different_answer():
    assert check_reply_claims("The correct answer is (C).", "no_change", "no_error", "(D) 4800 N/m^2")
    assert check_reply_claims("(B) is correct here.", "no_change", "no_error", "(D) 4800 N/m^2")
    assert check_reply_claims("The correct answer is 16.", "faculty_review", "defect", "4")
    assert not check_reply_claims("Sahi answer (D) 4800 N/m^2 hai.", "no_change", "no_error", "(D) 4800 N/m^2")
    assert not check_reply_claims("The correct answer is 4, from the ratio of sizes.", "no_change", "no_error", "4")
    # the value of the keyed option counts as the decision's answer
    assert not check_reply_claims("The correct answer is 50 V.", "auto_apply", "defect", "(A) 50 V")
    assert check_reply_claims("The correct answer is 70 V.", "auto_apply", "defect", "(A) 50 V")


def test_reply_must_not_claim_an_answer_when_the_decision_has_none():
    assert check_reply_claims("The correct answer is (B).", "faculty_review", "defect", "")


def test_d031_reply_states_no_answer_at_all():
    assert check_reply_claims("A teacher is checking (D).", "faculty_review", "defect", "", no_answer=True)
    assert check_reply_claims("A teacher is checking; 4800 looks right.", "faculty_review", "defect", "",
                              no_answer=True)
    for lang in ("english", "hinglish"):
        assert not check_reply_claims(Runner._neutral_reply(lang), "faculty_review", "defect", "", no_answer=True)


def test_full_reply_check_reads_the_decision_answer_from_the_facts():
    facts = "Correct answer: (A) 0.8\nKey step: F - 100mu = 10\nStudent's answer: (B)"
    assert any("not the decision's" in f for f in check_reply("The correct answer is (B) 0.4.", "no_change",
                                                              facts=facts, comment="B", verdict="no_error"))
