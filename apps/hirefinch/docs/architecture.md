# HireFinch architecture

## 1. Shape

One FastAPI process holds the API, the background scheduler and every service. It uses
PostgreSQL in production and SQLite locally. An nginx container serves the React SPA and proxies
`/api` on one origin. There are no separate LLM "agents": every decision that must be
reproducible or safe (scoring, dedupe, state, policy, validation) is ordinary deterministic code.
An LLM, when enabled, only proposes wording, and deterministic validators accept or reject it.

| Logical agent from the brief | Implementation | LLM? |
|---|---|---|
| Job Discovery | `connectors/*`, `services/jobs.run_source`, `net.SafeFetcher` | no |
| Job Parsing | `jobs/parser.py` (`PARSER_VERSION`), `skills.py` taxonomy | no |
| Profile Intelligence | `candidate.py` (years from dates, skills only with evidence) | no |
| Job Matching | `jobs/matching.py` (`SCORER_VERSION`), explainable criteria | no |
| Resume Tailoring | `resume/tailor.py` (select and reorder) + optional `llm_assist.rewrite_summary` | optional |
| Resume Validation | `resume/validator.py` (facts vs master, then the files themselves) | no |
| Application Preparation | `applications/answers.py`, `services/applications.prepare` | no |
| Application Execution | `applications/routes.py`, `services/applications.submit` | no |
| Recruiter Outreach | `services/outreach.py` + optional `llm_assist.polish_outreach` | optional |
| Notification | `notifications/outbox.py`, `services/notify.py` | no |
| Application Tracking | `workflow/states.py`, tracker API | no |
| Orchestrator | `workflow/pipeline.py`, `scheduler.py` | no |

## 2. Job lifecycle

```
discovered → match_evaluated → shortlisted → resume_pending → resume_ready
   → awaiting_approval ⇄ ready_to_apply → application_in_progress → applied
   → recruiter_contacted → interview_scheduled → rejected
side exits: withdrawn · expired · application_failed · needs_manual
```

`workflow/states.TRANSITIONS` is the single source of truth. Every change goes through
`transition()`, which validates the move and writes an audit event. The pipeline (`advance`)
runs every stage a job is ready for and commits after each one. That gives three guarantees:

- A crash resumes from the last completed stage.
- A stage that already reached the outside world is never re-run because a later stage failed.
- `advance` is safe to call repeatedly. The restart test calls it again on the same database and
  asserts no new attempts or emails.

The pipeline deliberately stops at `match_evaluated` in these cases, leaving the job for you:
- band `review`, `low` or `disqualified`;
- a suspicious posting, or text that tries to instruct an AI;
- an expired posting.

## 3. Scoring

There are six weighted criteria (defaults 30/25/15/10/10/10). Each returns a value in [0, 1], or
`None` when the posting does not say. The score is the weighted mean of the *available*
criteria, so missing pay lowers confidence, not the score. Confidence then depends on how much
of the weight was available and how many concrete skill requirements were found. A
low-confidence result cannot be banded `high` or `good`.

Disqualifiers override the number entirely:
- required years beyond your verified years plus the allowed gap;
- published pay under your floor;
- an unacceptable work mode;
- on-site outside your locations;
- a mandatory degree you may not hold;
- citizenship or clearance requirements;
- an excluded company or keyword.

## 4. Resume integrity

The master file is stored read-only (`data/masters/<sha>.ext`). Tailoring copies the parsed
structure and only changes:
- the order of skill groups, skills, bullets and projects;
- the headline, which becomes your own role label plus verified matching skills;
- the order of summary sentences;
- the bullets of older roles, trimmed to a configurable count and reported as omitted.

The validator rejects any version where:
- contact details, any employer, title, date or location, education or certifications differ;
- a bullet is not in the master;
- a skill is neither in the master nor a verified profile skill with evidence;
- the summary gains a number or technology;
- the summary claims more years than the dates support.

It then re-reads the generated DOCX and PDF to check that the text is selectable, the standard
headings are present, and the length, date style and keyword coverage are acceptable. Each
version is written once to its own folder with a checksum manifest. Attachments are re-hashed
before every send.

### Document layout

