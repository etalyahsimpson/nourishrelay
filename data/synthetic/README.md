# Synthetic Demonstration Dataset

All organizations, users, donations, pickups, receipts, and audit records in
this dataset are **synthetic**. No real people, businesses, addresses, phone
numbers, or charitable organizations are represented.

- `seed-organizations.json` — the full demonstration scenario fixture
  (8 organizations, 9 demo role accounts, 5 live donations, 1 pending
  proposal, 8 completed historical flows) consumed by
  `services/api/scripts/seed.py`.
- Demo accounts all use the public synthetic password documented in
  `README.md` (`demo-password`). They exist only to exercise role-based flows
  and must never be treated as real credentials.
- Donation/pickup windows are generated **relative to the moment the seed
  script runs** (offsets in hours), so the demonstration scenario never goes
  stale. Historical flows are placed at fixed day offsets in the past so
  reports, reliability inputs, and fairness ranking reflect recorded events.
- Seeding is **idempotent**: entities are keyed by fixed slugs, emails, and
  scenario keys; re-running the seed does not duplicate organizations, users,
  or the scenario records.
- Data provenance: authored for this portfolio project. No third-party or
  proprietary food-safety dataset is included.

**User-visible labeling (applies everywhere this data is displayed):**
`Portfolio demonstration · Synthetic organizations and records · Not for real
food-safety or dispatch decisions.`
