#!/usr/bin/env bash
# NourishRelay demo-database backup — pg_dump of the SYNTHETIC demo database only.
# Usage: ./scripts/backup.sh [output-file]   (default: backups/nourishrelay-demo-<ts>.sql)
# Exit codes: 0 ok; 1 dump failed; 2 environment error.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-${REPO_ROOT}/backups/nourishrelay-demo-$(date -u +%Y%m%dT%H%M%SZ).sql}"

DB_USER="${POSTGRES_USER:-nourishrelay}"
DB_NAME="${POSTGRES_DB:-nourishrelay}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
[ -x "$(command -v docker)" ] || { echo "backup.sh requires Docker (compose stack) or set COMPOSE_CMD" >&2; exit 2; }

mkdir -p "$(dirname "$OUT")"
echo "== Backing up synthetic demo database (${DB_NAME}) =="
"$COMPOSE_CMD" exec -T db pg_dump -U "$DB_USER" --no-owner --no-privileges "$DB_NAME" > "$OUT" || {
  echo "pg_dump failed" >&2; exit 1; }
[ -s "$OUT" ] || { echo "empty dump produced" >&2; exit 1; }
echo "Backup written: ${OUT}"
echo "This dump contains ONLY synthetic demonstration records (see data/synthetic/README.md)."
