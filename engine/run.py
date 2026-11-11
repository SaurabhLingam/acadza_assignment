"""Full triage run: code tier + LLM tiers in shadow mode, then results.json.

    python -m engine.run --reports <id>,<id>,...                   # test subset
    python -m engine.run                                           # all reports -> results.json
Options: --cap USD (default 0.50), --offline (cache only, no network), --no-cache,
         --swap-model MODEL (robustness test, D-005: MODEL replaces solver #1 and the checks; output goes
         to logs/runs/<run_id>-swap-<model>/ only, never to the root results.json or logs/run-summary.json)

Every tier runs on every report (D-003); what an early exit would have decided
is logged per tier. Code decides verdict, route and confidence (D-001, D-016).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import time
from datetime import datetime, timezone

from . import config
from .checks import DEFINITE, SIGNAL, build_vocab, parse_question, run_checks
from .claims import classify
from .decide import (KEY_OK, KEY_WRONG, TIER_NAMES, TIER_TRIAGE, UNSOUND, OptionVerdict, Signals, confidence,
                     SolverSig, counts, decide, disputed_items, route_for, same_value, triage_contradicts,
                     value_cand, value_clusters)
from .edits import code_edit, guard, map_clean_edit, public_edit, value_correction_check
from .llm import BudgetExceeded, Client, LLMError
from .loader import ROOT, load_questions, load_reports, load_taxonomy
from .mathexpr import parse_quantity, same_quantity, to_si
from .tiers import (asked_unit, findings_text, integer_match, run_audit, run_extract, run_guard,
                    run_option_check, run_reply, run_solver, run_triage, run_value_check)
from .verify import decide as decide_tier0

# Student-facing description of each repair, used as a reply fact (code-decided, never model-written).
WHAT_WAS_WRONG = {
    "answer_key": "the answer key was wrong.",
    "answer_key_malformed": "the answer key was saved in a broken format, so correct answers were marked wrong.",
    "type_mismatch": "the question was set as multiple-correct, but only one option is correct; it is now "
                     "single-correct, so marking it works properly.",
    "option_repair": "one of the options was blank or cut off.",
    "solution_fix": "the worked solution had a mistake.",
    "stem_data": "the question left out a value that is needed to solve it.",
    "spelling": "the question text had a spelling mistake.",
    "markup_leak": "the question showed raw formatting code instead of clean text.",
    "exam_reference": "the question carried an exam label it should not have.",
    "answer_form": "the question did not say what form or unit the answer should be in.",
    "unsound": "as written, no option is correct.",
    "wrong_question": "the solution belongs to a different question.",
    "syllabus": "",
    "wrong_chapter": "the question is filed under the wrong chapter.",
    "noise": "the question text had stray characters in it.",
    "notation": "the question used confusing notation.",
    "solution_missing": "the worked solution was missing.",
    "identical_options": "two of the options were the same.",
    "diagram": "the figure the question needs was missing or wrong.",
}

# Roles a --swap-model run replaces: solver #1 and the checks (solution audit, option checks, value checks).
# Triage, extract, reply, the guard and the second-family solver/tie-breakers keep their models.
SWAP_ROLES = ("solver_1", "audit", "option_check", "value_check")

RESULT_KEYS = ("reportId", "questionId", "verdict", "repair", "edit", "route", "confidence", "evidence",
               "student_reply")


class Runner:
    def __init__(self, client: Client, taxonomy: dict):
        self.c, self.tax = client, taxonomy
        self.memo: dict = {}

    def once(self, key, fn, default):
        """Per-run memo (duplicate reports share question-level calls); LLM errors become `default`."""
        if key not in self.memo:
            try:
                self.memo[key] = fn()
            except LLMError as e:
                self.memo[key] = default(str(e)) if callable(default) else default
        return self.memo[key]

    # ------------------------------------------------------------------ one report
    def process(self, r, pq, findings, vocab) -> dict:
        claim = classify(r.comment)
        t0 = decide_tier0(r, claim, pq, findings, vocab, self.tax)
        s = Signals(qtype=pq.q.qtype, key=pq.answer.values, option_letters=pq.split.letters,
                    claim_primary=claim.primary, claim_categories=tuple(claim.categories),
                    claim_letters=tuple(claim.letters), claim_values=tuple(claim.values),
                    injection_regex=claim.injection, findings=findings,
                    tier0={"outcome": t0.outcome, "verdict": t0.verdict, "repair": t0.repair, "route": t0.route,
                           "basis": t0.basis})
        qid = pq.q.id
        # tier 1-2: guard, blind solvers, extraction, audit
        s.guard = self.once(("guard", r.report_id), lambda: run_guard(self.c, r.report_id, r.comment),
                            lambda e: {"score": None, "label": "error", "flag": False, "raw": e[:80]})
        raw_solver = {}
        for role in ("solver_1", "solver_2"):
            from .decide import SolverSig
            sig, raw = self.once((role, qid), lambda role=role: run_solver(self.c, role, pq),
                                 lambda e, role=role: (SolverSig(role, "", False, error=e[:120]), {}))
            s.solvers.append(sig)
            raw_solver[role] = raw
            if pq.q.qtype == "integerQuestion":
                s.integer_matches[role] = integer_match(sig, pq)
        s.extract = self.once(("extract", qid), lambda: run_extract(self.c, pq), lambda e: None)
        s.audit = self.once(("audit", qid), lambda: run_audit(self.c, pq), lambda e: None)
        # tier 3: per-option checks only where a key change is on the table
        self._option_checks(s, pq, claim, findings)
        # tier 4: triage sees everything; code decides first and tells triage what is left
        d_code = decide(s, self.tax, upto=TIER_TRIAGE - 1)
        code_edits = self._code_edit_preview(d_code, pq, findings, claim)
        task = self._task(d_code, code_edits, self._value_fix(d_code, s, pq))
        s.triage = self.once(("triage", r.report_id), lambda: run_triage(
            self.c, pq, r, task, self.tax, self._signals_text(s, pq, code_edits)), lambda e: None)
        d = decide(s, self.tax)
        contradicted = triage_contradicts(s, d)
        if contradicted:
            d.against += 1
            d.basis.append("triage disagrees with the code decision")
        # D-020: option content needs two independent sources agreeing (the stored solution counts as one)
        content_sources_ok = None
        if d.repair == "option_repair" and s.triage and s.triage.get("option_content"):
            content_sources_ok = self._content_sources(d, s, str(s.triage["option_content"]))
        elif d.repair == "option_repair":
            content_sources_ok = False
            d.notes.append("No content proposed for the blank option")
        # edit, guards, route, confidence
        edit, how, fails = self._edit(d, pq, findings, claim, s)
        strong, bar_why = self._auto_bar(d, s)
        if content_sources_ok is False:
            strong = False
        route, why = route_for(d.verdict, d.repair, self.tax, strong=strong, edit_ok=bool(edit) and not fails,
                               injection=s.injection, contradicted=contradicted)
        if bar_why:
            why = [bar_why if w == "evidence does not meet the auto-apply bar" else w for w in why]
        if fails and fails != ["no edit"]:
            why = [("no edit that passes the guards: " + "; ".join(fails)) if w == "no edit that passes the guards"
                   else w for w in why]
        if content_sources_ok is False and route == "faculty_review":
            why = [w for w in why if w != "evidence does not meet the auto-apply bar"] + [
                "fewer than two independent sources agree on the missing option content (D-020)"]
        if d.verdict is None:
            route, why = "faculty_review", ["no verdict could be decided"]
        conf = confidence(d.agree, d.against, definite=(d.decided_by == "code" and t0.outcome != "needs_llm"))
        # shadow mode: what each earlier tier would have decided
        shadow = []
        for t in range(0, TIER_TRIAGE):
            dt = decide(s, self.tax, upto=t)
            if not dt.complete:
                shadow.append({"tier": t, "name": TIER_NAMES[t], "would_exit": False})
                continue
            rt, _ = route_for(dt.verdict, dt.repair, self.tax, strong=dt.against == 0,
                              edit_ok=bool(edit) and not fails and dt.repair == d.repair,
                              injection=s.injection if t >= 1 else s.injection_regex, contradicted=False)
            same = (dt.verdict, dt.repair, rt) == (d.verdict, d.repair, route)
            shadow.append({"tier": t, "name": TIER_NAMES[t], "would_exit": True, "verdict": dt.verdict,
                           "repair": dt.repair, "route": rt, "agrees_with_final": same})
        settled_tier = next((x["tier"] for x in shadow if x["would_exit"] and x["agrees_with_final"]), TIER_TRIAGE)
        evidence = self._evidence(d, s, why, pq)
        live_edit = edit if route == "auto_apply" and not fails else None
        reply, reply_fails, reply_src = self._reply(r, claim, d, route, pq, s, live_edit)
        result = {"reportId": r.report_id, "questionId": qid, "verdict": d.verdict, "repair": d.repair
                  if d.verdict == "defect" else None, "edit": public_edit(edit) if not fails else None,
                  "route": route, "confidence": conf, "evidence": evidence, "student_reply": reply}
        detail = {"reportId": r.report_id, "tier0": s.tier0, "claim": claim.as_dict(),
                  "disputed": sorted(disputed_items(s)), "key_status": d.key_status, "decided_by": d.decided_by,
                  "basis": d.basis, "notes": d.notes, "agree": d.agree, "against": d.against, "route_why": why,
                  "edit_how": how, "edit_guard_failures": fails, "proposed_edit": public_edit(edit),
                  "guard": s.guard, "injection_regex": claim.injection, "injection_blocks_auto_apply": s.injection,
                  "solvers": [vars(x) for x in s.solvers], "solver_raw": raw_solver, "extract": s.extract,
                  "audit": s.audit, "option_checks": {k: [vars(v) for v in vs] for k, vs in s.option_checks.items()},
                  "value_candidates": s.value_candidates,
                  "triage": s.triage, "triage_contradicts": contradicted, "shadow": shadow,
                  "settled_tier": settled_tier, "reply_check_failures": reply_fails, "reply_source": reply_src}
        return {"result": result, "detail": detail}

    # ------------------------------------------------------------------ helpers
    def _option_checks(self, s: Signals, pq, claim, findings):
        key = set(pq.answer.values)
        if not key:
            return
        on_table = ("key" in disputed_items(s)
                    or any(f.check == "answer_malformed" for f in findings)
                    or any(sv.ok and sv.letters and set(sv.letters) != key for sv in s.solvers)
                    or any(m is False for m in s.integer_matches.values())
                    or (s.extract and s.extract.get("letters") and set(s.extract["letters"]) != key))
        if not on_table:
            return
        qid = pq.q.id
        if pq.q.qtype == "integerQuestion":
            self._value_checks(s, pq)
            return
        else:
            letters = set(key)
            for sv in s.solvers:
                letters |= set(sv.letters)
            if s.extract and s.extract.get("letters"):
                letters |= set(s.extract["letters"]) & set(pq.split.letters)
            letters |= set(claim.letters) & set(pq.split.letters)
            cands = {L: pq.split.options_text[L] or "(this option is blank)" for L in sorted(letters)
                     if L in pq.split.options_text}
        for cand, text in cands.items():
            s.option_checks[cand] = [self.once(("oc", qid, cand), lambda c=cand, t=text: run_option_check(
                self.c, "option_check", pq, c, t), lambda e: OptionVerdict("option_check", "", "cannot_tell", e[:80]))]
        # tie-breaker (other family) where solvers disagree with each other or with an option check
        solver_sets = {frozenset(sv.letters) for sv in s.solvers if sv.ok and sv.letters}
        int_split = len({m for m in s.integer_matches.values() if m is not None}) > 1
        for cand, text in cands.items():
            v = s.option_checks[cand][0].verdict
            backs = [sv for sv in s.solvers if sv.ok and cand in sv.letters]
            conflict = (len(solver_sets) > 1 or int_split or (backs and v == "incorrect")
                        or (not backs and v == "correct" and cand not in key) or v == "cannot_tell")
            if conflict:
                s.option_checks[cand].append(self.once(("tb", qid, cand), lambda c=cand, t=text: run_option_check(
                    self.c, "tiebreak", pq, c, t), lambda e: OptionVerdict("tiebreak", "", "cannot_tell", e[:80])))
        # key judged incorrect and no candidate correct: check the rest, to tell unsound from a wrong key
        if pq.has_options:
            says = {c: {v.verdict for v in vs} for c, vs in s.option_checks.items()}
            key_bad = all("incorrect" in says.get(L, set()) and "correct" not in says.get(L, set()) for L in key)
            any_good = any("correct" in vs for vs in says.values())
            if key_bad and not any_good:
                for L in pq.split.letters:
                    if L not in s.option_checks:
                        t = pq.split.options_text[L] or "(this option is blank)"
                        s.option_checks[L] = [self.once(("oc", qid, L), lambda c=L, t=t: run_option_check(
                            self.c, "option_check", pq, c, t),
                            lambda e: OptionVerdict("option_check", "", "cannot_tell", e[:80]))]

    def _value_checks(self, s: Signals, pq):
        """integerQuestion: check the key's value and each distinct solver value that differs from it."""
        qid, unit = pq.q.id, asked_unit(pq.split.stem_text)
        cands = {"key": f"{pq.answer.values[0]} {unit}".strip()}
        off = [sv for sv in s.solvers if sv.ok and sv.value is not None and s.integer_matches.get(sv.role) is False]
        groups = value_clusters(off)
        for g in groups[:2]:
            c = value_cand(g[0].value)
            s.value_candidates[c] = (g[0].value, g[0].unit)
            cands[c] = f"{g[0].value:g} {g[0].unit or unit}".strip()

        def backers(cand):
            if cand == "key":
                return [sv for sv in s.solvers if s.integer_matches.get(sv.role)]
            v, u = s.value_candidates[cand]
            return [sv for sv in off if same_value(sv.value, sv.unit, v, u)]

        for cand, text in cands.items():
            s.option_checks[cand] = [self.once(("vc", qid, cand), lambda c=cand, t=text: run_value_check(
                self.c, "value_check", pq, c, t), lambda e: OptionVerdict("value_check", "", "cannot_tell", e[:80]))]
        split = len(groups) + any(s.integer_matches.get(sv.role) for sv in s.solvers) > 1
        for cand, text in cands.items():
            v, backs = s.option_checks[cand][0].verdict, backers(cand)
            if split or v == "cannot_tell" or (backs and v == "incorrect") or (not backs and v == "correct"):
                s.option_checks[cand].append(self.once(("vtb", qid, cand), lambda c=cand, t=text: run_value_check(
                    self.c, "value_tiebreak", pq, c, t),
                    lambda e: OptionVerdict("value_tiebreak", "", "cannot_tell", e[:80])))

    @staticmethod
    def _auto_bar(d, s: Signals) -> tuple[bool, str]:
        """D-023: whether the evidence meets the auto-apply bar for this repair's risk, and why not."""
        if d.against:
            return False, ""
        if d.repair in config.LOW_RISK_REPAIRS:
            t0 = s.tier0 or {}
            if any(f.strength in (DEFINITE, SIGNAL) and f.repair == d.repair for f in s.findings) or \
                    (t0.get("outcome") == "code_settled" and t0.get("repair") == d.repair):
                return True, ""             # a check finding, or a tier-0 settlement (e.g. a named word confirmed)
            return False, f"no code check supports the low-risk repair {d.repair} (D-023)"
        if d.decided_by == "triage":
            return False, f"high-stakes repair {d.repair} chosen by triage alone, not two independent sources (D-023)"
        if d.repair in ("answer_key", "type_mismatch") and d.key_status not in (KEY_OK, KEY_WRONG):
            return False, f"the blind solvers did not confirm the key for {d.repair} (D-023)"
        if d.complete or d.decided_by == "code+llm":
            return True, ""
        return False, ""

    @staticmethod
    def _content_sources(d, s: Signals, content: str) -> bool:
        """D-020: which independent sources give the same value as the proposed option content."""
        q = parse_quantity(content)
        agreeing, fams = [], set()
        if q:
            for sv in s.solvers:
                if counts(sv) and sv.value is not None and sv.family not in fams and \
                        same_quantity(q[0], q[1], sv.value, sv.unit, config.OPTION_REL_TOL):
                    fams.add(sv.family)
                    agreeing.append(f"{_model(sv.role)} blind solve ({sv.value:g} {sv.unit})".replace(" )", ")"))
            ex = s.extract or {}
            if ex.get("value") is not None and same_quantity(q[0], q[1], ex["value"], ex.get("unit", ""),
                                                             config.OPTION_REL_TOL):
                agreeing.append(f"the stored solution ({ex['value']:g} {ex.get('unit', '')})".replace(" )", ")"))
        if len(agreeing) >= 2:
            d.agree += len(agreeing)
            d.notes.append(f"Content \"{content}\" for the blank option agreed by {len(agreeing)} independent "
                           f"sources: {'; '.join(agreeing)}")
            return True
        d.against += 1
        d.notes.append(f"Content \"{content}\" for the blank option: only {len(agreeing)} independent source(s) "
                       f"agree{(': ' + '; '.join(agreeing)) if agreeing else ''}"
                       + ("" if q else " (the content is not a value code can compare)"))
        return False

    def _value_fix(self, d, s: Signals, pq):
        """(wrong value, right value, unit, text) when a solution_fix is a final-value correction that every
        signal backs: key confirmed by both solver families and the option/value check, solution ends elsewhere."""
        if d.repair != "solution_fix" or d.key_status != KEY_OK:
            return None
        ex, au = s.extract or {}, s.audit or {}
        if ex.get("value") is None or au.get("contradiction") or au.get("about_other_question"):
            return None
        fams = {sv.family for sv in s.solvers if counts(sv)}
        if len(fams) < 2:
            return None
        if pq.has_options:
            if any(_check_verdicts(s, L) != {"correct"} for L in s.key):
                return None
            q = parse_quantity(pq.split.options_text.get(s.key[0], "")) if len(s.key) == 1 else None
            if not q:
                return None
            right, unit = q
        else:
            if _check_verdicts(s, "key") != {"correct"}:
                return None
            try:
                right, unit = float(s.key[0]), asked_unit(pq.split.stem_text)
            except ValueError:
                return None
        wrong = ex["value"]
        if same_quantity(wrong, ex.get("unit", ""), right, unit, config.OPTION_REL_TOL):
            return None
        return wrong, right, unit

    def _code_edit_preview(self, d, pq, findings, claim) -> str:
        if d.verdict != "defect" or not d.repair:
            return "none"
        e, how = code_edit(d.repair, pq, findings, new_answer=self._new_answer(d, pq),
                           named_word=(claim.named_words or [None])[0])
        return f"{d.repair}: {json.dumps(public_edit(e), ensure_ascii=False)}" if e else f"none ({how})"

    @staticmethod
    def _new_answer(d, pq):
        if d.repair == "answer_key":
            return d.new_answer or (pq.answer.values if any("combined_string" in f or "empty_element" in f
                                                            for f in pq.answer.flags) else None)
        return None

    def _task(self, d, code_edits, value_fix=None) -> str:
        if d.needs_triage == "verdict":
            return ("Code could not decide the verdict from the evidence. Choose `verdict` and, for a defect, "
                    f"`repair`. Code signals point at these repairs: {list(d.allowed_repairs) or 'none'}. "
                    "Code will route your choice to faculty unless it agrees with those signals.")
        if d.needs_triage == "repair":
            return (f"Code decided verdict = {d.verdict}. Choose `repair` from exactly {list(d.allowed_repairs)}, "
                    "and give an `edit` if that repair needs one. If you believe the verdict is wrong, put the "
                    "verdict you believe in `verdict`; code will then route the case to faculty.")
        if d.needs_triage == "option_content":
            return (f"Code decided verdict = {d.verdict}, repair = {d.repair} (an option is blank or missing). "
                    "Give that option's correct content in `option_content`, using the stored solution if it "
                    "states it. Put the verdict you believe in `verdict`.")
        fix = ""
        if value_fix:
            wrong, right, unit = value_fix
            fix = (f" The stored solution ends at the wrong value {wrong:g}; the answer key, both blind solvers and "
                   f"the independent check agree on {right:g} {unit}. Propose the minimal solution_fix `edit` that "
                   f"changes only that final value to {right:g} (in the unit the solution uses).").replace(" .", ".")
        return (f"Code decided verdict = {d.verdict}, repair = {d.repair or 'none'}. Do not re-decide them; state "
                "in `verdict`/`repair` what you believe, so code can detect a disagreement and route to faculty. "
                f"Give an `edit` only if the repair needs one and it is not in the list of code edits.{fix}")

    def _signals_text(self, s: Signals, pq, code_edits: str) -> dict:
        solv = []
        for sv in s.solvers:
            if not sv.ok:
                solv.append(f"- {sv.role}: no answer ({sv.error})")
                continue
            val = f"{sv.value:g} {sv.unit}".strip() if sv.value is not None else "no numeric value"
            solv.append(f"- {sv.role} ({sv.family}): {val}; maps to option(s) {''.join(sv.letters) or '-'}; "
                        f"missing info: {sv.missing or 'none'}; issues: {list(sv.issues) or 'none'}")
        ex = s.extract or {}
        au = s.audit or {}
        oc = []
        for c, vs in s.option_checks.items():
            oc.append(f"- ({c}): " + "; ".join(f"{v.family}: {v.verdict} ({v.reason})" for v in vs))
        return {
            "code_findings": findings_text(s.findings),
            "solver_results": "\n".join(solv) or "- none",
            "extraction_result": (f"ends at {ex.get('shown') or ex.get('statement') or 'unknown'}; "
                                  f"names option: {ex.get('option_named') or 'none'}") if ex else "unavailable",
            "audit_result": (f"values not in question: {au.get('values_not_in_question') or 'none'}; "
                             f"contradiction: {au.get('contradiction')} {au.get('contradiction_quote', '')}; "
                             f"about another question: {au.get('about_other_question')} "
                             f"{au.get('other_question_quote', '')}") if au else "unavailable",
            "option_checks": "\n".join(oc) or "- not run (no key change on the table)",
            "code_edits": code_edits,
        }

    def _edit(self, d, pq, findings, claim, s):
        if d.verdict != "defect" or not d.repair:
            return None, "no edit (not a defect)", []
        if not self.tax["repairs"][d.repair]["auto"]:
            return None, "no edit (faculty-only repair)", []
        e, how = code_edit(d.repair, pq, findings, new_answer=self._new_answer(d, pq),
                           named_word=(claim.named_words or [None])[0],
                           option_content=(s.triage or {}).get("option_content"))
        if not e and s.triage and s.triage.get("edit") and s.triage.get("repair") == d.repair:
            e, how = map_clean_edit(pq, s.triage["edit"])
        if not e:
            why = (s.triage or {}).get("no_edit_reason")
            return None, how + (f"; triage gave no edit: {why}" if why else ""), ["no edit"]
        fails = guard(e, d.repair, pq, self.tax)
        if how.startswith("llm: mapped") and e["field"] in ("question", "solution"):
            if re.findall(r"<[^>]*>", e["find"]) != re.findall(r"<[^>]*>", e["replace"]):
                fails.append("edit drops or changes markup")
        if d.repair == "solution_fix":
            vf = self._value_fix(d, s, pq)
            if not vf:
                fails.append("solution_fix auto-applies only as a final-value correction that every signal backs")
            elif "_find_clean" not in e:
                fails.append("solution edit is not a clean-text value correction")
            else:
                wrong, right, unit = vf
                sol_unit = (s.extract or {}).get("unit", "")
                r_si, r_dim = to_si(right, unit)
                one_si, s_dim = to_si(1.0, sol_unit)
                right_sol = r_si / one_si if (r_dim and r_dim == s_dim) else right
                bad = value_correction_check(e["_find_clean"], e["_replace_clean"], wrong, right_sol)
                fails += bad
                if not bad:
                    d.notes.append(f"Solution edit changes only the final value {wrong:g} -> {right_sol:g}, "
                                   "matching the key, both blind solves and the independent check")
        if d.repair == "stem_data" and not fails:
            fails += self._resolve_check(d, s, pq, e)
        return e, how, fails

    def _resolve_check(self, d, s: Signals, pq, e) -> list[str]:
        """D-021: content inserted into the stem must let a blind re-solve reproduce the keyed answer."""
        fc, rc, stem = e.get("_find_clean"), e.get("_replace_clean"), pq.split.stem_text
        if e["field"] != "question" or not fc or rc is None or stem.count(fc) != 1:
            d.notes.append("Stem edit could not be re-solved: the edited span is not found once in the stem")
            return ["stem edit cannot be re-solved (D-021)"]
        new_stem = stem.replace(fc, rc, 1)
        results = []
        for role in ("solver_1", "solver_2"):
            sig, _ = self.once(("resolve", pq.q.id, role, new_stem),
                               lambda role=role: run_solver(self.c, role, pq, stem_text=new_stem),
                               lambda err, role=role: (SolverSig(role, "", False, error=err[:120]), {}))
            if pq.q.qtype == "integerQuestion":
                ok = integer_match(sig, pq) is True
            else:
                ok = bool(sig.letters) and set(sig.letters) == set(s.key)
            results.append((sig, ok))
        counted = [ok for sig, ok in results if counts(sig)]
        desc = "; ".join(_show_solver(sig, pq).replace("(blind solve)", "(re-solve)") for sig, _ in results)
        if counted and all(counted):
            d.notes.append(f"Re-solve with \"{rc}\" in the stem reproduces the key: {desc}")
            return []
        d.notes.append(f"Re-solve with \"{rc}\" in the stem does not reproduce the key: {desc}")
        return ["re-solve with the inserted value does not reproduce the keyed answer (D-021)"]

    EVIDENCE_MAX = 600

    @classmethod
    def _evidence(cls, d, s: Signals, why, pq) -> str:
        """Built in code from the signals: which model said what, what the stored solution and the key say.
        Triage's own evidence is added only where triage decided (the verdict, or the repair from a shortlist)."""
        parts, low = [], []
        t0 = s.tier0 or {}
        if t0.get("outcome") in ("code_settled", "code_routed") and t0.get("basis"):
            parts.append(f"Code check: {t0['basis']}")
        disputed = disputed_items(s)
        answer_related = bool(d.key_status) or bool({"key", "solution", "stem_data", "nothing_specific", "option"}
                                                     & disputed)
        if answer_related and s.key:
            parts.append("Key: " + _show_answer(s.key, pq))
            for sv in s.solvers:
                parts.append(_show_solver(sv, pq))
            ex = s.extract or {}
            if ex.get("ok"):
                end = ex.get("shown") or (f"\"{_clip(ex['statement'], 80)}\"" if ex.get("statement") else
                                          "no clear value")
                parts.append(f"Stored solution ({_model('extract')}) ends at {end}")
            checks = _show_checks(s)
            if checks:
                parts.append(checks)
                low = [checks]                 # dropped first when the evidence is too long
        parts += d.notes
        au = s.audit or {}
        if au.get("values_not_in_question") and "stem_data" in disputed:
            parts.append(f"Audit ({_model('audit')}): solution uses values the stem never gives: "
                         + _clip("; ".join(_show_value(v) for v in au["values_not_in_question"]), 140))
        if au.get("contradiction"):
            parts.append(f"Audit ({_model('audit')}): solution contradicts itself: "
                         f"\"{_clip(str(au.get('contradiction_quote')), 110)}\"")
        if au.get("about_other_question"):
            parts.append(f"Audit ({_model('audit')}): part of the solution is about another question: "
                         f"\"{_clip(str(au.get('other_question_quote')), 110)}\"")
        if d.decided_by in ("triage", "code+llm") and s.triage and s.triage.get("evidence"):
            parts.append(f"Triage ({_model('triage')}): {s.triage['evidence']}")
        if why and d.verdict in ("defect", None):
            parts.append("Sent to faculty: " + "; ".join(why))
        # over the limit: drop the per-option check line first, then the solver lines (their outcome is
        # already in the code notes / basis), then anything that still does not fit
        solver_lines = [p for p in parts if "(blind solve)" in str(p)]
        norm = lambda p: re.sub(r"\s+", " ", str(p)).strip().rstrip(".").strip()
        kept = [p for p in parts if norm(p)]
        for drop in (low, solver_lines):
            if len(". ".join(map(norm, kept))) <= cls.EVIDENCE_MAX:
                break
            kept = [p for p in kept if p not in drop]
        out = ""
        for p in kept:                        # keep whole parts, in order, within the limit
            nxt = f"{out}. {norm(p)}" if out else norm(p)
            if len(nxt) > cls.EVIDENCE_MAX:
                continue
            out = nxt
        return out + "." if out else out

    # ------------------------------------------------------------------ reply
    def _reply(self, r, claim, d, route, pq, s, live_edit=None):
        proposed = bool(claim.values or claim.letters) and not s.injection
        info = self._reply_info(claim, d, route, pq, s, live_edit)
        facts = self._facts(claim, d, route, info, proposed)
        lang = "hinglish" if claim.hinglish else "english"
        try:
            text, fails = run_reply(self.c, r, lang, d.verdict or "undecided", route, facts,
                                    syllabus="syllabus" in claim.categories, proposed_answer=proposed)
        except LLMError as e:
            text, fails = "", [f"call failed: {e}"[:120]]
        if fails or not text:
            return self._fallback_reply(d, route, lang, info, proposed), fails, "fallback"
        return text, fails, "llm"

    def _reply_info(self, claim, d, route, pq, s, live_edit=None) -> dict:
        """The answer facts the reply may use, all decided by code."""
        info = {"unsound": d.repair == "unsound" or d.key_status == UNSOUND, "answer": "", "step": "",
                "content": "", "letter": "", "what": ""}
        if d.verdict == "defect" and d.repair:
            malformed = any(f.check == "answer_malformed" for f in s.findings)
            info["what"] = (WHAT_WAS_WRONG["answer_key_malformed"] if d.repair == "answer_key" and malformed
                            else WHAT_WAS_WRONG.get(d.repair, ""))
        if info["unsound"]:
            return info
        if d.repair == "option_repair":
            content = str((s.triage or {}).get("option_content") or "")
            blank = [L for L in s.key if not pq.split.options_text.get(L, "").strip()]
            info["letter"] = blank[0] if blank else ""
            if content and route == "auto_apply" and info["letter"]:
                info["content"] = content
                info["answer"] = f"({info['letter']}) {content}"
                info["step"] = self._key_step(s, pq, value=parse_quantity(content))
            return info
        ans = d.new_answer if d.repair == "answer_key" and d.new_answer else (
            tuple(pq.answer.values) if d.key_status in (KEY_OK, KEY_WRONG) or d.verdict == "no_error" else None)
        if not ans:
            return info
        if pq.has_options:
            # option text as students will see it once a live edit is applied (e.g. a corrected spelling)
            info["answer"] = ", ".join(f"({L}) {_post_edit(pq.split.options_text.get(L, ''), live_edit)}".strip()
                                       for L in ans)
            info["step"] = self._key_step(s, pq, letters=set(ans))
        else:
            unit = asked_unit(pq.split.stem_text)
            info["answer"] = f"{ans[0]} {unit}".strip()
            try:
                info["step"] = self._key_step(s, pq, value=(float(ans[0]), unit))
            except ValueError:
                pass
        return info

    @staticmethod
    def _key_step(s: Signals, pq, letters=None, value=None) -> str:
        """The working of a blind solver whose answer is the correct one (code checked the match)."""
        for sv in s.solvers:
            if not counts(sv) or not sv.working:
                continue
            if letters is not None and sv.letters and set(sv.letters) == letters:
                return sv.working
            if value and sv.value is not None and same_quantity(sv.value, sv.unit, value[0], value[1],
                                                                config.OPTION_REL_TOL):
                return sv.working
        return ""

    def _facts(self, claim, d, route, info, proposed) -> str:
        lines = []
        if info["unsound"]:
            lines.append("No option is correct as written, so there is no right option to tell the student. "
                         "Do not name any option or value as the answer.")
        if info["what"]:
            lines.append(f"What was wrong with the question: {info['what']}")
        if info["answer"]:
            lines.append(f"Correct answer: {info['answer']}")
        if info["content"]:
            lines.append(f"Option ({info['letter']}) was blank; it now reads {info['content']}.")
        elif d.repair == "option_repair" and info["letter"]:
            lines.append(f"Option ({info['letter']}) is blank; a teacher will add its content.")
        if info["step"]:
            lines.append(f"Key step: {info['step']}")
        if proposed:
            given = [f"({L})" for L in claim.letters] or [f"{v:g}" for v in claim.values]
            lines.append(f"Student's answer: {', '.join(given)}")
        else:
            lines.append("The student did not propose an answer of their own; do not say their answer was wrong.")
        lines.append("The student spotted a real problem: " + ("yes" if d.verdict == "defect" else "no"))
        if d.verdict == "defect":
            lines.append({"auto_apply": "The fix is live now.", "faculty_review": "A teacher will review and fix it.",
                          }.get(route, ""))
        if d.verdict in ("display_issue", "app_issue"):
            lines.append("The stored question is complete; the problem is in the app or display.")
        if d.verdict == "language_mode":
            lines.append("The question is only available in English for now.")
        if "syllabus" in claim.categories:
            lines.append("The question stays live while a teacher checks whether it is in the syllabus; "
                         "it has not been removed.")
        if d.verdict == "already_fixed":
            lines.append("A teacher already corrected this; the live question is fixed.")
        return "\n".join(x for x in lines if x)

    @staticmethod
    def _fallback_reply(d, route, lang, info, proposed) -> str:
        """Code-built reply, used when the model's reply fails a check."""
        hi = lang == "hinglish"
        ans = info.get("answer") or ""
        if d.repair == "syllabus":
            return ("Thanks batane ke liye. Teacher check karenge ki yeh syllabus mein hai ya nahi; tab tak question "
                    "available rahega." if hi else "Thanks for flagging this. A teacher will check whether it is in "
                    "the syllabus; the question stays available meanwhile.")
        if info.get("unsound"):
            return ("Thanks, aapne sahi sawaal uthaya: jaisa likha hai, koi bhi option sahi nahi hai. Teacher is "
                    "question ko theek karenge." if hi else "Thanks, you were right to question this: as written, "
                    "none of the options is correct. A teacher will correct the question.")
        if d.verdict == "defect":
            if hi:
                return ("Thanks, aapne sahi pakda, is question mein galti hai." + (f" Sahi answer {ans} hai." if ans
                        else "") + (" Ab yeh theek ho gaya hai." if route == "auto_apply" else
                                    " Teacher check karke ise theek karenge."))
            return ("Thanks, you were right to flag this: there is a problem with this question."
                    + (f" The correct answer is {ans}." if ans else "")
                    + (" It's fixed now." if route == "auto_apply" else " A teacher will review and fix it."))
        if d.verdict == "no_error":
            if hi:
                return (f"Humne ise alag se dobara solve kiya: sahi answer {ans} hai, aur question theek hai."
                        if ans else "Humne ise dobara check kiya: question aur answer theek hain.")
            lead = "Thanks for checking it carefully. " if proposed else ""
            step = info.get("step") or ""
            tail = f" Key step: {step.rstrip('.')}." if step and len(step) <= 160 else ""
            return (lead + (f"We re-solved it independently and the correct answer is {ans}, so the question is "
                            "right as given." if ans else "We re-checked it and the question is right as given.")
                    + tail)
        if d.verdict in ("display_issue", "app_issue"):
            return ("Thanks batane ke liye. Question khud theek hai; yeh problem app team ko bhej di hai." if hi else
                    "Thanks for telling us. The question itself is fine; we've passed this to the app team.")
        if d.verdict == "language_mode":
            return ("Thanks poochne ke liye. Abhi yeh question sirf English mein available hai." if hi else
                    "Thanks for asking. This question is only available in English for now.")
        if d.verdict == "already_fixed":
            return ("Thanks! Teacher ne ise pehle hi theek kar diya hai." if hi else
                    "Thanks! A teacher has already fixed this, so the question should look right now.")
        return ("Thanks batane ke liye. Teacher ise dekhenge." if hi else
                "Thanks for the report. A teacher will take a look.")


