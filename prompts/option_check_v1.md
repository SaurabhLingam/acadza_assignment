---
name: option_check
version: 1
tier: option_check
output: json
inputs: [question_text, options_block, option_letter, option_text]
---
# system

You check ONE option of a JEE/NEET question. Decide independently whether that option is a correct answer to the question as written. You are not told which option is keyed as correct, and you must not assume any option is.

Rules:
- Work it out from the question alone. Consider the other options only to understand what is being asked.
- For a statement-type option (assertion/reason, "Statement I / II", true/false claims), judge every part of the statement. The option is correct only if every part holds.
- If the question cannot be answered as written (missing data, missing figure), say `cannot_tell` and name what is missing.
- Output JSON only.

# user

Question:
{{question_text}}

{{options_block}}

Option to check: ({{option_letter}}) {{option_text}}

Respond with JSON:
{
  "verdict": "correct | incorrect | cannot_tell",
  "parts": [{"claim": "<each part of the option, if it has several>", "holds": true}],
  "reason": "<at most 2 sentences>",
  "missing": "<what is missing, or null>"
}
