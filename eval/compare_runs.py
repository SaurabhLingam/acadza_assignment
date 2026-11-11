"""Compare two engine runs against the hand labels (D-005 robustness test: main run vs a swapped-model run).

    python -m eval.compare_runs <base_run_dir> <other_run_dir>

Per run: verdict accuracy, verdict+repair accuracy, new-key accuracy, route counts, and wrong auto-applies.
A wrong auto-apply is a report routed auto_apply whose verdict or repair disagrees with the label, or whose new
key disagrees with the labelled answer. Auto-applied edits that differ from the base run's edit are listed
separately: labels don't hold edit text, so those need a look by hand.
Writes <other_run_dir>/compare.md and prints it. Only eval/ reads docs/eval-labels.csv.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from eval.evaluate_profile import LABELS, ROOT, _read
from eval.evaluate_run import _norm_answer


def _load(d: Path) -> dict:
    return {r["reportId"]: r for r in json.loads((d / "results.json").read_text(encoding="utf-8"))}


def _score(res: dict, labels: dict) -> dict:
    v = vr = k = kt = 0
    wrong_auto = []
    for rid, r in res.items():
        lab = labels[rid]
        ok_v = r["verdict"] == lab["my_verdict"]
        ok_r = (r["repair"] or "") == (lab["my_repair"] or "")
        ok_k = True
        if lab["my_repair"] == "answer_key":
            kt += 1
            e = r.get("edit") or {}
            got = e.get("replace") if r["repair"] == "answer_key" and e.get("field") == "answer" else None
            ok_k = got is not None and _norm_answer(got) == _norm_answer(lab["my_answer"])
            k += ok_k
        v += ok_v
        vr += ok_v and ok_r
        if r["route"] == "auto_apply" and not (ok_v and ok_r and ok_k):
            wrong_auto.append(rid)
    return {"n": len(res), "verdict": v, "verdict_repair": vr, "key": k, "key_total": kt,
            "routes": Counter(r["route"] for r in res.values()), "wrong_auto": wrong_auto}


def main(argv=None) -> str:
    argv = sys.argv[1:] if argv is None else argv
    base_dir, other_dir = (Path(a) if Path(a).is_absolute() else ROOT / a for a in argv[:2])
    labels = {r["reportId"]: r for r in _read(LABELS)}
    base, other = _load(base_dir), _load(other_dir)
    sb, so = _score(base, labels), _score(other, labels)
    summ = lambda d: json.loads((d / "run-summary.json").read_text(encoding="utf-8"))
    mb, mo = summ(base_dir), summ(other_dir)

    moved = [(rid, base[rid]["route"], other[rid]["route"]) for rid in sorted(other)
             if rid in base and base[rid]["route"] != other[rid]["route"]]
    changed_verdict = [(rid, f"{base[rid]['verdict']}/{base[rid]['repair'] or '-'}",
                        f"{other[rid]['verdict']}/{other[rid]['repair'] or '-'}") for rid in sorted(other)
                       if rid in base and (base[rid]["verdict"], base[rid]["repair"]) !=
                       (other[rid]["verdict"], other[rid]["repair"])]
    edit_diff = [rid for rid in sorted(other) if other[rid]["route"] == "auto_apply" and rid in base
                 and other[rid].get("edit") != base[rid].get("edit")]

    def row(name, s, m):
        r = s["routes"]
        return (f"| {name} | {s['verdict']}/{s['n']} | {s['verdict_repair']}/{s['n']} | {s['key']}/{s['key_total']} | "
                f"{r.get('auto_apply', 0)} | {r.get('faculty_review', 0)} | {r.get('no_change', 0)} | "
                f"**{len(s['wrong_auto'])}** | {m.get('total_tokens', {}).get('in', 0) + m.get('total_tokens', {}).get('out', 0)} | "
                f"${m.get('spend_usd', 0):.4f} |")

    lines = [
        f"# {other_dir.name} vs {base_dir.name}",
        "",
        f"Swapped roles: `{json.dumps(mo.get('swapped_roles') or {})}`",
        "",
        "| run | verdict | verdict+repair | new key | auto_apply | faculty | no_change | wrong auto-applies | tokens | spend |",
        "|---|---|---|---|---|---|---|---|---|---|",
        row(base_dir.name, sb, mb),
        row(other_dir.name, so, mo),
        "",
        f"Wrong auto-applies: base {sb['wrong_auto'] or 'none'}; other {so['wrong_auto'] or 'none'}.",
        "",
        f"## Route changes ({len(moved)})",
        "",
        "| report | base | other |",
        "|---|---|---|",
    ] + [f"| {a} | {b} | {c} |" for a, b, c in moved] + [
        "",
        f"## Verdict/repair changes ({len(changed_verdict)})",
        "",
        "| report | base | other | label |",
        "|---|---|---|---|",
    ] + [f"| {a} | {b} | {c} | {labels[a]['my_verdict']}/{labels[a]['my_repair'] or '-'} |"
         for a, b, c in changed_verdict] + [
        "",
        f"## Auto-applied with an edit different from the base run ({len(edit_diff)})",
        "",
    ] + [f"- {rid}: base `{json.dumps(base[rid].get('edit'), ensure_ascii=False)}` -> other "
         f"`{json.dumps(other[rid].get('edit'), ensure_ascii=False)}`" for rid in edit_diff] + [""]
    text = "\n".join(lines)
    (other_dir / "compare.md").write_text(text, encoding="utf-8")
    print(text)
    return text


if __name__ == "__main__":
    main()
