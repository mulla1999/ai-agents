# AI Agents

[![HireFinch CI](https://github.com/mulla1999/ai-agents/actions/workflows/hirefinch-ci.yml/badge.svg)](https://github.com/mulla1999/ai-agents/actions/workflows/hirefinch-ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![React 19](https://img.shields.io/badge/react-19-61dafb)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Two production-minded AI agents built on one shared, provider-agnostic core. Each runs on Azure
OpenAI, Gemini or any OpenAI-compatible model, chosen by configuration. Every decision that has to
be correct (scoring, state, policy, validation) is deterministic code, and the LLM only proposes
wording that validators accept or reject.

| Project | What it does |
|---|---|
| **[HireFinch](apps/hirefinch)** | Multi-user job-search agent: finds jobs, scores them against your verified resume, tailors the resume, prepares applications and recruiter emails, and fills application forms through a Chrome extension. Nothing is sent without approval in supervised mode. |
| **[Saathi](apps/saathi)** | Helps people in India find government welfare schemes they qualify for, in their own language, on the web and WhatsApp. |
| **[agents-core](libs/agents-core)** | Shared building blocks: switchable LLM providers, PII redaction, a WhatsApp channel and a scripted LLM for tests. |

## HireFinch at a glance

- **Job discovery from 9 source types.** It reads the official public APIs of Greenhouse, Lever,
  Ashby and SmartRecruiters, plus Jooble, The Muse and Adzuna, company career pages
  (schema.org `JobPosting`), and LinkedIn/Naukri/Indeed alert emails over IMAP. A **Find company**
  search detects which job board a company uses and follows it. Sites that forbid automated access
  are never scraped.
- **Explainable matching.** Jobs are scored against the candidate's skills and experience. Years
  of experience are computed from dates, and a skill counts only with evidence. Every score shows
  its criteria, and a skill-gap flow asks about skills the resume doesn't mention.
- **Resume tailoring that never invents facts.** The tailoring step selects and reorders real
  content. Every AI rewrite is checked against the master resume, and numbers, employers and
  skills that aren't in the source are rejected.
- **ATS parse test.** The real PDF and Word files are rendered, parsed back and compared fact by
  fact ("98 of 98 facts read back"), alongside a separate recruiter-readiness review.
- **Resume Builder and interview prep.** Writing guidance is adapted from MIT-licensed skill
  packs, with pinned and hash-verified sources.
- **Safe automation.** An explicit state machine drives each job, with an audit event for every
  transition. Outbound actions are idempotent, so a crash never repeats them. Daily caps and
  sending windows apply, and an emergency stop halts everything.
- **Security.**
  - Every outbound request goes through one fetcher with an SSRF guard, a host allowlist,
    robots.txt checks and rate limits.
  - Each user's secrets are encrypted with Fernet key rotation.
  - Sessions use CSRF tokens, with optional TOTP 2FA and Google sign-in.
  - Job descriptions and emails are treated as untrusted input, with prompt-injection and scam
    checks.
- **Chrome extension (Manifest V3).** It fills an employer's application form from the prepared
  application, and leaves sensitive questions (religion, caste, nationality and similar) for the
  person.

### Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 |
| Data | PostgreSQL (production) or SQLite (local) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, TanStack Query |
| AI | Azure OpenAI, Gemini or OpenAI-compatible models through one `LLMProvider` interface |
| Documents | DOCX and PDF rendering, PDF/DOCX parsing |
| Delivery | Docker Compose, Caddy (automatic HTTPS), GitHub Actions CI, Tailscale Funnel / Cloudflare tunnel for self-hosting |
| Quality | ~500 backend tests and 48 frontend tests (pytest, Vitest, Testing Library), ruff, strict TypeScript |

Read more in the [HireFinch README](apps/hirefinch/README.md) and its
[architecture notes](apps/hirefinch/docs/architecture.md).

## Repository layout

```
.
├── libs/agents-core/        shared LLM providers, PII redaction, WhatsApp channel, test fakes
├── apps/
│   ├── hirefinch/           job-search agent
│   │   ├── backend/         FastAPI app (Python package `hirefinch`)
│   │   ├── frontend/        React web app
│   │   ├── extension/       Chrome extension
│   │   └── docs/            architecture and deployment
│   └── saathi/              welfare-scheme assistant (backend, frontend, docs)
├── .github/workflows/       CI
├── .env.example             every setting, with comments
└── Makefile                 install, test, lint, run and deploy targets
```

## Getting started

```bash
make install                 # creates .venv and installs every package in editable mode
cp .env.example .env         # fill in the LLM settings and the sections you need
make test                    # every Python test; no API keys or network needed
make lint                    # ruff
make hirefinch-api           # HireFinch API on http://127.0.0.1:8000 (SQLite)
make hirefinch-web           # HireFinch web app on http://localhost:5173 (Node runs in Docker)
```

Secrets come only from the environment or a secrets manager; `.env` is never committed.

## Adding a new agent

1. Create `apps/<name>/backend/` with `pyproject.toml`, `src/<name>/`, `tests/` and `README.md`
   (add `frontend/` if it has a UI), depending on `agents-core`.
2. Read LLM settings through `agents_core.llm.LLMSettings` and create the model with `create_llm`,
   never a provider SDK directly, so the agent stays provider-agnostic.
3. Give the agent its own settings prefix (`<NAME>_*`) and a section in `.env.example`.
4. Add it to `requirements-dev.txt` and write tests against `agents_core.llm.testing.ScriptedLLM`.

Code moves into `libs/agents-core` only once a second agent needs it.

## More projects

- **[Face Identity Service](https://github.com/mulla1999/face-service)**: face verification and real-time
  identification API (InsightFace ArcFace, FAISS, FastAPI).
- **[Task Management System](https://github.com/mulla1999/sprih-task-management-system)**: Spring Boot
  REST API with filtering, pagination and sorting.

## License

[MIT](LICENSE). Third-party material is listed in
[apps/hirefinch/THIRD_PARTY_NOTICES.md](apps/hirefinch/THIRD_PARTY_NOTICES.md).
