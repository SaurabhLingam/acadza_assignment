export type Route = "auto_apply" | "faculty_review" | "no_change" | "bonus";
export type ListKey = "needs" | "done" | "auto" | "nochange" | "bonus";
export type Kind = "answer" | "type" | "text" | "faculty" | "nochange" | "platform";
export type Cell = "y" | "n" | "mixed" | "";

export interface Edit {
  field: string;
  find: unknown;
  replace: unknown;
}

export interface Diff {
  field: string;
  before?: string;
  after?: string;
  findText?: string;
  replaceText?: string;
  error?: string;
}

export interface Grid {
  cols: { id: string; label: string; title: string }[];
  rows: { id: string; label: string; text: string; cells: Record<string, Cell>; notes: Record<string, string | number> }[];
}

export interface ReportRow {
  reportId: string;
  studentId: string;
  source: string;
  reportedAt: string;
  comment: string;
  reply: string;
  verdict: string;
  repair: string | null;
  route: string;
  inThisCase: boolean;
}

export interface Item {
  key: string;
  source: "report" | "bonus";
  route: Route;
  questionId: string;
  reportIds: string[];
  tier: number;
  tierLabel: string;
  reach: number;
  confidence: number;
  why: string;
  verdict: string;
  repair: string | null;
  edit: Edit | null;
  rawEvidence: { reportId: string; evidence: string }[];
  routeWhy: string[];
  decidedBy: string;
  reports: ReportRow[];
  kind: Kind;
  title: string;
  sentence: string;
  sure: string;
  grid: Grid | null;
  diff: Diff | null;
  answerChange: { from: string; to: string } | null;
  typeChange: { from: string; to: string } | null;
  suggestion: { text: string; detail: string } | null;
  nothing: string | null;
  questionHtml: string;
  solutionHtml: string | null;
  solutionOpen: boolean;
  certainty: "strong" | "partial" | "weak";
  couldAutoApply?: boolean;
}

export interface Question {
  id: string;
  type: string;
  subject: string;
  chapter: string;
  questionHtml: string;
  solutionHtml: string;
  answerRaw: unknown;
  key: string;
  letters: string[];
  optionStart: number | null;
}

export interface Data {
  meta: { runId: string; generatedAt: string; reports: number; items: number; repairFields: Record<string, string[]> };
  questions: Record<string, Question>;
  items: Item[];
}

/** What a reviewer can do with an item depends on its state. */
export type Mode = "live" | "faculty" | "auto" | "check";
export type ActionId =
  | "approve" | "approve_edited" | "reject"          // an edit waiting to go live
  | "confirm" | "not_defect"                        // faculty-only repair, no edit
  | "keep" | "keep_edited" | "undo_edit"            // already auto-applied
  | "looks_right" | "flag";                         // nothing was changed

export interface Decision {
  action: ActionId;
  at: string;
  reviewer: string;
  reason?: string;
  note?: string;
  edit?: Edit | null;
  replies?: Record<string, string>;
}

export interface AuditEntry {
  id: string;
  time: string;
  reviewer: string;
  questionId: string;
  reportIds: string[];
  item: string;
  action: string;
  before: unknown;
  after: unknown;
  reason?: string;
  note?: string;
}

export interface Draft {
  replace: string;          // raw replacement (HTML) for text edits
  plain: boolean;           // replacement edited as plain text (escaped on save)
  answer: string;           // answer-key edits: "A" or "A, B, D" or a number
  replies: Record<string, string>;
}
