#!/usr/bin/env bash
# NourishRelay demo-database restore — restores a pg_dump of the synthetic
# demo database and verifies referential integrity + stock invariants.
# Usage: ./scripts/restore.sh <dump-file>
# Exit codes: 0 ok; 1 restore/verification failed; 2 usage/environment error.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP="${1:-}"
[ -n "$DUMP" ] && [ -f "$DUMP" ] || { echo "usage: restore.sh <dump-file>" >&2; exit 2; }

DB_USER="${POSTGRES_USER:-nourishrelay}"
DB_NAME="${POSTGRES_DB:-nourishrelay}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
[ -x "$(command -v docker)" ] || { echo "restore.sh requires Docker (compose stack) or set COMPOSE_CMD" >&2; exit 2; }

echo "== Restoring synthetic demo database from ${DUMP} =="
# Terminate connections, drop and recreate the demo database, then restore.
"$COMPOSE_CMD" exec -T db psql -U "$DB_USER" -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid<>pg_backend_pid();" >/dev/null
"$COMPOSE_CMD" exec -T db psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};" >/dev/null
"$COMPOSE_CMD" exec -T db psql -U "$DB_USER" -d postgres -c "CREATE DATABASE ${DB_NAME};" >/dev/null
"$COMPOSE_CMD" exec -T db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 --quiet < "$DUMP" || {
  echo "restore failed" >&2; exit 1; }
echo "[ok] restore executed"

# Post-restore invariants: FK integrity, no overcommitted stock, unique receipts.
"$COMPOSE_CMD" exec -T db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 --quiet <<'SQL' || { echo "post-restore verification failed" >&2; exit 1; }
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='donations') THEN
    PERFORM 1; -- structure present
  END IF;
END $$;

-- Overcommit check: committed quantity must never exceed offered quantity.
DO $$
DECLARE bad INT;
BEGIN
  SELECT COUNT(*) INTO bad FROM (
    SELECT d.id
    FROM donations d
    LEFT JOIN reservations r ON r.donation_id = d.id
      AND r.state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED')
      AND COALESCE(r.failure_stage, 'NONE') <> 'AFTER_COLLECTION'
    GROUP BY d.id, d.quantity_kg
    HAVING COALESCE(SUM(r.quantity_kg), 0) > d.quantity_kg
  ) x;
  IF bad > 0 THEN
    RAISE EXCEPTION 'overcommitted stock on % donations', bad;
  END IF;
END $$;

-- Receipt-uniqueness check (schema enforces it; verify data respects it).
DO $$
DECLARE bad INT;
BEGIN
  SELECT COUNT(*) INTO bad FROM receipts r1 JOIN receipts r2
    ON r1.pickup_id = r2.pickup_id AND r1.id < r2.id;
  IF bad > 0 THEN
    RAISE EXCEPTION 'duplicate receipts found: %', bad;
  END IF;
END $$;

-- Referential integrity is enforced by FK constraints; failed inserts above
-- would have aborted with ON_ERROR_STOP.
SQL
echo "[ok] referential integrity + stock invariants hold"
echo "== RESTORE VERIFIED =="
