"""Compare the profiler's code-decided rows against the hand labels.

    python -m engine.profile          # first, writes logs/profile/reports.csv
    python -m eval.evaluate_profile   # then this

This is the only code that reads docs/eval-labels.csv. It lives outside engine/
so ground truth cannot leak into triage decisions. Labels marked claude_draft
are not ground truth; the report says how many rows are user_verified.

Writes logs/profile/eval.md and prints the same text.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "docs" / "eval-labels.csv"
PROFILE = ROOT / "logs" / "profile" / "reports.csv"
OUT = ROOT / "logs" / "profile" / "eval.md"


def _read(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> str:
    if not PROFILE.exists():
        raise SystemExit("Run `python -m engine.profile` first.")
    labels = {r["reportId"]: r for r in _read(LABELS)}
    rows = _read(PROFILE)
    sources = Counter(r.get("label_source", "") for r in labels.values())

    decided = [r for r in rows if r["outcome"] in ("code_settled", "code_routed")]
    agree, disagree, unlabelled = [], [], []
    for r in decided:
        lab = labels.get(r["reportId"])
        if not lab or not lab.get("my_verdict"):
            unlabelled.append(r)
            continue
        ok_v = r["verdict"] == lab["my_verdict"]
        ok_r = (r["repair"] or "") == (lab["my_repair"] or "")
        (agree if ok_v and ok_r else disagree).append((r, lab, ok_v, ok_r))

    def n_src(src):
        return sum(1 for _, lab, *_ in agree + disagree if lab.get("label_source") == src)

    lines = [
        "# Profiler vs labels",
        "",
        f"Labels: {len(labels)} rows (" + ", ".join(f"{k or 'blank'}={v}" for k, v in sorted(sources.items())) + ").",
        "**Only `user_verified` rows are ground truth; `claude_draft` rows are Claude's own guesses.**",
        "",
        f"Code-decided rows (settled + routed): {len(decided)} of {len(rows)}",
        f"- agree on verdict and repair: {len(agree)} "
        f"(user_verified {sum(1 for _, l, *_ in agree if l.get('label_source') == 'user_verified')})",
        f"- disagree: {len(disagree)} "
        f"(user_verified {sum(1 for _, l, *_ in disagree if l.get('label_source') == 'user_verified')})",
        f"- no label: {len(unlabelled)}",
        f"- compared against user_verified labels: {n_src('user_verified')}; against claude_draft: {n_src('claude_draft')}",
        "",
    ]
    if disagree:
        lines += ["## Disagreements", "", "| Report | Outcome | Engine | Label | Label source | Label notes |",
                  "|---|---|---|---|---|---|"]
        for r, lab, ok_v, ok_r in disagree:
            lines.append(
                f"| {r['reportId']} | {r['outcome']} | {r['verdict']}/{r['repair'] or '-'} | "
                f"{lab['my_verdict']}/{lab['my_repair'] or '-'} | {lab.get('label_source', '')} | "
                f"{lab.get('notes', '').replace('|', '/')} |")
        lines.append("")
    pending = Counter(labels[r["reportId"]]["my_verdict"] for r in rows
                      if r["outcome"] == "needs_llm" and r["reportId"] in labels)
    lines += ["## Left for the LLM tier, by label verdict", "",
              ", ".join(f"{k}={v}" for k, v in pending.most_common()) or "none", ""]
    text = "\n".join(lines)
    OUT.write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(main())
