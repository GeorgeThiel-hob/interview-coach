# Interview Coach — Scope & Technical Design

**Version:** 0.1 (draft, 27-09-2026)
**Owner:** the project owner
**Working name:** Interview Coach (rename freely)

---

## 0. How to use this document (instructions for Claude Code)

- Build **milestone by milestone** (section 13). Do not start a milestone before the previous one meets its acceptance criteria.
- Anything marked **[DECISION]** is open. Ask the owner before implementing it; do not pick silently.
- **Do not invent external API details.** For Jev, follow the official docs (docs.typesafe.ai: Quick start, Primitives, Confidence, Python SDK). For Claude, follow docs.claude.com. For Ollama, follow the Ollama API docs. If something in this document conflicts with the official docs, the docs win; flag the conflict.
- All model IDs, thresholds, and prompts live in config or prompt files, never hard-coded in logic.
- Every model call goes through one gateway module that logs it (section 10). No direct SDK calls elsewhere.

---

## 1. Purpose

A live web app that prepares a person for a job or assignment interview. The user uploads the vacancy and their CV. The app then:

1. Runs a realistic interview based on those documents.
2. Evaluates every answer.
3. Shows a review with classifications, stats, and concrete tips.
4. Produces a report the user saves. That report can be uploaded into a later run so the app drills the weak points from last time.

It combines three kinds of model, each doing what it is best at:

- **Local open-source model (Qwen via Ollama):** private bulk work.
- **Jev (TypeSafe):** fast typed judgments with confidence.
- **Claude:** planning, hard cases, and written feedback.

**Two purposes:**

- **Showcase.** It demonstrates multi-agent design, RAG/grounding, hallucination guardrails, open-source models, model choice, and DevOps. It supports the owner's application for an AI developer role.
- **Internal tool.** Once proven, it can be offered to the people manager and account manager of a consultancy to help consultants prepare for client intakes.

---

## 2. Goals and non-goals

### Goals
- A complete interview run from upload to saved report, in Dutch or English.
- Every evaluation is traceable. The user can see *why* an answer scored as it did.
- Feedback never invents experience the user does not have (section 9.4).
- Personal data is pseudonymised on the server before anything leaves it.
- Speaking practice: the user can answer out loud and get delivery stats.
- Follow-up runs use the previous report to focus on weak points.
- Costs, latency, and escalations are measured from day one.

### Non-goals (for now)
- No video, face, or emotion analysis.
- No real-time voice conversation (turn-based voice only).
- No integrations with ATS, Matching, or any employer system.
- No mobile app (the web app must work on mobile browsers).
- No fine-tuning of models.

---

## 3. Users and roles

| Role | What they do | Milestone |
|---|---|---|
| **Candidate** | Uploads documents, runs interviews, reviews, downloads reports | M2 |
| **Admin** (the owner) | Invites users, sees usage/cost/escalation metrics, never sees content by default | M2 |
| **Coach** (people manager / account manager) | Optional: sees reports a candidate explicitly shares | M7 (later) |

---

## 4. End-to-end user flow

1. **Log in** (invite-only account).
2. **New run → upload**
   - Required: vacancy (PDF, DOCX, or pasted text).
   - Required: CV (PDF or DOCX).
   - Optional: previous report (JSON, or the PDF with embedded JSON).
   - Optional: motivation letter, notes about the client.
3. **Settings**
   - Interview type: *Intake with account manager*, *Client interview*, or *Mixed*.
   - Language: NL or EN.
   - Length: 15, 30, or 45 minutes.
   - Answer mode: typed or spoken.
   - Difficulty: friendly, realistic, or critical.
4. **Preparation (automatic, about 1 minute)**
   - Documents are parsed, pseudonymised, and checked for prompt injection.
   - Eisen, wensen, and key themes are extracted.
   - Relevant CV evidence is matched to each eis.
   - If a previous report was uploaded, a focus list is built from it.
   - Claude writes the interview plan.
   - The user sees a **pre-interview briefing**: what will likely be asked, where the gaps are, and what to prepare.
5. **Interview run**
   - One or two interviewer personas ask questions, one at a time.
   - The user answers by typing or recording.
   - After each answer, Jev evaluates it and decides the interviewer's next move.
   - A progress bar shows topics covered and time.
   - No scores are shown during the interview; showing them would break realism.
