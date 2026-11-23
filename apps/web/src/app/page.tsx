import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "NourishRelay — intelligent food recovery coordination",
};

const CAPABILITIES = [
  {
    title: "Deterministic matching with explanations",
    body: "Hard constraints (verification, category, handling acknowledgment, receiving-window overlap, capacity, deadline, stock) filter first; a weighted demonstration score ranks feasible recipients and shows every factor and weight.",
  },
  {
    title: "Atomic partial-quantity reservations",
    body: "Only a recipient's acceptance commits stock — under PostgreSQL row locks. Concurrent 80kg + 80kg acceptances against a 120kg offer cannot oversubscribe: one side receives an honest 409 with the live availability.",
  },
  {
    title: "A pickup trail from offer to verified receipt",
    body: "Proposal → acceptance → assigned pickup → collection → delivery → recipient-confirmed receipt, with exception reasons, failure stages before/after collection, and an append-only audit trail.",
  },
  {
    title: "Reports computed from recorded events",
    body: "Offered / committed / collected / received quantities with explicit denominators, windows and organization scoping; CSV export is protected against spreadsheet formula injection.",
  },
];

const ROLES = [
  { role: "Donor", sees: "Publish offers, edit drafts with optimistic versioning, withdraw uncommitted stock." },
  { role: "Recipient", sees: "See proposals with transparent eligibility, accept or decline, confirm receipts." },
  { role: "Transport", sees: "Pickup queue for the assigned organization, collect/deliver/fail with quantities." },
  { role: "Coordinator", sees: "Matching with explanations, proposals, cancellations, reports, audit trail." },
  { role: "Analyst (read-only)", sees: "Operational reports and analytics without mutation rights." },
];

export default function HomePage() {
  return (
    <div className="space-y-12">
      <section className="rounded-xl border border-primary-200 bg-gradient-to-b from-primary-50 to-surface-raised p-8">
        <p className="inline-flex rounded-full border border-primary-300 bg-primary-100 px-3 py-1 text-xs font-semibold text-primary-800">
          Portfolio demonstration · Synthetic data
        </p>
        <h1 className="mt-4 max-w-2xl text-3xl font-bold tracking-tight text-ink sm:text-4xl">
          Move surplus food from offer to verified receipt — without double booking.
        </h1>
        <p className="mt-4 max-w-2xl text-base leading-relaxed text-ink-muted">
          NourishRelay is a full-stack coordination platform for food-recovery networks:
          a deterministic, explanation-producing matching engine, atomic partial-quantity
          reservations on PostgreSQL, a stateful pickup and receipt trail, expiry workers,
          and operational analytics. This instance runs on a synthetic demonstration
          dataset — no real organizations, people, or food.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/login"
            className="rounded-md bg-primary-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-primary-700"
          >
            Sign in to demo
          </Link>
          <Link
            href="/about"
            className="rounded-md border border-primary-300 px-6 py-3 text-sm font-semibold text-primary-800 hover:bg-primary-50"
          >
            How it works
          </Link>
          <a
            href="https://github.com/etalyahsimpson/nourishrelay"
            rel="noopener noreferrer"
            target="_blank"
            className="rounded-md border border-line px-6 py-3 text-sm font-semibold text-ink hover:bg-primary-50"
          >
            Source code
          </a>
        </div>
      </section>

      <section aria-labelledby="capabilities-heading">
        <h2 id="capabilities-heading" className="text-xl font-bold text-ink">
          What the system actually does
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-ink-muted">
          Every capability below is implemented and covered by automated tests — no
          dashboard theater. All figures in the app are queried from the transaction
          database, never invented.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {CAPABILITIES.map((c) => (
            <article key={c.title} className="rounded-lg border border-line bg-surface-raised p-5">
              <h3 className="font-semibold text-ink">{c.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-muted">{c.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="roles-heading">
        <h2 id="roles-heading" className="text-xl font-bold text-ink">
          Five demo roles
        </h2>
        <div className="mt-4 overflow-x-auto rounded-lg border border-line bg-surface-raised">
          <table className="w-full min-w-[560px] text-sm">
            <caption className="sr-only">Demo roles and their access</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase text-ink-muted">
                <th scope="col" className="px-4 py-2">Role</th>
                <th scope="col" className="px-4 py-2">Access</th>
              </tr>
            </thead>
            <tbody>
              {ROLES.map((r) => (
                <tr key={r.role} className="border-b border-line last:border-0">
                  <td className="px-4 py-2 font-medium text-ink">{r.role}</td>
                  <td className="px-4 py-2 text-ink-muted">{r.sees}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border border-amber-300 bg-amber-50 p-5 text-sm text-amber-900">
        <h2 className="font-semibold">Honest limitations</h2>
        <p className="mt-2 leading-relaxed">
          This platform coordinates records for synthetic donors and recipients. It does
          not certify food safety, guarantee physical transport, handle payments, or
          process personal data of real people. Matching relies on declared handling
          acknowledgments and window/stock constraints only.
        </p>
      </section>
    </div>
  );
}
