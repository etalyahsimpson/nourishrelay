-- NourishRelay canonical operations-report queries (consumed by
-- app/domain/reporting.py). All quantities are kg; windows are half-open
-- [from, to) UTC; %(org_id)s is NULL for platform-wide reports.
-- Scoping rule: an organization filter includes donations the org offered,
-- reservations where it is donor OR recipient, and pickups it transports.

-- name: report_offered
-- Offered quantity: donations published for pickup windows starting in the
-- report window (a donation is counted exactly once regardless of how many
-- reservations it later has — no join multiplication).
SELECT COALESCE(SUM(d.quantity_kg), 0)::text AS offered_kg,
       COUNT(*)::int AS offers
FROM donations d
WHERE d.status <> 'DRAFT'
  AND d.pickup_start >= %(from)s AND d.pickup_start < %(to)s
  AND (%(org_id)s::uuid IS NULL OR d.donor_org_id = %(org_id)s::uuid);

-- name: report_committed
-- Currently committed stock on donations offered in the window (snapshot of
-- held reservation states at query time, including failed-after-collection).
SELECT COALESCE(SUM(r.quantity_kg), 0)::text AS committed_kg
FROM reservations r
JOIN donations d ON d.id = r.donation_id
WHERE d.status <> 'DRAFT'
  AND d.pickup_start >= %(from)s AND d.pickup_start < %(to)s
  AND (%(org_id)s::uuid IS NULL OR d.donor_org_id = %(org_id)s::uuid OR r.recipient_org_id = %(org_id)s::uuid)
  AND (r.state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED')
       OR (r.state = 'FAILED' AND r.failure_stage = 'AFTER_COLLECTION'));

-- name: report_collected
-- Collected quantity: pickups recorded as collected in the window.
SELECT COALESCE(SUM(p.collected_quantity_kg), 0)::text AS collected_kg,
       COUNT(*)::int AS pickups
FROM pickups p
JOIN reservations r ON r.id = p.reservation_id
WHERE p.collected_at >= %(from)s AND p.collected_at < %(to)s
  AND (%(org_id)s::uuid IS NULL OR r.recipient_org_id = %(org_id)s::uuid
       OR p.assigned_transport_org_id = %(org_id)s::uuid
       OR r.donation_id IN (SELECT id FROM donations WHERE donor_org_id = %(org_id)s::uuid));

-- name: report_received
-- Received quantity: CONFIRMED receipts only (delivered is not received).
SELECT COALESCE(SUM(rc.received_quantity_kg), 0)::text AS received_kg,
       COUNT(*)::int AS receipts
FROM receipts rc
JOIN pickups p ON p.id = rc.pickup_id
JOIN reservations r ON r.id = p.reservation_id
WHERE rc.confirmed_at >= %(from)s AND rc.confirmed_at < %(to)s
  AND (%(org_id)s::uuid IS NULL OR r.recipient_org_id = %(org_id)s::uuid
       OR r.donation_id IN (SELECT id FROM donations WHERE donor_org_id = %(org_id)s::uuid));

-- name: report_reservations_count
SELECT COUNT(*)::int AS reservations
FROM reservations r
JOIN donations d ON d.id = r.donation_id
WHERE r.created_at >= %(from)s AND r.created_at < %(to)s
  AND (%(org_id)s::uuid IS NULL OR r.recipient_org_id = %(org_id)s::uuid OR d.donor_org_id = %(org_id)s::uuid);

-- name: report_failures
SELECT COUNT(*)::int AS failures
FROM pickups p
JOIN reservations r ON r.id = p.reservation_id
WHERE p.status = 'FAILED'
  AND p.updated_at >= %(from)s AND p.updated_at < %(to)s
  AND (%(org_id)s::uuid IS NULL OR r.recipient_org_id = %(org_id)s::uuid
       OR p.assigned_transport_org_id = %(org_id)s::uuid
       OR r.donation_id IN (SELECT id FROM donations WHERE donor_org_id = %(org_id)s::uuid));

-- name: report_cancellations
SELECT COUNT(*)::int AS cancellations
FROM reservations r
JOIN donations d ON d.id = r.donation_id
WHERE r.state = 'CANCELLED'
  AND r.updated_at >= %(from)s AND r.updated_at < %(to)s
  AND (%(org_id)s::uuid IS NULL OR r.recipient_org_id = %(org_id)s::uuid OR d.donor_org_id = %(org_id)s::uuid);

-- name: report_median_pickup_lead_minutes
-- Median minutes from proposal creation to collection (only where both exist).
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (
    ORDER BY EXTRACT(EPOCH FROM (p.collected_at - r.created_at)) / 60.0
)::float8 AS median_lead_minutes
FROM pickups p
JOIN reservations r ON r.id = p.reservation_id
WHERE p.collected_at >= %(from)s AND p.collected_at < %(to)s
  AND (%(org_id)s::uuid IS NULL OR r.recipient_org_id = %(org_id)s::uuid
       OR p.assigned_transport_org_id = %(org_id)s::uuid
       OR r.donation_id IN (SELECT id FROM donations WHERE donor_org_id = %(org_id)s::uuid));

-- name: report_cancellation_reasons
SELECT COALESCE(NULLIF(r.cancel_reason, ''), '(unspecified)') AS reason,
       COUNT(*)::int AS count
FROM reservations r
JOIN donations d ON d.id = r.donation_id
WHERE r.state = 'CANCELLED'
  AND r.updated_at >= %(from)s AND r.updated_at < %(to)s
  AND (%(org_id)s::uuid IS NULL OR r.recipient_org_id = %(org_id)s::uuid OR d.donor_org_id = %(org_id)s::uuid)
GROUP BY 1 ORDER BY count DESC, reason ASC;

-- name: report_failure_reasons
SELECT COALESCE(NULLIF(p.failure_reason, ''), '(unspecified)') AS reason,
       COUNT(*)::int AS count,
       COALESCE(SUM(p.collected_quantity_kg), 0)::text AS quantity_kg
FROM pickups p
JOIN reservations r ON r.id = p.reservation_id
WHERE p.status = 'FAILED'
  AND p.updated_at >= %(from)s AND p.updated_at < %(to)s
  AND (%(org_id)s::uuid IS NULL OR r.recipient_org_id = %(org_id)s::uuid
       OR p.assigned_transport_org_id = %(org_id)s::uuid
       OR r.donation_id IN (SELECT id FROM donations WHERE donor_org_id = %(org_id)s::uuid))
GROUP BY 1 ORDER BY count DESC, reason ASC;

-- name: report_categories
-- Per-category offered quantity/count for the window (same single-donation
-- semantics as report_offered).
SELECT d.category AS category,
       COUNT(*)::int AS offers,
       COALESCE(SUM(d.quantity_kg), 0)::text AS offered_kg
FROM donations d
WHERE d.status <> 'DRAFT'
  AND d.pickup_start >= %(from)s AND d.pickup_start < %(to)s
  AND (%(org_id)s::uuid IS NULL OR d.donor_org_id = %(org_id)s::uuid)
GROUP BY d.category ORDER BY d.category ASC;
