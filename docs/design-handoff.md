# Design handoff: Interview Coach web UI (v0.1)

For a designer or a design tool (e.g. Claude Design) that will give the web UI a visual
refresh. It explains what each page is for, what it must keep doing, and the technical limits.
The functionality works (MVP); this round is about how it looks and feels.

**What to give the design tool:** this file, plus the rendered example pages from
`make snapshots` (folder `design/snapshots/`, fictional data, open offline in a browser). The
source templates are in `app/templates/`.

## 1. The product in one paragraph

Interview Coach is a private practice tool for job interviews. A candidate uploads a vacancy and
their CV. The app prepares a briefing, then runs a mock interview in which an AI interviewer asks
questions one at a time (typed or spoken answers) and asks follow-up questions based on the
answers. Afterwards it shows a review: scores per answer, requirement coverage, charts,
concrete feedback with sources, and a practice plan, plus a PDF report. Privacy is a core
feature: personal data is replaced by placeholders before any text reaches an external AI
service.

**Audience:** job seekers (first the owner; later colleagues by invite). **Showcase:** the review
page is what recruiters will see first through a public `/demo` page (planned, see section 6).

**Tone:** calm, professional, encouraging; a coach, not a judge. Dutch first (NL), English
available (EN). No gamification, no emoji-heavy UI.

## 2. The flow

```
login ─► home (my runs) ─► new run (upload + settings) ─► preparing (~3 min, live steps)
      ─► briefing ─► interview (question → answer → next question, ~15–45 min)
      ─► writing review (~1–2 min, live steps) ─► review (+ PDF, practise a question again)
```

## 3. Pages

Snapshot file names refer to `design/snapshots/`. Priority: **A** = showcase-critical,
**B** = used every run, **C** = utility.

| # | Snapshot | Template | Route | Priority | Purpose and content | Interaction and states |
|---|---|---|---|---|---|---|
| 1 | `01-login` | `login.html` | `/login` | B | Email + password. Invite-only note with link to register. | Error alert on wrong password or rate limit. |
| 2 | `02-register` | `register.html` | `/register?code=` | C | Invite code (prefilled from the link), email, password (min. 10). | Error alert. |
| 3 | `03-home-empty`, `12-home-with-runs` | `home.html` | `/` | B | "New run" button; table of the user's runs: date, status (created, preparing, ready, interviewing, paused, reviewing, done, failed), link. | Warning banner when the local model (laptop) is offline: new runs are then blocked. Status values are raw words today: design a status pill. |
| 4 | `04-new-run` | `new_run.html` | `/runs/new` | B | Upload vacancy (file or pasted text), CV (required), optional previous report and motivation letter; settings: interview type, language, length (15/30/45 min), typed/spoken, difficulty. Privacy note at the bottom. | Start button disabled when the local model is offline. Plain `multipart` form post. |
| 5 | `05-preparing`, `09-writing-review` | `run_status.html` | `/runs/{id}` while preparing/reviewing | B | All steps listed up front ("Stap 2 van 5"), check marks, a filling bar; warnings (e.g. "the CV contains text aimed at AI systems") below. | Live via server-sent events; redirects itself when done. Shows an error alert if the run failed. Takes ~3 min: this page deserves care (reassurance, what is happening, privacy step). |
| 6 | `06-briefing` | `briefing.html` | `/runs/{id}/briefing` | A | Likely questions; strongest evidence per requirement (with CV references); honest gaps with advice; "prepare" checklist; "Start the interview" button. | Static. |
| 7 | `07-interview-question`, `08-interview-follow-up` | `interview.html` + `partials/question.html` | `/runs/{id}/interview` | A | Header "Vraag 3 · onderwerp 1 van 4 · vervolgvraag · 10 / 15 min" with a progress bar (topics), interviewer persona (hiring manager / technical lead / account manager), the question, answer textarea, send button, pause button. | Answer is posted with htmx and only the `#turn` block is swapped (no page reload); "the interviewer is thinking…" indicator during the request (5–20 s). Spoken mode adds the recorder (`partials/recorder.html`): record/stop with a timer, then the transcript lands in the textarea to confirm. After the last answer the "finished" partial appears and redirects. The question text may contain placeholders such as `[PERSON_1]` (pseudonymised). |
| 8 | `10-review` | `review.html` | `/runs/{id}/review` | **A (showcase)** | Title + downloads (PDF, JSON). Statistics: STAR rates (S/T/A/R bar chart), share of concrete and quantified answers, answer-quality distribution (chart), speaking stats for spoken runs (line chart). Requirement coverage table: each requirement, evidence in documents vs in interview (strong/partial/none), hint "you have this but did not bring it up". Practice plan (ranked actions with links to tips and answers). Focus for next time. Then one card per answer: persona and topic, question, the answer, score chips, feedback in four groups (Sterk / Voeg toe / Verken / Betere opbouw) with source chips (CV p8, jouw antwoord), "practise this question again". Delete-run button. | Charts via Chart.js. Score chips: green = good, red = weak, **dashed amber = the model was uncertain**; "· Claude" = a second model double-checked it. Chip tooltips show the rationale. Long page: consider a summary header, anchor navigation, collapsible answer cards. |
| 9 | `11-practice-question` | `practice.html` | `/runs/{id}/practice/{turn}` | B | Re-answer one question; attempts listed as "Before" and "After #n" with score chips, so progress is visible. | Plain form post; recorder in spoken mode. |
| 10 | `13-tips` | `tips.html` | `/tips` | C | Library of interview tips (STAR, pause before answering, closing question, ...), linked from the practice plan by `#id`. | Anchor targets must stay (`id` on each card). |
| 11 | `14-admin` | `admin.html` | `/admin` | C | Usage (calls, local share, cost), latency per role, escalations, safety events, runs (metadata only), invites (create, list). | Admin only; English is fine here. |
| 12 | `15-local-model-offline`, `16-error` | `partials/offline.html`, `error.html`, `partials/error.html` | – | C | Error states: laptop offline (answer not saved, retry later), generic error. | |
| – | – | `report_pdf.html` | `/runs/{id}/report.pdf` | B | The same review as a printable A4 PDF (WeasyPrint). | Separate print CSS in the file; only fonts installed in the container (DejaVu Sans). Keep it simple and printable; a matching visual identity is welcome. |

