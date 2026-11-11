import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ActionId, AuditEntry, Data, Decision, Draft, Item, ListKey } from "./types";
import { ACTIONS, KEYS, LISTS, PAST, type ActionDef, listOf, load, modeOf, save } from "./model";
import { diffHtml, draftEdit, guard, startDraft } from "./edit";
import { CaseView } from "./components/CaseView";
import { AuditDrawer, NameDialog, Queue, ReasonDialog, Shortcuts, Toast } from "./components/chrome";
import { Kbd } from "./components/ui";
import { Tour } from "./components/Tour";

type Theme = "dark" | "light";
interface Pending { def: ActionDef; reason?: string; note?: string }
interface ToastState { text: string; itemKey: string; list: ListKey; prev: Decision | undefined; id: number }

function initialTheme(): Theme {
  const p = new URLSearchParams(location.search).get("theme");
  if (p === "light" || p === "dark") return p;
  return load<Theme>(KEYS.theme, "dark") === "light" ? "light" : "dark";
}

function parseHash(): { list: ListKey | null; ref: string } {
  const [l, ref = ""] = decodeURIComponent(location.hash.slice(1)).split("/");
  return { list: l && l in LISTS ? (l as ListKey) : null, ref };
}

export function App() {
  const [data, setData] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [list, setList] = useState<ListKey>(() => parseHash().list ?? "needs");
  const [sel, setSel] = useState<Partial<Record<ListKey, string>>>({});
  const [decisions, setDecisions] = useState<Record<string, Decision>>(() => load(KEYS.decisions, {}));
  const [audit, setAudit] = useState<AuditEntry[]>(() => load(KEYS.audit, []));
  const [reviewer, setReviewer] = useState<string>(() => load(KEYS.reviewer, ""));
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [queueOpen, setQueueOpen] = useState<boolean>(() => load(KEYS.queue, window.innerWidth > 900));
  const [draft, setDraft] = useState<Draft | null>(null);
  const [askReason, setAskReason] = useState<ActionDef | null>(null);
  const [askName, setAskName] = useState<Pending | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [showKeys, setShowKeys] = useState(false);
  const [showAudit, setShowAudit] = useState(false);
  const [tour, setTourOpen] = useState(false);
  const toastTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`data.json: HTTP ${r.status}`))))
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; save(KEYS.theme, theme); }, [theme]);
  useEffect(() => save(KEYS.decisions, decisions), [decisions]);
  useEffect(() => save(KEYS.audit, audit), [audit]);
  useEffect(() => save(KEYS.queue, queueOpen), [queueOpen]);

  const items = data?.items ?? [];
  const lists = useMemo(() => {
    const out = {} as Record<ListKey, Item[]>;
    for (const k of Object.keys(LISTS) as ListKey[]) out[k] = listOf(items, k, decisions);
    return out;
  }, [items, decisions]);
  const counts = useMemo(() => {
    const c = {} as Record<ListKey, number>;
    for (const k of Object.keys(LISTS) as ListKey[]) c[k] = lists[k].length;
    return c;
  }, [lists]);

  // deep link: #<list>/<item key or question id prefix>
  // The tour runs on the first case of "Needs you", with the queue showing.
  const setTour = (on: boolean) => {
    if (on) {
      setShowKeys(false); setShowAudit(false); setDraft(null);
      setList("needs"); setQueueOpen(true);
      const first = listOf(items, "needs", decisions)[0];
      if (first) setSel((s) => ({ ...s, needs: first.key }));
    } else {
      save(KEYS.tour, true);
    }
    setTourOpen(on);
  };
  // first visit: show it once, remembered in this browser
  useEffect(() => {
    if (data && !load(KEYS.tour, false) && !parseHash().ref) setTour(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const listsRef = useRef(lists);
  listsRef.current = lists;
  useEffect(() => {
    if (!data) return;
    const follow = () => {
      const { list: l, ref } = parseHash();
      if (!l) return;
      setDraft(null);
      setList(l);
      const hit = ref && listsRef.current[l].find((i) => i.key === ref || i.questionId.startsWith(ref));
      if (hit) setSel((s) => ({ ...s, [l]: hit.key }));
    };
    follow();
    window.addEventListener("hashchange", follow);   // pasted links, back/forward
    return () => window.removeEventListener("hashchange", follow);
  }, [data]);

  const current: Item | null = lists[list].find((i) => i.key === sel[list]) ?? lists[list][0] ?? null;
  const q = current && data ? data.questions[current.questionId] : null;
  const mode = current ? modeOf(current) : null;
  const defs = mode ? ACTIONS[mode] : [];

  useEffect(() => {
    if (current) history.replaceState(null, "", `#${list}/${encodeURIComponent(current.key)}`);
  }, [current, list]);

  // edit mode: the edit the draft describes, the guard verdict and the live diff
  const edited = current && q && draft ? draftEdit(current, q, draft) : null;
  const editChanged = !!edited && JSON.stringify(edited) !== JSON.stringify(current?.edit);
  const guardError = current && q && data && edited && editChanged ? guard(edited, current.repair, q, data.meta.repairFields) : null;
  const draftDiff = q && edited && editChanged ? diffHtml(q, edited) : null;

  const select = useCallback((key: string | undefined) => {
    setDraft(null);
    if (key) setSel((s) => ({ ...s, [list]: key }));
    document.querySelector(".main")?.scrollTo({ top: 0 });
  }, [list]);

  const move = (step: number) => {
    const L = lists[list];
    if (!L.length) return;
    const i = Math.max(0, L.findIndex((x) => x.key === current?.key));
    select(L[Math.min(L.length - 1, Math.max(0, i + step))].key);
  };

  const commit = (def: ActionDef, reason?: string, note?: string, who = reviewer) => {
    if (!current) return;
    const it = current;
    const L = lists[list];
    const idx = L.findIndex((x) => x.key === it.key);
    let action: ActionId = def.id;
    let after: unknown = it.edit ? { field: it.edit.field, value: it.edit.replace } : null;
    let before: unknown = it.edit ? { field: it.edit.field, value: it.edit.find } : null;
    let replies: Record<string, string> | undefined;
    let edit = it.edit;
    if (def.edit && draft) {
      const changedReplies = Object.fromEntries(Object.entries(draft.replies).filter(([rid, txt]) =>
        it.reports.find((r) => r.reportId === rid)?.reply !== txt));
      replies = Object.keys(changedReplies).length ? changedReplies : undefined;
      edit = editChanged ? edited : it.edit;
      before = { edit: it.edit, replies: replies ? Object.fromEntries(Object.keys(replies).map((r) => [r, it.reports.find((x) => x.reportId === r)?.reply])) : undefined };
      after = { edit, replies };
      if (!editChanged && !replies) {                 // nothing was changed: record a plain approve / keep
        action = def.id === "keep_edited" ? "keep" : "approve";
        before = it.edit ? { field: it.edit.field, value: it.edit.find } : null;
        after = it.edit ? { field: it.edit.field, value: it.edit.replace } : null;
      }
    }
    if (def.id === "undo_edit") { before = it.edit ? { field: it.edit.field, value: it.edit.replace } : null; after = it.edit ? { field: it.edit.field, value: it.edit.find } : null; }
    if (def.id === "reject" || def.id === "not_defect" || def.id === "flag") after = before;
    const d: Decision = { action, at: new Date().toISOString(), reviewer: who, reason, note, edit, replies };
    const prev = decisions[it.key];
    setDecisions((s) => ({ ...s, [it.key]: d }));
    setAudit((a) => [...a, {
      id: `${Date.now()}-${a.length}`, time: d.at, reviewer: who, questionId: it.questionId, reportIds: it.reportIds,
      item: it.key, action: PAST[action], before, after, reason, note,
    }]);
    setDraft(null);
    // next case: the one after this in the list as it was (in "Needs you" the decided case leaves the list)
    const next = L[idx + 1] ?? L[idx - 1];
    if (next && next.key !== it.key) setSel((s) => ({ ...s, [list]: next.key }));
    document.querySelector(".main")?.scrollTo({ top: 0 });
    window.clearTimeout(toastTimer.current);
    const t: ToastState = { text: `${PAST[action]} · ${it.title}`, itemKey: it.key, list, prev, id: Date.now() };
    setToast(t);
    toastTimer.current = window.setTimeout(() => setToast((x) => (x?.id === t.id ? null : x)), 5000);
  };

  const undoLast = () => {
    if (!toast) return;
    const t = toast;
    setDecisions((s) => {
      const n = { ...s };
      if (t.prev) n[t.itemKey] = t.prev; else delete n[t.itemKey];
      return n;
    });
    const it = items.find((i) => i.key === t.itemKey);
    setAudit((a) => [...a, {
      id: `${Date.now()}-${a.length}`, time: new Date().toISOString(), reviewer, questionId: it?.questionId ?? "",
      reportIds: it?.reportIds ?? [], item: t.itemKey, action: `Reverted: ${t.text.split(" · ")[0]}`, before: null, after: null,
    }]);
    setList(t.list);
    setSel((s) => ({ ...s, [t.list]: t.itemKey }));
    setToast(null);
  };

  const act = (def: ActionDef, reason?: string, note?: string) => {
    if (!current) return;
    if (def.edit && !draft) { setDraft(startDraft(current)); return; }
    if (def.edit && draft && guardError) return;
    if (!reviewer) { setAskName({ def, reason, note }); return; }
    if (def.needsReason && !reason) { setAskReason(def); return; }
    commit(def, reason, note);
  };

  const editDef = defs.find((d) => d.edit);
  const saveEdit = () => { if (editDef && draft && !guardError) act(editDef); };

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (askReason || askName || showKeys || showAudit || tour) return;   // dialogs handle their own keys
      const t = e.target as HTMLElement;
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
      if (draft) {
        if (e.key === "Escape") { setDraft(null); e.preventDefault(); }
        else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { saveEdit(); e.preventDefault(); }
        return;
      }
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key;
      if (k === "j" || k === "J") { move(1); e.preventDefault(); }
      else if (k === "k" || k === "K") { move(-1); e.preventDefault(); }
      else if (k === "\\") { setQueueOpen((v) => !v); e.preventDefault(); }
      else if (k === "?") { setShowKeys(true); e.preventDefault(); }
      else if ((k === "z" || k === "Z") && toast) { undoLast(); e.preventDefault(); }
      else {
        const def = defs.find((d) => d.key.toLowerCase() === k.toLowerCase());
        if (def) { act(def); e.preventDefault(); }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (err) return <div className="boot">Could not load data: {err}. Run <code>npm run data</code>.</div>;
  if (!data) return <div className="boot">Loading…</div>;

  const needsTotal = items.filter((i) => i.route === "faculty_review").length;
  const remaining = counts.needs;
  const doneByAction = Object.values(decisions).reduce<Record<string, number>>((m, d) => ({ ...m, [PAST[d.action]]: (m[PAST[d.action]] ?? 0) + 1 }), {});

  return (
    <div className={`app ${queueOpen ? "" : "queue-hidden"}`}>
      <header className="top">
        <button className="icon" onClick={() => setQueueOpen((v) => !v)} title="Show or hide the queue (\)" aria-label="Toggle queue">☰</button>
        <span className="product">Report review</span>
        <span className="note">Precomputed results, no live AI calls</span>
        <div className="progress" title={`${needsTotal - remaining} of ${needsTotal} decided`}>
          <span><b>{remaining}</b> of {needsTotal} need you</span>
          <span className="bar" aria-hidden><span style={{ width: `${needsTotal ? ((needsTotal - remaining) / needsTotal) * 100 : 100}%` }} /></span>
        </div>
        <button className="link" onClick={() => setTour(true)}>Tour</button>
        <button className="link" data-tour="audit" onClick={() => setShowAudit(true)}>Audit log{audit.length ? ` · ${audit.length}` : ""}</button>
        <button className="icon" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Toggle light or dark theme"
          title="Light / dark">{theme === "dark" ? "☀" : "☾"}</button>
      </header>

      {queueOpen && (
        <Queue list={list} items={lists[list]} counts={counts} questions={data.questions} decisions={decisions}
          selected={current?.key ?? null} onList={(l) => { setDraft(null); setList(l); }} onSelect={select} />
      )}

      <main className="main">
        {current && q ? (
          <CaseView key={current.key} item={current} q={q} decision={decisions[current.key]}
            draft={draft} setDraft={setDraft} draftDiff={draftDiff} guardError={guardError} />
        ) : list === "needs" ? (
          <div className="empty">
            <p className="empty-mark" aria-hidden>✓</p>
            <h1>All caught up</h1>
            <p className="muted">Nothing needs you right now. {Object.keys(decisions).length} decided in this browser.</p>
            {Object.keys(doneByAction).length > 0 && (
              <ul className="tally">{Object.entries(doneByAction).map(([k, n]) => <li key={k}><b>{n}</b> {k.toLowerCase()}</li>)}</ul>
            )}
            <p className="muted small">
              Spot-check the rest:{" "}
              {(["auto", "nochange", "bonus"] as ListKey[]).map((k, i) => (
                <span key={k}>{i > 0 && " · "}<button className="link" onClick={() => setList(k)}>{LISTS[k]} ({counts[k]})</button></span>
              ))}
            </p>
          </div>
        ) : (
          <div className="empty"><h1>Nothing here</h1></div>
        )}
      </main>

      <footer className="actions" data-tour="actions">
        <span className="pos">
          {current ? `${lists[list].findIndex((x) => x.key === current.key) + 1} / ${lists[list].length}` : ""}
          <span className="hint"><Kbd>J</Kbd><Kbd>K</Kbd></span>
        </span>
        <div className="buttons">
          {current && draft ? (
            <>
              {guardError && <span className="guard-inline">Blocked by an edit guard (see above)</span>}
              <button className="btn" onClick={() => setDraft(null)}>Cancel <Kbd>Esc</Kbd></button>
              <button className="btn primary" disabled={!!guardError} onClick={saveEdit}>
                {mode === "auto" ? "Save and keep" : "Save and approve"} <Kbd>Ctrl ↵</Kbd>
              </button>
            </>
          ) : current ? (
            defs.map((d) => (
              <button key={d.id} className={`btn ${d.kind}`} onClick={() => act(d)}>
                {d.label} <Kbd>{d.key}</Kbd>
              </button>
            ))
          ) : null}
        </div>
        <button className="link small" onClick={() => setShowKeys(true)}>Shortcuts <Kbd>?</Kbd></button>
      </footer>

      {toast && <Toast text={toast.text} onUndo={undoLast} />}
      {askName && (
        <NameDialog onCancel={() => setAskName(null)} onDone={(n) => {
          setReviewer(n); save(KEYS.reviewer, n);
          const p = askName; setAskName(null);
          if (p.def.needsReason && !p.reason) setAskReason(p.def); else commit(p.def, p.reason, p.note, n);
        }} />
      )}
      {askReason && (
        <ReasonDialog title={`${askReason.label}: why?`} onCancel={() => setAskReason(null)}
          onDone={(r, n) => { const d = askReason; setAskReason(null); commit(d, r, n); }} />
      )}
      {showKeys && <Shortcuts onClose={() => setShowKeys(false)} onTour={() => setTour(true)} />}
      {tour && <Tour onClose={() => setTour(false)} />}
      {showAudit && (
        <AuditDrawer entries={audit} reviewer={reviewer} onClose={() => setShowAudit(false)}
          onRename={() => { setShowAudit(false); setReviewer(""); save(KEYS.reviewer, ""); }}
          onOpen={(key) => {
            const it = items.find((i) => i.key === key);
            if (!it) return;
            const l: ListKey = decisions[key] ? "done" : it.route === "faculty_review" ? "needs" : it.route === "auto_apply" ? "auto" : it.route === "no_change" ? "nochange" : "bonus";
            setList(l); setSel((s) => ({ ...s, [l]: key })); setShowAudit(false);
          }} />
      )}
    </div>
  );
}
