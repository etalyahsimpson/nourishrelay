# NourishRelay

**Move surplus food from offer to verified receipt — without double booking.**

> Portfolio demonstration | Synthetic data | Not for real food-safety or dispatch decisions.

NourishRelay is an independent portfolio project: a full-stack food-recovery
coordination platform with a deterministic, explanation-producing matching
engine, **atomic partial-quantity reservations** on PostgreSQL row locks, a
stateful pickup/receipt trail, Celery-driven expiry, and reports computed
strictly from recorded events.

**Status: implementation in progress — this repository is being built
release-first (backend → workers → web app → tests → docs). Clone and check
back, or inspect `docs/` for the engineering contract being implemented.**

Planned stack: FastAPI (Python 3.12) + PostgreSQL 16 + Redis/Celery + Next.js
(App Router, TypeScript, Tailwind CSS) + Docker Compose + GitHub Actions.

Owner: [@etalyahsimpson](https://github.com/etalyahsimpson)
