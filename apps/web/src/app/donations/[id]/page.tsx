"use client";

import Link from "next/link";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { StatusBadge } from "@/components/StatusBadge";
import { formatKg } from "@/components/MetricCard";
import { formatDateTime, relativeTime } from "@/lib/dates";
import type { DonationDetail } from "@/lib/contracts";

export default function DonationDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const queryClient = useQueryClient();
  const { user } = useSession();
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const donation = useQuery({
    queryKey: ["donation", id],
    queryFn: () => api.donation(id),
    retry: false,
  });

  async function act(action: "publish" | "withdraw") {
    setBusy(true);
    setActionError(null);
    try {
      if (action === "publish") await api.publishDonation(id);
      else await api.withdrawDonation(id);
      await queryClient.invalidateQueries({ queryKey: ["donation", id] });
      await queryClient.invalidateQueries({ queryKey: ["donations"] });
    } catch (err) {
      setActionError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (donation.isLoading) {
    return <p className="text-sm text-ink-muted" aria-live="polite">Loading donation…</p>;
  }
  if (donation.isError) {
    const error = donation.error as ApiError;
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-6">
        <h1 className="text-lg font-semibold text-rose-900">Donation not found</h1>
        <p className="mt-2 text-sm text-rose-800">
          {error.code}: {error.message} — cross-tenant resources are never revealed.
        </p>
        <Link href="/donations" className="mt-4 inline-block text-sm font-medium text-primary-700 hover:underline">
          ← Back to donations
        </Link>
      </div>
    );
  }

  if (!donation.data) {
    return <p className="text-sm text-ink-muted">Donation data unavailable.</p>;
  }
  const d: DonationDetail = donation.data;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/donations" className="text-sm text-primary-700 hover:underline">← Donations</Link>
          <h1 className="mt-2 flex flex-wrap items-center gap-3 text-2xl font-bold text-ink">
            <span className="capitalize">{d.category}</span> · {formatKg(d.quantity_kg)} kg
            <StatusBadge status={d.status} />
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            Offered by {d.donor_org_name} · created {formatDateTime(d.created_at)}
          </p>
        </div>
        {user && d.allowed_actions.includes("publish") ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void act("publish")}
            className="rounded-md bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-60"
          >
            Publish (attest handling review)
          </button>
        ) : null}
        {user && d.allowed_actions.includes("withdraw") ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void act("withdraw")}
            className="rounded-md border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-60"
          >
            Withdraw offer
          </button>
        ) : null}
      </header>

      {actionError ? (
        <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {actionError}
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="stock-heading" className="rounded-lg border border-line bg-surface-raised p-5">
          <h2 id="stock-heading" className="font-semibold text-ink">Stock &amp; timing</h2>
          <dl className="mt-3 grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-xs uppercase text-ink-muted">Quantity</dt>
              <dd className="tabular-nums text-lg font-semibold">{formatKg(d.quantity_kg)} kg</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-ink-muted">Available</dt>
              <dd className="tabular-nums text-lg font-semibold text-emerald-700" data-testid="detail-available">
                {formatKg(d.available_kg)} kg
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-ink-muted">Committed</dt>
              <dd className="tabular-nums text-lg font-semibold">{formatKg(d.committed_kg)} kg</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-ink-muted">Version</dt>
              <dd className="tabular-nums text-lg font-semibold">{d.version}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-ink-muted">Pickup window</dt>
              <dd className="text-xs">{formatDateTime(d.pickup_start)} → {formatDateTime(d.pickup_end)}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-ink-muted">Deadline</dt>
              <dd className="text-xs">
                {formatDateTime(d.deadline)} ({relativeTime(d.deadline)})
              </dd>
            </div>
            <div className="col-span-2">
              <dt className="text-xs uppercase text-ink-muted">Handling tags</dt>
              <dd className="mt-1 flex flex-wrap gap-2">
                {d.handling_tags.length ? d.handling_tags.map((t) => (
                  <span key={t} className="rounded-full border border-primary-200 bg-primary-50 px-2 py-0.5 text-xs font-medium text-primary-800">
                    {t}
                  </span>
                )) : <span className="text-ink-muted">none declared</span>}
              </dd>
            </div>
            <div className="col-span-2">
              <dt className="text-xs uppercase text-ink-muted">Location (synthetic)</dt>
              <dd>{d.location_label}</dd>
            </div>
            {d.notes ? (
              <div className="col-span-2">
                <dt className="text-xs uppercase text-ink-muted">Notes</dt>
                <dd className="text-ink-muted">{d.notes}</dd>
              </div>
            ) : null}
          </dl>
        </section>

        <section aria-labelledby="reservations-heading" className="rounded-lg border border-line bg-surface-raised p-5">
          <h2 id="reservations-heading" className="font-semibold text-ink">
            Reservations ({d.reservations.length})
          </h2>
          <p className="mt-1 text-xs text-ink-muted">
            PROPOSED does not reserve stock; only ACCEPTED+ states commit quantity.
          </p>
          <ul className="mt-3 space-y-2 text-sm">
            {d.reservations.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2">
                <Link href="/reservations" className="tabular-nums font-medium text-primary-700 hover:underline">
                  {formatKg(r.quantity_kg)} kg
                </Link>
                <StatusBadge status={r.state} />
                <span className="text-xs text-ink-muted">{formatDateTime(r.created_at)}</span>
              </li>
            ))}
            {d.reservations.length === 0 ? (
              <li className="text-ink-muted">No reservations recorded.</li>
            ) : null}
          </ul>
        </section>

        <section aria-labelledby="revisions-heading" className="rounded-lg border border-line bg-surface-raised p-5">
          <h2 id="revisions-heading" className="font-semibold text-ink">Version history</h2>
          <ul className="mt-3 space-y-2 text-sm">
            {d.revisions.map((r) => (
              <li key={r.version} className="text-ink-muted">
                <span className="font-medium text-ink">v{r.version}</span> · {formatDateTime(r.changed_at)}
                <ul className="mt-1 list-disc pl-5 text-xs">
                  {Object.keys(r.after as Record<string, unknown>).slice(0, 6).map((key) => {
                    const before = (r.before as Record<string, unknown>)[key];
                    const after = (r.after as Record<string, unknown>)[key];
                    return before !== after ? (
                      <li key={key}>
                        {key}: {String(before)} → {String(after)}
                      </li>
                    ) : null;
                  })}
                </ul>
              </li>
            ))}
            {d.revisions.length === 0 ? (
              <li className="text-ink-muted">No edits recorded.</li>
            ) : null}
          </ul>
        </section>

        <section aria-labelledby="transitions-heading" className="rounded-lg border border-line bg-surface-raised p-5">
          <h2 id="transitions-heading" className="font-semibold text-ink">Lifecycle</h2>
          <p className="mt-2 text-sm text-ink-muted">
            Allowed next states: {d.available_transitions.length ? d.available_transitions.join(", ") : "terminal"}.
          </p>
          <p className="mt-2 text-xs text-ink-muted">
            Allowed actions for your role: {d.allowed_actions.length ? d.allowed_actions.join(", ") : "read-only"}.
          </p>
        </section>
      </div>
    </div>
  );
}