# --------------------------------------------------------------------------
# Evidence helpers (code-built, D-001)

def _check_verdicts(s: Signals, cand: str) -> set:
    return {v.verdict for v in s.option_checks.get(cand, []) if v.verdict in ("correct", "incorrect")}


def _model(role: str) -> str:
    return config.ROLES[role][1].split("/")[-1]


def _plain(x) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(x or "")))).strip()


def _post_edit(text: str, edit) -> str:
    """Clean option text after a live question edit, if the edit touches it."""
    if not edit or edit.get("field") != "question":
        return text
    f, r = _plain(edit.get("find")), _plain(edit.get("replace"))
    return text.replace(f, r) if f and f in text else text


def _clip(text: str, n: int) -> str:
    """Cut at a word boundary, with an ellipsis."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;:.")
    return cut + "…"


def _show_value(v) -> str:
    try:
        x = json.loads(v) if isinstance(v, str) and v.startswith("{") else v
    except ValueError:
        x = v
    if isinstance(x, dict):
        return f"{x.get('what', '')} {x.get('value', '')}".strip()
    return str(x)


def _show_answer(ans, pq) -> str:
    if pq.has_options:
        return ", ".join(f"({L}) " + (_clip(pq.split.options_text.get(L, ''), 40).rstrip('.') or "[blank]")
                         for L in sorted(ans))
    return " ".join([str(ans[0]), asked_unit(pq.split.stem_text)]).strip()


def _show_solver(sv, pq) -> str:
    who = f"{_model(sv.role)} (blind solve)"
    if not sv.ok:
        return f"{who}: no answer"
    val = f"{sv.value:g} {sv.unit}".strip() if sv.value is not None else ""
    if pq.has_options:
        if sv.letters and val:
            txt = f"{val} = ({''.join(sv.letters)})"
        elif sv.letters:
            txt = f"({''.join(sv.letters)}), letter only (no value given)"
        elif val:
            txt = f"{val}, which matches no listed option"
        else:
            txt = "no option and no value"
    else:
        txt = val or "no value"
    if sv.missing:
        txt += f"; reports missing data ({_clip(sv.missing, 50)}), so not counted"
    return f"{who}: {txt}"


def _show_checks(s: Signals) -> str:
    if not s.option_checks:
        return ""
    items = []
    for cand, vs in s.option_checks.items():
        label = ("key value" if cand == "key" else cand[1:]) if s.qtype == "integerQuestion" else f"({cand})"
        items.append(f"{label} " + ", ".join(f"{v.verdict} [{_model(v.role)}]" for v in vs))
    name = "Value checks" if s.qtype == "integerQuestion" else "Option checks"
    return f"{name}: " + "; ".join(items)


def _provider_stats(client) -> dict:
    """Which provider answered this run's calls (from the call log): cache hits, live calls, D-022 fallbacks."""
    out = {"fallback_calls": client.fallback_calls}
    try:
        lines = client.log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        x = json.loads(line)
        if x.get("run_id") != client.run_id or x.get("status") != "ok":
            continue
        k = f"{x.get('provider')}:{x.get('model')}" + (" (cache)" if x.get("cache_hit") else "") +             (" (fallback)" if x.get("fallback") else "")
        out[k] = out.get(k, 0) + 1
    return out


