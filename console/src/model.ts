import type { ActionId, Decision, Item, ListKey, Mode } from "./types";

export const LISTS: Record<ListKey, string> = {
  needs: "Needs you",
  done: "Done",
  auto: "Auto-applied",
  nochange: "No change",
  bonus: "Bonus findings",
};

const CERT = { strong: 0, partial: 1, weak: 2 } as const;

/** D-026: harm first, then reach (distinct reporters), then certainty (agreeing evidence first). */
export function byUrgency(a: Item, b: Item): number {
  return b.tier - a.tier || b.reach - a.reach || CERT[a.certainty] - CERT[b.certainty] ||
    b.confidence - a.confidence || a.key.localeCompare(b.key);
}

export function listOf(items: Item[], key: ListKey, decisions: Record<string, Decision>): Item[] {
  const sorted = [...items].sort(byUrgency);
  switch (key) {
    case "needs": return sorted.filter((i) => i.route === "faculty_review" && !decisions[i.key]);
    case "done": return items.filter((i) => decisions[i.key]).sort((a, b) => decisions[b.key].at.localeCompare(decisions[a.key].at));
    case "auto": return sorted.filter((i) => i.route === "auto_apply");
    case "nochange": return sorted.filter((i) => i.route === "no_change");
    case "bonus": return sorted.filter((i) => i.route === "bonus");
  }
}

export function modeOf(i: Item): Mode {
  if (i.route === "auto_apply") return "auto";
  if (i.route === "no_change") return "check";
  return i.edit ? "live" : "faculty";
}

export interface ActionDef { id: ActionId; key: string; label: string; kind: "primary" | "plain" | "danger"; needsReason?: boolean; edit?: boolean }

export const ACTIONS: Record<Mode, ActionDef[]> = {
  live: [
    { id: "approve", key: "A", label: "Approve", kind: "primary" },
    { id: "approve_edited", key: "E", label: "Edit", kind: "plain", edit: true },
    { id: "reject", key: "R", label: "Reject", kind: "danger", needsReason: true },
  ],
  faculty: [
    { id: "confirm", key: "A", label: "Confirm defect", kind: "primary" },
    { id: "not_defect", key: "R", label: "Not a defect", kind: "danger", needsReason: true },
  ],
  auto: [
    { id: "keep", key: "A", label: "Keep", kind: "primary" },
    { id: "keep_edited", key: "E", label: "Edit", kind: "plain", edit: true },
    { id: "undo_edit", key: "U", label: "Undo", kind: "danger", needsReason: true },
  ],
  check: [
    { id: "looks_right", key: "A", label: "Looks right", kind: "primary" },
    { id: "flag", key: "R", label: "Flag", kind: "danger", needsReason: true },
  ],
};

export const PAST: Record<ActionId, string> = {
  approve: "Approved", approve_edited: "Approved with edits", reject: "Rejected",
  confirm: "Confirmed as a defect", not_defect: "Marked not a defect",
  keep: "Kept", keep_edited: "Kept with edits", undo_edit: "Undone",
  looks_right: "Marked as right", flag: "Flagged",
};

export const REASONS = ["AI is wrong", "Needs a rewrite", "Not a defect", "Other"];

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// ---------------------------------------------------------------- browser storage (per-viewer, may be unavailable)

export const KEYS = { decisions: "rr.decisions.v1", audit: "rr.audit.v1", reviewer: "rr.reviewer", theme: "rr.theme", queue: "rr.queue", tour: "rr.tourSeen" };

export function load<T>(k: string, fallback: T): T {
  try {
    const v = localStorage.getItem(k);
    return v == null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

export function save(k: string, v: unknown): void {
  try {
    localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* private window or storage blocked: the session still works, it just isn't remembered */
  }
}
