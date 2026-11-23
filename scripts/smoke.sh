#!/usr/bin/env bash
# NourishRelay local smoke test — runs against an ALREADY RUNNING stack
# (Docker Compose or local dev; see README.md "Run the demo").
#
# Verifies: web reachable, API health + readiness (DB), demo fixtures seeded,
# and one complete synthetic workflow donor→publish→match→propose→accept→
# pickup→collect→deliver→receipt→report, using only real HTTP calls.
#
# Usage:
#   ./scripts/smoke.sh                    # web on :3000, api on :8000
#   WEB_URL=... API_URL=... ./scripts/smoke.sh
#
# Exit codes: 0 = all checks passed; 1 = a check failed; 2 = usage/environment error.
set -euo pipefail

WEB_URL="${WEB_URL:-http://localhost:3000}"
API_URL="${API_URL:-http://localhost:8000}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

echo "== NourishRelay smoke =="
echo "web:  ${WEB_URL}"
echo "api:  ${API_URL}"

# 1) Web app responds
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "${WEB_URL}/" || true)"
[ "$code" = "200" ] || fail "web / returned HTTP ${code} (expected 200)"
echo "[ok] web / -> 200"

# 2) API health
body="$(curl -s --max-time 10 "${API_URL}/api/v1/health" || true)"
echo "$body" | grep -q '"service":"nourishrelay-api"' || fail "api /api/v1/health unexpected body: $body"
echo "[ok] api health"

# 3) API readiness (database connectivity)
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${API_URL}/api/v1/ready" || true)"
[ "$code" = "200" ] || fail "api /api/v1/ready returned HTTP ${code} (expected 200; DB or dependency missing)"
echo "[ok] api ready (database reachable)"

# 4) Demo fixtures seeded (login endpoint responds; full fixture check is part of workflow below)
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "${API_URL}/api/v1/auth/login" \
  -H 'Content-Type: application/json' -d '{"email":"nonexistent@demo.nourishrelay.example","password":"wrong"}' || true)"
[ "$code" = "401" ] || fail "api login returned HTTP ${code} for bad credentials (expected 401)"
echo "[ok] auth rejects bad credentials"

# 5) Full workflow via real HTTP calls
if ! "$PY" "${REPO_ROOT}/services/api/scripts/smoke_flow.py" --api-url "${API_URL}"; then
  fail "workflow script failed (see output above)"
fi
echo "[ok] complete donor→receipt workflow executed"

echo "== SMOKE PASSED =="
