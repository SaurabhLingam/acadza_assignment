"""Run the injection detector alone (code families + prompt guard) on the user's fresh comment set.

    python -m eval.fresh_injection_check      # reads eval/heldout/fresh_injection_comments.csv
                                              # writes eval/heldout/fresh_injection_results.csv

Measures D-030 as frozen: patterns are not changed after seeing these comments. Blocking = any blocking
code family, or a guard score >= GUARD_THRESHOLD (the same rule as Signals.injection).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from engine import config
from engine.claims import BLOCKING_INJECTION_FAMILIES, injection_families
from engine.llm import Client
from engine.tiers import run_guard

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "eval" / "heldout" / "fresh_injection_comments.csv"
OUT = ROOT / "eval" / "heldout" / "fresh_injection_results.csv"


def main():
    rows = list(csv.DictReader(SRC.open(encoding="utf-8", newline="")))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-fresh-injection"
    client = Client(run_id, cap_usd=0.05)
    out = []
    for r in rows:
        fams = injection_families(r["comment"])
        code = any(f in BLOCKING_INJECTION_FAMILIES for f in fams)
        g = run_guard(client, r["id"], r["comment"])
        score = g.get("score")
        guard = score is not None and score >= config.GUARD_THRESHOLD
        out.append({"id": r["id"], "expected_flag": r["expected_flag"],
                    "flagged": "yes" if (code or guard) else "no", "code_flag": "yes" if code else "no",
                    "families": "+".join(fams), "guard_score": "" if score is None else f"{score:.4f}",
                    "guard_flag": "yes" if guard else "no", "why": r["why"]})
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    inj = [x for x in out if x["expected_flag"] == "yes"]
    ben = [x for x in out if x["expected_flag"] == "no"]
    print(f"run {run_id}: recall {sum(x['flagged'] == 'yes' for x in inj)}/{len(inj)}, "
          f"false positives {sum(x['flagged'] == 'yes' for x in ben)}/{len(ben)}; "
          f"spend ${client.spend.spent_usd:.4f}")


if __name__ == "__main__":
    main()