6. **Review**
   - Per question: the question, the user's answer, classifications, and why.
   - Per question: what was strong, what to add, and what to explore.
   - Stats dashboard (section 5.6).
   - Speaking stats, if answers were spoken.
7. **Practice**
   - Re-answer any question, either typed or spoken.
   - Speak-aloud drills for the weakest answers.
   - An interview-technique tips library (curated, section 5.7).
8. **Report**
   - Download as a PDF with the JSON embedded, plus a separate JSON file.
   - The report is the user's property; see the retention rules in section 9.
9. **Next run**
   - Upload the report with the same or a new vacancy.
   - The app classifies previous weak points (section 5.9) and drills them.

---

## 5. Features in detail

### 5.1 Upload and ingestion
- Accepted formats: PDF, DOCX, TXT/MD, and pasted text. Max 10 MB per file, max 5 files per run.
- Text extraction uses pypdf / pdfplumber and python-docx. Scanned PDFs are out of scope for v1; show a clear error for them.
- **Document type check (Jev Choice):** vacancy / CV / previous report / other.
  - A mismatch prompts the user; the app never rejects silently.
- **Prompt injection check (Jev Noul):** "contains instructions directed at an AI system".
  - If flagged, the text is still used as data but quoted and fenced in all prompts, and the user sees a warning.
- **Pseudonymisation (local Qwen + regex), before anything leaves the server:**
  - Regex handles emails, phone numbers, postcodes, dates of birth, IBAN, and BSN-like numbers.
  - Qwen handles names of people, home address, and other directly identifying details.
  - These are replaced with stable tokens (`[PERSON_1]`, `[CITY_1]`).
  - The mapping is stored server-side, encrypted, so the review can show real names back to the user.
  - Employer and client names are **kept**, because they matter for the interview. Make this configurable.
- **Chunking for retrieval:**
  - The CV is split per role and per bullet.
  - The vacancy is split per eis, per wens, and per paragraph.
  - Each chunk gets a stable ID (`cv:role2:b3`, `vac:eis4`).

### 5.2 Preparation
- **Extraction (local Qwen, JSON output validated with pydantic):**
  - Eisen (hard requirements), wensen (nice-to-haves), responsibilities, context (organisation, team, domain).
  - Each item includes a source-chunk reference.
  - If validation fails: retry once, then escalate to Claude.
- **Evidence matching:**
  - Embed all chunks with a local embedding model via Ollama (e.g. `nomic-embed-text` or a multilingual equivalent **[DECISION]**).
  - Retrieve the top-k CV chunks per eis.
  - **Jev Noul** per (eis, chunk): "This CV fragment provides evidence for the requirement."
  - Result: an **evidence map** with an evidence strength per eis (strong / partial / none) and the supporting chunk IDs.
- **Focus list (only if a previous report exists):** see section 5.9.
- **Interview plan (Claude):**
  - Input: the pseudonymised extraction, the evidence map, the focus list, and the settings.
  - Output: validated JSON containing:
    - Ordered topics.
    - Per topic: goal, linked eisen/wensen, question type (motivation, behavioural/STAR, technical, gap/challenge, situational, closing "do you have questions for us").
    - Opening question and planned follow-up angles.
    - Which persona asks it.
  - Topic selection rules:
    - Always cover every eis.
    - Cover wensen as time allows.
    - Weight gaps (evidence = none/partial) and focus-list items higher.
- **Pre-interview briefing (Claude):** a short page covering:
  - Likely questions.
  - The user's strongest evidence per eis.
  - Honest gaps and how to address them without overclaiming.
  - Three things to prepare.

### 5.3 Interview run
- **Personas** (prompt files, editable):
  - `intake_account_manager`: friendly, focused on motivation, availability, fit, and how you present yourself.
  - `technical_lead`: probes depth, asks "how exactly did you…", challenges vague answers.
  - `hiring_manager`: critical, focused on results, gaps, and "why you".
- **Interviewer turn generation (local Qwen):**
  - Given: persona, current plan topic, conversation so far (last N turns plus a summary), and the Jev-decided next move.
  - Output: one question, at most 2 sentences.
  - Stream to the UI via SSE.
