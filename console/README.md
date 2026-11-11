# console/

Faculty review console: a static React + Vite + TypeScript site. It reads one precomputed file,
`public/data.json`. No backend, no LLM calls, no API keys (see `CLAUDE.md`, D-006).

## Run locally (PowerShell)

```powershell
cd console
npm install            # once
npm run data           # optional: rebuild public/data.json from the engine outputs (needs Python; data.json is committed)
npm run dev            # http://localhost:5173
```

`npm run build` type-checks and writes the static site to `dist/`; `npm run preview` serves that build.

## Design

One case at a time. Every case answers, top to bottom: **What's wrong?** (one sentence) · **How sure?** (one line,
with the evidence grid behind "Show evidence") · **What changes?** (rendered before/after, the answer change with
KEY / NEW tags in the question, an AI suggestion that was not applied, or "Nothing changes"). Stored solution,
student reports and details are collapsed below. Actions sit in the same place in the bottom bar:

| Item | Actions |
|---|---|
| An edit waiting to go live (bonus findings with an edit) | Approve **A** · Edit **E** · Reject **R** |
| Faculty-only repair, no edit | Confirm defect **A** · Not a defect **R** |
| Already auto-applied | Keep **A** · Edit **E** · Undo **U** |
| Nothing changed | Looks right **A** · Flag **R** |

Reject / Not a defect / Flag / Undo ask for a reason (chips 1–4 plus a note). Edit re-runs the edit guards in
the browser (`src/edit.ts`, a port of `engine/edits.py`): allowed fields, the text to replace must be unique,
no literal `^` `\` `_{`, spelling fixes can't change digits or symbols, unit fixes are additive only, formatted
maths can't become plain text. Every action shows an undo toast for 5 s (Z) and moves to the next case.
J / K move, `\` hides the queue, `?` lists the keys. Deep links: `#<list>/<question id prefix>`.

Queue order (D-026): harm, then reach (distinct reporters), then certainty.

Colour: monochrome. Primary buttons are near-white on dark / near-black on light; links and focus rings are one
calm blue. Red and green appear only in diffs (including the OLD KEY / NEW tags, where the old option's value is
struck through) and ✓/✗ marks. Headlines are kept to about 110 characters and use non-breaking spaces inside
values ("a = 20 cm", "C (130 V)"), so a line never breaks mid-value.

A seven-step guided tour (`src/components/Tour.tsx`, no library) opens on the first visit, on the first case of
"Needs you": queue, list tabs, headline, how sure, what changes, action bar, audit log. It is remembered in localStorage
(`rr.tourSeen`), skippable (Esc), keyboard-driven (→ / Enter next, ← back, focus kept in the popover) and can be
reopened from the **Tour** button or the `?` screen. A first visit through a deep link skips it, so a shared
link opens straight on its case.

## Data build (`scripts/build_data.py`)

Run from the repo root (`npm run data`). It uses the engine's parser and reads `results.json`, the
`details.jsonl` of the run that produced it (refused if the two `results.json` differ), and
`bonus_findings.json`. It never reads `docs/eval-labels.csv`. Per queue item (one per question per route, and
one per bonus finding) it precomputes the sentence, the "how sure" line, the evidence grid, before/after HTML
with each edit applied and marked, KEY/NEW tags, flagged solution spans and the reports with their replies.
The "how sure" line is generated from the same grid the reviewer can open, so it cannot claim more than the
grid shows.

## Audit log and storage

The reviewer's name is asked once. Decisions and the audit log (time, reviewer, question id, report ids,
action, before/after, reason, note) are stored in this browser's localStorage and can be exported as JSON from
the drawer. The UI says so. Nothing is sent anywhere.

## Safety

Question HTML is sanitised with DOMPurify (HTML + MathML; scripts, event handlers, forms, frames and inline
styles removed). Student comments and replies are rendered as plain text.

## Deploy (Vercel)

Root directory `console`, framework preset Vite (build `npm run build`, output `dist`). See the steps in the
project notes or below:

1. vercel.com → Add New… → Project → import the GitHub repo.
2. Root Directory: `console`. Framework Preset: Vite (auto-detected). Build command `npm run build`,
   output `dist`, install `npm install`. No environment variables.
3. Deploy.
