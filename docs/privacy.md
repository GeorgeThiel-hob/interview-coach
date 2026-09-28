# Privacy and data handling

What leaves your machines, what is stored, and for how long. If you run the app for other people,
complete the checklist at the end first.

## What leaves the server

| Data | Where it goes | Form |
|---|---|---|
| Uploaded documents, typed/spoken answers | your own model machine (Ollama over Tailscale) | raw, for pseudonymisation only |
| Pseudonymised documents, answers, questions | Jev (TypeSafe), Claude (Anthropic) | names, contact details, addresses, IBAN/BSN, birth dates replaced by tokens |
| Audio (spoken answers, optional) | nowhere | transcribed on the server, deleted right after |

Enforced in code: external providers only accept `SafeText` (see docs/architecture.md), and
`tests/test_privacy.py` fails if raw text could reach them. Employer and client names are kept
because they matter for the interview.

Known limits of pseudonymisation: detection is regex plus a local model; unusual identifiers
(e.g. a rare project code name that identifies a person) can slip through. Users are told not to
upload sensitive data beyond a normal CV.

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

- [ ] TypeSafe data retention and training terms for API traffic (direct API): ...
- [ ] Anthropic API data retention for this account/organisation: ...
- [ ] Employer AI policy (if colleagues will use it): allowed tools, what may be processed, approval needed: ...
- [ ] Decide: is your own machine as the inference node acceptable for other people's data?
- [ ] Record the outcome and date here.
