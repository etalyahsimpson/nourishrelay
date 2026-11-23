import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About — NourishRelay",
};

export default function AboutPage() {
  return (
    <div className="space-y-10">
      <header>
        <h1 className="text-2xl font-bold text-ink">About NourishRelay</h1>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-ink-muted">
          An independent portfolio engineering project: a food-recovery coordination
          platform built as a modular monolith with a FastAPI backend, PostgreSQL 16,
          Redis/Celery background workers and a Next.js operations interface. Every
          number in this application is derived from recorded transactions in a
          synthetic demonstration database.
        </p>
      </header>

      <section aria-labelledby="arch-heading">
        <h2 id="arch-heading" className="text-lg font-semibold text-ink">Architecture</h2>
        <pre className="mt-3 overflow-x-auto rounded-lg border border-line bg-surface-raised p-4 text-xs leading-relaxed text-ink-muted" role="img" aria-label="Architecture diagram: browser to web to API to PostgreSQL, with Redis broker feeding Celery workers">
{`Browser ── Next.js web (App Router, Node 22) ── same-origin /api/v1 proxy
                     │
                     ▼
          FastAPI (Python 3.12, uvicorn :8000)
             │                    │
             ▼                    ▼
       PostgreSQL 16        Redis 7 (broker only)
       (authoritative:          │
        donations,            Celery worker + beat
        reservations,          (expiry + simulated
        pickups, receipts,     notifications)
        events, audit) —──────┘ writes through the same
                                guarded domain code`}
        </pre>
        <p className="mt-2 text-xs text-ink-muted">
          PostgreSQL is the single source of truth; Redis only carries job schedules. A
          worker failure can delay expiry timing but never corrupt stock accounting.
        </p>
      </section>

      <section aria-labelledby="safety-heading">
        <h2 id="safety-heading" className="text-lg font-semibold text-ink">Safety &amp; provenance</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-ink-muted">
          <li>
            All organizations, accounts, donations, pickups and receipts are synthetic
            fixtures seeded from <code className="font-mono text-xs">data/synthetic/seed-organizations.json</code>.
          </li>
          <li>
            Matching uses declared handling acknowledgments plus window/stock/capacity
            constraints — it never certifies food safety, and scores are demonstration
            weights, not transport guarantees.
          </li>
          <li>
            The platform deliberately excludes payments, public file uploads and real
            notification channels; the simulated notification worker writes a local
            event row only.
          </li>
          <li>
            Audit records are append-only and transactional; no secrets or personal data
            are ever recorded.
          </li>
        </ul>
      </section>

      <section aria-labelledby="links-heading">
        <h2 id="links-heading" className="text-lg font-semibold text-ink">Documentation &amp; source</h2>
        <ul className="mt-3 space-y-2 text-sm">
          <li>
            <a className="font-medium text-primary-700 hover:underline" href="https://github.com/etalyahsimpson/nourishrelay" target="_blank" rel="noopener noreferrer">
              GitHub repository (etalyahsimpson/nourishrelay)
            </a>
            <span className="ml-2 text-ink-muted">— source, CI, and this app&apos;s exact code</span>
          </li>
          <li>
            <span className="text-ink-muted">In-repo docs:</span>{" "}
            <code className="font-mono text-xs">docs/ARCHITECTURE.md</code>,{" "}
            <code className="font-mono text-xs">docs/DOMAIN_RULES.md</code>,{" "}
            <code className="font-mono text-xs">docs/API_CONTRACTS.md</code>,{" "}
            <code className="font-mono text-xs">docs/THREAT_MODEL.md</code>,{" "}
            <code className="font-mono text-xs">docs/TESTING.md</code>,{" "}
            <code className="font-mono text-xs">docs/DEMO_WALKTHROUGH.md</code>.
          </li>
          <li>
            <span className="text-ink-muted">Interactive API reference:</span>{" "}
            <a className="font-medium text-primary-700 hover:underline" href="/api/v1/openapi.json" target="_blank" rel="noopener noreferrer">
              OpenAPI schema
            </a>{" "}
            (served by FastAPI; also at <code className="font-mono text-xs">/docs</code> on the API origin).
          </li>
        </ul>
      </section>

      <section className="rounded-lg border border-amber-300 bg-amber-50 p-5 text-sm text-amber-900">
        <h2 className="font-semibold">Not for real food-safety or dispatch decisions</h2>
        <p className="mt-2 leading-relaxed">
          This is a portfolio demonstration with synthetic organizations and records.
          Human food handling, regulatory review and physical transport remain entirely
          outside this platform&apos;s control.
        </p>
      </section>

      <p className="text-sm text-ink-muted">
        <Link href="/" className="font-medium text-primary-700 hover:underline">← Back to the overview</Link>
      </p>
    </div>
  );
}
