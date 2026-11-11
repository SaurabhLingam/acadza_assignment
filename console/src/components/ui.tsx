import DOMPurify from "dompurify";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Grid } from "../types";

/** Stored HTML is untrusted: keep HTML + MathML; drop scripts, event handlers, forms, frames and inline styles
 *  (the authoring tool's inline colours are black-on-white and would vanish in dark mode). */
export function sanitize(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true, mathMl: true },
    FORBID_TAGS: ["style", "script", "iframe", "object", "embed", "form", "input", "button", "textarea", "select"],
    FORBID_ATTR: ["style"],
  });
}

export function Html({ html, className = "" }: { html: string; className?: string }) {
  const clean = useMemo(() => sanitize(html), [html]);
  const ref = useRef<HTMLDivElement | null>(null);
  // Wide maths scrolls sideways; make sure a marked change is in view rather than past the edge.
  useEffect(() => {
    const box = ref.current;
    const mark = box?.querySelector(".ins, .del, .flag");
    if (!box || !mark || box.scrollWidth <= box.clientWidth) return;
    const b = box.getBoundingClientRect(), m = mark.getBoundingClientRect();
    if (m.right > b.right - 16 || m.left < b.left + 16) box.scrollLeft += m.left - b.left - b.width / 2 + m.width / 2;
  }, [clean]);
  return <div ref={ref} className={`prose ${className}`} dangerouslySetInnerHTML={{ __html: clean }} />;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

/** A secondary section: one line when closed. */
export function Fold({ title, summary, open, onToggle, children }:
  { title: string; summary?: ReactNode; open: boolean; onToggle: () => void; children: ReactNode }) {
  return (
    <section className={`fold ${open ? "open" : ""}`}>
      <button className="fold-head" onClick={onToggle} aria-expanded={open}>
        <span className="fold-caret" aria-hidden>{open ? "▾" : "▸"}</span>
        <span className="fold-title">{title}</span>
        {summary && <span className="fold-summary">{summary}</span>}
      </button>
      {open && <div className="fold-body">{children}</div>}
    </section>
  );
}

const MARK: Record<string, { t: string; c: string; label: string }> = {
  y: { t: "✓", c: "pass", label: "yes" },
  n: { t: "✗", c: "fail", label: "no" },
  mixed: { t: "±", c: "muted", label: "checks disagree" },
  "": { t: "–", c: "muted", label: "no signal" },
};

export function EvidenceGrid({ grid }: { grid: Grid }) {
  return (
    <div className="grid-wrap">
      <table className="egrid">
        <thead>
          <tr>
            <th scope="col" className="egrid-opt">{grid.rows[0]?.text ? "Option" : "Value"}</th>
            {grid.cols.map((c) => (
              <th key={c.id} scope="col" title={c.title}>
                <span className="th-label">{c.label}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.rows.map((r) => (
            <tr key={r.id}>
              <th scope="row" className="egrid-opt">
                <span className="opt-letter">{r.label}</span>
                {r.text && <span className="opt-text">{r.text}</span>}
              </th>
              {grid.cols.map((c) => {
                const v = r.cells[c.id] ?? "";
                const judge = c.id === "check";
                const m = v === "y" && !judge ? { ...MARK.y, c: "pick", label: "picked this" } : MARK[v];
                const note = c.id === "check" ? (r.notes.check as string | undefined) : undefined;
                const twice = c.id === "check" && Number(r.notes.checkCount ?? 0) > 1 && v !== "";
                return (
                  <td key={c.id} className={m.c} title={note || `${c.label}: ${m.label}`}>
                    {m.t}{twice && <sup className="twice">×{r.notes.checkCount}</sup>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function useToggle(initial = false): [boolean, () => void, (v: boolean) => void] {
  const [v, set] = useState(initial);
  return [v, () => set((x) => !x), set];
}
