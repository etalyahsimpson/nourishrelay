# Infrastructure & Deployment Configuration

## Service graph (Docker Compose)

```
                       localhost:3000                localhost:8000
                            │                              │
                       ┌────▼─────┐                  ┌──────▼──────┐
                       │   web    │  server-side    │     api     │
                       │ Next.js  │──proxy /api/v1──►  FastAPI    │
                       │ Node 22  │  (API_PROXY_     │  Python 3.12│
                       └──────────┘   TARGET)        └──────┬──────┘
                                                        │        │
                                            ┌───────────▼──┐  ┌──▼────────┐
                                            │  db          │  │  redis     │
                                            │  PostgreSQL16│  │  Redis 7   │
                                            │ (volume)     │  │ (broker)  │
                                            └────────▲─────┘  └──▲────────┘
                                                     │           │
                                          ┌──────────┴───────────┴──────┐
                                          │  worker + beat (Celery)      │
                                          │  expiry & notification jobs │
                                          └─────────────────────────────┘
```

- `db` — PostgreSQL 16 (`postgres:16-bookworm`), named volume `pgdata`,
  `pg_isready` healthcheck. Authoritative store for **all** business state.
- `redis` — Redis 7 (`redis:7-bookworm`), internal broker only; no business
  state is held exclusively in Redis.
- `api` — FastAPI (uvicorn) on container port 8000; runs versioned migrations
  and the idempotent seed at startup; readiness at `/api/v1/ready`.
- `worker` / `beat` — Celery worker and single-instance scheduler for expiry
  and simulated-notification tasks.
- `web` — Next.js production server on port 3000; proxies same-origin
  `/api/v1/*` requests to `http://api:8000` server-side, so browsers never
  see internal Docker hostnames.

## Ports and exposure

| Service | Container port | Published (localhost only) |
|---|---|---|
| web | 3000 | `127.0.0.1:3000` |
| api | 8000 | `127.0.0.1:8000` |
| db | 5432 | **not published** |
| redis | 6379 | **not published** |

## Volumes

- `pgdata` — PostgreSQL data directory (synthetic demo data). Removable with
  `docker compose down -v` (destroys only this stack's demo database).

## Environment

See `.env.example` at the repository root. Required values: `POSTGRES_PASSWORD`
(demo-only), `SESSION_SECRET` (generate a unique random value for any
non-demo run). `NEXT_PUBLIC_API_URL` defaults to `/api/v1` (same-origin proxy
mode); the alternative direct mode `http://localhost:8000/api/v1` is covered in
`docs/DEPLOYMENT_RUNBOOK.md` (cross-origin cookie/CORS behavior).

## Hosted-run preconditions (beyond local Docker)

Self-hosting this stack on an internet-reachable host requires, at minimum:
unique generated `SESSION_SECRET`/`POSTGRES_PASSWORD`, TLS termination in front
of ports 3000/8000 (cookies are `Secure` when the public origin is https),
restricted network exposure of db/redis (never published), recurring PostgreSQL
backups (`scripts/backup.sh`), and an explicit organizational review of whether
the demo identity model fits the operating environment. The cloud option
discussed in the specification (AWS) was **not** authorized or deployed for
this release; see `docs/DEPLOYMENT_RUNBOOK.md` for the honest status.