def _guard_stats(details) -> dict:
    """Prompt-guard flag rate. A guard flag (score >= GUARD_THRESHOLD) is logged; on its own it blocks
    auto-apply only at score >= GUARD_BLOCK_ALONE, or at any flag when the regex detector also fires."""
    n = len(details)
    g = lambda d: (d.get("guard") or {})
    flagged = [d for d in details if g(d).get("flag")]
    regex = sum(1 for d in details if d.get("injection_regex"))
    both = sum(1 for d in flagged if d.get("injection_regex"))
    unparsed = sum(1 for d in details if g(d).get("label") in ("unparsed", "error"))
    return {"reports": n, "prompt_guard_flagged": len(flagged),
            "prompt_guard_flag_rate": round(len(flagged) / n, 3) if n else None,
            "regex_flagged": regex, "both_flagged": both, "guard_only": len(flagged) - both,
            "regex_only": regex - both, "guard_unparsed_or_error": unparsed,
            "guard_flagged_reports": {d["reportId"]: round(g(d).get("score") or 0, 4) for d in flagged},
            "guard_flags_logged_only (below block threshold, no regex)": {
                d["reportId"]: round(g(d).get("score") or 0, 4) for d in flagged
                if not d.get("injection_regex") and (g(d).get("score") or 0) < config.GUARD_BLOCK_ALONE},
            "blocked_auto_apply": [d["reportId"] for d in details if d.get("injection_blocks_auto_apply")]}


# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", default="", help="comma-separated report ids (default: all)")
    ap.add_argument("--cap", type=float, default=config.DEFAULT_SPEND_CAP_USD)
    ap.add_argument("--offline", action="store_true", help="cache only; never touch the network")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--swap-model", default="", metavar="MODEL",
                    help="robustness test (D-005): MODEL for " + ", ".join(SWAP_ROLES) + "; writes only to logs/runs/")
    a = ap.parse_args(argv)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    swapped = {}
    if a.swap_model:
        if a.swap_model not in config.FAMILY:
            raise SystemExit(f"--swap-model: unknown model {a.swap_model} (add it to config.FAMILY)")
        for role in SWAP_ROLES:
            prov, model, *rest = config.ROLES[role]
            swapped[role] = [model, a.swap_model]
            config.ROLES[role] = (prov, a.swap_model, *rest)
        run_id += "-swap-" + a.swap_model.split("/")[-1]
    t_start = time.perf_counter()
    taxonomy = load_taxonomy()
    questions = load_questions()
    reports = sorted(load_reports(), key=lambda r: r.report_id)
    wanted = [x.strip() for x in a.reports.split(",") if x.strip()]
    if wanted:
        reports = [r for r in reports if r.report_id in set(wanted)]
    full_run = not wanted

    parsed = {qid: parse_question(q) for qid, q in questions.items()}
    vocab = build_vocab(list(parsed.values()))
    findings = {qid: run_checks(pq, vocab) for qid, pq in parsed.items()}

    client = Client(run_id, cap_usd=a.cap, use_cache=not a.no_cache, offline=a.offline)
    runner = Runner(client, taxonomy)
    out, details, stopped = [], [], None
    for r in reports:
        try:
            res = runner.process(r, parsed[r.question_id], findings[r.question_id], vocab)
        except BudgetExceeded as e:
            stopped = f"spend cap reached before {r.report_id}: {e}"
            break
        out.append(res["result"])
        details.append(res["detail"])
        print(f"{r.report_id}: {res['result']['verdict']}/{res['result']['repair'] or '-'} -> "
              f"{res['result']['route']} ({res['result']['confidence']}) spent ${client.spend.spent_usd:.4f}")

    run_dir = ROOT / "logs" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results = [{k: x[k] for k in RESULT_KEYS} for x in out]
    (run_dir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(run_dir / "details.jsonl", "w", encoding="utf-8") as fh:
        for d in details:
            fh.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
    if full_run and not stopped and not swapped:
        (ROOT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    shadow_dis = [{"reportId": d["reportId"], "tier": s["tier"], "name": s["name"],
                   "early": [s["verdict"], s["repair"], s["route"]]}
                  for d in details for s in d["shadow"] if s.get("would_exit") and not s.get("agrees_with_final")]
    settled = {}
    for d in details:
        settled[TIER_NAMES[d["settled_tier"]]] = settled.get(TIER_NAMES[d["settled_tier"]], 0) + 1
    summary = {
        "run_id": run_id, "swapped_roles": swapped, "reports_requested": len(reports), "reports_done": len(out), "full_run": full_run,
        "stopped": stopped, "total_time_s": round(time.perf_counter() - t_start, 1),
        "total_tokens": {"in": client.tokens_in_total, "out": client.tokens_out_total},
        "spend_usd": round(client.spend.spent_usd, 6), "spend_cap_usd": client.spend.cap_usd,
        "spend_by_model": {k: round(v, 6) for k, v in client.spend.by_model.items()},
        "calls_per_stage": client.calls_by_stage,
        "cases_settled_per_tier": settled,
        "routed_to_faculty": sum(1 for x in out if x["route"] == "faculty_review"),
        "auto_applied": sum(1 for x in out if x["route"] == "auto_apply"),
        "shadow_early_exit_disagreements": shadow_dis,
        "injection_flags": _guard_stats(details),
        "calls_by_provider": _provider_stats(client),
        "results_file": str((run_dir / "results.json").relative_to(ROOT)),
    }
    (run_dir / "run-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if not swapped:
        (ROOT / "logs" / "run-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("reports_done", "stopped", "spend_usd", "routed_to_faculty",
                                              "auto_applied", "injection_flags")}, indent=1))
    return summary


if __name__ == "__main__":
    main()
