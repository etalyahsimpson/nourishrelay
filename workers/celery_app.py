"""Celery application for NourishRelay background jobs.

Broker/result backend: Redis (approved transport). PostgreSQL remains the
authoritative state store; a broker outage degrades expiry TIMING only —
correctness is never Redis-dependent (see docs/DECISIONS.md).

PYTHONPATH must include services/api (app package) and workers/ — both the
Docker image and the compose worker/beat services set this up.
"""

from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "nourishrelay",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["workers.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,  # at-least-once delivery; all tasks are idempotent
    worker_prefetch_multiplier=1,
    result_expires=3600,
    beat_schedule={
        "expire-proposals": {
            "task": "workers.tasks.expire_proposals_task",
            "schedule": 60.0,
        },
        "expire-donations": {
            "task": "workers.tasks.expire_donations_task",
            "schedule": 60.0,
        },
        "worker-heartbeat": {
            "task": "workers.tasks.worker_heartbeat_task",
            "schedule": 60.0,
        },
        "simulate-notifications": {
            "task": "workers.tasks.simulate_notifications_task",
            "schedule": 300.0,
        },
    },
    beat_schedule_filename="/tmp/nourishrelay-beat-schedule",  # beat runs single-instance
)
