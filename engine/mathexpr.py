"""Safe evaluation of model-written math expressions, units, and numeric matching.

No eval/exec: expressions are parsed with `ast` and walked with a whitelist
(numbers, + - * / ** and unary minus, a few functions and constants). Sizes and
exponents are capped. Anything else raises ExprError.
"""
from __future__ import annotations

import ast
import math
import re

from . import config


class ExprError(ValueError):
    pass


_FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "ln": math.log, "log": math.log10, "log10": math.log10, "exp": math.exp, "abs": abs,
}
_CONSTS = {"pi": math.pi, "e": math.e}
MAX_LEN = 200
MAX_EXP = 64
MAX_MAG = 1e300


def _normalize(expr: str) -> str:
    s = expr.strip()
    s = (s.replace("−", "-").replace("–", "-").replace("×", "*").replace("·", "*").replace("÷", "/")
         .replace("π", "pi").replace("√", "sqrt").replace("^", "**"))
    s = re.sub(r"(?<=\d)\s*[x]\s*(?=\d)", "*", s)               # 5.7 x 10 -> 5.7*10
    s = re.sub(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", r"(\1)/(\2)", s)   # ratio a:b -> a/b
    s = re.sub(r"sqrt\s*(\d+(?:\.\d+)?)", r"sqrt(\1)", s)       # sqrt2 -> sqrt(2)
    # implicit multiplication: 8sqrt(2) -> 8*sqrt(2), 2pi -> 2*pi; keep 5.7e-5 as scientific notation
    s = re.sub(r"(\d)\s*(?=[a-df-z(]|e(?![+\-]?\d))", r"\1*", s)
    s = re.sub(r"\)\s*(?=[\d(a-z])", ")*", s)                  # (2)(3) -> (2)*(3)
    return s


def evaluate(expr: str) -> float:
    if expr is None:
        raise ExprError("empty")
    s = _normalize(str(expr))
    if not s or len(s) > MAX_LEN:
        raise ExprError("empty or too long")
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"syntax: {e.msg}") from None
    v = _walk(tree.body)
    if isinstance(v, complex) or math.isnan(v) or math.isinf(v) or abs(v) > MAX_MAG:
        raise ExprError("non-finite result")
    return float(v)


def _walk(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return n.value
    if isinstance(n, ast.Name) and n.id in _CONSTS:
        return _CONSTS[n.id]
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = _walk(n.operand)
        return -v if isinstance(n.op, ast.USub) else v
    if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        a, b = _walk(n.left), _walk(n.right)
        if isinstance(n.op, ast.Pow):
            if abs(b) > MAX_EXP:
                raise ExprError("exponent too large")
            return a ** b
        if isinstance(n.op, ast.Div):
            if b == 0:
                raise ExprError("division by zero")
            return a / b
        return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b}[type(n.op)]
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS
            and len(n.args) == 1 and not n.keywords):
        try:
            return _FUNCS[n.func.id](_walk(n.args[0]))
        except (ValueError, OverflowError) as e:
            raise ExprError(f"{n.func.id}: {e}") from None
    raise ExprError(f"not allowed: {type(n).__name__}")


# --------------------------------------------------------------------------
# Units: unit -> (dimension, factor to SI)
# --------------------------------------------------------------------------

_U = {}


def _add(dim, **units):
    for k, f in units.items():
        _U[k] = (dim, f)


_add("length", m=1, cm=1e-2, mm=1e-3, km=1e3, um=1e-6, μm=1e-6, nm=1e-9, pm=1e-12, Å=1e-10, A_ring=1e-10,
     angstrom=1e-10, metre=1, meter=1)
_add("time", s=1, sec=1, second=1, seconds=1, ms=1e-3, μs=1e-6, us=1e-6, min=60, minute=60, minutes=60,
     h=3600, hr=3600, hour=3600, hours=3600, day=86400, days=86400, year=3.156e7, years=3.156e7)
_add("mass", kg=1, g=1e-3, mg=1e-6, gram=1e-3)
_add("energy", J=1, kJ=1e3, mJ=1e-3, eV=1.602176634e-19, keV=1.602176634e-16, MeV=1.602176634e-13,
     cal=4.184, kcal=4184, joule=1)
_add("voltage", V=1, mV=1e-3, kV=1e3, μV=1e-6, volt=1, volts=1)
_add("current", A=1, mA=1e-3, μA=1e-6, uA=1e-6, ampere=1, amp=1)
_add("power", W=1, kW=1e3, mW=1e-3, MW=1e6, watt=1)
_add("charge", C=1, mC=1e-3, μC=1e-6, uC=1e-6, nC=1e-9, coulomb=1)
_add("capacitance", F=1, mF=1e-3, μF=1e-6, uF=1e-6, nF=1e-9, pF=1e-12, farad=1)
_add("inductance", H=1, mH=1e-3, μH=1e-6, uH=1e-6, henry=1)
_add("resistance", Ω=1, ohm=1, ohms=1, kΩ=1e3, kohm=1e3, MΩ=1e6)
_add("force", N=1, kN=1e3, newton=1, dyne=1e-5)
_add("pressure", Pa=1, kPa=1e3, MPa=1e6, atm=101325, bar=1e5, **{"N/m^2": 1, "N/m2": 1, "Nm^-2": 1})
_add("frequency", Hz=1, kHz=1e3, MHz=1e6)
_add("angle", rad=1, radian=1, radians=1, deg=math.pi / 180, degree=math.pi / 180, degrees=math.pi / 180,
     **{"°": math.pi / 180})
