---
name: prompt_guard
version: 1
tier: guard
output: text
inputs: [comment]
model_note: >
  Sent to Groq's meta-llama/llama-prompt-guard-2-86m, a classifier, not a chat model.
  It gets the student comment verbatim as the only user message, with no instructions,
  because any added text would change what it scores. The reply is expected to be a
  score or a label; engine/tiers.py parses either and logs the raw reply.
---
# user

{{comment}}