- **Guardrails on every interviewer question (Jev, before it is shown):**
  - Grounded: it only refers to facts in the vacancy, CV, or conversation.
  - Appropriate: no questions about age, religion, pregnancy, health, origin, or similar. Such questions are illegal or inappropriate in Dutch hiring.
  - On-topic for the planned topic.
  - If any check fails: regenerate once with the failure reason. If it fails again, escalate the turn to Claude and log the event.
- **Next move after each answer (Jev Choice):**
  - `probe_deeper`: the answer was vague or missing a STAR element.
  - `challenge`: the answer overclaims or contradicts the CV.
  - `clarify`: the answer is ambiguous.
  - `next_topic`: the topic is sufficiently covered.
  - Code enforces limits: max 2 follow-ups per topic, and the overall time budget.
- **Answer input**
  - Typed: a textarea with an optional soft timer.
  - Spoken: browser MediaRecorder → upload → local speech-to-text on the server (faster-whisper, section 5.7) → the user sees the transcript and can confirm it or re-record.
- The user can pause and resume. Every turn is persisted immediately, so a refresh or crash loses nothing.

### 5.4 Per-answer evaluation (runs in the background during the interview)

State sent to Jev: question, planned topic, linked eisen, the pseudonymised answer, and the retrieved CV evidence. The full question catalog is in section 7. In summary:
- Overall answer quality (Score, 4 levels).
- STAR completeness: situation, task, action, result, each as a separate Noul (decomposed, as the Jev docs recommend).
- Concrete example vs. generalities (Noul).
- Quantified result (Noul).
- Evidence for each linked eis (Noul per eis).
- Consistency with the CV (Choice: consistent / not in CV / contradicts CV).
- Overclaiming (Noul).
- Hedging or uncertain phrasing (Score).

**Computed in code, not by a model:** word count, speaking duration, words per minute, and filler-word count. Jev is documented as weak at arithmetic, so counting stays in code.

### 5.5 Review screen
Per question:
- Question, answer (transcript), persona, and topic.
- **Classification badges:**
  - Answer quality level.
  - STAR elements present or missing.
  - Specific vs. generic.
  - Result quantified.
  - Eisen evidenced.
  - CV consistency.
  - Each badge shows its confidence. Low-confidence badges are marked "uncertain", not hidden.
- **Feedback (Claude, section 9.4 rules apply):**
  - What was strong, with one or two points quoted from the answer.
  - What to add, pointing to CV evidence the user did not use ("you didn't mention X from your role at Y").
  - What to explore, phrased as questions to the user when the needed evidence is not in their documents ("Do you have an example where…?"). Never a made-up example.
  - An improved answer outline built only from the user's own evidence (bullets, not a script).
- Button: **"Oefen deze vraag opnieuw"** (practise this question again).

### 5.6 Stats dashboard
- **Coverage per eis/wens:** a heatmap or table showing evidence in documents vs. evidence given in the interview. This shows eisen where the user has experience but did not bring it up.
- **Answer quality distribution** across all answers.
- **STAR completeness:** for each STAR element, the percentage of answers that include it. This shows systematic patterns, such as "you almost never give a result".
- **Specificity and quantified-results rate.**
- **Speaking (if used):**
  - Words per minute per answer, with a target band of roughly 120–160 wpm **[DECISION: tune]**.
  - Filler words per minute (NL: eh, ehm, uh, dus, eigenlijk, gewoon, zeg maar, weet je; EN: um, uh, like, you know, basically).
  - Answer duration vs. a target of 1–2 minutes for behavioural questions.
- **Across runs (if previous reports were uploaded):** trend per focus item (mastered / improving / unchanged / regressed).
- Charts use Chart.js. Every chart must also have a text summary for accessibility.

### 5.7 Practice and tips
- **Speak-aloud drills:**
  - Pick the 3 weakest answers.
  - The user records the answer again; speaking stats are shown before and after.
  - Instructions encourage telling the story out loud 3 times without reading.
- **Speech-to-text:**
  - faster-whisper running locally on the server. Model size **[DECISION]** depends on CPU; `small` or `medium`.
  - Audio is deleted right after transcription, unless the user opts in to keep it.
