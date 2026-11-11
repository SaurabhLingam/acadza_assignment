/* Browser-side edit guards and diff marking. Ports of engine/edits.py (guard) and
   console/scripts/build_data.py (mark), so an edit made in the console is held to the same rules. */
import type { Draft, Edit, Item, Question } from "./types";

export function visible(html: string): string {
  const t = document.createElement("textarea");
  t.innerHTML = html.replace(/<[^>]*>/g, "");
  return t.value;
}

export function escapeText(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function count(hay: string, needle: string): number {
  if (!needle) return 0;
  let n = 0;
  for (let i = hay.indexOf(needle); i >= 0; i = hay.indexOf(needle, i + needle.length)) n++;
  return n;
}

const MATH_TAG = /<\/?m(?:row|i|n|o|frac|sup|sub|sqrt|text|style|ath)\b/;
const LITERAL: [string, string][] = [["^", "a caret"], ["\\", "a backslash (LaTeX)"], ["_{", "“_{” (LaTeX)"]];

export function fieldRaw(q: Question, field: string): string {
  return field === "solution" ? q.solutionHtml : q.questionHtml;
}

/** First failed guard as one line, or null if the edit may be saved. */
export function guard(edit: Edit, repair: string | null, q: Question, repairFields: Record<string, string[]>): string | null {
  const allowed = repairFields[repair ?? ""] ?? [];
  if (!allowed.includes(edit.field)) return `A ${repair} repair may not change the ${edit.field}.`;
  if (edit.field === "question" || edit.field === "solution") {
    const raw = fieldRaw(q, edit.field);
    const find = String(edit.find ?? "");
    const rep = edit.replace;
    if (typeof rep !== "string") return "The replacement must be text.";
    const n = count(raw, find);
    if (n !== 1) return n === 0 ? "The text to replace is not in the stored record." : `The text to replace occurs ${n} times; it must be unique.`;
    if (rep === find) return "The replacement is the same as the original.";
    const vf = visible(find), vr = visible(rep);
    for (const [seq, what] of LITERAL) {
      if (count(vr, seq) > count(vf, seq)) return `The new text contains ${what}, which would show literally. Write it as a student reads it (e.g. 95.5 mH).`;
    }
    if (MATH_TAG.test(find) && !MATH_TAG.test(rep)) return "This would replace formatted maths with plain text.";
    if (repair === "spelling") {
      const strip = (s: string) => s.replace(/[A-Za-z\s]/g, "");
      if (strip(vf) !== strip(vr)) return "A spelling fix may not change digits or symbols.";
    }
    if (repair === "answer_form" && !(rep.includes(find) && rep.length > find.length))
      return "A unit/answer-form fix may only add text; the original must stay.";
    if (repair === "option_repair" && edit.field === "question" && q.optionStart != null && raw.indexOf(find) < q.optionStart)
      return "An option fix may not change the question stem.";
    return null;
  }
  if (edit.field === "answer") {
    const rep = edit.replace;
    if (q.type === "integerQuestion") return /^[+-]?\d+(\.\d+)?$/.test(String(rep)) ? sameAnswer(edit) : "An integer key must be a number.";
    if (q.type === "scq") return typeof rep === "string" && q.letters.includes(rep) ? sameAnswer(edit) : `Pick one of ${q.letters.join(", ")}.`;
    if (q.type === "mcq")
      return Array.isArray(rep) && rep.length > 0 && rep.every((x) => q.letters.includes(String(x))) ? sameAnswer(edit) : `Use letters from ${q.letters.join(", ")}, comma-separated.`;
  }
  return null;
}

function sameAnswer(e: Edit): string | null {
  return JSON.stringify(e.find) === JSON.stringify(e.replace) ? "The new key is the same as the stored key." : null;
}

/** The edit a draft describes. */
export function draftEdit(item: Item, q: Question, d: Draft): Edit | null {
  const e = item.edit;
  if (!e) return null;
  if (e.field === "answer") {
    const parts = d.answer.split(/[,\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
    const replace = q.type === "mcq" ? parts : q.type === "integerQuestion" ? d.answer.trim() : parts[0] ?? "";
    return { field: "answer", find: e.find, replace };
  }
  if (e.field === "question" || e.field === "solution")
    return { field: e.field, find: e.find, replace: d.plain ? escapeText(d.replace) : d.replace };
  return e;
}

export function startDraft(item: Item): Draft {
  const e = item.edit;
  const replies: Record<string, string> = {};
  for (const r of item.reports) if (r.inThisCase) replies[r.reportId] = r.reply;
  let replace = "", plain = true, answer = "";
  if (e && (e.field === "question" || e.field === "solution")) {
    const rep = String(e.replace ?? "");
    plain = !/<[^>]+>/.test(rep);
    replace = plain ? visible(rep) : rep;
  } else if (e && e.field === "answer") {
    answer = Array.isArray(e.replace) ? (e.replace as unknown[]).join(", ") : String(e.replace ?? "");
  }
  return { replace, plain, answer, replies };
}

// ---------------------------------------------------------------- marking (port of build_data.mark)

function inMath(raw: string, i: number): [number, number] | null {
  const s = raw.lastIndexOf("<math", i);
  if (s < 0 || raw.lastIndexOf("</math>", i) > s) return null;
  const e = raw.indexOf("</math>", i);
  return e >= 0 ? [s, e + 7] : null;
}

function wholeElements(seg: string): boolean {
  seg = seg.trim();
  if (!seg.startsWith("<") || !seg.endsWith(">") || seg.startsWith("</")) return false;
  let depth = 0;
  for (const m of seg.matchAll(/<(\/?)([a-zA-Z][\w:-]*)[^>]*?(\/?)>/g)) {
    if (m[3]) continue;
    depth += m[1] ? -1 : 1;
    if (depth < 0) return false;
  }
  return depth === 0;
}

function mark(raw: string, i: number, n: number, seg: string, cls: "ins" | "del"): string {
  const out = raw.slice(0, i) + seg + raw.slice(i + n);
  const m = inMath(out, i);
  if (m && wholeElements(seg)) return out.slice(0, i) + `<mrow class="${cls}">` + seg + "</mrow>" + out.slice(i + seg.length);
  if (m) return out.slice(0, m[0]) + `<span class="${cls} whole-math">` + out.slice(m[0], m[1]) + "</span>" + out.slice(m[1]);
  const tag = cls === "del" ? "s" : "u";
  if (!seg.trim()) return out.slice(0, i) + `<${tag} class="${cls} caret"></${tag}>` + out.slice(i);
  return out.slice(0, i) + `<${tag} class="${cls}">` + seg + `</${tag}>` + out.slice(i + seg.length);
}

export function diffHtml(q: Question, e: Edit): { before: string; after: string } | null {
  if (e.field !== "question" && e.field !== "solution") return null;
  const raw = fieldRaw(q, e.field);
  const find = String(e.find ?? "");
  const i = raw.indexOf(find);
  if (i < 0) return null;
  return { before: mark(raw, i, find.length, find, "del"), after: mark(raw, i, find.length, String(e.replace ?? ""), "ins") };
}
