import { useState } from "react";
import type { Bonus, Case, Diff, Group, Question } from "../types";
import { bonusWhy, fmtTime, prettyField } from "../model";
import { ChangePill, Chip, Html, Section } from "./bits";

const ROUTE_LABEL: Record<string, string> = { auto_apply: "auto-applied", faculty_review: "needs you", no_change: "no change" };

function SideBySide({ diff }: { diff: Diff }) {
  if (diff.error) return <div className="note bad">{diff.error}</div>;
  return (
    <div className="sbs">
      <div className="sbs-col">
        <div className="sbs-label">Before</div>
        <Html html={diff.before ?? ""} className="paper" />
      </div>
      <div className="sbs-col">
        <div className="sbs-label after">After</div>
        <Html html={diff.after ?? ""} className="paper" />
      </div>
    </div>
  );
}

function QuestionCard({ q, html, label = "Question" }: { q: Question; html?: string; label?: string }) {
  return (
    <Section title={label} aside={<span className="muted small">{q.type.replace("integerQuestion", "integer")} · key {q.answer.long}</span>}>
      <Html html={html ?? q.questionHtml} className="paper" />
    </Section>
  );
}

function SolutionCard({ q }: { q: Question }) {
  const [open, setOpen] = useState(false);
  return (
    <Section title="Stored solution" aside={<button className="link" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"}</button>}>
      {open && <Html html={q.solutionHtml} className="paper" />}
    </Section>
  );
}

function RawEvidence({ c }: { c: Case }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="raw">
      <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? "Hide raw evidence" : "Raw evidence"}
      </button>
      {open && (
        <div className="raw-body">
          <p className="raw-line"><b>Engine evidence</b> {c.evidence}</p>
          {c.basis.length > 0 && <p className="raw-line"><b>Basis</b> {c.basis.join(" · ")}</p>}
          {c.notes.length > 0 && <p className="raw-line"><b>Notes</b> {c.notes.join(" · ")}</p>}
          {c.routeWhy.length > 0 && <p className="raw-line"><b>Why this route</b> {c.routeWhy.join(" · ")}</p>}
          {c.edit && <pre className="mono">{JSON.stringify(c.edit, null, 2)}</pre>}
          <details>
            <summary>Full signal record ({c.reportId})</summary>
            <pre className="mono">{JSON.stringify(c.details, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}

function Comments({ cases }: { cases: Case[] }) {
  if (!cases.length) return null;
  return (
    <Section title={`Student reports on this question (${cases.length})`}>
      <ul className="comments">
        {cases.map((c) => (
          <li key={c.reportId} className="comment">
            <div className="comment-meta">
              <span className="mono">{c.reportId}</span>
              <span>{c.studentId}</span>
              <span>{c.source}</span>
              <span>{fmtTime(c.reportedAt)}</span>
              <span className={`tag route-${c.route}`}>{ROUTE_LABEL[c.route]}</span>
              <span className="muted">{c.verdict}{c.repair ? ` / ${c.repair}` : ""}</span>
            </div>
            {/* comments are untrusted: rendered as text, never as HTML */}
            <blockquote className="comment-text">{c.comment || <i className="muted">(empty comment)</i>}</blockquote>
            <div className="reply">
              <div className="reply-label">Reply preview <span className="muted">· editing arrives in stage 2</span></div>
              <textarea className="reply-text" value={c.reply} readOnly rows={Math.min(6, Math.max(2, Math.ceil(c.reply.length / 90)))} />
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Change({ c, q }: { c: Case; q: Question }) {
  const parts = [];
  if (c.answerChange)
    parts.push(
      <Section key="a" title="Answer key change">
        <ChangePill from={c.answerChange.from.long} to={c.answerChange.to.long} />
      </Section>,
    );
  if (c.typeChange)
    parts.push(
      <Section key="t" title="Question type change">
        <ChangePill from={c.typeChange.from} to={c.typeChange.to} />
      </Section>,
    );
  if (c.diff)
    parts.push(
      <Section key="d" title={`${prettyField(c.diff.field)}: before / after`}
        aside={<span className="muted small">changes marked; rendered, not raw</span>}>
        <SideBySide diff={c.diff} />
      </Section>,
    );
  if (!c.diff || c.diff.field !== "question") parts.push(<QuestionCard key="q" q={q} />);
  if (!c.diff || c.diff.field !== "solution") parts.push(<SolutionCard key="s" q={q} />);
  return <>{parts}</>;
}

export function CaseView({ group, q, allCases }: { group: Group; q: Question; allCases: Case[] }) {
  const c = group.cases[0];
  const others = group.cases.length > 1 ? group.cases.slice(1).filter((x) => x.headline !== c.headline) : [];
  return (
    <article className="case">
      <header className="case-head">
        <div className="eyebrow">
          <span className={`harm-tag harm-${c.harm}`}>{c.harmLabel}</span>
          <span>{q.subject} · {q.chapter}</span>
          <span className="mono muted">{q.id.slice(0, 8)}</span>
        </div>
        <h1 className="headline">
          {c.headline}
          <span className="headline-meta"> · {c.reach} student{c.reach === 1 ? "" : "s"} · <span className={`tone-text-${c.certaintyTone}`}>{c.certainty}</span></span>
        </h1>
        <p className="why"><b>Why it's here:</b> {group.why}{c.routeWhy.length ? ` · held because: ${c.routeWhy.join("; ")}` : ""}</p>
        {others.length > 0 && <p className="note">Other outcomes on this question: {others.map((o) => `${o.reportId}: ${o.headline}`).join(" · ")}</p>}
      </header>
      <div className="chips">{c.chips.map((ch, i) => <Chip key={i} chip={ch} />)}</div>
      <RawEvidence c={c} />
      <Change c={c} q={q} />
      <Comments cases={allCases} />
    </article>
  );
}

export function BonusView({ group, q, allCases }: { group: Group; q: Question; allCases: Case[] }) {
  return (
    <article className="case">
      <header className="case-head">
        <div className="eyebrow">
          <span className={`harm-tag harm-${group.harm}`}>Bonus finding</span>
          <span>{q.subject} · {q.chapter}</span>
          <span className="mono muted">{q.id.slice(0, 8)}</span>
        </div>
        <h1 className="headline">
          {group.bonus.length} finding{group.bonus.length === 1 ? "" : "s"} no student reported
          <span className="headline-meta"> · {allCases.length ? `${allCases.length} report(s) on this question were about something else` : "nobody reported this question"}</span>
        </h1>
      </header>
      {group.bonus.map((b) => <BonusItem key={b.id} b={b} q={q} />)}
      {!group.bonus.some((b) => (b.diff ?? b.flag)?.field === "question") && <QuestionCard q={q} />}
      <Comments cases={allCases} />
    </article>
  );
}

function BonusItem({ b, q }: { b: Bonus; q: Question }) {
  const view = b.diff ?? b.flag;
  return (
    <Section verbatim title={b.headline} aside={<span className={`tag ${b.could_auto_apply ? "route-auto_apply" : "route-faculty_review"}`}>{b.could_auto_apply ? "could auto-apply" : "needs approval"}</span>}>
      <p className="why"><span className={`harm-tag harm-${b.harm}`}>{b.harmLabel}</span> {bonusWhy(b)}</p>
      <p className="detail">{b.detail}</p>
      <p className="muted small">{b.why}</p>
      {b.field === "chapter" && <ChangePill from={q.chapter} to="faculty to choose" />}
      {b.occurrences && b.occurrences.length > 0 && (
        <p className="small">Occurrences: {b.occurrences.map((o, i) => <span key={i} className="occ"><span className="mono">{o.text}</span> in {o.field}</span>)}</p>
      )}
      {b.diff && <SideBySide diff={b.diff} />}
      {!b.diff && view?.flagged && (
        <>
          <div className="sbs-label">{prettyField(view.field)}, finding marked</div>
          <Html html={view.flagged} className="paper" />
        </>
      )}
    </Section>
  );
}
