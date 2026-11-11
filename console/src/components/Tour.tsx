import { useEffect, useLayoutEffect, useRef, useState } from "react";

/** A lightweight guided tour: a spotlight over one [data-tour] target, a dimmed backdrop, and a small
 *  popover. Keyboard: → / Enter next, ← back, Esc skip. Focus stays inside the popover. */

export const TOUR_STEPS: { target: string; title: string; text: string }[] = [
  { target: "queue", title: "Queue", text: "Cases that need you, most harmful first. Grouped by question." },
  { target: "headline", title: "Headline", text: "What's wrong, in one sentence." },
  { target: "sure", title: "How sure", text: "How much independent evidence agrees. Open “Show evidence” for the grid." },
  { target: "changes", title: "What changes", text: "Before and after. Nothing goes live without your action here." },
  { target: "actions", title: "Action bar", text: "Approve, Edit or Reject. Keyboard: A / E / R, J / K to move." },
  { target: "audit", title: "Audit log", text: "Every action is recorded with your name. Export anytime." },
];

const PAD = 6;
const GAP = 12;
const W = 320;

export function Tour({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const pop = useRef<HTMLDivElement | null>(null);
  const nextBtn = useRef<HTMLButtonElement | null>(null);
  const step = TOUR_STEPS[i];
  const last = i === TOUR_STEPS.length - 1;

  // find and measure the target; bring it into view first if it is off-screen
  useLayoutEffect(() => {
    const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
    if (!el) { setRect(null); return; }
    const r0 = el.getBoundingClientRect();
    if (r0.top < 0 || r0.bottom > window.innerHeight) el.scrollIntoView({ block: "center" });
    const measure = () => setRect(el.getBoundingClientRect());
    measure();
    const raf = requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    document.querySelector(".main")?.addEventListener("scroll", measure);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", measure);
      document.querySelector(".main")?.removeEventListener("scroll", measure);
    };
  }, [step.target]);

  // place the popover beside the target, kept inside the window
  useLayoutEffect(() => {
    const h = pop.current?.offsetHeight ?? 120;
    const vw = window.innerWidth, vh = window.innerHeight;
    const width = Math.min(W, vw - 32);
    if (!rect) { setPos({ top: vh / 2 - h / 2, left: vw / 2 - width / 2 }); return; }
    let top: number, left: number;
    if (rect.right + GAP + width < vw - 16 && rect.width < vw * 0.4) {           // right of a narrow target (queue)
      top = rect.top; left = rect.right + GAP;
    } else if (rect.bottom + GAP + h < vh - 16) {                                 // below
      top = rect.bottom + GAP; left = rect.left;
    } else {                                                                      // above
      top = rect.top - GAP - h; left = rect.left;
    }
    if (step.target === "audit") left = rect.right - width;                       // right-aligned under the top bar link
    setPos({ top: Math.max(16, Math.min(top, vh - h - 16)), left: Math.max(16, Math.min(left, vw - width - 16)) });
  }, [rect, i, step.target]);

  useEffect(() => nextBtn.current?.focus(), [i]);

  const next = () => (last ? onClose() : setI((x) => x + 1));
  const back = () => setI((x) => Math.max(0, x - 1));

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-text"
      onKeyDown={(e) => {
        if (e.key === "Escape") { e.preventDefault(); onClose(); }
        else if (e.key === "ArrowRight") { e.preventDefault(); next(); }
        else if (e.key === "ArrowLeft") { e.preventDefault(); back(); }
        else if (e.key === "Tab") {                                                // keep focus in the popover
          const f = pop.current?.querySelectorAll<HTMLElement>("button");
          if (!f?.length) return;
          const first = f[0], end = f[f.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); end.focus(); }
          else if (!e.shiftKey && document.activeElement === end) { e.preventDefault(); first.focus(); }
        }
      }}>
      {rect ? (
        <div className="tour-spot" aria-hidden style={{
          top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
        }} />
      ) : <div className="tour-dim" aria-hidden />}
      <div ref={pop} className="tour-pop" style={{ top: pos.top, left: pos.left, width: Math.min(W, window.innerWidth - 32) }}>
        <p className="tour-count">{i + 1} of {TOUR_STEPS.length}</p>
        <h2 id="tour-title">{step.title}</h2>
        <p id="tour-text">{step.text}</p>
        <div className="tour-actions">
          <button className="link" onClick={onClose}>Skip</button>
          <span className="tour-dots" aria-hidden>{TOUR_STEPS.map((_, k) => <span key={k} className={k === i ? "on" : ""} />)}</span>
          {i > 0 && <button className="btn" onClick={back}>Back</button>}
          <button ref={nextBtn} className="btn primary" onClick={next}>{last ? "Done" : "Next"}</button>
        </div>
      </div>
    </div>
  );
}
