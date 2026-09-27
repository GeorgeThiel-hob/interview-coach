# Evaluation set (spec 10.2)

`make eval` runs every Jev question from `app/judgments/catalog.py` against hand-labelled
examples, reports accuracy and confidence calibration per question, and recommends the
thresholds for `config/thresholds.yaml`. Results are written to `eval/results/`.

**Owner task:** the files in `set/` are a handful of synthetic examples that show the format.
Write the real set yourself (target: ~30 answers of known quality to your target vacancy
questions, ~10 inappropriate or ungrounded interviewer questions, ~10 documents with injection
attempts, plus clean counterparts). Use invented people and data only: the set is committed
to git and sent to Jev.

## Format (one JSON object per line, in `set/*.jsonl`)

```json
{"id": "ans-01", "kind": "answer", "question": "...", "answer": "...", "topic": "...",
 "requirements": ["eis_1: ..."], "cv": "...",
 "labels": {"a_quality": 2, "a_star_s": true, "a_star_r": false, "a_cv_consistency": "consistent"}}
{"id": "q-01", "kind": "question", "vacancy": "...", "cv": "...", "conversation": "...",
 "topic": "...", "question": "...", "labels": {"q_appropriate": false, "q_grounded": true}}
{"id": "doc-01", "kind": "document", "text": "...", "labels": {"doc_type": "cv", "doc_injection": true}}
```

Only the labels you give are scored. Noul labels are `true`/`false`, choice labels are the
option name, score labels are the level number (0 = first level in the catalog).

## Commands

```bash
make eval                               # full set, real Jev (needs TYPESAFE_API_KEY)
uv run python scripts/run_eval.py --subset 10   # what CI runs
```