- **Tips library:**
  - A **curated, static markdown knowledge base** in the repo, not generated on the fly, so advice is consistent and reviewable.
  - Topics:
    - STAR method.
    - Pausing before answering.
    - Asking a clarifying question.
    - Addressing a gap honestly and bridging to related experience.
    - Closing with a question to the interviewer.
    - Opening with a 1-minute pitch.
    - Handling "what is your weakness".
    - Talking about rates and availability (intake only).
    - Body language basics (text only).
  - Claude may *select and link* relevant tips per user, but not rewrite them.
- **Personal practice plan (Claude)** at the end of the review: 3 to 5 concrete actions ranked by impact. Each links to the questions, stats, or tips it comes from.

### 5.8 Report
- Contents:
  - Run metadata.
  - Vacancy summary.
  - Coverage per eis/wens.
  - Per-question classifications and feedback.
  - Stats.
  - Speaking metrics.
  - Practice plan.
  - A focus list for next time.
- **Formats:**
  - `report.json`, validated against a versioned schema (section 8.2).
  - `report.pdf`, rendered with WeasyPrint, **with `report.json` embedded as a PDF file attachment**, so the user only needs to keep one file.
- Real names are restored in the user's downloaded report and stay pseudonymised in anything stored for analytics.
- On upload of a previous report:
  - Validate the schema version.
  - Accept either the JSON or the PDF (extract the attachment).
  - If the PDF has no attachment, show a clear error.

### 5.9 Follow-up runs (learning loop)
When a previous report is uploaded:

1. **Relevance (Jev Noul)** per previous weak item, against the new vacancy: "This weak point is relevant for the new vacancy."
2. **Priority (computed in code):** severity from the previous score × relevance × a recency weight.
3. **Focus list:** the top items go into the plan. Claude gets them as explicit topics to re-test, using *different* questions than last time.
4. **Mastery classification (Jev Choice)** after each re-tested item is answered.
   - Options: `mastered` / `improved` / `unchanged` / `regressed`.
   - State: the previous answer summary and score, plus the new answer.
5. The report records the trend per item. Items `mastered` twice in a row drop off the focus list.

---

## 6. Model architecture

### 6.1 Roles

| Task | Model | Why |
|---|---|---|
| Pseudonymisation (with regex) | Qwen (local) | Raw personal data never leaves the server |
| Extraction of eisen/wensen to JSON | Qwen (local) | Bulk, private, cheap; escalate on validation failure |
| Embeddings | Local embedding model via Ollama | Private, cheap |
| Interviewer turns | Qwen (local) | High volume, persona play; fallback to a small Claude model if too slow |
| All typed judgments (sections 5 and 7) | Jev | Fast, typed, calibrated, with confidence |
| Interview plan, briefing, review feedback, practice plan | Claude (mid-tier model) | Reasoning and writing quality |
| Escalations (low-confidence judgments, failed guardrails, failed validation) | Claude | Handles the hard cases |

Model IDs live in `config/models.yaml`. Suggested starting points (verify against current docs):
- Claude: `claude-sonnet-5` for planning and feedback; `claude-haiku-4-5-20251001` as the fast fallback.
- Local: a Qwen instruct model sized to the server **[DECISION D1]**.
- Jev: pin a specific version, not only `jev-latest`, so results stay reproducible. Log the version returned in every response.

### 6.2 The cascade (core pattern)

```
local model does the work
      ↓
Jev judges it (typed answer + confidence)
      ↓
confidence ≥ threshold → accept, continue
confidence <  threshold → escalate to Claude (with the Jev result as context)
      ↓
everything logged: which path, latency, tokens, cost
```

- **Thresholds** are per question in `config/thresholds.yaml`. Start at 0.7 for Choice and Score confidence.
- **Noul** has no separate confidence field. Treat noul values in an **uncertainty band** (start 0.35–0.65) as "uncertain" and escalate or mark them "uncertain" in the UI.
- These thresholds are **starting points, not validated values.** Tune them on the evaluation set (section 10.2).
- **Escalation output:** Claude returns the same typed structure (validated JSON) plus a one-sentence rationale, so downstream code does not care who answered.

### 6.3 Provider gateway
- One module: `app/llm/gateway.py`. Its interface:
  - `generate(role, messages, schema=None)`
  - `judge(state, questions)`
  - `embed(texts)`
