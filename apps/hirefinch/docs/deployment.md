# Deploying HireFinch (multi-user)

One server runs PostgreSQL, the API (with the scheduler), the web app, and Caddy for HTTPS, all with
Docker Compose. It suits a small community of users. See "Scaling" before going beyond one
instance.

## 1. Server

- A Linux VM with 2 vCPU, 4 GB RAM and 20 GB disk, and Docker 24+ with the compose plugin.
- A DNS record (for example `jobs.yourdomain.com`) pointing at the server.
- Ports 80 and 443 open. Nothing else needs to be public: the database and API are reachable only
  inside the Compose network.

## 2. Secrets (`.env` at the workspace root on the server)

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                               # HIREFINCH_SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # HIREFINCH_ENCRYPTION_KEYS
python3 -c "import secrets; print(secrets.token_urlsafe(24))"                               # HIREFINCH_DB_PASSWORD
```

```
HIREFINCH_DOMAIN=jobs.yourdomain.com
HIREFINCH_SUPERADMIN_EMAIL=you@example.com
HIREFINCH_SECRET_KEY=...
HIREFINCH_ENCRYPTION_KEYS=...
HIREFINCH_DB_PASSWORD=...
```

- **Store `HIREFINCH_ENCRYPTION_KEYS` in a password manager.** Every user's SMTP password and AI key
  is encrypted with it; if you lose it, users must enter those again. To rotate, put a new key
  first and keep the old one after a comma. Re-saved secrets then use the new key.
- `chmod 600 .env`, and never commit it. Nothing in the database holds a plaintext secret.

## 3. Start

```bash
SKIP_BACKUP=1 apps/hirefinch/deploy/deploy.sh   # on the server, first time: build, start, wait for HTTPS
# Later upgrades back up first. From your machine (runs the tests, then copies and deploys):
#   make hirefinch-deploy TARGET=me@server
docker compose --env-file .env -f apps/hirefinch/docker-compose.yml -f apps/hirefinch/docker-compose.prod.yml \
  exec backend hirefinch create-superadmin --email you@example.com      # prompts for the password
```

Caddy obtains the TLS certificate automatically on first request. The backend refuses to start in
production without the secret key, the encryption key, an `https://` public URL and secure cookies.
The demo job source and the simulated ATS are switched off.

## 4. First steps as superadmin

1. Sign in, then go to **Administration → Platform settings → System email**. Enter the account that
   sends verification and password-reset emails, for example Gmail with an App Password, then click
   **Send test**. Until this works, nobody can confirm a new account.
2. Decide on **Registration**: open, closed, or limited to email domains. Set **Limits**: resumes
   per user, companies per source, minimum discovery interval, and daily caps on recruiter emails
   and applications.
3. Each user then sets up their own email, AI key and job sources under **Integrations**.

### Optional platform features

- **Sign in with Google.**
  1. In Google Cloud Console, open APIs & Services → Credentials → OAuth client ID → Web application.
  2. Add the redirect URI shown under **Platform settings → Sign in with Google**
     (`https://<domain>/api/auth/google/callback`).
  3. Paste the client id and secret into that card. The button then appears on the sign-in page.
- **System email at volume.** Gmail caps how much one account can send per day. For a busy
  platform, choose **Resend**: verify your domain in Resend, create an API key and select it in the
  system email card. Any transactional service that offers SMTP also works through the SMTP option:
  Amazon SES, Postmark, SendGrid and Brevo all do.
- **Two-factor sign-in.** Each user turns it on under Account → Two-factor sign-in, with any
  authenticator app. They get 10 single-use recovery codes. Encourage admins to use it.
- **Data retention.** Under Platform settings → Data retention: accounts with no sign-in for
  `inactive_days` (default 365, minimum 90, 0 = keep forever) get a warning email. After `warn_days`
  (default 30) they are deleted with all their data. Audit and notification history is trimmed
  separately. The superadmin is never deleted. State the same rule in your privacy notice.

## 5. What protects users

| Risk | Control |
|---|---|
| One user reading another's data | Every row has an owner, and every query and file download checks it. Other users' ids return 404. Covered by tests. |
| Stolen database | Passwords are scrypt hashes. Sessions and tokens are stored as SHA-256 hashes. SMTP and AI secrets are Fernet-encrypted with a key held outside the database. |
| Secrets leaking through the UI or API | Secret fields are write-only: the API returns only which fields are set. Admins never see them. |
| The server attacking its own network (SSRF) | User-entered SMTP hosts and AI endpoints must resolve to public addresses, and SMTP only on mail ports. This is checked on save and on every use. |
| Using the server's cloud identity | AI providers always need the user's own key. Azure managed identity and Vertex service accounts are not offered. |
| Account takeover | Lockout after 10 failures, per-IP rate limits, verified email, password reset by single-use 1-hour link, and all sessions ended on password change or reset. |
| Account enumeration | Sign-up and password-reset responses are identical whether or not the email exists. |
| Spam through the platform | Recruiter emails need a verified contact and go out one per recipient per job, under the user's limit and the platform cap. Users send from their own mailbox. |
| CSRF and clickjacking | Double-submit CSRF token on every state-changing call, SameSite cookies, CSP, `frame-ancestors 'self'`. |

Users can delete their account and everything in it (Account → Delete). Admins can disable accounts,
which ends their sessions at once.

## 6. Backups

`make hirefinch-backup` (`deploy/backup.sh`) writes the database dump and the files volume together
to `backups/hirefinch-<time>/` with checksums, and keeps 14 days. Schedule it daily:

```
30 2 * * * cd /opt/hirefinch && apps/hirefinch/deploy/backup.sh >> backups/backup.log 2>&1
```

Copy `backups/` off the server too. The encryption key is not in the backup on purpose; keep
`HIREFINCH_ENCRYPTION_KEYS` in a password manager. A database without its files, or without that
key, is incomplete.

Restore into a staging server first: `pg_restore --clean -U hirefinch -d hirefinch db.dump`, then
untar `files.tgz` into the files volume (`/var/lib/hirefinch` in the backend container).

## 7. Upgrades

```bash
make hirefinch-deploy TARGET=me@server   # from your machine: tests, copy, backup, rebuild, health check
# or on the server after git pull: apps/hirefinch/deploy/deploy.sh
# The backend runs `alembic upgrade head` before serving.
```

Take a backup first. Migrations are tested on SQLite and PostgreSQL, but downgrades are not
supported: restore the backup instead.

## 8. Scaling

- The production overlay runs Redis, so sign-in rate limits are shared by every backend instance.
  If Redis is down, each instance falls back to its own counters, and account lockout stays in the
  database. Scheduled tasks use database leases, so several instances never run the same task at
  once. For many users, run one extra backend with `HIREFINCH_SCHEDULER_ENABLED=false` per API replica.
- Discovery and resume generation run per user, one after another. With many active users, raise
  the minimum discovery interval in Limits, or move the scheduler to a separate worker container.

## 9. Before you invite other people

- Publish real terms and a privacy notice. The bundled `/privacy` page is a plain summary, not legal
  advice. You will hold other people's resumes and contact details.
- Job boards' terms apply to everyone who uses the platform. The agent only uses official public
  job-board APIs and pages that allow it in robots.txt.
- Decide how long to keep data of inactive accounts, and say so in the privacy notice.
