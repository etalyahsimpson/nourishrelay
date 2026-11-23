"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { MetricCard, formatKg, formatRatio } from "@/components/MetricCard";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime, relativeTime } from "@/lib/dates";
import type { OperationsReport } from "@/lib/contracts";

function windowQuery(days = 14) {
  const to = new Date(Date.now() + 2 * 86400_000);
  const from = new Date(Date.now() - days * 86400_000);
  return { from: from.toISOString().replace("+00:00", "Z"), to: to.toISOString().replace("+00:00", "Z") };
}

export default function DashboardPage() {
  const { user, loading } = useSession();

  const report = useQuery({
    queryKey: ["report", "dashboard"],
    queryFn: () => api.operationsReport(windowQuery()),
    enabled: !!user && ["coordinator", "analyst", "admin", "donor", "recipient", "transport"].includes(user.role),
  });

  const donations = useQuery({
    queryKey: ["donations", "dashboard"],
    queryFn: () => api.donations({ limit: "100" }),
    enabled: !!user && ["donor", "recipient", "coordinator", "admin", "analyst"].includes(user.role),
  });

  const reservations = useQuery({
    queryKey: ["reservations", "dashboard"],
    queryFn: () => api.reservations({ limit: "100" }),
    enabled: !!user,
  });

  const pickups = useQuery({
    queryKey: ["pickups", "dashboard"],
    queryFn: () => api.pickups({ limit: "100" }),
    enabled: !!user,
  });

  if (loading) {
    return <p className="text-ink-muted" aria-live="polite">Loading session…</p>;
  }
  if (!user) {
    return (
      <div className="rounded-lg border border-line bg-surface-raised p-6">
        <h1 className="text-xl font-bold">Dashboard</h1>
        <p className="mt-2 text-sm text-ink-muted">Sign in to see role-specific metrics.</p>
        <Link href="/login" className="mt-4 inline-block rounded-md bg-primary-600 px-4 py-2 text-sm font-semibold text-white">
          Sign in to demo
        </Link>
      </div>
    );
  }

  const reportData: OperationsReport | undefined = report.data;
  const donationItems = donations.data?.items ?? [];
  const reservationItems = reservations.data?.items ?? [];
  const pickupItems = pickups.data?.items ?? [];

  const openDonations = donationItems.filter((d) =>
    ["AVAILABLE", "PARTIALLY_RESERVED", "FULLY_RESERVED"].includes(d.status),
  );
  const myProposals = reservationItems.filter((r) => r.state === "PROPOSED");
  const scheduled = pickupItems.filter((p) => p.status === "SCHEDULED");
  const awaitingReceipt = pickupItems.filter((p) => p.status === "DELIVERED");

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-ink">Dashboard</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {user.display_name} · role <span className="font-mono uppercase">{user.role}</span> ·
          all metrics queried live from the transaction database
        </p>
      </header>

      {report.isLoading ? (
        <p className="text-sm text-ink-muted" aria-live="polite">Loading metrics…</p>
      ) : report.isError ? (
        <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">

        </p>
      ) : reportData ? (
        <section aria-labelledby="kpi-heading">
          <h2 id="kpi-heading" className="sr-only">Key metrics</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="Offered (kg)"
              value={formatKg(reportData.offered_kg)}
              unit="kg"
              hint={`trailing 14 days · ${reportData.offers} offers`}
            />
            <MetricCard
              label="Committed (kg)"
              value={formatKg(reportData.committed_kg)}
              unit="kg"
              hint="currently held stock"
            />
            <MetricCard
              label="Collected (kg)"
              value={formatKg(reportData.collected_kg)}
              unit="kg"
              hint={`${reportData.pickups} pickups`}
            />
            <MetricCard
              label="Received (kg)"
              value={formatKg(reportData.received_kg)}
              unit="kg"
              hint={`confirmed receipts · recovery ${formatRatio(
                reportData.ratios.find((r) => r.label === "received / offered")?.value ?? null,
              )} of offered`}
            />
          </div>
        </section>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {user.role === "donor" ? (
          <section aria-labelledby="my-donations" className="rounded-lg border border-line bg-surface-raised p-5">
            <h2 id="my-donations" className="font-semibold text-ink">
              My organization&apos;s donations
            </h2>
            <ul className="mt-3 space-y-2 text-sm">
              {donationItems.slice(0, 6).map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-2">
                  <Link href={`/donations/${d.id}`} className="font-medium text-primary-700 hover:underline">
                    {d.category}
                  </Link>
                  <span className="tabular-nums text-ink-muted">{formatKg(d.quantity_kg)} kg</span>
                  <StatusBadge status={d.status} />
                  <span className="text-xs text-ink-muted">{relativeTime(d.deadline)} deadline</span>
                </li>
              ))}
              {donationItems.length === 0 ? (
                <li className="text-ink-muted">No donations yet — create one from the Donations tab.</li>
              ) : null}
            </ul>
          </section>
        ) : null}

        {user.role === "recipient" ? (
          <section aria-labelledby="my-proposals" className="rounded-lg border border-line bg-surface-raised p-5">
            <h2 id="my-proposals" className="font-semibold text-ink">
              Proposals awaiting my decision
            </h2>
            <ul className="mt-3 space-y-2 text-sm">
              {myProposals.slice(0, 6).map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2">
                  <span className="tabular-nums font-medium text-ink">{formatKg(r.quantity_kg)} kg</span>
                  <span className="text-ink-muted">{r.donation_category} from {r.donor_org_name}</span>
                  {r.proposal_expires_at ? (
                    <span className="text-xs text-ink-muted">expires {relativeTime(r.proposal_expires_at)}</span>
                  ) : null}
                </li>
              ))}
              {myProposals.length === 0 ? (
                <li className="text-ink-muted">No pending proposals.</li>
              ) : null}
            </ul>
            <Link href="/reservations" className="mt-3 inline-block text-sm font-medium text-primary-700 hover:underline">
              Go to the reservations queue →
            </Link>
          </section>
        ) : null}

        {user.role === "transport" ? (
          <section aria-labelledby="my-pickups" className="rounded-lg border border-line bg-surface-raised p-5">
            <h2 id="my-pickups" className="font-semibold text-ink">
              My pickup queue
            </h2>
            <ul className="mt-3 space-y-2 text-sm">
              {pickupItems.slice(0, 6).map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-2">
                  <span className="tabular-nums font-medium text-ink">{formatKg(p.reserved_quantity_kg)} kg</span>
                  <span className="text-ink-muted">{p.donation_category} · {p.recipient_org_name}</span>
                  <StatusBadge status={p.status} />
                  <span className="text-xs text-ink-muted">{formatDateTime(p.pickup_window_start)}</span>
                </li>
              ))}
              {pickupItems.length === 0 ? (
                <li className="text-ink-muted">No assigned pickups.</li>
              ) : null}
            </ul>
          </section>
        ) : null}

        {["coordinator", "admin", "analyst"].includes(user.role) ? (
          <section aria-labelledby="coord-queue" className="rounded-lg border border-line bg-surface-raised p-5">
            <h2 id="coord-queue" className="font-semibold text-ink">
              Coordination queue
            </h2>
            <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
              <MetricCard label="Open donations" value={openDonations.length} hint="available or partly reserved" />
              <MetricCard label="Pending proposals" value={myProposals.length} hint="awaiting recipient decision" />
              <MetricCard label="Scheduled pickups" value={scheduled.length} hint="assigned to transport" />
              <MetricCard label="Awaiting receipt" value={awaitingReceipt.length} hint="delivered, receipt pending" />
            </div>
            <Link href="/matching" className="mt-3 inline-block text-sm font-medium text-primary-700 hover:underline">
              Open the matching view →
            </Link>
          </section>
        ) : null}

        <section aria-labelledby="activity-heading" className="rounded-lg border border-line bg-surface-raised p-5">
          <h2 id="activity-heading" className="font-semibold text-ink">
            Recent reservations
          </h2>
          {reservations.isLoading ? (
            <p className="mt-2 text-sm text-ink-muted" aria-live="polite">Loading…</p>
          ) : (
            <ul className="mt-3 space-y-2 text-sm">
              {reservationItems.slice(0, 8).map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2">
                  <span className="tabular-nums font-medium text-ink">{formatKg(r.quantity_kg)} kg</span>
                  <span className="text-ink-muted">
                    {r.donation_category} · {r.recipient_org_name}
                  </span>
                  <StatusBadge status={r.state} />
                  {r.failure_stage ? (
                    <span className="text-xs text-rose-700">failed {r.failure_stage.toLowerCase().replace("_", " ")}</span>
                  ) : null}
                </li>
              ))}
              {reservationItems.length === 0 ? (
                <li className="text-ink-muted">No reservations recorded yet.</li>
              ) : null}
            </ul>
          )}
        </section>

        <section aria-labelledby="failures-heading" className="rounded-lg border border-line bg-surface-raised p-5">
          <h2 id="failures-heading" className="font-semibold text-ink">
            Failures & exceptions ({reportData?.failures ?? 0} failures, {reportData?.cancellations ?? 0} cancellations)
          </h2>
          <ul className="mt-3 space-y-2 text-sm">
            {(reportData?.failure_reasons ?? []).slice(0, 5).map((f) => (
              <li key={f.kind} className="flex flex-wrap items-center gap-2 text-ink-muted">
                <span className="rounded border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs text-rose-800">
                  {f.count}×
                </span>
                {f.kind}
                {f.quantity_kg ? <span className="tabular-nums">({formatKg(f.quantity_kg)} kg)</span> : null}
              </li>
            ))}
            {(reportData?.cancellation_reasons ?? []).slice(0, 3).map((c) => (
              <li key={`c-${c.kind}`} className="flex flex-wrap items-center gap-2 text-ink-muted">
                <span className="rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-800">
                  {c.count}×
                </span>
                cancelled: {c.kind}
              </li>
            ))}
            {!reportData?.failure_reasons.length && !reportData?.cancellation_reasons.length ? (
              <li className="text-ink-muted">No failures or cancellations recorded in the window.</li>
            ) : null}
          </ul>
        </section>
      </div>
    </div>
  );
}