Shared pieces: `base.html` (layout, header with brand, tips, admin, language switch NL/EN,
logout; **all CSS lives here** in one `<style>` block with CSS variables), `_macros.html` (score
chips and source chips).

## 4. Technical constraints (must keep)

- **No build step.** Server-rendered Jinja2 templates; plain CSS in `base.html`; no npm, no
  Tailwind build, no React. A small amount of vanilla JS or Alpine is fine.
- **Libraries already vendored** in `app/static/vendor/` and nothing else: htmx 2.0.4, Alpine.js
  3.14.8, Chart.js 4.4.7. No CDNs.
- **Content-Security-Policy:** `default-src 'self'`; inline styles and scripts allowed; images
  only from the site or `data:` URIs. So: **no Google Fonts or external images**; use system
  fonts, or add font files to `app/static/` (open licence) and reference them locally. Icons as
  inline SVG.
- **Keep working hooks:** every `{{ ... }}` / `{% ... %}` expression, `t('key')` text keys (all UI
  text goes through the NL/EN table in `app/web/i18n.py`; new text needs a key there), form field
  `name`s, hidden `csrf` inputs, `hx-*` attributes, `x-data` / `x-init` / `x-show`, ids used by
  scripts or anchors (`turn`, `answer`, `audio_duration_s`, `starChart`, `qualityChart`,
  `speakingChart`, `star-summary`, tip ids, answer-card ids).
- **Accessibility:** WCAG AA contrast; visible focus states; labels on every input; charts keep
  their text summaries (`aria-describedby`); `aria-live` on the progress list.
- **Responsive:** must work on a phone (interview and review especially); current content width
  860 px.
- **Dutch strings are longer** than English ones; allow wrapping in buttons and headers.
- Colours carry meaning (good / weak / uncertain) and must stay distinguishable without colour
  (the ✓ / ✗ and dashed border already help).

## 5. Current visual state

**v0.2 "Terracotta" (2026-09-28) is applied:** warm terracotta accent with sage for good results,
Caprasimo (display) and Figtree (body) served from `app/static/fonts/` (SIL Open Font License,
licence files next to the fonts), light and dark mode via `prefers-color-scheme`, radio pills on
the new-run form, a two-column review with summary cards and a sticky contents list, Chart.js
theme in `app/static/chart-theme.js`. All CSS still lives in `base.html`.

The v0.1 starting point is kept below for reference.

### v0.1 (before the refresh)

Neutral light grey background, white cards with a thin border and 10 px radius, system font,
one blue accent (`#1f5fbf`), green/red/amber for status. Functional but plain: no brand mark, no
illustration, dense review page, default Chart.js styling, raw status words on the home page.
Tokens: `--fg #1b1d21`, `--muted #626873`, `--bg #f6f7f9`, `--card #fff`, `--line #dfe3e8`,
`--accent #1f5fbf`, `--ok #1d7a46`, `--warn #9a6300`, `--bad #b3261e`.

## 6. What we would like from the design round

1. A small visual identity: name treatment for "Interview Coach", colour palette, type scale,
   spacing, and components (buttons, cards, chips, status pills, alerts, steps, tables, form
   controls), expressed as CSS variables and classes for `base.html`.
2. Page designs in priority order: review (showcase), interview, briefing, preparing, home,
   new run; the rest follow the system.
3. Chart styling that matches (Chart.js options: colours, fonts, grid).
4. A public **demo page** (`/demo`, planned): one complete fictional run shown read-only without
   login (briefing, a few interview exchanges, the full review), with a short intro of what the
   app does, how privacy works (pseudonymisation, local model), and links to the GitHub repo.
   This is the link that goes into a CV, so first impression matters most here.
5. Optional: dark mode through the same CSS variables.

**Hand back:** updated `base.html` CSS and template markup (same file names), or a design spec
plus mock-ups that a developer applies to the templates. Keep the hooks in section 4 intact.
