# HireFinch

A multi-user job-search agent. Each person signs up, uploads their own resume, and connects their own
email, AI key and job sources. The agent finds jobs, scores each one against that person's verified
resume, tailors the resume for each job, and manages their applications. One superadmin runs the
platform. In supervised mode (the default) nothing is
submitted or sent until you approve it. Every external action is audited, and none is ever
repeated after a crash or a retry.

```
apps/hirefinch/
├── backend/             FastAPI + SQLAlchemy + Alembic (Python package `hirefinch`)
│   ├── src/hirefinch/
│   │   ├── api/             HTTP routers, sign-in + CSRF middleware
│   │   ├── connectors/      job sources (Greenhouse, Lever, Ashby, SmartRecruiters, Jooble, The Muse, Adzuna,
│   │   │                    career pages, LinkedIn/Naukri/Indeed alert emails) + catalogue
│   │   ├── jobs/            JD parser, matching engine, dedupe, prompt-injection & scam checks
│   │   ├── resume/          resume parser, tailoring, validator, DOCX/PDF renderer
│   │   ├── applications/    question answering, approval policy, submission routes
│   │   ├── notifications/   email providers (file, SMTP, Gmail API), outbox
│   │   ├── services/        ingest, tailoring, applications, outreach, notifications, settings, audit
│   │   ├── workflow/        state machine and pipeline orchestrator
│   │   ├── scheduler.py     persistent background tasks
│   │   ├── net.py           the only outbound HTTP client (allowlist, SSRF, robots.txt, rate limits)
│   │   └── llm_assist.py    optional LLM steps; every output is re-validated
│   ├── migrations/      Alembic (SQLite and PostgreSQL)
│   └── tests/           ~390 tests; mocked sources and email, nothing real is sent
├── frontend/            React 19 + TypeScript + Vite + Tailwind; 16 pages
├── extension/           Chrome extension (Manifest V3) that fills employers' application forms
├── config/              *.example.yaml profile, preferences and policy templates
├── artifacts/           generated resumes, JD snapshots, application records (gitignored)
├── data/                SQLite database, master resumes, local mailbox (gitignored, created on first run)
├── docs/architecture.md, docs/deployment.md
├── deploy/Caddyfile     HTTPS front door for production (docker-compose.prod.yml)
├── docker-compose.yml       PostgreSQL + API + nginx/UI
└── docker-compose.home.yml  share from your own PC through a tunnel (no open ports)
```

## Quick start (local, SQLite)

From the repository root:

```bash
make install                       # once: installs every workspace package into .venv
make hirefinch-test                # ~390 tests, under a minute, no keys or network needed
make hirefinch-api                 # migrates data/hirefinch.db and serves http://127.0.0.1:8000
make hirefinch-web                 # second terminal: UI on http://localhost:5173 (Node runs in Docker)
```

Open http://localhost:5173 and sign in. Your account is the superadmin, set by
`HIREFINCH_SUPERADMIN_EMAIL` in `.env`. Create it with `.venv/bin/hirefinch create-superadmin`, which
prompts for the password. Data from before accounts existed belongs to this account. Then:

1. **Profile & Preferences**: upload your resume (PDF or DOCX), check the parsed structure, and
   fill in the facts forms ask for (notification email, notice period, expected CTC, work
   authorisation). Blank fields stay blank: forms that need them wait for you.
2. **Integrations**: your own email (SMTP or Gmail API), AI provider (Azure OpenAI,
   OpenAI-compatible or Gemini) and job sources. Secrets are encrypted and never shown again.
3. **Dashboard → Run discovery now**, then review the **Application Queue**.

Other people sign up at `/register` and confirm their email. Locally, without a platform email,
the confirmation link is shown on screen. In production, set the system email under
**Administration → Platform settings** first.

## Production (Docker Compose, PostgreSQL, HTTPS)

