import { useEffect, useRef } from "react";
import type { Group, Question, TabKey } from "../types";
import { TABS } from "../model";
import { Dot } from "./bits";

interface Props {
  tab: TabKey;
  groups: Record<TabKey, Group[]>;
  questions: Record<string, Question>;
  selected: string | null;
  onTab: (t: TabKey) => void;
  onSelect: (key: string) => void;
}

export function Queue({ tab, groups, questions, selected, onTab, onSelect }: Props) {
  const list = groups[tab];
  const activeRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" }); // newer browsers return a value here; never return it
  }, [selected]);

  return (
    <aside className="queue">
      <nav className="tabs" role="tablist">
        {TABS.map((t, i) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={t.key === tab}
            className={`tab ${t.key === tab ? "active" : ""}`}
            onClick={() => onTab(t.key)}
            title={`${t.hint}  (${i + 1})`}
          >
            {t.label}
            <span className="tab-count">{groups[t.key].reduce((n, g) => n + (g.cases.length || g.bonus.length), 0)}</span>
          </button>
        ))}
      </nav>
      <div className="queue-hint">{TABS.find((t) => t.key === tab)?.hint} · sorted by harm, reach, certainty</div>
      <ol className="rows">
        {list.map((g) => {
          const q = questions[g.questionId];
          const n = g.tab === "bonus" ? g.bonus.length : g.reach;
          const on = g.key === selected;
          return (
            <li key={g.key}>
              <button ref={on ? activeRef : null} className={`row ${on ? "on" : ""}`} onClick={() => onSelect(g.key)}>
                <Dot harm={g.harm} />
                <span className="row-main">
                  <span className="row-top">
                    <span className="row-topic">{q?.chapter || q?.subject}</span>
                    <span className="row-count" title={g.tab === "bonus" ? "findings on this question" : "distinct students who reported it"}>
                      {g.tab === "bonus" ? "◆" : "●"} {n}
                    </span>
                  </span>
                  <span className="row-reason">{g.headline}</span>
                  <span className="row-why">{g.why}</span>
                </span>
              </button>
            </li>
          );
        })}
        {list.length === 0 && <li className="empty">Nothing here.</li>}
      </ol>
    </aside>
  );
}
