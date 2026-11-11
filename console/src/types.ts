export type Tone = "ok" | "bad" | "warn" | "neutral";
export type Route = "auto_apply" | "faculty_review" | "no_change";
export type TabKey = "needs" | "auto" | "nochange" | "bonus";

export interface Chip {
  tone: Tone;
  label: string;
  title?: string;
}

export interface Edit {
  field: string;
  find: unknown;
  replace: unknown;
}

export interface Diff {
  field: string;
  before?: string;
  after?: string;
  find_text?: string;
  replace_text?: string;
  flagged?: string;
  error?: string;
}

export interface AnswerShow {
  short: string;
  long: string;
}

export interface Case {
  reportId: string;
  questionId: string;
  studentId: string;
  source: string;
  reportedAt: string;
  comment: string;
  verdict: string;
  repair: string | null;
  route: Route;
  confidence: number;
  edit: Edit | null;
  evidence: string;
  reply: string;
  headline: string;
  harm: number;
  harmLabel: string;
  certainty: string;
  certaintyTone: Tone;
  reach: number;
  why: string;
  chips: Chip[];
  diff: Diff | null;
  answerChange: { from: AnswerShow; to: AnswerShow } | null;
  typeChange: { from: string; to: string } | null;
  routeWhy: string[];
  basis: string[];
  notes: string[];
  details: Record<string, unknown>;
}

export interface Bonus {
  id: string;
  questionId: string;
  repair: string;
  check: string;
  strength: string;
  field: string;
  detail: string;
  evidence_text: string;
  evidence_raw: string | null;
  proposed_edit: Edit | null;
  could_auto_apply: boolean;
  why: string;
  source: "code_check" | "manual_review";
  found_by?: string;
  reports_on_question: string[];
  occurrences?: { field: string; text: string; raw: string | null; raw_unique: boolean }[];
  harm: number;
  harmLabel: string;
  headline: string;
  diff: Diff | null;
  flag: Diff | null;
}

export interface Question {
  id: string;
  type: string;
  subject: string;
  chapter: string;
  concept: string;
  questionHtml: string;
  solutionHtml: string;
  answerRaw: unknown;
  answer: AnswerShow;
  stem: string;
}

export interface Data {
  meta: { runId: string; generatedAt: string; reports: number; questions: number; bonus: number; note: string };
  questions: Record<string, Question>;
  cases: Case[];
  bonus: Bonus[];
}

/** One queue row: everything on one question within one tab. */
export interface Group {
  key: string;
  tab: TabKey;
  questionId: string;
  cases: Case[];
  bonus: Bonus[];
  harm: number;
  reach: number;
  tone: Tone;
  confidence: number;
  headline: string;
  why: string;
}
