#!/usr/bin/env bash
# NourishRelay repository release verification — structural self-audit that
# also runs in CI (see .github/workflows/ci.yml).
#
# Checks:
#   1. Required top-level files exist.
#   2. No secrets: .env not tracked; no token-like strings in tracked files.
#   3. No forbidden technology markers in tracked manifests/imports.
#   4. project-summary.json parses and has truthful null hosted_demo_url.
#   5. README-referenced docs/assets paths exist.
#
# Exit codes: 0 verified; 1 violation found; 2 usage error.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
fail() { echo "VERIFY-REPOSITORY FAIL: $*" >&2; exit 1; }
ok() { echo "[ok] $*"; }

echo "== NourishRelay repository verification =="

# 1) Required files
for f in README.md .gitignore .env.example docker-compose.yml project-summary.json \
         apps/web/package.json services/api/requirements.in services/api/requirements.lock.txt \
         services/api/app/main.py workers/tasks.py data/synthetic/seed-organizations.json \
         scripts/smoke.sh scripts/clean-clone.sh scripts/backup.sh scripts/restore.sh \
         .github/workflows/ci.yml docs/ARCHITECTURE.md docs/THREAT_MODEL.md docs/TESTING.md; do
  [ -f "$f" ] || fail "missing required file: $f"
done
ok "required files present"

# 2) Secrets
if git ls-files --error-unmatch .env >/dev/null 2>&1; then fail ".env is tracked"; fi
ok ".env not tracked"
if git ls-files | grep -qE '(^|/)\.env($|\.)' | grep -v '\.env\.example'; then
  if git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example' | grep -q .; then
    fail "unexpected tracked .env* file"
  fi
fi
if git grep -lE 'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}' -- ':!scripts/verify-repository.sh' >/dev/null 2>&1 && \
   git grep -E 'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}' -- ':!scripts/verify-repository.sh' | grep -q .; then
  fail "token-like string found in tracked files"
fi
ok "no token-like strings in tracked files"

# 3) Forbidden technology markers (spec §3.3)
if git grep -liE 'prisma|drizzle|supabase|firebase|mongodb|graphql' -- 'apps/web/package.json' 'apps/web/package-lock.json' 'services/api/requirements.*' | grep -q .; then
  fail "forbidden dependency name found in a tracked manifest"
fi
ok "no forbidden dependencies in manifests"

# 4) project-summary.json
python3 - <<'PY' || fail "project-summary.json invalid"
import json, sys
with open("project-summary.json") as f:
    d = json.load(f)
required = {"name","slug","purpose","target_users","release_status","synthetic_data",
            "implemented_features","planned_features","stack","source_paths",
            "verification_paths","local_run","hosted_demo_url","test_commands",
            "repo_url","limitations"}
missing = required - set(d)
assert not missing, f"missing keys: {missing}"
assert d["synthetic_data"] is True
assert d["hosted_demo_url"] is None, "hosted_demo_url must be null unless actually hosted"
assert isinstance(d["implemented_features"], list) and isinstance(d["limitations"], list)
PY
ok "project-summary.json valid and truthful"

# 5) README-referenced local asset paths exist
python3 - <<'PY' || fail "README references missing files"
import re, pathlib, sys
readme = pathlib.Path("README.md").read_text()
refs = re.findall(r'\]\((?!https?://|#)([^)]+)\)', readme)
missing = [r for r in refs if not (pathlib.Path(r.split('#')[0]).exists() or (pathlib.Path('docs')/r.split('#')[0]).exists())]
missing = [m for m in missing if m.strip()]
assert not missing, f"README links to missing files: {missing}"
PY
ok "README local links resolve"

echo "== REPOSITORY VERIFICATION PASSED =="
