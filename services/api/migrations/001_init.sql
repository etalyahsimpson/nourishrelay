-- NourishRelay schema 001 — initial domain tables.
-- All quantities NUMERIC(12,3) kilograms; timestamps TIMESTAMPTZ (UTC);
-- half-open [start, end) windows; UUID primary keys.
-- Enum-like values validated by CHECK constraints + application-level guards.

BEGIN;

CREATE TABLE organizations (
    id           UUID PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('donor', 'recipient', 'transport', 'platform')),
    verified     BOOLEAN NOT NULL DEFAULT FALSE,
    service_area TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY,
    organization_id UUID REFERENCES organizations(id),
    display_name    TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('donor','recipient','transport','coordinator','admin','analyst')),
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT users_org_required
        CHECK (organization_id IS NOT NULL OR role IN ('coordinator','admin','analyst'))
);

CREATE TABLE recipient_profiles (
    organization_id      UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    accepted_categories   TEXT[] NOT NULL DEFAULT '{}',
    max_kg_per_day        NUMERIC(12,3) CHECK (max_kg_per_day IS NULL OR max_kg_per_day >= 0),
    handling_acknowledged TEXT[] NOT NULL DEFAULT '{}',
    receiving_start      TIME NOT NULL,
    receiving_end        TIME NOT NULL,
    timezone             TEXT NOT NULL DEFAULT 'UTC',
    active               BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (receiving_end > receiving_start)
);

CREATE TABLE donations (
    id            UUID PRIMARY KEY,
    donor_org_id  UUID NOT NULL REFERENCES organizations(id),
    created_by    UUID NOT NULL REFERENCES users(id),
    category      TEXT NOT NULL,
    quantity_kg   NUMERIC(12,3) NOT NULL CHECK (quantity_kg > 0),
    handling_tags TEXT[] NOT NULL DEFAULT '{}',
    pickup_start  TIMESTAMPTZ NOT NULL,
    pickup_end    TIMESTAMPTZ NOT NULL,
    deadline      TIMESTAMPTZ NOT NULL,
    status        TEXT NOT NULL DEFAULT 'DRAFT'
                  CHECK (status IN ('DRAFT','AVAILABLE','PARTIALLY_RESERVED','FULLY_RESERVED','CLOSED','EXPIRED','WITHDRAWN')),
    location_label TEXT NOT NULL,
    notes         TEXT,
    version       INT NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at  TIMESTAMPTZ,
    CHECK (pickup_end > pickup_start),
    CHECK (deadline > pickup_start),
    CHECK (deadline <= pickup_end)
);

CREATE TABLE donation_revisions (
    id          UUID PRIMARY KEY,
    donation_id UUID NOT NULL REFERENCES donations(id) ON DELETE CASCADE,
    version     INT NOT NULL,
    actor_id    UUID NOT NULL REFERENCES users(id),
    before_json JSONB NOT NULL,
    after_json  JSONB NOT NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (donation_id, version)
);

CREATE TABLE reservations (
    id                  UUID PRIMARY KEY,
    donation_id         UUID NOT NULL REFERENCES donations(id),
    recipient_org_id    UUID NOT NULL REFERENCES organizations(id),
    proposed_by         UUID NOT NULL REFERENCES users(id),
    quantity_kg         NUMERIC(12,3) NOT NULL CHECK (quantity_kg > 0),
    state               TEXT NOT NULL DEFAULT 'PROPOSED'
                        CHECK (state IN ('PROPOSED','ACCEPTED','DECLINED','CANCELLED','EXPIRED',
                                          'PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED','FAILED')),
    failure_stage       TEXT CHECK (failure_stage IN ('BEFORE_COLLECTION','AFTER_COLLECTION') OR failure_stage IS NULL),
    proposal_expires_at TIMESTAMPTZ,
    accepted_at         TIMESTAMPTZ,
    released_at         TIMESTAMPTZ,
    decline_reason      TEXT,
    cancel_reason       TEXT,
    failure_reason      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pickups (
    id                        UUID PRIMARY KEY,
    reservation_id            UUID NOT NULL UNIQUE REFERENCES reservations(id),
    assigned_transport_org_id UUID REFERENCES organizations(id),
    pickup_window_start       TIMESTAMPTZ NOT NULL,
    pickup_window_end         TIMESTAMPTZ NOT NULL,
    status                    TEXT NOT NULL DEFAULT 'SCHEDULED'
                               CHECK (status IN ('SCHEDULED','COLLECTED','DELIVERED','FAILED')),
    collected_quantity_kg     NUMERIC(12,3) CHECK (collected_quantity_kg IS NULL OR collected_quantity_kg > 0),
    collected_at              TIMESTAMPTZ,
    delivered_at              TIMESTAMPTZ,
    failure_reason            TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (pickup_window_end > pickup_window_start)
);

CREATE TABLE receipts (
    id                   UUID PRIMARY KEY,
    pickup_id            UUID NOT NULL UNIQUE REFERENCES pickups(id),
    recipient_user_id    UUID NOT NULL REFERENCES users(id),
    received_quantity_kg NUMERIC(12,3) NOT NULL CHECK (received_quantity_kg >= 0),
    exception_reason     TEXT,
    confirmed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (received_quantity_kg > 0 OR exception_reason IS NOT NULL)
);

CREATE TABLE events (
    id              UUID PRIMARY KEY,
    aggregate_type  TEXT NOT NULL,
    aggregate_id    UUID NOT NULL,
    actor_id        UUID REFERENCES users(id),
    event_type      TEXT NOT NULL,
    idempotency_key TEXT NOT NULL DEFAULT '',
    request_hash    TEXT,
    response_json   JSONB,
    payload         JSONB NOT NULL DEFAULT '{}',
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (actor_id, event_type, idempotency_key)
);

-- System/worker events (actor_id IS NULL) need their own idempotency guard:
CREATE UNIQUE INDEX events_system_key_unique
    ON events (event_type, idempotency_key)
    WHERE actor_id IS NULL AND idempotency_key <> '';

CREATE TABLE audit_records (
    id             UUID PRIMARY KEY,
    actor_id       UUID REFERENCES users(id),
    organization_id UUID REFERENCES organizations(id),
    action         TEXT NOT NULL,
    resource_type  TEXT NOT NULL,
    resource_id    UUID,
    outcome        TEXT NOT NULL,
    safe_summary   JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migration bookkeeping
CREATE TABLE schema_migrations (
    version     TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms INT NOT NULL DEFAULT 0
);

COMMIT;