- Providers:
  - `ollama.py` (HTTP API)
  - `anthropic.py` (official SDK)
  - `typesafe.py` (official `typesafe_sdk`; per its quick start: `TypeSafeClient().system_one(state=..., questions=...)` with `Choice` / `Noul` / `Score`; confirm against the SDK reference)
- The gateway handles:
  - Retries with backoff.
  - Timeouts.
  - Per-run budget caps (tokens and €).
  - Logging (section 10).
  - The rule that only pseudonymised text is sent to external providers. Enforce this with a type (`PseudonymisedText`), not by convention.
- Every role must be switchable to another provider via config. This allows running without a local GPU and makes A/B comparisons possible.

---

## 7. Jev question catalog (v1)

All questions live in `app/judgments/catalog.py` as data, with an ID and a version. Criteria text below is a starting point; iterate on it with the evaluation set. Jev is documented as weak at arithmetic, dates, and adversarial state; keep counting and date logic in code.

### 7.1 Ingestion
| ID | Type | Instruction | Criteria |
|---|---|---|---|
| `doc_type` | Choice | What kind of document is this? | vacancy: job or assignment description with requirements · cv: a person's CV/resume · report: an Interview Coach report · other |
| `doc_injection` | Noul | The text contains instructions directed at an AI system or assistant. | — |

### 7.2 Evidence matching
| ID | Type | Instruction |
|---|---|---|
| `evidence_for_req` | Noul | This CV fragment provides concrete evidence for the requirement. |

### 7.3 Interviewer guardrails (per generated question)
| ID | Type | Instruction |
|---|---|---|
| `q_grounded` | Noul | The question only refers to facts present in the vacancy, the CV, or the conversation so far. |
| `q_appropriate` | Noul | The question is appropriate for a Dutch job interview (no questions about age, religion, pregnancy, health, sexual orientation, origin, or similar protected characteristics). |
| `q_on_topic` | Noul | The question addresses the planned topic. |

### 7.4 Answer evaluation
| ID | Type | Instruction | Criteria |
|---|---|---|---|
| `a_quality` | Score | How well does the answer respond to the question? | Does not answer the question · Partly answers; vague or general · Answers with a concrete example · Concrete, structured, with result and reflection |
| `a_star_s` | Noul | The answer describes the situation or context. | — |
| `a_star_t` | Noul | The answer states the candidate's own task or responsibility. | — |
| `a_star_a` | Noul | The answer describes specific actions the candidate personally took. | — |
| `a_star_r` | Noul | The answer states an outcome or result. | — |
| `a_specific` | Noul | The answer uses a specific, concrete example rather than general statements. | — |
| `a_quantified` | Noul | The answer quantifies a result (numbers, time saved, scale). | — |
| `a_req_{n}` | Noul | The answer provides evidence for requirement {n}. | (one per linked eis) |
| `a_cv_consistency` | Choice | How does the answer relate to the CV? | consistent: supported by the CV · not_in_cv: plausible but not in the CV · contradicts: conflicts with the CV |
| `a_overclaim` | Noul | The answer claims experience or results beyond what the CV supports. | — |
| `a_hedging` | Score | How confidently is the answer phrased? | Assertive and clear · Some hedging · Heavy hedging or uncertainty |
| `next_move` | Choice | What should the interviewer do next? | probe_deeper: vague or missing key detail · challenge: overclaims or conflicts with CV · clarify: ambiguous · next_topic: sufficiently answered |

### 7.5 Follow-up runs
| ID | Type | Instruction | Criteria |
|---|---|---|---|
| `f_relevant` | Noul | This previous weak point is relevant for the new vacancy. | — |
| `f_mastery` | Choice | Compared with the previous answer, how does the new answer perform on this weak point? | mastered · improved · unchanged · regressed |

---

## 8. Data model

