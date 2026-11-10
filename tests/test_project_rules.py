"""Guards for project rules in CLAUDE.md that code review alone would miss."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE_FILES = sorted((ROOT / "engine").rglob("*.py"))


def _ids() -> set[str]:
    with open(ROOT / "data" / "questions.json", encoding="utf-8") as fh:
        qids = {q["_id"] for q in json.load(fh)}
    with open(ROOT / "data" / "reports.json", encoding="utf-8") as fh:
        rids = {r["reportId"] for r in json.load(fh)}
    return qids | rids


def test_engine_has_no_question_or_report_ids():
    """Generic rules only: no question id (or 8+ char prefix) or report id in engine code."""
    ids = _ids()
    offenders = []
    for path in ENGINE_FILES:
        src = path.read_text(encoding="utf-8")
        for i in ids:
            pat = re.escape(i[:8]) if len(i) > 8 else rf"\b{re.escape(i)}\b"
            if re.search(pat, src):
                offenders.append(f"{path.name}: {i}")
    assert not offenders, offenders


def test_engine_never_references_eval_labels():
    for path in ENGINE_FILES:
        assert "eval-labels" not in path.read_text(encoding="utf-8"), path.name
