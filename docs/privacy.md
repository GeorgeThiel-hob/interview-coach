# Privacy and data handling

What leaves your machines, what is stored, and for how long. If you run the app for other people,
complete the checklist at the end first.

## What leaves the server

| Data | Where it goes | Form |
|---|---|---|
| Uploaded documents, typed/spoken answers | your own model machine (Ollama over Tailscale) | raw, for pseudonymisation only |
| Pseudonymised documents, answers, questions | Jev (TypeSafe, hosted in the US), Claude (Anthropic) | personal identifiers replaced by tokens (below) |
| Audio (spoken answers, optional) | nowhere | transcribed on the server, deleted right after |

What is replaced (`app/ingest/pseudonymise.py`, `prompts/pseudonymise.md`):

| Pass | Replaces |
|---|---|
| Regex, every text | e-mail addresses, LinkedIn/GitHub/X profile links, phone numbers (9+ digits), IBAN (checksum), Dutch postcodes, BSN (11-test), dates of birth **only when labelled** ("geboren", "date of birth", "born") |
| Local model | names of people (also first names alone; surnames map to the same token), home addresses (and the town when part of one), other direct identifiers (handles, licence plates, ID numbers) |

Kept on purpose (the local model is told not to list them): organisations, employers, clients,
schools, universities, products, job titles, skills, technologies, cities where an organisation is
based. Not covered: unlabelled dates and years, age, nationality, gender, and identifying detail in
free text.

Enforced in code: external providers only accept `SafeText` (`app/llm/gateway.py`, see
docs/architecture.md), and `tests/test_privacy.py` fails if raw text could reach them. Documents,
interview answers and practice answers are all pseudonymised; if the local model fails twice the
run stops instead of sending unfiltered text.

Known limits: this is pseudonymisation, not anonymisation. Detection can miss an unusual
identifier, and a career profile (employer, role, years, school) can still identify a person.
The register and new-round pages say so (`app/templates/partials/privacy_notice.html`); keep that
text in step with the table above.

## Storage and retention

- Raw uploads are never written to disk; only pseudonymised text is stored.
- The token→name mapping per run is encrypted with Fernet (`PII_ENCRYPTION_KEY`).
- Runs are deleted automatically after `RETENTION_DAYS` (default 30, decision D8); users can
  delete a run at any time (all content, the mapping and the report copy are removed).
- `model_calls` keeps content-free metadata (tokens, cost, latency) for cost reporting.
- Downloaded reports belong to the user and contain real names.

## Access

Candidates see only their own runs. Admins see usage metadata and invites, never content.
(Coach sharing is planned for M7.)

## Before other people use your instance (decision D5)

**Reference instance, owner's own use: decided 2026-09-27.** The owner accepts that pseudonymised text from their own
documents and answers goes to Anthropic and TypeSafe. Reason: what remains after
pseudonymisation (employers, roles, projects, technologies, the target vacancy) is already
public in the owner's applications and public profiles, and their own name is theirs to share.
The checklist below still applies before anyone else uses the app.

Checked 2026-10-01, when the shared `/demo` sign-up code opened the app to visitors:

- [x] **TypeSafe**: privacy policy: "We will not train or fine tune any artificial intelligence or
      machine learning models on your prompts or other Input"; "The Services are hosted in the
      United States". **No retention period for API content is stated** (only "as long as
      reasonably necessary"), no DPA and no sub-processor list; the API docs say nothing about
      data. Open: ask TypeSafe for the API retention period and a DPA.
- [x] **Anthropic**: API key from the Anthropic Console, so the Commercial Terms apply:
      "Anthropic may not train models on Customer Content from Services"; API inputs/outputs
      deleted within 30 days (flagged content up to 2 years); a Data Processing Addendum is
      incorporated by reference.
- [ ] Employer AI policy: not applicable while no colleagues use it.
- [ ] Decide: is the owner's laptop, which sees raw uploads to pseudonymise them, acceptable for
      other people's data? (Owner to confirm.)
- [x] Visitors are told what is and is not replaced, that it is pseudonymisation and not
      anonymisation, and to share only an ordinary CV and a vacancy (register and new-round pages).
