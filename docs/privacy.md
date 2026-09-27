# Privacy and data handling

Status: **draft**. Decision D5 (below) must be completed by the owner before colleagues use the app.

## What leaves the server

| Data | Where it goes | Form |
|---|---|---|
| Uploaded documents, typed/spoken answers | the owner's laptop (Ollama over Tailscale) | raw, for pseudonymisation only |
| Pseudonymised documents, answers, questions | Jev (TypeSafe), Claude (Anthropic) | names, contact details, addresses, IBAN/BSN, birth dates replaced by tokens |
| Audio | nowhere | transcribed on the server, deleted right after |

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

## D5: to complete before colleague use (owner)

- [ ] TypeSafe data retention and training terms for API traffic (direct API): ...
- [ ] Anthropic API data retention for this account/organisation: ...
- [ ] House of Bèta AI policy: allowed tools, what may be processed, approval needed: ...
- [ ] Decide: is the laptop-as-inference-node acceptable for colleagues' data?
- [ ] Record the outcome and date here.
