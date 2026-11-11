import { useEffect, useMemo, useState } from "react";
import type { Data, Group, TabKey } from "./types";
import { TABS, buildGroups, casesOnQuestion } from "./model";
import { Queue } from "./components/Queue";
import { BonusView, CaseView } from "./components/CaseView";
import { Kbd } from "./components/bits";

type Theme = "dark" | "light";

function readTheme(): Theme {
  const forced = new URLSearchParams(location.search).get("theme");
  if (forced === "light" || forced === "dark") return forced;
  try {
    return localStorage.getItem("console-theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function App() {
  const [data, setData] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("needs");
  const [sel, setSel] = useState<Record<TabKey, string | null>>({ needs: null, auto: null, nochange: null, bonus: null });
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [auditOpen, setAuditOpen] = useState(false);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`data.json: HTTP ${r.status}`))))
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("console-theme", theme);
    } catch {
      /* private mode: theme just isn't remembered */
    }
  }, [theme]);

  const groups = useMemo(() => (data ? buildGroups(data) : null), [data]);

  // Deep link: #<tab>/<questionId> selects a case (used by links from the audit log and for sharing).
  useEffect(() => {
    if (!groups) return;
    const [t, qid] = decodeURIComponent(location.hash.slice(1)).split("/");
    if (t && t in groups) {
      setTab(t as TabKey);
      const g = groups[t as TabKey].find((x) => x.questionId === qid);
      if (g) setSel((s) => ({ ...s, [t]: g.key }));
    }
  }, [groups]);
  const list: Group[] = groups ? groups[tab] : [];
  const selectedKey = sel[tab] ?? list[0]?.key ?? null;
  const group = list.find((g) => g.key === selectedKey) ?? null;

  useEffect(() => {
    if (group) history.replaceState(null, "", `#${tab}/${group.questionId}`);
  }, [group, tab]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if ((k === "j" || k === "k") && list.length) {
        const i = Math.max(0, list.findIndex((g) => g.key === selectedKey));
        const next = list[Math.min(list.length - 1, Math.max(0, i + (k === "j" ? 1 : -1)))];
        setSel((s) => ({ ...s, [tab]: next.key }));
        document.querySelector(".centre")?.scrollTo({ top: 0 });
        e.preventDefault();
      } else if (["1", "2", "3", "4"].includes(k)) {
        setTab(TABS[Number(k) - 1].key);
      } else if (k === "escape") {
        setAuditOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [list, selectedKey, tab]);

  if (err) return <div className="boot bad">Could not load data: {err}. Run <code>npm run data</code> first.</div>;
  if (!data || !groups) return <div className="boot">Loading…</div>;

  const total = (Object.values(groups) as Group[][]).reduce((n, gs) => n + gs.length, 0);
  const count = (t: TabKey) => groups[t].reduce((n, g) => n + (g.cases.length || g.bonus.length), 0);
  const q = group ? data.questions[group.questionId] : null;
  const pos = group ? list.indexOf(group) + 1 : 0;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>◧</span>
          <span className="brand-name">Report review</span>
          <span className="banner" title={`Run ${data.meta.runId}, built ${data.meta.generatedAt}`}>Precomputed results, no live AI calls.</span>
        </div>
        <div className="progress" title="Queue items (one per question per tab) you have acted on">
          <span className="progress-text"><b>0</b> of {total} reviewed</span>
          <span className="progress-bar"><span style={{ width: "0%" }} /></span>
        </div>
        <div className="counts">
          <span className="count c-needs">{count("needs")} need you</span>
          <span className="count c-auto">{count("auto")} auto-applied</span>
          <span className="count c-none">{count("nochange")} no change</span>
          <span className="count c-bonus">{count("bonus")} bonus</span>
        </div>
        <div className="top-actions">
          <button className="link" onClick={() => setAuditOpen(true)}>Audit log</button>
          <button className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title="Toggle light/dark">
            {theme === "dark" ? "☀" : "☾"}
          </button>
        </div>
      </header>

      <div className="body">
        <Queue tab={tab} groups={groups} questions={data.questions} selected={selectedKey}
          onTab={setTab} onSelect={(k) => setSel((s) => ({ ...s, [tab]: k }))} />
        <main className="centre">
          {group && q ? (
            group.tab === "bonus" ? (
              <BonusView group={group} q={q} allCases={casesOnQuestion(data, q.id)} />
            ) : (
              <CaseView group={group} q={q} allCases={casesOnQuestion(data, q.id)} />
            )
          ) : (
            <div className="boot">Nothing selected.</div>
          )}
        </main>
      </div>

      <footer className="actionbar">
        <span className="ab-pos">{pos ? `${pos} / ${list.length}` : "–"}</span>
        <div className="ab-buttons" title="Actions arrive in stage 2">
          <button className="btn approve" disabled>Approve <Kbd>A</Kbd></button>
          <button className="btn" disabled>Edit <Kbd>E</Kbd></button>
          <button className="btn reject" disabled>Reject <Kbd>R</Kbd></button>
        </div>
        <span className="ab-hint"><Kbd>J</Kbd><Kbd>K</Kbd> next / previous · <Kbd>1</Kbd>–<Kbd>4</Kbd> tabs · actions in stage 2</span>
      </footer>

      {auditOpen && (
        <div className="drawer-wrap" onClick={() => setAuditOpen(false)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <header className="section-head"><h3>Audit log</h3><button className="link" onClick={() => setAuditOpen(false)}>Close</button></header>
            <p className="muted">Every action will record time, reviewer, case, action, before/after and reason.</p>
            <p className="note">Stored in this browser only (localStorage). Clearing site data deletes it; export to JSON to keep a copy.</p>
            <p className="muted">No actions recorded yet. Actions arrive in stage 2.</p>
            <button className="btn" disabled>Export JSON</button>
          </aside>
        </div>
      )}
    </div>
  );
}
