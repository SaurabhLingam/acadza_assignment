# console/

Faculty review console: a static React + Vite + TypeScript site. It reads one precomputed file,
`public/data.json`. No backend, no LLM calls, no API keys (see `CLAUDE.md`, D-006).

## Run locally (PowerShell)

```powershell
cd console
npm install            # once
npm run data           # bake ../data, ../results.json, the run's evidence and ../bonus_findings.json -> public/data.json
npm run dev            # http://localhost:5173
```

`npm run build` type-checks and writes the static site to `dist/`; `npm run preview` serves that build.

## Data build (`scripts/build_data.py`)

Run from the repo root (`npm run data` does this). It uses the engine's parser (option text, clean text) and
reads `results.json`, the `details.jsonl` of the run that produced it (located via `logs/run-summary.json`,
and refused if the two `results.json` files differ), and `bonus_findings.json`. For each case it precomputes:

- the before/after HTML with each edit applied and the change marked (`<s>`/`<u>` in HTML; inside MathML an
  `<mrow>` around the changed elements, or the whole `<math>` when the span is not whole elements);
- headline, evidence chips (✓ supports the decision, ✗ against it or the defect, · no answer), harm, reach
  (distinct reporting students on the question) and certainty, and the "why it's here" line.

It never reads `docs/eval-labels.csv`. `public/data.json` is committed so the Vercel build does not need Python.

## Queue order

Harm, then reach, then certainty (agreeing evidence first: quick wins). Harm dominates: a cosmetic fix
reported by five students stays below a wrong key reported by one.

- Harm 3, blocks the right answer: answer_key, stem_data, unsound, type_mismatch, diagram, wrong_question,
  a blank or missing *keyed* option.
- Harm 2: solution_fix, solution_missing, identical_options, a missing distractor.
- Harm 1, cosmetic: spelling, noise, exam_reference, markup_leak, answer_form, notation, wrong_chapter, syllabus.

## Safety

Question HTML is sanitised with DOMPurify (HTML + MathML profiles; scripts, event handlers, forms, iframes
and inline styles removed). Student comments and replies are rendered as text, never as HTML.

## Deploy (Vercel)

Project root directory: `console`. Framework preset: Vite (build `npm run build`, output `dist`).

## Stages

1. (done) Data build, layout with real data, queue, case view with rendered questions, J/K navigation,
   deep links (`#<tab>/<questionId>`), light/dark.
2. Actions: approve / edit (guards re-run) / reject with reasons, undo toast, editable replies, audit log in
   localStorage with JSON export.
