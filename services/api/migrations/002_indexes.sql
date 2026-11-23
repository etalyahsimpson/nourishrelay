-- NourishRelay schema 002 — operational indexes.
-- Justification: worker expiry scans, recipient matching aggregation,
-- report window scans, pickup queues and audit timelines. All are exercised
-- by seed data and tests.

BEGIN;

-- Donation expiry worker scan (status + deadline).
CREATE INDEX idx_donations_status_deadline ON donations (status, deadline);

-- Coordinator/recipient listing by state and recency.
CREATE INDEX idx_reservations_state_created ON reservations (state, created_at DESC);

-- Proposal expiry worker scan.
CREATE INDEX idx_reservations_proposal_expiry
    ON reservations (proposal_expires_at)
    WHERE state = 'PROPOSED';

-- Report window scans on reservation acceptance.
CREATE INDEX idx_reservations_accepted_at ON reservations (accepted_at)
    WHERE accepted_at IS NOT NULL;

-- Pickup queue scans by transport org and status.
CREATE INDEX idx_pickups_transport_status ON pickups (assigned_transport_org_id, status);

-- Collected/delivered timestamps for report windows.
CREATE INDEX idx_pickups_collected_at ON pickups (collected_at)
    WHERE collected_at IS NOT NULL;
CREATE INDEX idx_pickups_delivered_at ON pickups (delivered_at)
    WHERE delivered_at IS NOT NULL;

-- Audit timeline default ordering.
CREATE INDEX idx_audit_records_created ON audit_records (created_at DESC);

-- Events timeline per aggregate.
CREATE INDEX idx_events_aggregate_time ON events (aggregate_type, aggregate_id, occurred_at);

COMMIT;
