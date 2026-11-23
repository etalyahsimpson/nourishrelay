"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { MetricCard, formatKg, formatRatio } from "@/components/MetricCard";
import { formatDateTime } from "@/lib/dates";
import type { OperationsReport } from "@/lib/contracts";

const WINDOWS = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 14 days", days: 14 },
  { label: "Last 30 days", days: 30 },
];

function windowQuery(days: number) {
  return {
    from: new Date(Date.now() - days * 86400_000).toISOString().replace("+00:00", "Z"),
    to: new Date(Date.now() + 2 * 86400_000).toISOString().replace("+00:00", "Z"),
  };
}

export default function ReportsPage() {
  const [days, setDays] = useState(14);
  const report = useQuery({
    queryKey: ["report", days],
    queryFn: () => api.operationsReport(windowQuery(days)),
  });

  const data: OperationsReport | undefined = report.data;

  function downloadCsv() {
    const url = api.operationsCsvUrl(windowQuery(days));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "nourishrelay-operations.csv";
    anchor.click();
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-ink">Operational report</h1>
          <p className="mt-1 max-w-3xl text-sm text-ink-muted">
            Computed strictly from recorded transactions in this synthetic demo database.
            Ratios carry explicit numerators and denominators; a zero denominator renders
            N/A — never a fabricated 0%/100%.
          </p>
        </div>
        <button
          type="button"
          onClick={downloadCsv}
          className="rounded-md border border-primary-300 px-4 py-2 text-sm font-semibold text-primary-800 hover:bg-primary-50"
        >
          Export CSV
        </button>
      </header>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Report window">
        {WINDOWS.map((w) => (
          <button
            key={w.days}
            type="button"
            aria-pressed={days === w.days}
            onClick={() => setDays(w.days)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              days === w.days
                ? "bg-primary-100 text-primary-800 border border-primary-300"
                : "border border-line text-ink-muted hover:bg-primary-50"
            }`}
          >
            {w.label}
          </button>
        ))}
      </div>

      {report.isLoading ? (
        <p className="text-sm text-ink-muted" aria-live="polite">Computing report…</p>
      ) : report.isError ? (
        <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {(report.error as Error).message} — your role may be restricted to its own
          organization&apos;s scope.
        </p>
      ) : data ? (
        <>
          <p className="text-xs text-ink-muted">
            Window {formatDateTime(data.window_from)} → {formatDateTime(data.window_to)} ·
            scope: {data.scope_organization_name ?? "all organizations (platform scope)"}
          </p>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="Offered" value={formatKg(data.offered_kg)} unit="kg" hint={`${data.offers} offers`} />
            <MetricCard label="Committed (current)" value={formatKg(data.committed_kg)} unit="kg" />
            <MetricCard label="Collected" value={formatKg(data.collected_kg)} unit="kg" hint={`${data.pickups} pickups`} />
            <MetricCard label="Received (confirmed)" value={formatKg(data.received_kg)} unit="kg" />
            <MetricCard label="Reservations" value={data.reservations} />
            <MetricCard label="Failures" value={data.failures} hint={`after/before collection`} />
            <MetricCard label="Cancellations" value={data.cancellations} />
            <MetricCard
              label="Median pickup lead"
              value={data.median_pickup_lead_time_minutes === null ? "N/A" : data.median_pickup_lead_time_minutes}
              unit={data.median_pickup_lead_time_minutes === null ? undefined : "min"}
              hint="proposal → collection, where events exist"
            />
          </div>

          <section aria-labelledby="ratios-heading" className="rounded-lg border border-line bg-surface-raised p-5">
            <h2 id="ratios-heading" className="font-semibold text-ink">Ratios (numerator / denominator)</h2>
            <ul className="mt-3 space-y-2 text-sm">
              {data.ratios.map((r) => (
                <li key={r.label} className="flex flex-wrap items-center gap-2">
                  <span className="min-w-44 font-medium text-ink">{r.label}</span>
                  <span className="tabular-nums text-ink-muted">
                    {formatKg(r.numerator)} / {formatKg(r.denominator)} kg
                  </span>
                  <span className="rounded border border-primary-200 bg-primary-50 px-2 py-0.5 font-semibold tabular-nums text-primary-800">
                    {formatRatio(r.value)}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <section aria-labelledby="categories-heading" className="rounded-lg border border-line bg-surface-raised p-5">
              <h2 id="categories-heading" className="font-semibold text-ink">Offered by category</h2>
              <div className="mt-3 flex items-end gap-4" role="img" aria-label="Bar chart of offered kilograms by category">
                {data.categories.map((c) => {
                  const max = Math.max(...data.categories.map((x) => Number(x.offered_kg)), 1);
                  const height = Math.max((Number(c.offered_kg) / max) * 100, 2);
                  return (
                    <div key={c.category} className="flex w-16 flex-col items-center gap-1">
                      <span className="text-xs tabular-nums text-ink-muted">{formatKg(c.offered_kg)}</span>
                      <div
                        className="w-full rounded-t bg-primary-500"
                        style={{ height: `${height}px` }}
                        aria-hidden="true"
                      />
                      <span className="text-xs font-medium capitalize text-ink">{c.category}</span>
                    </div>
                  );
                })}
              </div>
            </section>

            <section aria-labelledby="exceptions-heading" className="rounded-lg border border-line bg-surface-raised p-5">
              <h2 id="exceptions-heading" className="font-semibold text-ink">Exception reasons</h2>
              <ul className="mt-3 space-y-2 text-sm">
                {data.failure_reasons.map((f) => (
                  <li key={f.kind} className="flex flex-wrap items-center gap-2">
                    <span className="rounded border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs text-rose-800">
                      {f.count}× failure
                    </span>
                    <span className="text-ink-muted">{f.kind}</span>
                  </li>
                ))}
                {data.cancellation_reasons.map((c) => (
                  <li key={c.kind} className="flex flex-wrap items-center gap-2">
                    <span className="rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-800">
                      {c.count}× cancelled
                    </span>
                    <span className="text-ink-muted">{c.kind}</span>
                  </li>
                ))}
                {!data.failure_reasons.length && !data.cancellation_reasons.length ? (
                  <li className="text-ink-muted">No exceptions recorded in the window.</li>
                ) : null}
              </ul>
            </section>
          </div>

          <p className="text-xs text-ink-muted">{data.note}</p>
        </>
      ) : null}
    </div>
  );
}
