# Saathi

An open-source assistant that helps people in India find government welfare schemes they qualify
for, in their own language, prepare the documents, and track their applications. It works on the
web and over WhatsApp.

> **Status: early MVP.** The seed scheme data consists of **unverified drafts**. An admin must
> check each scheme against its official source and mark it verified before real users rely on it.

| Who | Uses Saathi to |
|---|---|
| **Citizen** | Chat in their own language, see eligible schemes, get document checklists, track applications |
| **Helper** (volunteer / CSC operator) | Register people without a smartphone and do all of the above for them |
| **Admin** | Edit and verify scheme data, manage roles, see usage |

The design is in [docs/architecture.md](docs/architecture.md): system overview, sign-in flows,
database schema, security controls and the API.

## Layout

```
apps/saathi/
├── backend/            FastAPI + SQLAlchemy + Alembic (Python package `saathi`)
│   ├── src/saathi/
│   │   ├── api/        HTTP routers and schemas
│   │   ├── auth/       sessions, CSRF, Google OIDC, OTP, SMS, role checks
│   │   ├── services/   access control, schemes, conversations, applications, audit
│   │   ├── agent/      LLM conversation loop
│   │   ├── schemes/    eligibility rules engine
│   │   └── db/         tables
│   ├── migrations/     Alembic
│   ├── data/schemes/   seed scheme YAML
│   └── tests/
├── frontend/           React + TypeScript + Vite + Tailwind, served by nginx
│   └── src/{api,auth,components,features,i18n}
├── docs/architecture.md
└── docker-compose.yml  PostgreSQL + backend + frontend
```

## Run it (Docker Compose)

From the workspace root:

```bash
cp .env.example .env
# In .env set at least:
#   SAATHI_DB_PASSWORD   random string
#   SAATHI_SECRET_KEY    random string (python3 -c "import secrets; print(secrets.token_urlsafe(48))")
#   LLM settings         for chat (Azure OpenAI or Gemini); everything else works without them
make saathi-up          # http://localhost:8080
make saathi-logs        # development OTP codes are printed here
make saathi-down
```

Migrations and the seed schemes are applied automatically when the backend starts.

### First admin

- **Google:** put your email in `SAATHI_ADMIN_EMAILS` and sign in with Google.
- **Phone:** sign in once, then run
  `docker compose --env-file .env -f apps/saathi/docker-compose.yml exec backend saathi users set-role 98765XXXXX admin`

Admins promote helpers on the **Users** page.

### Google sign-in

In Google Cloud Console, create an OAuth client of type **Web application** with this authorized
redirect URI: `<SAATHI_PUBLIC_URL>/api/auth/google/callback`. Then set `SAATHI_GOOGLE_CLIENT_ID`
and `SAATHI_GOOGLE_CLIENT_SECRET`. The Google button only appears once these are set.

### WhatsApp (chat, voice notes, free sign-in)

1. Create a Meta app with the WhatsApp product; set the four `SAATHI_WHATSAPP_*` values.
2. Register `<SAATHI_PUBLIC_URL>/webhooks/whatsapp` as the webhook (HTTPS) and subscribe to `messages`.
3. Set `SAATHI_WHATSAPP_LOGIN_NUMBER` to the bot's number to show **Sign in with WhatsApp** on the
   website. It costs nothing per sign-in, because messages people send to the bot are free.

People who message the bot get the same account and profile as a web sign-in with that number.
For **voice notes**, set `SPEECH_PROVIDER`:

| Provider | Cost | Notes |
|---|---|---|
| `azure` | Free F0 tier: 5 hours speech-to-text + 0.5M characters text-to-speech a month | 13 Indian languages |
| `bhashini` | Free API access for proof-of-concept use; confirm production terms with Bhashini | 22 languages, government service |
| `bhashini` + `BHASHINI_INFERENCE_URL` | Free, self-hosted on your GPU | AI4Bharat models (MIT/Apache-2.0) via Dhruva-Platform |

WhatsApp pricing (from 1 Oct 2026): 1,000 free service replies per number per month, then about
₹0.115 per message. Inbound messages are always free.

### SMS for OTP

`SAATHI_SMS_PROVIDER=console` writes codes to the backend log and is refused in production.
Set it to `twilio` with the `SAATHI_TWILIO_*` values to send real SMS. Commercial SMS to Indian
numbers also needs DLT registration of the sender ID and message template, and there is no free
route, so prefer **Sign in with WhatsApp** above.

## Develop without Docker

```bash
make install && source .venv/bin/activate
# PostgreSQL running locally; set SAATHI_DATABASE_URL in .env. Run these from the workspace root
# so the root .env is read.
alembic -c apps/saathi/backend/alembic.ini upgrade head
saathi seed
saathi serve                                   # API on :8000
cd apps/saathi/frontend && npm install && npm run dev   # UI on :5173, proxies /api
```

## Tests

```bash
make test                     # Python tests (SQLite in memory, fake LLM and SMS; no keys needed)
make saathi-frontend-build    # TypeScript check and production build
```

## Scheme data sources

myScheme's terms of use forbid scraping, and datasets published as "open" on Hugging Face were
scraped from it, so Saathi does not use them. Scheme records are written by hand from official
guidelines, each with its `source_url`. To scale up, ask myScheme / API Setu for written permission
or API access as a non-commercial open-source project. data.gov.in (GODL-India licence) has useful
statistics but not eligibility rules.

## Before a public launch

- Verify every scheme (Admin → Schemes), then set `SAATHI_INCLUDE_DRAFT_SCHEMES=false`.
- `SAATHI_ENVIRONMENT=production`, HTTPS in front of nginx, `SAATHI_COOKIE_SECURE=true`.
- Real SMS provider with DLT registration; PostgreSQL backups.
- DPDP Act review: privacy notice, consent text, retention periods, grievance officer contact.
