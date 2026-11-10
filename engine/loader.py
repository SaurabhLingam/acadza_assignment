"""Read-only loading of the given data files into typed records.

Files under data/ are opened read-only and never written.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

QUESTION_TYPES = ("scq", "mcq", "integerQuestion")


@dataclass(frozen=True)
class HistoryEntry:
    type: str
    actor: str
    at: str
    note: str


@dataclass(frozen=True)
class Question:
    id: str
    qtype: str
    subject: str
    chapter: str
    question_html: str
    solution_html: str
    answer_raw: object  # str for scq / integerQuestion, list for mcq (as stored)
    ques_images: tuple
    solution_images: tuple
    error_history: tuple[HistoryEntry, ...]
    updated_at: str
    raw: dict = field(repr=False, compare=False)


@dataclass(frozen=True)
class Report:
    report_id: str
    question_id: str
    student_id: str
    source: str
    reported_at: str
    comment: str


def _read_json(name: str):
    with open(DATA_DIR / name, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_questions() -> dict[str, Question]:
    out: dict[str, Question] = {}
    for q in _read_json("questions.json"):
        qtype = q["questionType"]
        body = q.get(qtype) or {}
        history = tuple(
            HistoryEntry(
                type=str(h.get("type", "")),
                actor=str(h.get("actor", "")),
                at=str(h.get("at", "")),
                note=str(h.get("note", "")),
            )
            for h in (q.get("errorHistory") or [])
        )
        out[q["_id"]] = Question(
            id=q["_id"],
            qtype=qtype,
            subject=q.get("subject") or "",
            chapter=q.get("chapter") or "",
            question_html=body.get("question") or "",
            solution_html=body.get("solution") or "",
            answer_raw=body.get("answer"),
            ques_images=tuple(body.get("quesImages") or ()),
            solution_images=tuple(body.get("solutionImages") or ()),
            error_history=history,
            updated_at=q.get("updatedAt") or "",
            raw=q,
        )
    return out


def load_reports() -> list[Report]:
    return [
        Report(
            report_id=r["reportId"],
            question_id=r["questionId"],
            student_id=r.get("studentId", ""),
            source=r.get("source", ""),
            reported_at=r.get("reportedAt", ""),
            comment=r.get("comment") or "",
        )
        for r in _read_json("reports.json")
    ]


def load_taxonomy() -> dict:
    return _read_json("taxonomy.json")
