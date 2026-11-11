import type { Bonus, Case, Data, Group, TabKey, Tone } from "./types";

export const TABS: { key: TabKey; label: string; hint: string }[] = [
  { key: "needs", label: "Needs you", hint: "Routed to faculty: approve, edit or reject" },
  { key: "auto", label: "Auto-applied", hint: "Already live; undo if wrong" },
  { key: "nochange", label: "No change", hint: "Spot-check: nothing was changed" },
  { key: "bonus", label: "Bonus", hint: "Bonus findings: defects no student reported" },
];

const ROUTE_TAB: Record<string, TabKey> = { faculty_review: "needs", auto_apply: "auto", no_change: "nochange" };

// Certainty: agreeing evidence first (quick wins), then mixed, then contested.
const TONE_RANK: Record<Tone, number> = { ok: 0, neutral: 1, warn: 1, bad: 2 };

/** Urgency = harm, then reach (distinct reporters), then certainty. Harm always dominates:
 *  a cosmetic fix reported by five students still sits below a wrong key reported by one. */
export function byUrgency(a: Group, b: Group): number {
  return (
    b.harm - a.harm ||
    b.reach - a.reach ||
    TONE_RANK[a.tone] - TONE_RANK[b.tone] ||
    b.confidence - a.confidence ||
    a.questionId.localeCompare(b.questionId)
  );
}

function caseRank(a: Case, b: Case) {
  return b.harm - a.harm || TONE_RANK[a.certaintyTone] - TONE_RANK[b.certaintyTone] || a.reportId.localeCompare(b.reportId);
}

function bonusTone(b: Bonus): Tone {
  if (b.source === "manual_review" || b.strength === "definite") return "ok";
  return "warn";
}

export function bonusWhy(b: Bonus): string {
  const src = b.source === "manual_review" ? `manual review (${b.found_by})` : `${b.strength} code check`;
  return `${b.harmLabel} · ${src} · ${b.could_auto_apply ? "could auto-apply" : "needs approval"}`;
}

export function buildGroups(data: Data): Record<TabKey, Group[]> {
  const out: Record<TabKey, Group[]> = { needs: [], auto: [], nochange: [], bonus: [] };
  const byKey = new Map<string, Case[]>();
  for (const c of data.cases) {
    const tab = ROUTE_TAB[c.route];
    const k = `${tab}:${c.questionId}`;
    if (!byKey.has(k)) byKey.set(k, []);
    byKey.get(k)!.push(c);
  }
  for (const [k, cs] of byKey) {
    cs.sort(caseRank);
    const top = cs[0];
    const tab = k.split(":")[0] as TabKey;
    out[tab].push({
      key: k, tab, questionId: top.questionId, cases: cs, bonus: [],
      harm: top.harm, reach: top.reach, tone: top.certaintyTone, confidence: top.confidence,
      headline: top.headline, why: top.why,
    });
  }
  const bq = new Map<string, Bonus[]>();
  for (const b of data.bonus) {
    if (!bq.has(b.questionId)) bq.set(b.questionId, []);
    bq.get(b.questionId)!.push(b);
  }
  for (const [qid, bs] of bq) {
    bs.sort((a, b) => b.harm - a.harm || TONE_RANK[bonusTone(a)] - TONE_RANK[bonusTone(b)]);
    const top = bs[0];
    out.bonus.push({
      key: `bonus:${qid}`, tab: "bonus", questionId: qid, cases: [], bonus: bs,
      harm: top.harm, reach: 0, tone: bonusTone(top), confidence: 0,
      headline: top.headline + (bs.length > 1 ? `  +${bs.length - 1} more` : ""),
      why: bonusWhy(top),
    });
  }
  for (const t of Object.keys(out) as TabKey[]) out[t].sort(byUrgency);
  return out;
}

export function casesOnQuestion(data: Data, qid: string): Case[] {
  return data.cases.filter((c) => c.questionId === qid).sort((a, b) => a.reportedAt.localeCompare(b.reportedAt));
}

export const HARM_CLASS = ["harm-0", "harm-1", "harm-2", "harm-3"];

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function prettyField(f: string): string {
  return { question: "Question", solution: "Solution", answer: "Answer key", questionType: "Question type", chapter: "Chapter" }[f] ?? f;
}
