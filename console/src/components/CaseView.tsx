import { useState } from "react";
import type { Decision, Draft, Item, Question } from "../types";
import { PAST, fmtTime } from "../model";
import { EvidenceGrid, Fold, Html } from "./ui";

interface Props {
  item: Item;
  q: Question;
  decision?: Decision;
  draft: Draft | null;
  setDraft: (d: Draft) => void;
  draftDiff: { before: string; after: string } | null;
  guardError: string | null;
}

const STATUS: Record<string, string> = {
  faculty_review: "Waiting for you",
  auto_apply: "Already live",
  no_change: "Nothing was changed",
  bonus: "Found without a student report",
};

export function CaseView({ item, q, decision, draft, setDraft, draftDiff, guardError }: Props) {
  const [showEvidence, setShowEvidence] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const textDiffOnSolution = item.diff?.field === "solution";
  const [open, setOpen] = useState<Record<string, boolean>>({
    question: false,
    solution: item.solutionOpen && !textDiffOnSolution,
    reports: false,
    details: false,
  });
  const toggle = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }));
  const editing = draft !== null;
  const students = item.source === "bonus" ? "no student reports" : `${item.reach} student${item.reach === 1 ? "" : "s"}`;
  const inCase = item.reports.filter((r) => r.inThisCase);

  return (
    <article className="case" aria-labelledby="case-title">
      <div className="context">
        <span className={`tier tier-${item.tier}`}>{item.tierLabel}</span>
        <span className="sep">·</span>
        <span>{q.subject} · {q.chapter}</span>
        <span className="sep">·</span>
        <span>{students}</span>
        <span className="status">{STATUS[item.route]}</span>
      </div>

      {decision && (
        <p className="decided" role="status">
          {PAST[decision.action]} by {decision.reviewer} · {fmtTime(decision.at)}
          {decision.reason ? ` · ${decision.reason}` : ""}{decision.note ? ` (“${decision.note}”)` : ""}
        </p>
      )}

      {/* 1. What's wrong */}
      <h1 id="case-title" className="sentence" data-tour="headline">{item.sentence}</h1>

      {/* 2. How sure */}
      <p className="sure" data-tour="sure">
        {item.sure}{" "}
        <button className="link" onClick={() => setShowEvidence((v) => !v)} aria-expanded={showEvidence}>
          {showEvidence ? "Hide evidence" : "Show evidence"}
        </button>
      </p>
      {showEvidence && (
        <div className="evidence">
          {item.grid && <EvidenceGrid grid={item.grid} />}
          {item.grid && <p className="legend">✓ the source picks this · in the check column, <span className="pass">✓</span> judged right and <span className="fail">✗</span> judged wrong · – no signal. Hover a column for the model.</p>}
          {item.routeWhy.length > 0 && <p className="muted small">Why this route: {item.routeWhy.join("; ")}</p>}
          <button className="link small" onClick={() => setShowRaw((v) => !v)} aria-expanded={showRaw}>
            {showRaw ? "Hide raw evidence" : "Raw evidence"}
          </button>
          {showRaw && (
            <div className="raw">
              {item.rawEvidence.map((r, i) => (
                <p key={i}>{r.reportId && <span className="id">{r.reportId}</span>} {r.evidence}</p>
              ))}
            </div>
          )}
        </div>
      )}
      <p className="why">Why it's here: {item.why}</p>

      {/* 3. What changes */}
      <section className="changes" aria-label="What changes" data-tour="changes">
        <h2 className="label">What changes</h2>
        <Changes item={item} q={q} draft={draft} setDraft={setDraft} draftDiff={draftDiff} guardError={guardError} />
      </section>

      {/* 4. Secondary, collapsed */}
      <div className="folds">
        {textDiffOnSolution && (
          <Fold title="Question" summary="the question this solution belongs to" open={open.question} onToggle={() => toggle("question")}>
            <Html html={item.questionHtml} className="paper" />
          </Fold>
        )}
        {!textDiffOnSolution && (
          <Fold title="Stored solution" summary={item.solutionHtml ? "flagged parts marked" : undefined}
            open={open.solution} onToggle={() => toggle("solution")}>
            <Html html={item.solutionHtml ?? q.solutionHtml} className="paper" />
          </Fold>
        )}
        <Fold title="Student reports" summary={item.reports.length ? `${item.reports.length}` : "none"}
          open={open.reports || editing} onToggle={() => toggle("reports")}>
          {item.reports.length === 0 && <p className="muted">No student reported this question.</p>}
          <ul className="reports">
            {item.reports.map((r) => (
              <li key={r.reportId} className={r.inThisCase ? "" : "other"}>
                <p className="report-meta">
                  <span className="id">{r.reportId}</span> · {r.source} · {fmtTime(r.reportedAt)}
                  {!r.inThisCase && <> · different outcome ({r.verdict}{r.repair ? `, ${r.repair}` : ""})</>}
                </p>
                {/* untrusted: plain text only */}
                <p className="comment">{r.comment || <em className="muted">(empty comment)</em>}</p>
                {r.inThisCase && editing && draft ? (
                  <label className="reply-edit">
                    <span className="label">Reply to the student</span>
                    <textarea value={draft.replies[r.reportId] ?? r.reply} rows={3}
                      onChange={(e) => setDraft({ ...draft, replies: { ...draft.replies, [r.reportId]: e.target.value } })} />
                  </label>
                ) : (
                  <p className="reply"><span className="label">Reply</span> {r.reply}</p>
                )}
              </li>
            ))}
          </ul>
          {inCase.length > 0 && !editing && <p className="muted small">Press E to edit replies.</p>}
        </Fold>
        <Fold title="Details" summary={`${item.reportIds.join(", ") || "bonus finding"} · ${item.route.replace("_", " ")}`}
          open={open.details} onToggle={() => toggle("details")}>
          <dl className="details">
            <dt>Reports</dt><dd className="id">{item.reportIds.join(", ") || "none (found without a report)"}</dd>
            <dt>Question</dt><dd className="id">{item.questionId}</dd>
            <dt>Route</dt><dd>{item.route}</dd>
            <dt>Verdict / repair</dt><dd>{item.verdict}{item.repair ? ` / ${item.repair}` : ""}</dd>
            {item.source === "report" && <><dt>Confidence</dt><dd>{item.confidence.toFixed(2)}</dd></>}
            <dt>Decided by</dt><dd>{item.decidedBy || "–"}</dd>
            <dt>Stored key</dt><dd>{q.key}</dd>
          </dl>
        </Fold>
      </div>
    </article>
  );
}