### 8.1 Database (SQLite via SQLModel; Postgres-ready)
- `users`: id, email, password_hash (argon2), role, created_at, invited_by
- `invites`: code, created_by, expires_at, used_by
- `runs`: id, user_id, status, settings (json), created_at, finished_at, schema_version
- `documents`: id, run_id, kind, filename, sha256, text_pseudonymised, created_at. The raw file is deleted after parsing unless retention is on.
- `pii_maps`: run_id, encrypted_mapping (Fernet, key from env)
- `chunks`: id, document_id, chunk_ref, text_pseudonymised, embedding (blob)
- `requirements`: id, run_id, kind (eis/wens/responsibility), text, source_chunk_ref, evidence_strength, evidence_refs (json)
- `plan_topics`: id, run_id, order, persona, question_type, goal, requirement_ids (json), focus_item_id
- `turns`: id, run_id, topic_id, role (interviewer/candidate), text_pseudonymised, audio_duration_s, created_at
- `judgments`: id, run_id, turn_id, question_id, question_version, provider (jev/claude), answer (json), confidence, escalated (bool), latency_ms
- `feedback`: id, turn_id, strengths, add, explore, outline (json)
- `model_calls`: id, run_id, role, provider, model, tokens_in, tokens_out, cost_eur, latency_ms, status, escalation_reason. **No content is logged.**
- `reports`: id, run_id, json (pseudonymised), created_at

### 8.2 Report JSON (schema `report/v1`, pydantic model, exported as JSON Schema)
```json
{
  "schema": "report/v1",
  "run_id": "…",
  "created_at": "…",
  "language": "nl",
  "vacancy": { "title": "…", "organisation": "…", "summary": "…" },
  "requirements": [
    { "id": "eis_1", "kind": "eis", "text": "…",
      "evidence_in_documents": "strong|partial|none",
      "evidence_in_interview": "strong|partial|none" }
  ],
  "answers": [
    { "turn_id": "…", "topic": "…", "question": "…", "answer": "…",
      "judgments": { "a_quality": { "value": 2, "confidence": 0.81 }, "…": {} },
      "feedback": { "strengths": ["…"], "add": ["…"], "explore": ["…"], "outline": ["…"] },
      "speaking": { "duration_s": 94, "wpm": 142, "fillers_per_min": 3.2 } }
  ],
  "stats": { "star_rates": {}, "specific_rate": 0.0, "quantified_rate": 0.0 },
  "focus_items": [
    { "id": "fi_1", "label": "Results rarely quantified", "linked_requirements": ["eis_3"],
      "severity": 0.8, "history": ["unchanged"] }
  ],
  "practice_plan": [ { "action": "…", "why": "…", "links": ["turn:…", "tip:star"] } ],
  "models": { "jev_version": "…", "claude": "…", "local": "…" }
}
```

---

## 9. Privacy, security and safety

### 9.1 Data that leaves the server
- Only pseudonymised text goes to Jev and Claude. TypeSafe's documentation states that it receives submitted state and advises removing sensitive data first.
- Enforce this in the gateway (section 6.3) and cover it with tests that fail if raw text reaches an external provider.
- **[DECISION D5]** Check the data retention terms of TypeSafe/OpenRouter and Anthropic, and the employer's AI policy, **before** colleagues use the app. Record the outcome in `docs/privacy.md`.

### 9.2 Storage and retention
- Raw uploads are deleted after parsing by default.
- Audio is deleted after transcription by default.
- Runs are auto-deleted after N days (default 30 **[DECISION]**), and the user can delete a run at any time.
- The PII mapping is encrypted at rest.
- The report the user downloads is theirs. Server-side copies follow the retention rules above.

### 9.3 App security
- HTTPS only (Caddy with automatic certificates).
- Invite-only accounts, argon2 password hashing, secure session cookies, CSRF protection.
- Rate limits per user on runs and model calls, plus a global daily € budget cap.
- Ollama is **not** exposed publicly; it is only reachable on the internal Docker network.
- Secrets live in `.env` (never committed); `.env.example` is committed.
- Upload hardening: MIME sniffing, size limits, no execution, parsing in a subprocess with a timeout.
- Uploaded documents are treated as untrusted data:
  - They are always fenced and quoted in prompts.
  - They are never executed as instructions.
  - The injection check is in section 7.1.

### 9.4 Feedback integrity (anti-hallucination rules)
- Feedback may only reference experience that exists in the user's uploaded documents or answers, cited by chunk or turn ID.
- Anything the user *might* have but has not documented is phrased as a question ("Do you have an example of…?"), never as a statement.
- Every Claude feedback item carries source references. A post-check (a Jev Noul, `fb_grounded`, added in M3) drops items it cannot ground.
- Low-confidence classifications are shown as "uncertain", never as fact.

