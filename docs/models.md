# Models: who does what, and why

Interview Coach uses three kinds of model. Each does the work it is best at, and every call goes
through one gateway (`app/llm/gateway.py`) that adds retries, timeouts, budget caps, content-free
logging and the privacy check. Which provider handles which **role** is configuration
(`config/models.yaml`), not code.

| Kind | Default | Runs | Why this one |
|---|---|---|---|
| Local LLM | **Qwen 3.6 35B-A3B** via [Ollama](https://ollama.com) | on your own machine | sees raw text (names, contact details) to pseudonymise it, so it must never leave your hardware; also cheap enough to ask every interview question |
| Embeddings | **bge-m3** via Ollama | on your own machine | multilingual (Dutch and English) retrieval of CV evidence per requirement |
| Judge | **Jev 1.13.0** via the [TypeSafe](https://typesafe.ai) API | external | typed yes/no, choice and score answers **with a probability**, fast (~0.3 s) and cheap (~€0.002 per run) |
| Writer | **Claude Sonnet 5** (and Haiku 4.5) via the [Anthropic](https://docs.anthropic.com) API | external | the long, careful texts: interview plan, briefing, feedback with sources, practice plan, and a second opinion when Jev is unsure |

External models only ever receive **pseudonymised** text; see [privacy.md](privacy.md) and the
`SafeText` type in [architecture.md](architecture.md).

## Roles

| Role | Default | Handles raw text? | What it does |
|---|---|---|---|
| `pseudonymise` | Qwen (Ollama) | **yes**, `local_only: true` | finds names, contact details and other personal data and replaces them with labels like `[PERSON_1]` |
| `extract` | Qwen | no | pulls requirements ("eisen" / "wensen") out of the vacancy |
| `embed` | bge-m3 | no | embeddings for matching CV fragments to requirements |
| `interviewer` | Qwen | no | writes the next interview question |
| `judge` | Jev | no | all typed judgments (next section) |
| `plan`, `briefing`, `feedback` | Claude Sonnet 5 | no | interview plan, briefing, feedback per answer and the practice plan |
| `escalation`, `extract_escalation` | Claude Sonnet 5 | no | a second opinion when Jev is unsure, or when extraction fails |
| `interviewer_escalation`, `fallback_fast` | Claude Haiku 4.5 | no | writes the question when the local model's attempts fail the guardrails twice |

`local_only` roles are checked when the config loads: pointing `pseudonymise` at an external
provider is refused. When the local model is offline, **new runs are blocked**; there is no
external fallback for raw text. Finished runs stay available.

## Why Jev, and where it is used

Most decisions in an interview coach are small, typed questions: *does this answer name a
result?*, *is this question grounded in the CV?*, *should the interviewer probe deeper?* A
general LLM answers those as free text you have to parse, without a calibrated confidence. Jev
answers them as **typed values with a probability**, in about 0.3 seconds, for a fraction of a
cent. That gives three things the app relies on:

1. **Every badge is traceable.** Each judgment is stored with provider, question version,
   confidence, and whether it was uncertain or escalated. The review shows uncertain scores with
   a dashed border and marks double-checked ones with "Claude".
2. **A confidence cascade.** Answers below a confidence threshold (or, for yes/no questions,
   inside an uncertainty band) are escalated to Claude with the same typed shape. Only the
   unsure 7–11 % of judgments go to the expensive model.
3. **Fast guardrails.** Every generated interview question is checked before the candidate sees
   it, without making the conversation feel slow.

The questions are data, versioned in `app/judgments/catalog.py`; thresholds live in
`config/thresholds.yaml` (starting values, to be tuned with the evaluation set in `eval/`).

| Stage | Jev question | Type | What happens with the answer |
|---|---|---|---|
| Upload | `doc_type` | choice | warns when the "CV" looks like a vacancy (or the other way round) |
| Upload | `doc_injection` | yes/no | flags text aimed at AI systems; it is then treated strictly as data |
| Preparation | `evidence_for_req` | yes/no | how strongly each CV fragment supports each requirement (strong / partial / none) |
| Every question | `q_grounded`, `q_appropriate`, `q_on_topic` | yes/no | the question is only shown if all three pass (`q_appropriate`: no questions about protected characteristics). Fail → regenerate with the reason → Claude Haiku → a safe fallback question |
| Every answer | `next_move` | choice | probe deeper, challenge, clarify or next topic; code then enforces follow-up and time limits |
| Every answer | `a_quality` | score 0–3 | the quality score per answer |
| Every answer | `a_star_s`, `a_star_t`, `a_star_a`, `a_star_r` | yes/no | STAR elements (situation, task, action, result) |
| Every answer | `a_specific`, `a_quantified` | yes/no | concrete example? numbers in the result? |
| Every answer | `a_req` (per linked requirement) | yes/no | does the answer give evidence for this requirement? (the coverage table) |
| Every answer | `a_cv_consistency`, `a_overclaim` | choice, yes/no | consistent with the CV, not in it, or contradicting; claiming more than the CV supports |
| Every answer | `a_hedging` | score | how confidently the answer is phrased |
| Feedback | `fb_grounded` | yes/no | each feedback item may only refer to the cited CV fragments or answers; unsupported items are dropped |
| Next run | `f_relevant`, `f_mastery` | yes/no, choice | which weak points from the previous report matter for the new vacancy, and whether they improved |

Counting, dates and arithmetic (time budget, statistics, topic limits) are done in code, never by
a model.

**Jev is required.** Only the TypeSafe provider implements the `judge()` operation; Ollama and
Anthropic refuse it. Replacing Jev means writing a provider that implements `judge()` (typed
answers with a confidence) in `app/llm/`.

## Running without Claude (fully local writing)

Every generating role can point at Ollama, which supports JSON-schema output. For example, in
`config/models.yaml`:

```yaml
  plan:
    provider: ollama
    model: qwen3.6:35b-a3b
    timeout_s: 300
    options: {think: false, temperature: 0.3}
```

Do the same for `briefing`, `feedback`, `escalation`, `extract_escalation`,
`interviewer_escalation` and `fallback_fast`, and remove `ANTHROPIC_API_KEY` from the setup.
Only Jev then leaves your machine.

**Status: supported by configuration, not yet tested end to end.** Expect slower preparation on
the local machine and weaker plans and feedback than with Claude; the grounding checks still
apply. Try it with the evaluation set before relying on it.

## Hardware for the local model

| | |
|---|---|
| Qwen 3.6 35B-A3B (q4_K_M) | ~23 GB download; runs well on Apple Silicon with 32 GB unified memory or a GPU with 24 GB+ |
| bge-m3 | 1.2 GB |
| Smaller machines | `qwen3.8:27b` (17 GB) or a smaller Qwen; compare with `make bench` first |
| Alternative runtime | [oMLX](https://github.com/jundot/omlx) (MLX, macOS) through the `omlx` provider |

Measured on the reference setup (Apple M1 Max, 32 GB): an interview question takes 4–6.5 s
(p50), requirement extraction ~21 s, pseudonymising a document or answer 2–3.5 s (p50).

## Costs (measured)

Three 15-minute demo runs (fictional candidate, 5–7 answers each):

| | per run |
|---|---|
| Total | **€0.13–0.20** |
| Claude (plan, briefing, feedback, escalations) | €0.13–0.20 (99 % of the cost) |
| Jev (32–40 calls, 175–230 judgments) | €0.001–0.002 |
| Local model | €0 (your electricity) |
| Judgments escalated to Claude | 7–11 % |

Budget caps (per run and per day, in EUR) are set in `config/models.yaml` under `budgets`;
the gateway refuses calls beyond them. Prices per model are also listed there (update them from
the providers' pricing pages).
