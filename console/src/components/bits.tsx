import DOMPurify from "dompurify";
import { useMemo, type ReactNode } from "react";
import type { Chip as ChipT, Tone } from "../types";
import { HARM_CLASS } from "../model";

/** Stored question HTML is untrusted: keep HTML + MathML, drop scripts, event handlers, inline styles
 *  (inline colours are black-on-white from the authoring tool and would vanish in dark mode). */
export function sanitize(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true, mathMl: true },
    FORBID_TAGS: ["style", "script", "iframe", "object", "embed", "form", "input"],
    FORBID_ATTR: ["style"],
  });
}

export function Html({ html, className = "" }: { html: string; className?: string }) {
  const clean = useMemo(() => sanitize(html), [html]);
  return <div className={`qhtml ${className}`} dangerouslySetInnerHTML={{ __html: clean }} />;
}

export function Dot({ harm, title }: { harm: number; title?: string }) {
  return <span className={`dot ${HARM_CLASS[harm] ?? "harm-0"}`} title={title} aria-hidden />;
}

const MARK: Record<Tone, string> = { ok: "✓", bad: "✗", warn: "!", neutral: "·" };

export function Chip({ chip }: { chip: ChipT }) {
  return (
    <span className={`chip tone-${chip.tone}`} title={chip.title || undefined}>
      <span className="chip-mark">{MARK[chip.tone]}</span>
      {chip.label}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

export function Section({ title, aside, children, verbatim = false }:
  { title: string; aside?: ReactNode; children: ReactNode; verbatim?: boolean }) {
  return (
    <section className="section">
      <header className="section-head">
        <h3 className={verbatim ? "verbatim" : undefined}>{title}</h3>
        {aside}
      </header>
      {children}
    </section>
  );
}

export function ChangePill({ from, to }: { from: string; to: string }) {
  return (
    <span className="change-pill">
      <span className="cp-from">{from}</span>
      <span className="cp-arrow">→</span>
      <span className="cp-to">{to}</span>
    </span>
  );
}
