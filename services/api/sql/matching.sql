-- NourishRelay canonical matching/stock queries (consumed by app/domain/matching.py
-- via the named-query loader in app/domain/queries.py).
-- Placeholders are named (%(name)s) psycopg parameters.
-- Every query below is exercised by tests/backend tests and the seed scenario.

-- name: committed_stock_for_donation
-- Stock currently held (committed) on one donation. Includes FAILED reservations
-- with failure_stage = AFTER_COLLECTION (collected food is never automatically
-- reoffered). Excludes PROPOSED, DECLINED, CANCELLED, EXPIRED and
-- FAILED(BEFORE_COLLECTION) which release stock.
SELECT COALESCE(SUM(r.quantity_kg), 0)::text AS committed_kg
FROM reservations r
WHERE r.donation_id = %(donation_id)s::uuid
  AND (r.state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED')
       OR (r.state = 'FAILED' AND r.failure_stage = 'AFTER_COLLECTION'));

-- name: recipient_day_capacity_usage
-- Quantity a recipient has committed for one receiving day. The receiving day is
-- the calendar date of the donation's pickup window start, interpreted in the
-- RECIPIENT's timezone. Capacity states only (failed flows delivered nothing).
SELECT COALESCE(SUM(r.quantity_kg), 0)::text AS committed_kg
FROM reservations r
JOIN donations d ON d.id = r.donation_id
WHERE r.recipient_org_id = %(recipient_org_id)s::uuid
  AND r.state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED')
  AND (d.pickup_start AT TIME ZONE %(tz)s)::date = %(receiving_date)s::date;

-- name: recipient_recent_received_kg
-- Trailing-window received quantity per recipient — the fairness input.
-- Zero history is reported as-is (no invented values).
SELECT COALESCE(SUM(rc.received_quantity_kg), 0)::text AS received_kg,
       COUNT(*)::int AS receipt_count
FROM receipts rc
JOIN pickups p ON p.id = rc.pickup_id
JOIN reservations r ON r.id = p.reservation_id
WHERE r.recipient_org_id = %(recipient_org_id)s::uuid
  AND rc.confirmed_at >= %(since)s
  AND rc.confirmed_at < %(until)s;

-- name: recipient_pickup_reliability
-- Pickup reliability inputs per recipient. concluded = collected + failed;
-- on_time = collected within the assigned pickup window.
SELECT
  COUNT(*) FILTER (WHERE p.collected_at IS NOT NULL AND p.collected_at <= p.pickup_window_end)::int AS on_time,
  COUNT(*) FILTER (WHERE p.collected_at IS NOT NULL)::int AS collected,
  COUNT(*) FILTER (WHERE p.status = 'FAILED')::int AS failed
FROM pickups p
JOIN reservations r ON r.id = p.reservation_id
WHERE r.recipient_org_id = %(recipient_org_id)s::uuid;

-- name: recipient_profiles_for_matching
-- Active recipient organizations with profiles for a match computation.
SELECT o.id, o.name, o.verified, o.service_area,
       rp.accepted_categories, rp.max_kg_per_day, rp.handling_acknowledged,
       rp.receiving_start, rp.receiving_end, rp.timezone, rp.active
FROM organizations o
JOIN recipient_profiles rp ON rp.organization_id = o.id
WHERE o.kind = 'recipient';