`resume/style.py` is the single formatting specification for both formats:
- A4 page, single column, 0.65–0.75 in margins;
- Arial in the DOCX and the metric-compatible Liberation Sans embedded in the PDF, so line breaks match;
- body text 9.5–10.5 pt, headings 11.5 pt, name 19 pt;
- fixed leading, 10–12 pt before headings, 3 pt after bullets.

`render_resume` first tries the standard variant. It uses the compact variant (9.6 pt) only when that saves a page. It never goes below the minimum font size.

Pagination rules, applied in both formats:
- headings and role/project titles are kept with the first bullet;
- bullets of six lines or fewer never split across pages;
- no widow or orphan lines;
- the last two words of a bullet are bound together.

The PDF also adds:
- a "Title — Company (continued)" line when an entry crosses a page;
- a "Page X of Y" footer, drawn after the content so it comes last in the text layer.

`resume/layout.py` then checks the rendered files themselves:
- the files open, there are no blank pages, and every font is embedded;
- text stays inside the margins and font sizes stay within the limits;
- the text layer has the name first and the sections in order;
- every bullet is present in both the DOCX and the PDF;
- no heading is stranded at the bottom of a page;
- the DOCX XML is in schema order.

Page previews are saved to `v<n>/preview/` for visual review.

## 5. Applying safely

- `Application.job_id` is unique: one application per job.
- `previously_applied` also covers duplicates and reposts.
- A submission:
  1. re-checks the emergency stop, the state, approval or the automatic policy, prior attempts,
     resume validity and the attachment checksum;
  2. **commits an attempt row**;
  3. only then calls the route.
- A timeout leaves `UNKNOWN`. A process crash leaves `STARTED`, which startup recovery turns into
  `UNKNOWN`. Either way, the job waits in `needs_manual` until **Verify** asks the route (the
  mock ATS can answer; email cannot), and nothing is ever resubmitted automatically.
- Outcomes are recorded honestly:
  - `confirmed` needs a reference;
  - a mail server's acceptance, or your word without a reference, is `uncertain`;
  - a failure is `failed`, with retryable and permanent failures kept distinct (at most 3 attempts).

## 6. Outbound email

All email goes through one `EmailSender`:
- `file` writes `.eml` files and sends nothing;
- `smtp` uses STARTTLS;
- `gmail_api` uses an OAuth refresh token.

Message-IDs are deterministic per logical message. Personal notifications go through an outbox
with unique dedupe keys:
- exponential backoff, dead after 6 attempts;
- held while no recipient is set, or during an emergency stop.

Recruiter email has its own safeguards:
- verified contacts only (personal domains and addresses from injected text are refused);
- one email per recipient per job, enforced by a unique key;
- a daily cap;
- drafts by default.

## 7. Data model

The tables are `user_profile`, `automation_policy`, `resume_master`, `resume_version`,
`resume_tailoring_run`, `job_source`, `job_posting`, `job_requirement`, `job_match`,
`application`, `application_answer`, `application_attempt`, `recruiter_contact`, `email_draft`,
`email_delivery`, `notification_outbox`, `approval_request`, `scheduled_task` and `audit_event`,
plus the account tables `app_user`, `user_session`, `auth_token`, `user_integration` (encrypted
per-user secrets) and `platform_setting`. `application.scheduled_for` and
`email_draft.scheduled_for` hold when an automatic action is due (see `workflow/timing.py`). Statuses are strings
validated in Python, which keeps migrations simple. JSON columns are JSONB on PostgreSQL.

## 8. Deviations from the brief

- **Layout.** The app is under `apps/hirefinch/` and reuses `libs/agents-core`, following this
  workspace's conventions (`README.md` at the root), rather than a top-level `hirefinch/`.
- **Resume paths.** They are `artifacts/resumes/<company>/job-<id>/v<n>/resume_<family>.*`. The
  extra `v<n>` level keeps the file actually submitted immutable when you regenerate.
- **Scheduler.** It is an in-process asyncio loop over a persistent `scheduled_task` table with
  leases, not Celery or APScheduler. It is sufficient for one user and one process, with no extra
  infrastructure.
- **No form-filling browser automation on third-party sites.** Their terms, CAPTCHAs and logins
  rule it out. Those jobs use the `manual` route.