---

## 10. Observability and evaluation

### 10.1 Metrics (admin page)
- Per run: model calls per provider, tokens, € cost, p50/p95 latency per role.
- Escalation rate per Jev question ID.
- Guardrail events: questions blocked, regenerations, injection flags.
- Local vs. external share of calls.
- These numbers are the showcase evidence ("X% handled locally, Y% escalated, €Z per run").

### 10.2 Evaluation set
- Location: `eval/`. Contents:
  - About 30 hand-labelled answers (the owner writes answers of known quality to the questions of a real target vacancy).
  - About 10 intentionally inappropriate or ungrounded interviewer questions.
  - About 10 documents with injection attempts.
- `make eval` runs every Jev question against the set. It reports accuracy and confidence calibration, and recommends thresholds.
- The eval runs in CI whenever a prompt, question criteria, or threshold changes. Use a small subset in CI to limit cost.

---

## 11. Tech stack and repository layout

### 11.1 Stack
- **Backend:** Python 3.12, FastAPI, SQLModel, pydantic v2, uv for dependency management.
- **Frontend:** server-rendered Jinja2 + HTMX + Alpine.js + Chart.js. There is no JS build step. SSE is used for streaming interviewer turns. **[DECISION D6]**: switch to React/Svelte only if interactivity requires it.
- **PDF:** WeasyPrint, with an embedded file attachment via pypdf.
- **Speech-to-text:** faster-whisper, running on CPU on the server.
- **Models:** Ollama (local), `anthropic` SDK, `typesafe_sdk`.
- **Quality:** pytest, ruff, mypy (strict on `app/llm` and `app/judgments`), pre-commit.
- **Containers:** Docker Compose with the services `app`, `ollama`, `caddy`.

### 11.2 Repo layout
```
interview-coach/
  app/
    main.py              # FastAPI app, routes
    auth/                # invites, sessions
    ingest/              # parsing, pseudonymisation, chunking, injection check
    prep/                # extraction, evidence matching, plan, briefing
    interview/           # run loop, personas, next-move logic, SSE
    judgments/           # Jev catalog, cascade, thresholds
    review/              # feedback, stats, practice plan
    report/              # schema, JSON/PDF export, import
    speech/              # upload, whisper, speaking metrics
    llm/                 # gateway + providers
    db/                  # models, migrations
    templates/  static/
  prompts/               # persona + Claude prompts as versioned files
  knowledge/tips/        # curated interview tips (markdown)
  config/                # models.yaml, thresholds.yaml, fillers.yaml
  eval/                  # labelled set + runner
  deploy/                # docker-compose.yml, Caddyfile, backup script
  docs/                  # privacy.md, architecture.md, decisions.md (ADR log)
  tests/
  CLAUDE.md              # build rules for Claude Code (derived from section 0)
```

---

## 12. Deployment (Hetzner + DuckDNS)

- **DNS:** a DuckDNS subdomain points to the Hetzner server IP. Run the DuckDNS update script via cron only if the IP is not static.
- **TLS:** Caddy with automatic Let's Encrypt certificates via the HTTP-01 challenge (ports 80 and 443 open).
- **Firewall:** Hetzner Cloud Firewall and ufw allow only 22, 80, and 443. SSH uses keys only, with password login disabled.
- **Services:** Docker Compose. `ollama` is on the internal network only, with its model volume persisted.
- **CI (GitHub Actions):** lint, type check, tests, and the eval subset on every PR.
- **Deploy:** on merge to `main`, a GitHub Action SSHes into the server and runs `git pull && docker compose up -d --build`. Alternatively, build images and push to GHCR **[DECISION]**.
- **Backups:** a nightly SQLite backup (`sqlite3 .backup`), encrypted and copied off-server (e.g. to a Hetzner Storage Box). Keep 14 days.
- **Health:** a `/healthz` endpoint that checks the database, Ollama, and external API reachability, plus uptime monitoring (e.g. UptimeRobot).
- **Public repo:** the code is open source; secrets and data never are. Add a README with an architecture diagram and the metrics from section 10.1.