_add("volume", **{"m^3": 1, "cm^3": 1e-6, "mm^3": 1e-9, "L": 1e-3, "l": 1e-3, "mL": 1e-6, "ml": 1e-6,
                  "litre": 1e-3})
_add("area", **{"m^2": 1, "cm^2": 1e-4, "mm^2": 1e-6})
_add("speed", **{"m/s": 1, "km/h": 1 / 3.6, "cm/s": 1e-2, "km/s": 1e3})
_add("acceleration", **{"m/s^2": 1, "cm/s^2": 1e-2})
_add("optical_power", D=1, dioptre=1, dioptres=1, diopter=1)
_add("percent", **{"%": 0.01, "percent": 0.01})


def normalize_unit(u: str | None) -> str:
    if not u:
        return ""
    s = u.strip().replace("−", "-").replace("²", "^2").replace("³", "^3").replace("μ", "μ").replace("µ", "μ")
    s = re.sub(r"\s+", "", s)
    s = s.replace("ohm", "Ω") if s.lower() in ("ohm", "ohms") else s
    return s


def unit_info(u: str | None):
    """(dimension, SI factor) or None if unknown/empty."""
    s = normalize_unit(u)
    if not s:
        return None
    if s in _U:
        return _U[s]
    low = {k.lower(): v for k, v in _U.items()}
    # lower-case fallback only for unambiguous multi-letter names (not 'm' vs 'M', 'mA' vs 'MA')
    if len(s) > 2 and s.lower() in low:
        return low[s.lower()]
    return None


def to_si(value: float, unit: str | None):
    """(value in SI, dimension) — dimension None when the unit is unknown or absent."""
    info = unit_info(unit)
    if not info:
        return value, None
    dim, f = info
    return value * f, dim


# --------------------------------------------------------------------------
# Quantities in option / answer text
# --------------------------------------------------------------------------

_UNIT_IN_ROOT = re.compile(r"√\(\s*([\d.]+)\s+([A-Za-zμΩÅ°%/^\d]+)\s*\)")
_INV_TRIG = re.compile(r"\b(sin|cos|tan)\s*\^?\s*[−-]\s*1\s*")


def parse_quantity(text: str):
    """Leading numeric quantity in text, e.g. '4800 N/m^2', '5.7 x 10^-5/°C', '8√(2 m)',
    'tan^−1(4)', '1:4'. Returns (value, unit) or None if the text does not start with one."""
    if not text:
        return None
    t = text.strip()
    t = _UNIT_IN_ROOT.sub(lambda m: f"√({m.group(1)}) {m.group(2)}", t)   # unit written inside a root
    t = _INV_TRIG.sub(lambda m: "a" + m.group(1), t)                       # tan^-1( -> atan(
    t = re.sub(r"(?<=\d)\s*[x×]\s*10\s*\^\s*\(?([+\-−]?\d+)\)?", r"*10^(\1)", t)
    if not re.match(r"\s*(?:[+\-−]?[\d.(]|√|a?(?:sin|cos|tan)\(|pi|π)", t):
        return None
    ratio = re.fullmatch(r"\s*([^:]+?)\s*:\s*([^:]+?)\s*", t)
    if ratio:  # a:b, where either side may be an expression (2:√3)
        try:
            a, b = evaluate(ratio.group(1)), evaluate(ratio.group(2))
            return (a / b, "") if b else None
        except ExprError:
            return None
    # longest prefix that evaluates; the rest is the unit
    best = None
    for cut in range(len(t), 0, -1):
        head = t[:cut].rstrip()
        if not head or head[-1] in "+-−*/^(x×":
            continue
        if cut < len(t) and t[cut - 1].isalpha() and t[cut].isalpha():
            continue  # never split a word: '16.8 eV' must not read as 16.8*e + 'V'
        if re.search(r"(?<![a-z])(?:e|pi)$", head) and cut < len(t) and t[cut:cut + 1].strip():
            continue  # a bare 'e'/'pi' right before more text is a unit letter, not a constant
        try:
            v = evaluate(head)
        except ExprError:
            continue
        best = (v, t[cut:].strip())
        break
    if not best:
        return None
    v, rest = best
    unit = re.split(r"\s{2,}|[,;]", rest)[0].strip() if rest else ""
    unit = unit.split(" ")[0] if unit and " " in unit and not unit_info(unit) else unit
    return v, unit


def same_quantity(a: float, ua: str, b: float, ub: str, rel_tol: float, abs_tol: float = 0.0) -> bool:
    """Compare two quantities, converting units when both are known and of the same dimension."""
    sa, da = to_si(a, ua)
    sb, db = to_si(b, ub)
    if da and db:
        if da != db:
            return False
        a, b = sa, sb
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def match_option(value: float, unit: str, options_text: dict) -> tuple[str | None, list[str]]:
    """Option letter whose quantity matches (value, unit) within OPTION_REL_TOL. Returns
    (letter or None, all matching letters); None when zero or several options match."""
    hits = []
    for L, t in options_text.items():
        q = parse_quantity(t)
        if q and same_quantity(value, unit, q[0], q[1], config.OPTION_REL_TOL):
            hits.append(L)
    return (hits[0] if len(hits) == 1 else None), hits


def match_integer_key(value: float, unit: str, key: float, key_unit: str) -> bool:
    return same_quantity(value, unit, key, key_unit, config.INTEGER_REL_TOL, config.INTEGER_ABS_TOL)