See **[docs/deployment.md](docs/deployment.md)** for the full checklist. In short: set
`HIREFINCH_DOMAIN`, `HIREFINCH_DB_PASSWORD`, `HIREFINCH_SECRET_KEY`, `HIREFINCH_ENCRYPTION_KEYS` and
`HIREFINCH_SUPERADMIN_EMAIL`, then run `make hirefinch-prod-up`, which adds Caddy with automatic TLS.

Local Docker stack without HTTPS:

```bash
make hirefinch-up                  # http://localhost:8090 (bound to 127.0.0.1)
make hirefinch-logs
make hirefinch-down                # data stays in the hirefinch-pgdata and hirefinch-files volumes
```

For anything reachable beyond localhost, set `HIREFINCH_ENVIRONMENT=production`. The app then
refuses to start without a 32+ character secret key, a 12+ character admin password and
`HIREFINCH_COOKIE_SECURE=true`. Put it behind HTTPS.

**Deploy, upgrade and back up** (production overlay):

```bash
make hirefinch-deploy TARGET=me@server     # from your machine: tests, copy (never .env or data), backup, build, HTTPS check
apps/hirefinch/deploy/deploy.sh            # or on the server itself, after git pull
make hirefinch-backup                      # database + files to ./backups, 14 days kept; schedule it with cron
```

CI (`.github/workflows/hirefinch-ci.yml`) runs the backend tests, the PostgreSQL migration check and
the web app build and tests. It never deploys on its own.

**Share from your own PC** (free, no domain, no open ports): `make hirefinch-home-up` runs the API,
the web app and a tunnel in Docker with restart policies. All services share one private network
namespace, so nothing binds a port on the host. The tunnel is Tailscale Funnel when
`data/tailscale.key` holds an auth key (a fixed `https://hirefinch.<tailnet>.ts.net` address), or a
Cloudflare quick tunnel otherwise. `make hirefinch-home-logs` and `make hirefinch-home-down` follow and stop it.

Locally, copy `apps/hirefinch/data/` and `apps/hirefinch/artifacts/` while the API is stopped.
Restore into a staging copy first.

## Configuration

| What | Where |
|---|---|
| Profile, preferences, automation policy | UI (stored in the DB, every change audited). Templates: `config/*.example.yaml`; load with `hirefinch load-config --profile … --preferences …` |
| Platform secrets and infrastructure | `.env` (`HIREFINCH_SECRET_KEY`, `HIREFINCH_ENCRYPTION_KEYS`, database, domain; see the section in the root `.env.example`). Never in files under git. |
| Each user's AI key, email, job-alert mailbox, Adzuna/Jooble keys | **Integrations** page, per account, encrypted in the database. Secret fields are write-only. AI is optional: off unless **Use the LLM** is ticked in Automation. `hirefinch import-env-integrations` copies the old `HIREFINCH_EMAIL_*`/`SMTP_*` values into one account once. |
| Platform email (sign-up and reset links) | **Administration → Platform settings → System email** (SMTP or Resend). |
| Job sources | Integrations page: enable a source and give its config, e.g. Greenhouse `{"boards": [{"token": "stripe", "company": "Stripe"}]}`, career pages `{"pages": ["https://careers.example.com/jobs"]}`, Adzuna `{"country": "in", "queries": ["java backend"]}`. Single postings: **Jobs → Import job → Fetch** fills the form from a link. |

## Job assistant (chat)

Open **Assistant** in the sidebar, or the chat button on any page. Ask in plain words:
- "find backend jobs in Pune posted this week";
- "tell me about #12";
- "apply to #12";
- "email the recruiter for #12";
- "what's my status?";
- "my notice period is 60 days";
- or paste a job link.

With an AI provider (Integrations) it understands free-form requests. Without one it runs in quick
mode on the same commands. Applying, sending email and profile changes always wait for **Confirm**.
For live web results, add a Brave Search or Tavily key under Integrations → Web search.

## Browser extension: Auto-apply on employer sites

Employer sites (Greenhouse, Lever, Ashby, Workday) give candidates no submission API, so the agent
applies there through your own browser with the extension (`extension/`, Chrome and Edge, Manifest V3).

**Set up once:**
1. **Account → Browser extension:** download it (`make hirefinch-extension` builds the zip) and load it
   unpacked in `chrome://extensions`.
