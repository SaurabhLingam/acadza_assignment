import { useEffect, useRef, useState } from "react";
import type { AuditEntry, Decision, Item, ListKey, Question } from "../types";
import { LISTS, PAST, REASONS, fmtTime } from "../model";
import { Kbd } from "./ui";

// ---------------------------------------------------------------- queue

interface QueueProps {
  list: ListKey;
  items: Item[];
  counts: Record<ListKey, number>;
  questions: Record<string, Question>;
  decisions: Record<string, Decision>;
  selected: string | null;
  onList: (l: ListKey) => void;
  onSelect: (key: string) => void;
}

const OTHER: ListKey[] = ["auto", "nochange", "bonus"];

/** "Other ▾" and its small menu: ↑ / ↓ move, Enter picks, Esc closes (focus goes back to the tab). */
function OtherMenu({ list, counts, onList }: { list: ListKey; counts: Record<ListKey, number>; onList: (l: ListKey) => void }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement | null>(null);
  const tab = useRef<HTMLButtonElement | null>(null);
  const on = OTHER.includes(list);
  const items = () => [...(wrap.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [])];
  useEffect(() => {
    if (!open) return;
    (items()[Math.max(0, OTHER.indexOf(list))] ?? items()[0])?.focus();
    const away = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const close = () => { setOpen(false); tab.current?.focus(); };
  return (
    <div className="other" ref={wrap}>
      <button ref={tab} role="tab" aria-selected={on} aria-haspopup="menu" aria-expanded={open}
        className={`qtab ${on ? "on" : ""}`} onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => { if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); } }}>
        Other <span className="caret" aria-hidden>▾</span>
      </button>
      {open && (
        <div className="menu" role="menu" aria-label="Other lists"
          onKeyDown={(e) => {
            const all = items(), i = all.indexOf(document.activeElement as HTMLButtonElement);
            if (e.key === "ArrowDown") { e.preventDefault(); all[(i + 1) % all.length]?.focus(); }
            else if (e.key === "ArrowUp") { e.preventDefault(); all[(i - 1 + all.length) % all.length]?.focus(); }
            else if (e.key === "Home") { e.preventDefault(); all[0]?.focus(); }
            else if (e.key === "End") { e.preventDefault(); all[all.length - 1]?.focus(); }
            else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); e.stopPropagation(); close(); }
            e.stopPropagation(); // keep J / K / A … for the case, not the menu
          }}>
          {OTHER.map((k) => (
            <button key={k} role="menuitemradio" aria-checked={list === k} className={list === k ? "on" : ""}
              onClick={() => { onList(k); close(); }}>
              <span className="mark" aria-hidden>{list === k ? "✓" : ""}</span>
              <span className="menu-label">{LISTS[k]}</span>
              <span className="n">{counts[k]}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Queue({ list, items, counts, questions, decisions, selected, onList, onSelect }: QueueProps) {
  const active = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    active.current?.scrollIntoView({ block: "nearest" }); // never return this (newer browsers return a value)
  }, [selected]);
  const other = OTHER.includes(list);
  return (
    <nav className="queue" aria-label="Queue" data-tour="queue">
      <div className="qtabs" role="tablist" data-tour="tabs">
        {(["needs", "done"] as ListKey[]).map((k) => (
          <button key={k} role="tab" aria-selected={list === k} className={`qtab ${list === k ? "on" : ""}`} onClick={() => onList(k)}>
            {LISTS[k]} <span className="n">{counts[k]}</span>
          </button>
        ))}
        <OtherMenu list={list} counts={counts} onList={onList} />
      </div>
      {other && <p className="qhead">{LISTS[list]} · {counts[list]}</p>}
      <ol className="rows">
        {items.map((it) => {
          const on = it.key === selected;
          const done = !!decisions[it.key];
          const q = questions[it.questionId];
          return (
            <li key={it.key}>
              <button ref={on ? active : null} className={`row ${on ? "on" : ""} ${done ? "done" : ""}`} onClick={() => onSelect(it.key)}
                aria-current={on ? "true" : undefined}>
                {done ? <span className="tick" aria-label="done">✓</span> : <span className={`dot t${it.tier}`} title={it.tierLabel} />}
                <span className="row-body">
                  <span className="row-title">{it.title}</span>
                  <span className="row-meta">
                    <span className="row-topic">{q?.chapter}</span>
                    {it.reach > 0 && <span className="row-n" title="distinct students who reported it">{it.reach}</span>}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {items.length === 0 && <li className="empty-row">Nothing here.</li>}
      </ol>
    </nav>
  );
}

// ---------------------------------------------------------------- dialogs

export function NameDialog({ onDone, onCancel }: { onDone: (name: string) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  return (
    <div className="scrim" role="dialog" aria-modal="true" aria-labelledby="name-title">
      <form className="dialog small" onSubmit={(e) => { e.preventDefault(); if (name.trim()) onDone(name.trim()); }}
        onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}>
        <h2 id="name-title">Who is reviewing?</h2>
        <p className="muted">Your name goes on every entry in the audit log. Asked once; remembered in this browser.</p>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" aria-label="Your name" />
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn primary" disabled={!name.trim()}>Continue</button>
        </div>
      </form>
    </div>
  );
}

export function ReasonDialog({ title, onDone, onCancel }:
  { title: string; onDone: (reason: string, note: string) => void; onCancel: () => void }) {
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const noteRef = useRef<HTMLTextAreaElement | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  useEffect(() => box.current?.focus(), []);
  const submit = () => reason && onDone(reason, note.trim());
  return (
    <div className="scrim" role="dialog" aria-modal="true" aria-labelledby="reason-title">
      <div className="dialog" ref={box} tabIndex={-1}
        onKeyDown={(e) => {
          const typing = e.target instanceof HTMLTextAreaElement;
          if (e.key === "Escape") { e.preventDefault(); onCancel(); }
          else if (e.key === "Enter" && (!typing || e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); }
          else if (!typing && /^[1-4]$/.test(e.key)) { setReason(REASONS[Number(e.key) - 1]); e.preventDefault(); }
          else if (!typing && e.key.toLowerCase() === "n") { noteRef.current?.focus(); e.preventDefault(); }
        }}>
        <h2 id="reason-title">{title}</h2>
        <div className="chips" role="radiogroup" aria-label="Reason">
          {REASONS.map((r, i) => (
            <button key={r} role="radio" aria-checked={reason === r} className={`chip ${reason === r ? "on" : ""}`} onClick={() => setReason(r)}>
              <Kbd>{i + 1}</Kbd> {r}
            </button>
          ))}
        </div>
        <textarea ref={noteRef} rows={2} placeholder="Note (optional) · N" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note" />
        <div className="dialog-actions">
          <span className="muted small">Enter to save · Esc to cancel</span>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn primary" disabled={!reason} onClick={submit}>Save</button>
        </div>
      </div>
    </div>
  );
}

const SHORTCUTS: [string, string][] = [
  ["J / K", "Next / previous case"], ["A", "Approve · Confirm · Keep · Looks right"], ["E", "Edit the change and the replies"],
  ["R", "Reject · Not a defect · Flag"], ["U", "Undo an auto-applied change"], ["Z", "Undo your last action (while the toast shows)"],
  ["Ctrl + Enter", "Save an edit"], ["Esc", "Cancel / close"], ["\\", "Show or hide the queue"], ["?", "This list"],
];

export function Shortcuts({ onClose, onTour }: { onClose: () => void; onTour: () => void }) {
  return (
    <div className="scrim" role="dialog" aria-modal="true" aria-labelledby="sc-title" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2 id="sc-title">Keyboard</h2>
        <dl className="shortcuts">
          {SHORTCUTS.map(([k, v]) => (<div key={k}><dt><Kbd>{k}</Kbd></dt><dd>{v}</dd></div>))}
        </dl>
        <div className="dialog-actions"><button className="btn" onClick={onTour}>Take the tour</button><button className="btn" autoFocus onClick={onClose}>Close</button></div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- audit drawer

export function AuditDrawer({ entries, reviewer, onRename, onClose, onOpen }:
  { entries: AuditEntry[]; reviewer: string; onRename: () => void; onClose: () => void; onOpen: (item: string) => void }) {
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(entries, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `review-audit-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <div className="scrim right" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="audit-title" onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
        <header className="drawer-head">
          <h2 id="audit-title">Audit log</h2>
          <button className="btn" onClick={exportJson} disabled={!entries.length}>Export JSON</button>
          <button className="btn" onClick={onClose} autoFocus>Close</button>
        </header>
        <p className="muted small">
          Stored in this browser. Clearing site data deletes it; export to keep a copy.
          {reviewer && <> Reviewing as <b>{reviewer}</b> · <button className="link" onClick={onRename}>change</button></>}
        </p>
        {entries.length === 0 && <p className="muted">No actions yet.</p>}
        <ol className="audit">
          {[...entries].reverse().map((e) => (
            <li key={e.id}>
              <p className="audit-top">
                <b>{e.action}</b> <span className="muted">· {fmtTime(e.time)} · {e.reviewer}</span>
              </p>
              <p className="small">
                <button className="link id" onClick={() => onOpen(e.item)}>{e.questionId.slice(0, 8)}</button>
                {e.reportIds.length > 0 && <span className="id"> · {e.reportIds.join(", ")}</span>}
                {e.reason && <> · {e.reason}</>}{e.note && <> · “{e.note}”</>}
              </p>
              {(e.before != null || e.after != null) && JSON.stringify(e.before) !== JSON.stringify(e.after) && (
                <details className="small"><summary>Before / after</summary>
                  <pre className="mono">{JSON.stringify({ before: e.before, after: e.after }, null, 2)}</pre>
                </details>
              )}
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------- toast

export function Toast({ text, onUndo }: { text: string; onUndo: () => void }) {
  return (
    <div className="toast" role="status">
      <span>{text}</span>
      <button className="link" onClick={onUndo}>Undo <Kbd>Z</Kbd></button>
    </div>
  );
}

export { PAST };
