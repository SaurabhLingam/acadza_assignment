"""Code decides verdict, repair, route and confidence from the signals (D-001, D-016).

Pure functions over a `Signals` bundle; no I/O. The LLM tiers only fill Signals.

Answer disputes are settled by agreement between the blind solvers and the
per-option checks (per-value checks for integer questions), for or against the key.
A solver that reports missing information assumed something, so its answer is
not counted as independent agreement either way.
  KEY_OK     -> no_error (for a dispute of the key)
  KEY_WRONG  -> defect / answer_key, new key = the agreed answer
  UNSOUND    -> defect / unsound (no option survives the option checks)
  UNCLEAR    -> code cannot settle: triage proposes, route is faculty_review
Triage chooses the verdict only where code cannot (e.g. solution_fix vs
wrong_question, missing stem data without agreeing signals). If triage
contradicts what code decided, the case goes to faculty.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .checks import DEFINITE, SIGNAL
from .mathexpr import same_quantity

KEY_OK, KEY_WRONG, UNSOUND, UNCLEAR = "key_ok", "key_wrong", "unsound", "unclear"

TIER_CODE, TIER_SOLVE1, TIER_SOLVE2, TIER_OPTIONS, TIER_TRIAGE = 0, 1, 2, 3, 4
TIER_NAMES = {0: "code", 1: "solver_1+guard", 2: "solver_2+extract+audit", 3: "option_checks+tiebreak",
              4: "triage"}

NON_DEFECT_ROUTE = "no_change"


@dataclass
class SolverSig:
    role: str
    family: str
    ok: bool
    value: float | None = None          # evaluated final_expression
    unit: str = ""
    letters: tuple = ()                 # option letters this solver's answer maps to
    missing: str | None = None
    issues: tuple = ()
    error: str = ""
    working: str = ""                   # the solver's own key steps (used as the reply's key step)
    from_letter: bool = False           # no expression given; the picked letter is this solver's answer


@dataclass
class OptionVerdict:
    role: str
    family: str
    verdict: str                        # correct | incorrect | cannot_tell
    reason: str = ""
    own_answer: str = ""


@dataclass
class Signals:
    """Everything gathered for one report. Fields for tiers not yet run stay None/empty."""
    qtype: str
    key: tuple                          # normalised stored key (letters, or one number string)
    option_letters: tuple
    claim_primary: str
    claim_categories: tuple
    claim_letters: tuple = ()
    claim_values: tuple = ()
    injection_regex: bool = False
    findings: list = field(default_factory=list)        # checks.Finding
    tier0: dict | None = None                           # profiler decision (outcome, verdict, repair, route, basis)
    guard: dict | None = None                           # {"score", "label", "flag", "raw"}
    solvers: list = field(default_factory=list)         # SolverSig
    extract: dict | None = None                         # {"value","unit","letters","option_named","statement"}
    audit: dict | None = None                           # {"values_not_in_question","contradiction","about_other_question"}
    option_checks: dict = field(default_factory=dict)   # candidate -> [OptionVerdict]; candidates are option
                                                        # letters, or "key" / "=<value>" for integer questions
    value_candidates: dict = field(default_factory=dict) # "=<value>" -> (value, unit) for integer questions
    triage: dict | None = None
    integer_matches: dict = field(default_factory=dict) # solver role -> bool (matches key), for integer questions

    @property
    def injection(self) -> bool:
        return self.injection_regex or bool(self.guard and self.guard.get("flag"))


@dataclass
class Decision:
    verdict: str | None
    repair: str | None
    route: str
    confidence: float
    decided_by: str                     # code | code+llm | triage | none
    complete: bool                      # True if code could settle it with the signals available
    basis: list = field(default_factory=list)
    new_answer: tuple | None = None
    agree: int = 0
    against: int = 0
    needs_triage: str = ""              # what triage must decide ("" = nothing)
    allowed_repairs: tuple = ()         # when triage chooses the repair
    key_status: str = ""
    notes: list = field(default_factory=list)   # extra code-built evidence (e.g. which sources agreed)


# --------------------------------------------------------------------------
# Resolving the answer from solvers + option checks
# --------------------------------------------------------------------------

def counts(sv: SolverSig) -> bool:
    """A solver answer counts as independent evidence only if it needed no assumption."""
    return sv.ok and not sv.missing


def _assumed(s: Signals) -> list[str]:
    return [f"{sv.role} reports missing information ({str(sv.missing)[:60]}), so its answer is not counted"
            for sv in s.solvers if sv.ok and sv.missing]


def value_cand(value: float) -> str:
    return f"={value:g}"


def same_value(a: float, ua: str, b: float, ub: str) -> bool:
    return same_quantity(a, ua or "", b, ub or "", config.INTEGER_REL_TOL, config.INTEGER_ABS_TOL)


def value_clusters(solvers) -> list[list[SolverSig]]:
    """Group solver values that agree within the integer tolerance."""
    groups: list[list[SolverSig]] = []
    for sv in solvers:
        for g in groups:
            if same_value(sv.value, sv.unit, g[0].value, g[0].unit):
                g.append(sv)
                break
        else:
            groups.append([sv])
    return groups


def _value_check_for(s: Signals, value: float, unit: str) -> str:
    for cand, (v, u) in s.value_candidates.items():
        if same_value(value, unit, v, u):
            return _check_says(s, cand)
    return "unknown"


def _answers(s: Signals) -> list[tuple[str, frozenset]]:
    """(family, answer set) for each solver that produced an answer it did not have to assume data for."""
    out = []
    for sv in s.solvers:
        if not counts(sv):
            continue
        if s.qtype == "integerQuestion":
            if sv.value is not None:
                out.append((sv.family, frozenset({("int", round(sv.value, 6))})))
        elif sv.letters:
            out.append((sv.family, frozenset(sv.letters)))
    return out


def _checks_for(s: Signals, cand: str) -> list[OptionVerdict]:
    return s.option_checks.get(cand, [])


def _check_says(s: Signals, cand: str) -> str:
    """Combined option-check verdict for one candidate: correct / incorrect / split / unknown."""
    vs = {v.verdict for v in _checks_for(s, cand) if v.verdict in ("correct", "incorrect")}
    if not vs:
        return "unknown"
    return vs.pop() if len(vs) == 1 else "split"


def resolve_key(s: Signals) -> tuple[str, tuple | None, list[str], int, int]:
    """Return (status, agreed_answer, basis, agree, against) for the stored key."""
    basis: list[str] = _assumed(s)
    key = set(s.key)
    if s.qtype == "integerQuestion":
        votes = [(sv, s.integer_matches.get(sv.role)) for sv in s.solvers if counts(sv) and sv.value is not None]
        if not votes:
            return UNCLEAR, None, basis + ["no usable solver answer"], 0, 0
        ok = [sv.family for sv, m in votes if m]
        bad = [sv for sv, m in votes if m is False]
        kc = _check_says(s, "key")
        if bad and not ok:
            fams = {sv.family for sv in bad}
            groups = value_clusters(bad)
            if len(fams) >= 2 and len(groups) == 1:
                v0 = groups[0][0]
                alt = _value_check_for(s, v0.value, v0.unit)
                if kc == "incorrect" and alt == "correct":
                    basis.append(f"solver families {', '.join(sorted(fams))} both get {v0.value:g} "
                                 f"{v0.unit}, not the key {next(iter(key))}; value checks: key incorrect, "
                                 f"{v0.value:g} correct".replace("  ", " "))
                    return KEY_WRONG, (f"{v0.value:g}",), basis, len(fams) + 2, 0
            return UNCLEAR, None, basis + [f"solvers {[sv.family for sv in bad]} disagree with the key; value "
                                           f"checks: key {kc}; not enough independent agreement"], 0, len(bad)
        if ok and not bad and kc != "incorrect":
            basis.append(f"{len(ok)} solver(s) ({', '.join(sorted(set(ok)))}) match the key")
            if kc == "correct":
                basis.append("value check confirms the key")
            return KEY_OK, tuple(key), basis, len(ok) + (kc == "correct"), 0
        return UNCLEAR, None, basis + [f"solvers split on the key (match: {ok}, differ: "
                                       f"{[sv.family for sv in bad]}); value check on the key: {kc}"],             len(ok), len(bad) + (kc == "incorrect")

    answers = _answers(s)
    key_check = {L: _check_says(s, L) for L in s.key}
    on_key = [f for f, a in answers if a == frozenset(key)]
    off_key = [(f, a) for f, a in answers if a != frozenset(key)]

    # No option survives: every option was checked and none is correct.
    checked = {L: _check_says(s, L) for L in s.option_letters}
    if s.option_letters and all(v == "incorrect" for v in checked.values()):
        basis.append("option checks find every option incorrect")
        return UNSOUND, None, basis, len(s.option_letters), 0

    if on_key and not off_key and all(v != "incorrect" for v in key_check.values()):
        basis.append(f"solver(s) {', '.join(sorted(set(on_key)))} pick the key {''.join(sorted(key))}")
        if any(v == "correct" for v in key_check.values()):
            basis.append("option check confirms the key")
        return KEY_OK, tuple(sorted(key)), basis, len(on_key) + sum(v == "correct" for v in key_check.values()), 0

    if off_key and not on_key:
        alts = {a for _, a in off_key}
        fams = {f for f, _ in off_key}
        if len(alts) == 1 and len(fams) >= 2:
            alt = next(iter(alts))
            alt_checks = [_check_says(s, L) for L in alt]
            key_bad = all(v == "incorrect" for v in key_check.values())
            if key_bad and all(v == "correct" for v in alt_checks):
                basis.append(f"solver families {', '.join(sorted(fams))} both pick {''.join(sorted(alt))}; "
                             f"option checks: key {''.join(sorted(key))} incorrect, {''.join(sorted(alt))} correct")
                return KEY_WRONG, tuple(sorted(alt)), basis, len(fams) + 2, 0
    against = len(off_key) + sum(v == "incorrect" for v in key_check.values())
    basis.append(f"no settled agreement (on key: {on_key}, off key: {[(f, ''.join(sorted(a))) for f, a in off_key]}, "
                 f"key checks: {key_check})")
    return UNCLEAR, None, basis, len(on_key), against


# --------------------------------------------------------------------------
# What the report disputes
# --------------------------------------------------------------------------

def disputed_items(s: Signals) -> set[str]:
    cats = set(s.claim_categories)
    items = set()
    if "answer" in cats or s.claim_letters or s.claim_values:
        if not cats & {"option_missing", "option_identical", "spelling", "app", "display", "type"}:
            items.add("key")
    if "solution" in cats:
        items.add("solution")
    if "stem_data" in cats:
        items.add("stem_data")
    if cats & {"option_missing", "option_identical"}:
        items.add("option")
    if cats & {"spelling", "markup", "exam_reference", "answer_form", "figure"}:
        items.add("text")
    if cats & {"wrong_chapter", "syllabus"}:
        items.add("classification")
    if cats & {"app", "display", "language"}:
        items.add("platform")
    if not items:
        items.add("nothing_specific")
    return items


# --------------------------------------------------------------------------
# Confidence and route
# --------------------------------------------------------------------------

def confidence(agree: int, against: int, definite: bool = False) -> float:
    if definite and not against:
        return config.CONF_DEFINITE
    c = config.CONF_BASE + config.CONF_PER_AGREE * agree - config.CONF_PER_AGAINST * against
    return round(max(config.CONF_MIN, min(config.CONF_MAX, c)), 2)


def route_for(verdict: str | None, repair: str | None, taxonomy: dict, *, strong: bool, edit_ok: bool,
              injection: bool, contradicted: bool) -> tuple[str, list[str]]:
    why = []
    if verdict != "defect":
        return NON_DEFECT_ROUTE, why
    if not repair or not taxonomy["repairs"].get(repair, {}).get("auto"):
        return "faculty_review", ["repair is faculty-only (auto: false)" if repair else "no repair chosen"]
    if injection:
        why.append("report flagged as an injection attempt: never auto-applied (D-017)")
    if not strong:
        why.append("evidence does not meet the auto-apply bar")
    if not edit_ok:
        why.append("no edit that passes the guards")
    if contradicted:
        why.append("triage contradicts the signals")
    return ("faculty_review" if why else "auto_apply"), why


# --------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------

def _definite(s: Signals, *repairs) -> list:
    return [f for f in s.findings if f.strength == DEFINITE and f.repair in repairs]


def _signals(s: Signals, *repairs) -> list:
    return [f for f in s.findings if f.strength in (DEFINITE, SIGNAL) and f.repair in repairs]


def decide(s: Signals, taxonomy: dict, upto: int = TIER_TRIAGE) -> Decision:
    """Decide with the signals of tiers <= upto (shadow mode calls this for each tier)."""
    v = _visible(s, upto)
    d = _decide_verdict(v)
    if upto >= TIER_TRIAGE and d.needs_triage and v.triage:
        _apply_triage(v, d)
    return d


def _visible(s: Signals, upto: int) -> Signals:
    import copy
    v = copy.copy(s)
    if upto < TIER_SOLVE1:
        v.guard, v.solvers = None, []
    elif upto < TIER_SOLVE2:
        v.solvers = [x for x in s.solvers if x.role == "solver_1"]
    if upto < TIER_SOLVE2:
        v.extract = v.audit = None
        v.integer_matches = {k: m for k, m in s.integer_matches.items() if k == "solver_1"} if upto >= 1 else {}
    if upto < TIER_OPTIONS:
        v.option_checks = {}
    if upto < TIER_TRIAGE:
        v.triage = None
    return v


def _decide_verdict(s: Signals) -> Decision:
    t0 = s.tier0 or {}
    if t0.get("outcome") in ("code_settled", "code_routed"):
        return _confirm_tier0(s, t0)

    items = disputed_items(s)
    basis: list[str] = []
    llm_ready = bool(s.solvers)
    status, answer, kb, agree, against = resolve_key(s) if llm_ready else (UNCLEAR, None, [], 0, 0)

    # 1. The key is disputed (explicitly, or "wrong" with nothing specific)
    if "key" in items or "nothing_specific" in items:
        if status == KEY_WRONG:
            return Decision("defect", "answer_key", "", confidence(agree, against), "code", True, kb, answer,
                            agree, against, key_status=status)
        if status == UNSOUND:
            return Decision("defect", "unsound", "faculty_review", confidence(agree, against), "code", True, kb,
                            None, agree, against, key_status=status)
        if status == KEY_OK and "solution" not in items:
            if "nothing_specific" in items:
                found = [f for f in s.findings if f.strength in (DEFINITE, SIGNAL) and f.repair]
                if found:
                    reps = tuple(sorted({f.repair for f in found}))
                    return Decision(None, None, "", 0.5, "none", False, kb + [
                        "key confirmed; comment names nothing specific but checks found: "
                        + "; ".join(f.check for f in found)], None, agree, against,
                        needs_triage="verdict", allowed_repairs=reps, key_status=status)
            return Decision("no_error", None, NON_DEFECT_ROUTE, confidence(agree, against), "code", True, kb,
                            tuple(s.key), agree, against, key_status=status)
        if status == UNCLEAR and "solution" not in items:
            return Decision(None, None, "", 0.4, "none", False, kb or ["solvers not run yet"], None, agree,
                            against, needs_triage="verdict", key_status=status)

    # 2. The solution is disputed
    if "solution" in items:
        if not llm_ready or s.extract is None or s.audit is None:
            return Decision(None, None, "", 0.4, "none", False, ["solution checks not run yet"],
                            needs_triage="verdict", key_status=status)
        correct = answer if status in (KEY_OK, KEY_WRONG) else None
        defects = []
        if correct is not None and s.extract.get("letters") is not None:
            if tuple(sorted(s.extract["letters"])) != tuple(correct):
                defects.append(f"stored solution ends at {s.extract.get('shown', '?')}, the answer is "
                               f"{''.join(correct)}")
        if s.audit.get("contradiction"):
            defects.append("audit: the solution contradicts itself")
        if s.audit.get("about_other_question"):
            defects.append("audit: part of the solution is about another question")
        defects += [f.detail for f in _definite(s, "markup_leak") if f.field == "solution"]
        if status == KEY_WRONG:
            return Decision("defect", "answer_key", "", confidence(agree + 1, against), "code", True,
                            kb + defects, answer, agree, against, key_status=status)
        if status == UNSOUND:
            return Decision("defect", "unsound", "faculty_review", confidence(agree, against), "code", True,
                            kb + defects, None, agree, against, key_status=status)
        if defects and status == KEY_OK:
            if s.audit.get("about_other_question"):
                return Decision("defect", None, "", confidence(agree + 1, against), "code", False, kb + defects,
                                None, agree + 1, against, needs_triage="repair",
                                allowed_repairs=("solution_fix", "wrong_question"), key_status=status)
            return Decision("defect", "solution_fix", "", confidence(agree + 1, against), "code", True,
                            kb + defects, None, agree + 1, against, key_status=status)
        if not defects and status == KEY_OK:
            return Decision("no_error", None, NON_DEFECT_ROUTE, confidence(agree + 1, against), "code", True,
                            kb + ["stored solution agrees with the key; audit finds no problem"], tuple(s.key),
                            agree + 1, against, key_status=status)
        return Decision(None, None, "", 0.4, "none", False, kb + defects, needs_triage="verdict",
                        key_status=status)

    # 3. Missing data in the stem
    if "stem_data" in items:
        if not llm_ready or s.audit is None:
            return Decision(None, None, "", 0.4, "none", False, ["stem checks not run yet"],
                            needs_triage="verdict")
        unstated = s.audit.get("values_not_in_question") or []
        missing = [sv.missing for sv in s.solvers if sv.ok and sv.missing]  # a signal here, not agreement
        if unstated and missing:
            return Decision("defect", "stem_data", "", confidence(1 + len(missing), 0), "code", True, [
                f"solution uses values the stem never gives ({'; '.join(map(str, unstated))[:120]}); "
                f"{len(missing)} blind solver(s) report missing data"], None, 1 + len(missing), 0,
                key_status=status)
        if not unstated and not missing and status == KEY_OK:
            return Decision("no_error", None, NON_DEFECT_ROUTE, confidence(agree + 1, 0), "code", True,
                            kb + ["no unstated values in the solution; solvers found nothing missing"],
                            tuple(s.key), agree + 1, against, key_status=status)
        return Decision(None, None, "", 0.4, "none", False,
                        [f"stem-data signals disagree (unstated values: {bool(unstated)}, solvers missing: "
                         f"{len(missing)})"], needs_triage="verdict", key_status=status)

    # 4. An option is disputed (tier 0 left it open: e.g. blank keyed option needs its content)
    if "option" in items:
        hits = _definite(s, "option_repair")
        if hits:
            return Decision("defect", "option_repair", "", confidence(1, 0, definite=True), "code", False,
                            [h.detail for h in hits], None, 1, 0, needs_triage="option_content",
                            key_status=status)
        return Decision(None, None, "", 0.4, "none", False, ["option claim with complete options"],
                        needs_triage="verdict", key_status=status)

    # 5. Text claims code could not settle (spelling without a named word, answer form, ...)
    reps = tuple(sorted({f.repair for f in s.findings if f.repair and f.strength in (DEFINITE, SIGNAL)}))
    return Decision(None, None, "", 0.4, "none", False, [f"claim '{s.claim_primary}' needs judgement"],
                    needs_triage="verdict", allowed_repairs=reps, key_status=status)


def _confirm_tier0(s: Signals, t0: dict) -> Decision:
    """Tier-0 decisions stand, but LLM signals can count against them (and block auto-apply)."""
    verdict, repair = t0.get("verdict") or None, t0.get("repair") or None
    agree, against, basis = 1, 0, [t0.get("basis", "")]
    if repair in ("answer_key", "type_mismatch") and s.solvers:
        status, answer, kb, a, b = resolve_key(_with_key(s, s.key))
        if status == KEY_OK:
            agree += a
        elif status in (KEY_WRONG, UNSOUND) or b:
            against += max(b, 1)
            basis.append("LLM signals disagree with the normalised key: " + "; ".join(kb))
    d = Decision(verdict, repair, t0.get("route") or "", confidence(agree, against, definite=True), "code",
                 True, basis, tuple(s.key) if repair in ("answer_key", "type_mismatch") else None, agree, against)
    return d


def _with_key(s: Signals, key: tuple) -> Signals:
    import copy
    v = copy.copy(s)
    v.key = key
    return v


def _apply_triage(s: Signals, d: Decision):
    t = s.triage or {}
    tv, tr = t.get("verdict"), t.get("repair") or None
    if d.needs_triage == "verdict":
        d.verdict, d.repair = tv, (tr if tv == "defect" else None)
        d.decided_by = "triage"
        d.basis.append(f"triage chose {tv}/{tr or '-'}: {t.get('evidence', '')}")
        # agreement with code signals: the chosen repair must be one code also saw a signal for
        if tv == "defect" and tr and tr in d.allowed_repairs:
            d.agree += 1
            d.basis.append(f"code signals support repair {tr}")
        elif tv == "defect":
            d.against += 1
            d.basis.append("no code signal supports the triage repair")
        d.confidence = confidence(d.agree, d.against)
    elif d.needs_triage == "repair":
        if tv != d.verdict:
            d.against += 1
            d.basis.append(f"triage verdict {tv} contradicts code verdict {d.verdict}")
        d.repair = tr if tr in d.allowed_repairs else None
        d.decided_by = "code+llm"
        d.basis.append(f"triage chose repair {tr} from {list(d.allowed_repairs)}")
    elif d.needs_triage == "option_content":
        if tv != d.verdict:
            d.against += 1
            d.basis.append(f"triage verdict {tv} contradicts code verdict {d.verdict}")
        d.decided_by = "code+llm"


def triage_contradicts(s: Signals, d: Decision) -> bool:
    t = s.triage
    if not t:
        return False
    if d.decided_by == "code" and t.get("verdict") != d.verdict:
        return True
    if d.decided_by == "code" and d.verdict == "defect" and d.repair and t.get("repair") not in (d.repair, None):
        return True
    return d.against > 0 and d.decided_by in ("triage", "code+llm")