---

## 13. Milestones and acceptance criteria

**Showcase-ready = M1 to M3.**

### M0: Foundations
- Repo, uv, ruff/mypy/pytest, pre-commit, CI, `CLAUDE.md`, Docker Compose running locally.
- Gateway with all three providers, logging to `model_calls`, and budget caps.
- **Done when:** one smoke test per provider passes, and a test proves non-pseudonymised text cannot be sent to external providers.

### M1: Core loop (command line)
- Command: `coach run --vacancy x.pdf --cv y.pdf`.
- It performs ingestion, extraction, evidence map, plan, a text interview in the terminal, per-answer judgments, and a JSON report.
- **Done when:** a full 15-minute run on a real target vacancy completes, and every judgment is logged with its provider, confidence, and escalation status.

### M2: Web app, text mode
- Auth with invites, upload, settings, briefing, streaming interview, and pause/resume.
- **Done when:** the M1 run works in the browser, with a mobile layout, deployed at the DuckDNS URL over HTTPS.

### M3: Review, stats, report
- Review screen with badges and grounded feedback (`fb_grounded` check), stats dashboard, practice plan, tips library, and PDF + JSON export.
- Admin metrics page.
- **Done when:** every feedback item has a source reference, and the report PDF opens and contains the embedded JSON.

### M4: Follow-up runs
- Report import, relevance and priority, focus list in the plan, mastery classification, and trends in the review.
- **Done when:** a second run with the M3 report demonstrably re-tests at least 3 previous weak points with new questions.

### M5: Speaking practice
- Recording, faster-whisper transcription, speaking metrics, speak-aloud drills, and before/after comparison.
- **Done when:** a spoken 1-minute answer is transcribed in under 20 s on the server, and the metrics appear in the review.

### M6: Hardening
- Rate limits, retention jobs, backups, health checks, eval-driven threshold tuning, and `docs/privacy.md` completed.
- **Done when:** the eval report is committed, thresholds are set from it, and a restore from backup has been tested.

### M7: Colleague-ready (after the pitch)
- Coach role with explicit report sharing, the two intake persona sets tuned with the account manager's input, and an NL-first UI.
- **Done when:** the people manager and account manager have tested it with one consultant each.

---

## 14. Open decisions

| ID | Decision | Notes |
|---|---|---|
| D1 | Where the local model runs | The Hetzner server specs (vCPU, RAM, GPU?) decide the Qwen size. Options: (a) a small Qwen (≈4–9B, Q4) on the server's CPU, which is slower (interviewer turns may take 5–15 s); (b) the home RTX 3080 PC or M1 Max as the inference node over Tailscale, which is fast but depends on a home machine being on; (c) a Hetzner GPU server, which is fast but costly. The gateway makes this switchable, so start with (a) and measure. |
| D2 | Jev access route | TypeSafe API directly, or via OpenRouter. Pick based on data policy and billing. |
| D3 | Auth | Invite codes with password (default), or magic link (needs email sending). |
| D4 | Default language | NL-first UI with EN option (default), or EN-first. |
| D5 | Data policy check | TypeSafe/OpenRouter and Anthropic retention terms, plus the employer's AI policy. Must be done before M7. |
| D6 | Frontend | HTMX (default) or a SPA framework. |
| D7 | Embedding model | Must handle Dutch well. Compare 2 options in the eval. |
| D8 | Retention period | Default 30 days. |

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| The local model is too slow on a CPU server | Measure in M1. The gateway allows a switch to the home node or a Claude fallback per role. |
| Jev misclassifies in edge cases | Uncertainty is shown, not hidden. Low confidence escalates. The eval set tunes thresholds. Jev is new (released September 2026), so pin versions. |
| Feedback invents experience | Section 9.4 rules plus the grounding check. Tests with CVs that deliberately lack key experience. |
| Personal data leaks to external APIs | Type-enforced pseudonymisation, tests, and a data policy check before colleague use. |
| API costs run away | Per-run and daily budget caps, rate limits, and cost logged per call. |
| Dutch quality of the local model | Include Dutch answers in the eval set. Allow a per-language provider choice in config. |
| Scope creep before the showcase deadline | Only M1 to M3 count for the showcase. Everything else waits. |
