# Run 20261110T172651Z vs labels

Labels: 44 rows (user_verified=44).

- verdict correct: **12/12**
- verdict and repair correct: **12/12**
- new key correct (answer_key labels): **4/4**

| report | result | label | verdict | verdict+repair | new key | route |
|---|---|---|---|---|---|---|
| R001 | defect/answer_key | defect/answer_key | ok | ok | ok (A vs A) | auto_apply |
| R004 | defect/answer_key | defect/answer_key | ok | ok | ok (D vs D) | auto_apply |
| R005 | defect/answer_key | defect/answer_key | ok | ok | ok (1 vs 1) | auto_apply |
| R007 | defect/stem_data | defect/stem_data | ok | ok |  | auto_apply |
| R011 | defect/option_repair | defect/option_repair | ok | ok |  | auto_apply |
| R016 | defect/solution_fix | defect/solution_fix | ok | ok |  | auto_apply |
| R020 | defect/answer_key | defect/answer_key | ok | ok | ok (A,B,D vs A,B,D) | auto_apply |
| R021 | defect/type_mismatch | defect/type_mismatch | ok | ok |  | auto_apply |
| R027 | no_error/- | no_error/- | ok | ok |  | no_change |
| R029 | no_error/- | no_error/- | ok | ok |  | no_change |
| R034 | defect/unsound | defect/unsound | ok | ok |  | faculty_review |
| R039 | language_mode/- | language_mode/- | ok | ok |  | no_change |