function Changes({ item, q, draft, setDraft, draftDiff, guardError }: Omit<Props, "decision">) {
  const editing = draft !== null;
  const e = item.edit;

  if (editing && draft && e && (e.field === "question" || e.field === "solution")) {
    return (
      <>
        <label className="edit-field">
          <span className="label">Replacement text {draft.plain ? "" : "(contains formatting markup; edit with care)"}</span>
          <textarea className={draft.plain ? "" : "mono"} value={draft.replace} rows={draft.plain ? 2 : 4} autoFocus
            onChange={(ev) => setDraft({ ...draft, replace: ev.target.value })} />
        </label>
        {guardError ? <p className="guard-fail" role="alert">✗ {guardError}</p> : <p className="guard-ok">✓ Passes every edit guard</p>}
        {draftDiff && <SideBySide before={draftDiff.before} after={draftDiff.after} field={e.field} />}
      </>
    );
  }
  if (editing && draft && e && e.field === "answer") {
    return (
      <>
        <label className="edit-field">
          <span className="label">New answer key {q.type === "mcq" ? "(letters, comma-separated)" : ""}</span>
          <input value={draft.answer} autoFocus onChange={(ev) => setDraft({ ...draft, answer: ev.target.value })} />
        </label>
        {guardError ? <p className="guard-fail" role="alert">✗ {guardError}</p> : <p className="guard-ok">✓ Passes every edit guard</p>}
        <Html html={item.questionHtml} className="paper" />
      </>
    );
  }

  if (item.answerChange) {
    return (
      <>
        <p className="answer-line">
          <span className="label-inline">Answer</span>
          <span className="del-text">{item.answerChange.from}</span>
          <span className="arrow">→</span>
          <span className="ins-text">{item.answerChange.to}</span>
        </p>
        <Html html={item.questionHtml} className="paper" />
      </>
    );
  }
  if (item.typeChange) {
    return (
      <>
        <p className="answer-line">
          <span className="label-inline">Question type</span>
          <span className="del-text">{item.typeChange.from === "mcq" ? "multiple-correct" : item.typeChange.from}</span>
          <span className="arrow">→</span>
          <span className="ins-text">{item.typeChange.to === "scq" ? "single-correct" : item.typeChange.to}</span>
        </p>
        <Html html={item.questionHtml} className="paper" />
      </>
    );
  }
  if (item.diff) {
    if (item.diff.error) return <p className="guard-fail">{item.diff.error}</p>;
    return <SideBySide before={item.diff.before ?? ""} after={item.diff.after ?? ""} field={item.diff.field} />;
  }
  if (item.nothing) {
    return (
      <>
        <p className="nothing">{item.nothing}</p>
        <Html html={item.questionHtml} className="paper" />
      </>
    );
  }
  return (
    <>
      {item.suggestion ? (
        <div className="suggestion">
          <p><span className="label-inline">Suggested fix</span> <span className="muted">(AI suggestion, not applied)</span></p>
          <p className="suggestion-text">{item.suggestion.text}</p>
          {item.suggestion.detail && <p className="muted small">{item.suggestion.detail}</p>}
        </div>
      ) : (
        <p className="nothing">No automatic change. Your decision is recorded for the content team.</p>
      )}
      <Html html={item.questionHtml} className="paper" />
    </>
  );
}

function SideBySide({ before, after, field }: { before: string; after: string; field: string }) {
  return (
    <div className="sbs">
      <div>
        <p className="sbs-label">Before · {field}</p>
        <Html html={before} className="paper" />
      </div>
      <div>
        <p className="sbs-label">After · {field}</p>
        <Html html={after} className="paper" />
      </div>
    </div>
  );
}
