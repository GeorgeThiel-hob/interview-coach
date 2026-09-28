# Answer sheet for the demo runs (fictional candidate: Sanne Visser)

Use this to answer the interview questions *in character* during the two demo runs (NL and EN).
Everything here is fictional and consistent with `cv-nl.md` / `cv-en.md`. Answer in the run's
language; paraphrase freely, it should read like a real person typing.

## Settings for both runs
- Vacancy: `vacancy-nl.md` (NL run) or `vacancy-en.md` (EN run), uploaded as a file.
- CV: `cv-nl.md` or `cv-en.md`.
- Interview type **Mixed**, length **15 min**, answers **Typed**, difficulty **Realistic**.
- Language: **Nederlands** for the first run, **English** for the second.

## Make the review interesting (so the demo shows what the coach does)
- Give **two or three strong STAR answers** (story 1, 2 or 3): situation, your task, what *you*
  did, and a result with a number.
- Give **one deliberately weaker answer**: general, no concrete example, no result (e.g. on
  stakeholders: "I always try to communicate clearly and involve everyone early.").
- Give **one answer that skips the result** (tell story 4 but stop after the actions).
- In the closing question, ask one or two good questions (see the end).
- Keep answers to roughly 60–150 words; a typed interview.

## Stories

**1. RAG assistant for customs rules (Harbour Logistics, 2023–now)**
S: 40 planners lost time searching customs rules in PDFs and mailboxes; answers were
inconsistent. T: build an assistant that answers with the right source. A: interviewed planners,
built a RAG pipeline in Python with LangChain over the rule documents, required a citation in
every answer, shipped a pilot to 5 planners first, then all 40. R: average search time per
question from 12 to 3 minutes; planners trust it because every answer shows its source.

**2. Evaluation set and guardrails (Harbour Logistics)**
S: early version sometimes invented rules. T: make quality measurable and reduce wrong answers.
A: built an evaluation set of 200 questions with answers verified by two senior planners, ran it
on every change in CI, added guardrails (refuse when no source is found, show the source). R:
wrong answers from 18% to 6% in three iterations; no release without passing the set.

**3. Batch to streaming (DataWorks Consultancy, 2021–2023)**
S: an energy client got daily reports a day late. T: speed up the pipeline without breaking
downstream reports. A: redesigned the batch job as a streaming set-up with Airflow triggers and
PostgreSQL, ran old and new in parallel for two weeks and compared outputs. R: report turnaround
from one day to 15 minutes; the client used it for intraday decisions.

**4. Pseudonymising client data with a privacy officer (DataWorks)**
S: a logistics client wanted analytics on driver data containing personal data. T: make it
GDPR-proof. A: worked with the privacy officer on a data-protection impact assessment, replaced
names and licence plates with pseudonyms before the data reached the analytics environment,
documented who can see what. R: (skip this in the "no result" answer) approved by the client's
DPO; analytics went live two weeks later than planned but without findings in the audit.

**5. Explaining to non-technical colleagues**
Runs a monthly open-source AI meetup (~30 attendees); at Harbour Logistics gave a demo to the
management team explaining in plain words why the assistant sometimes says "I don't know" and why
that is a feature.

**6. Weak spots (honest gaps)**
- Kubernetes: basic knowledge, the platform team runs the cluster.
- Public sector: only an internship at a water authority; motivated by working on services for
  residents.
- LLM experience: two years, not more.

## Motivation (if asked why this role)
Wants to build AI that helps residents directly, where reliability and privacy matter more than
flashy features; the city's focus on explainability matches how Sanne worked with citations and
evaluation sets.

## Questions for the interviewer (closing)
- How do you decide when an AI application is good enough to put in front of residents?
- Who in the team owns the evaluation of model output once something is live?
