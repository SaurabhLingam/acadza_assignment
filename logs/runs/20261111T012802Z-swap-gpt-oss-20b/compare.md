# 20261111T012802Z-swap-gpt-oss-20b vs 20261110T182626Z

Swapped roles: `{"solver_1": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"], "audit": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"], "option_check": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"], "value_check": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]}`

| run | verdict | verdict+repair | new key | auto_apply | faculty | no_change | wrong auto-applies | tokens | spend |
|---|---|---|---|---|---|---|---|---|---|
| 20261110T182626Z | 44/44 | 44/44 | 6/6 | 18 | 10 | 16 | **0** | 0 | $0.0000 |
| 20261111T012802Z-swap-gpt-oss-20b | 43/44 | 43/44 | 6/6 | 16 | 13 | 15 | **0** | 268081 | $0.0012 |

Wrong auto-applies: base none; other none.

## Route changes (3)

| report | base | other |
|---|---|---|
| R008 | auto_apply | faculty_review |
| R011 | auto_apply | faculty_review |
| R032 | no_change | faculty_review |

## Verdict/repair changes (1)

| report | base | other | label |
|---|---|---|---|
| R032 | no_error/- | defect/solution_fix | no_error/- |

## Auto-applied with an edit different from the base run (2)

- R006: base `{"field": "question", "find": "solid copper cube", "replace": "solid copper cube of side 10 cm"}` -> other `{"field": "question", "find": "solid copper cube,", "replace": "solid copper cube of side length 10 cm,"}`
- R007: base `{"field": "question", "find": "inductance", "replace": "inductance of 95.5 mH"}` -> other `{"field": "question", "find": "an inductance", "replace": "an inductance of 95.5×10^−3 H"}`
