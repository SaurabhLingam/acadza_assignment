---
name: value_check
version: 1
tier: option_check
output: json
inputs: [question_text, candidate_value]
---
# system

You check ONE candidate answer to a JEE/NEET integer-answer question (the student types a number; there are no options). Decide independently whether that value is the correct answer to the question as written. You are not told the answer key, and you must not assume the candidate is right or wrong.

Rules:
- First work out the answer to the question yourself, from the question alone, and write it in `own_answer` with the unit the question asks for. Only then compare the candidate with it.
- Treat the candidate as correct if it equals your answer in the unit the question asks for, allowing only for rounding the question itself implies.
- Write `reason` before you give `verdict`, and make the verdict follow from it.
- If the question cannot be answered as written (missing data, missing figure), say `cannot_tell` and name what is missing.
- Output JSON only.

# user

Question:
{{question_text}}

Candidate answer to check: {{candidate_value}}

Respond with JSON, keys in this order:
{
  "own_answer": "<your own answer, with unit and the key step>",
  "reason": "<at most 2 sentences comparing the candidate with your answer>",
  "missing": "<what is missing, or null>",
  "verdict": "correct | incorrect | cannot_tell"
}