2. Create a key and paste it with this site's address into the extension's settings.
3. Tick **Allow Auto-apply on Greenhouse, Lever and Ashby**.

**For each job:** click **Auto-apply with the extension** on the application in the Queue. The
extension then:
1. opens the employer's form with a signed, 15-minute ticket for that one application;
2. fills your details and prepared answers, and attaches the tailored resume;
3. submits it, but only when every required field is filled, the resume is attached, there is exactly
   one Submit button, no CAPTCHA and no error showing, after a 5-second countdown you can cancel;
4. records the application as **confirmed** only when the employer's "thank you / application
   received" page appears. You then get the "Applied: <job> at <company>" email with the submitted
   resume attached. Without that page it is recorded as "uncertain" so you check.

When anything is uncertain, it fills what it can, shows what needs you on the page, and leaves the
submit to you. On other career sites, open the form and click the extension → **Fill and submit if
certain**.

**What it never does:**
- touch a CAPTCHA;
- answer gender, diversity, disability or legal questions, or yes/no questions it isn't sure about;
- overwrite what you typed;
- run on LinkedIn, Naukri or Indeed.

Automatic submit can be switched off in the extension settings.

## Supervised and automatic modes

- **Supervised (default).** Every application waits in the Application Queue. **Approve and
  submit** sends it through its route. Jobs that use the employer's own form (route `manual`)
  give you the package; you apply there, then click **I applied manually** and enter the reference.
- **Automatic.** In **Automation Settings**, set the mode to automatic and type
  `ENABLE AUTOMATIC MODE`. The change is audited. An application is then submitted only when
  **every** condition holds:
  - the score is at least the automatic threshold (default 85);
  - the match is recommended and the role is close to your targets;
  - the job is not expired, not suspicious and has no injected text;
  - you have not applied to it or to a duplicate of it;
  - the resume passed validation;
  - every question has a verified answer;
  - the route is automatable and enabled, and the daily and weekly limits are not reached.

  Anything else falls back to the queue. Demographic questions, legal declarations, CAPTCHAs and
  free-text answers always wait for you.
- **When automatic actions happen.** An automatic application or recruiter email is scheduled,
  not sent at once. It waits for the review period (default 60 minutes; you are notified and can
  choose **Hold** in the queue or **Cancel** in Outreach), then goes out in the next send window,
  by default Mon–Fri 09:30–12:30 and 14:00–16:30 in your timezone, when recruiters are working
  through their inbox. Discovery runs 06:00–22:00, so overnight postings are ready before the
  morning window. All of this is in Automation Settings. Anything you approve yourself is sent at once.
- Automatic recruiter emails are a separate switch with the same confirmation phrase.
- **Pause** stops scheduled work. **Emergency stop** also blocks every submission and email,
  including approved ones, until you clear it.

## Tests

```bash
make hirefinch-test                                              # everything mocked
HIREFINCH_LIVE_TESTS=1 .venv/bin/pytest -m live apps/hirefinch/backend/tests   # read-only call to a public Greenhouse board
```

## Security notes

- Job descriptions, web pages and emails are untrusted data:
  - They are shown as plain text and scanned for prompt injection, including hidden HTML.
  - They are quoted as data in any LLM prompt.
  - They are never allowed to change a policy decision.
- Outbound HTTP is limited:
  - only allow-listed hosts, over HTTPS;
  - every redirect hop is re-checked;
  - private and metadata IP addresses are refused;
  - robots.txt is honoured for pages;
  - there is a per-host interval, a size cap and bounded retries.
- Sign-in and API protection:
  - one admin password with a signed HttpOnly SameSite cookie;
  - double-submit CSRF on every state-changing API call;
  - the dev server binds to 127.0.0.1.
- Secrets come only from the environment. The integrations table records which variables are
  read, never their values. Logs and the audit trail never contain tokens or whole documents.
- Sensitive answers (salary, demographic) are masked in the API and replaced after submission.
  CSV exports neutralise spreadsheet formulas.
