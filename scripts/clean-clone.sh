#!/usr/bin/env bash
# NourishRelay clean-clone verification — proves a fresh checkout runs.
#
# Simulates the documented clean-clone startup path:
#   1. clone the repository (or use the current checkout as the source) into
#      a temp directory,
#   2. create a fresh .env with generated demo values,
#   3. docker compose up --build -d (migrations + idempotent seed run in the
#      api container entrypoint),
#   4. wait for health probes,
#   5. run the explicit documented seed command,
#   6. run scripts/smoke.sh (full donor→receipt workflow),
#   7. tear the stack down and remove the temp clone.
#
# Usage:
#   ./scripts/clean-clone.sh                     # clone from origin remote
#   ./scripts/clean-clone.sh --local              # use current checkout as source
#
# Exit codes: 0 = clean-clone verified; 1 = verification failed; 2 = usage error.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${REMOTE:-origin}"
WORKDIR="$(mktemp -d /tmp/nourishrelay-cleanclone.XXXXXX)"
KEEP="${KEEP:-0}"
SOURCE_MODE="clone"

[ "${1:-}" = "--local" ] && SOURCE_MODE="local"
[ "${1:-}" = "--help" ] && { echo "usage: $0 [--local]"; exit 2; }

cleanup() {
  if [ "$KEEP" = "1" ]; then
    echo "keep: $WORKDIR"
  else
    docker compose -p "nourishrelay-cc" down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$WORKDIR"
  fi
}
trap cleanup EXIT

fail() { echo "CLEAN-CLONE FAIL: $*" >&2; exit 1; }

echo "== NourishRelay clean-clone verification =="

# 1) Obtain source
if [ "$SOURCE_MODE" = "local" ]; then
  echo "[1/7] Using current checkout as source: ${REPO_ROOT}"
  cp -a "$REPO_ROOT" "$WORKDIR/nourishrelay"
else
  REPO_URL="$(git -C "$REPO_ROOT" remote get-url "$REMOTE")"
  echo "[1/7] Cloning ${REPO_URL}"
  git clone --depth 1 "$REPO_URL" "$WORKDIR/nourishrelay" || fail "git clone failed"
fi
cd "$WORKDIR/nourishrelay"

# No cached .env or dependencies may exist in a clean clone
[ ! -f .env ] || fail "unexpected .env in fresh clone"
[ ! -d node_modules ] || fail "unexpected node_modules in fresh clone"

# 2) Fresh .env with generated values (demo-only, never committed)
GEN_SECRET="$('python3' -c 'import secrets; print(secrets.token_urlsafe(48))')"
GEN_PG="$('python3' -c 'import secrets; print(secrets.token_urlsafe(24))')"
sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${GEN_PG}|" \
    -e "s|^SESSION_SECRET=.*|SESSION_SECRET=${GEN_SECRET}|" \
    .env.example > .env
echo "[2/7] Generated fresh demo .env"

# 3) Build and start the stack under an isolated project name
export COMPOSE_PROJECT_NAME="nourishrelay-cc"
docker compose up --build -d || fail "docker compose up failed"
echo "[3/7] Stack built and started (web, api, db, redis, worker, beat)"

# 4) Wait for health (bounded)
for i in $(seq 1 60); do
  api_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8000/api/v1/ready || true)"
  web_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:3000/ || true)"
  if [ "$api_code" = "200" ] && [ "$web_code" = "200" ]; then break; fi
  sleep 5
done
[ "${api_code:-}" = "200" ] || fail "api never became ready (last: ${api_code:-none})"
[ "${web_code:-}" = "200" ] || fail "web never became ready (last: ${web_code:-none})"
echo "[4/7] Health probes green (api ready=200, web=200)"

# 5) Documented explicit seed invocation (idempotent)
docker compose exec -T api python services/api/scripts/seed.py || fail "explicit seed invocation failed"
echo "[5/7] Explicit seed command re-run (idempotent)"

# 6) Full smoke workflow
./scripts/smoke.sh || fail "smoke.sh failed on clean clone"
echo "[6/7] Full smoke workflow passed on clean clone"

# 7) Teardown happens via trap
echo "[7/7] Cleanup"
echo "== CLEAN-CLONE VERIFIED =="
