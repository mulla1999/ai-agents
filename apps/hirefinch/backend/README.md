# hirefinch backend

The Python package `hirefinch`: FastAPI app, services, connectors and the scheduler. See
[../README.md](../README.md) for setup and [../docs/architecture.md](../docs/architecture.md)
for the design.

```bash
# from the workspace root
make hirefinch-migrate                        # alembic upgrade head (SQLite in apps/hirefinch/data by default)
make hirefinch-api                            # uvicorn --factory hirefinch.app:create_app on 127.0.0.1:8000
make hirefinch-test

.venv/bin/hirefinch upload-resume path/to/resume.docx --activate
.venv/bin/hirefinch load-config --profile apps/hirefinch/config/profile.yaml
.venv/bin/hirefinch run [--source mock]       # one discovery + pipeline pass
.venv/bin/hirefinch tick                      # run due scheduled tasks once (e.g. from cron with the scheduler off)
.venv/bin/hirefinch recover                   # mark interrupted submissions for verification
```

New migration after changing `db/models.py`:
`cd apps/hirefinch/backend && ../../../.venv/bin/alembic revision --autogenerate -m "..."`.
Review it, then run `alembic check`.
