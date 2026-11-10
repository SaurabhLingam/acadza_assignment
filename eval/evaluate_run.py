"""Score an engine run's results.json against the hand labels.

    python -m eval.evaluate_run                       # latest run in logs/runs/
    python -m eval.evaluate_run logs/runs/<run_id>    # a given run

Only code in eval/ reads docs/eval-labels.csv (see CLAUDE.md). Scored per report:
- verdict: result verdict == my_verdict
- repair: result repair == my_repair (blank label = no repair)
- new key: for answer_key labels, the edit's replacement == my_answer (letters compared as sets)
Writes <run_dir>/eval.md and prints the same text.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from eval.evaluate_profile import LABELS, ROOT, _read


def _norm_answer(x) -> str:
    if isinstance(x, list):
        x = ",".join(map(str, x))
    parts = [p.strip().upper() for p in re.split(r"[,\s]+", str(x or "")) if p.strip()]
    if parts and all(re.fullmatch(r"[A-E]", p) for p in parts):
        return ",".join(sorted(set(parts)))
    try:
        return f"{float(parts[0]):g}" if len(parts) == 1 else ",".join(parts)
    except ValueError:
        return ",".join(parts)


def main(argv=None) -> str:
    argv = sys.argv[1:] if argv is None else argv
    run_dir = Path(argv[0]) if argv else max((p for p in (ROOT / "logs" / "runs").iterdir() if p.is_dir()),
                                             key=lambda p: p.name)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    labels = {r["reportId"]: r for r in _read(LABELS)}
    sources = Counter(r.get("label_source", "") for r in labels.values())

    rows, n_v, n_r, n_k, k_total = [], 0, 0, 0, 0
    for res in results:
        lab = labels.get(res["reportId"])
        if not lab:
            rows.append((res["reportId"], "unlabelled", "", "", "", ""))
            continue
        ok_v = res["verdict"] == lab["my_verdict"]
        ok_r = (res["repair"] or "") == (lab["my_repair"] or "")
        n_v += ok_v
        n_r += ok_v and ok_r
        key_cell = ""
        if lab["my_repair"] == "answer_key":
            k_total += 1
            got = (res.get("edit") or {}).get("replace") if res["repair"] == "answer_key" and \
                (res.get("edit") or {}).get("field") == "answer" else None
            ok_k = got is not None and _norm_answer(got) == _norm_answer(lab["my_answer"])
            n_k += ok_k
            key_cell = f"{'ok' if ok_k else 'MISS'} ({_norm_answer(got) if got is not None else 'no key edit'} " \
                       f"vs {_norm_answer(lab['my_answer'])})"
        rows.append((res["reportId"], f"{res['verdict']}/{res['repair'] or '-'}",
                     f"{lab['my_verdict']}/{lab['my_repair'] or '-'}", "ok" if ok_v else "MISS",
                     "ok" if ok_v and ok_r else "MISS", key_cell, res["route"]))

    n = sum(1 for r in rows if r[1] != "unlabelled")
    lines = [
        f"# Run {run_dir.name} vs labels",
        "",
        f"Labels: {len(labels)} rows (" + ", ".join(f"{k or 'blank'}={v}" for k, v in sorted(sources.items())) + ").",
        "",
        f"- verdict correct: **{n_v}/{n}**",
        f"- verdict and repair correct: **{n_r}/{n}**",
        f"- new key correct (answer_key labels): **{n_k}/{k_total}**",
        "",
        "| report | result | label | verdict | verdict+repair | new key | route |",
        "|---|---|---|---|---|---|---|",
    ] + [f"| {' | '.join(map(str, r))} |" for r in rows]
    text = "\n".join(lines) + "\n"
    (run_dir / "eval.md").write_text(text, encoding="utf-8")
    print(text)
    return text


if __name__ == "__main__":
    main()
