"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RoleGuard } from "@/components/RoleGuard";
import { MatchTable } from "@/components/MatchTable";
import { formatKg } from "@/components/MetricCard";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime } from "@/lib/dates";

export default function MatchingPage() {
  const donations = useQuery({
    queryKey: ["donations", "matching"],
    queryFn: () => api.donations({ status: "AVAILABLE", limit: "50" }),
  });
  const partly = useQuery({
    queryKey: ["donations", "matching-partial"],
    queryFn: () => api.donations({ status: "PARTIALLY_RESERVED", limit: "50" }),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const items = [...(donations.data?.items ?? []), ...(partly.data?.items ?? [])];
  const matches = useQuery({
    queryKey: ["matches", selected],
    queryFn: () => api.matches(selected as string),
    enabled: !!selected,
  });

  return (
    <RoleGuard allow={["coordinator", "admin"]} title="Matching">
      <div className="space-y-6">
        <header>
          <h1 className="text-2xl font-bold text-ink">Matching</h1>
          <p className="mt-1 max-w-3xl text-sm text-ink-muted">
            Deterministic, constraint-first matching with full explanations. Select an open
            donation to compute eligible recipients, exclusion reasons and the weighted
            demonstration score. You (the coordinator) stay in control: proposals are
            created only when you choose them.
          </p>
        </header>

        <section aria-labelledby="open-heading" className="rounded-lg border border-line bg-surface-raised p-4">
          <h2 id="open-heading" className="text-sm font-semibold text-ink">
            Open donations
          </h2>
          <div className="nr-scroll mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <caption className="sr-only">Open donations eligible for matching</caption>
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase text-ink-muted">
                  <th scope="col" className="px-3 py-2">Donor</th>
                  <th scope="col" className="px-3 py-2">Category</th>
                  <th scope="col" className="px-3 py-2">Available</th>
                  <th scope="col" className="px-3 py-2">Status</th>
                  <th scope="col" className="px-3 py-2">Pickup</th>
                  <th scope="col" className="px-3 py-2"><span className="sr-only">Compute</span></th>
                </tr>
              </thead>
              <tbody>
                {items.map((d) => (
                  <tr key={d.id} className={`border-b border-line last:border-0 ${selected === d.id ? "bg-primary-50" : ""}`}>
                    <td className="px-3 py-2">{d.donor_org_name}</td>
                    <td className="px-3 py-2 capitalize">{d.category}</td>
                    <td className="px-3 py-2 tabular-nums">{formatKg(d.available_kg)} kg</td>
                    <td className="px-3 py-2"><StatusBadge status={d.status} /></td>
                    <td className="px-3 py-2 text-xs text-ink-muted">{formatDateTime(d.pickup_start)}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => { setSelected(d.id); setMessage(null); }}
                        aria-pressed={selected === d.id}
                        className="rounded border border-primary-300 px-2.5 py-1 text-xs font-semibold text-primary-700 hover:bg-primary-50"
                      >
                        {selected === d.id ? "Selected" : "Compute matches"}
                      </button>
                    </td>
                  </tr>
                ))}
                {items.length === 0 ? (
                  <tr><td colSpan={6} className="px-3 py-6 text-center text-ink-muted">No open donations right now.</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        {message ? (
          <p
            role="status"
            className={`rounded-md border p-3 text-sm ${message.tone === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-800"}`}
          >
            {message.text}
          </p>
        ) : null}

        {selected ? (
          <section aria-labelledby="result-heading">
            <h2 id="result-heading" className="text-lg font-semibold text-ink">Match results</h2>
            {matches.isLoading ? (
              <p className="mt-2 text-sm text-ink-muted" aria-live="polite">Computing matches…</p>
            ) : matches.isError ? (
              <p className="mt-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
                {(matches.error as Error).message}
              </p>
            ) : matches.data ? (
              <div className="mt-3 space-y-4">
                <p className="text-sm text-ink-muted">
                  Donation available stock: <span className="tabular-nums font-medium text-ink">{formatKg(matches.data.available_kg)} kg</span> · computed {formatDateTime(matches.data.generated_at)}
                </p>
                <MatchTable
                  matches={matches.data}
                  proposeEnabled
                  onPropose={(result) => {
                    setMessage(
                      result.status === "proposed"
                        ? { tone: "ok", text: "Proposal created — awaiting the recipient's acceptance decision." }
                        : { tone: "error", text: result.message ?? "Proposal failed." },
                    );
                    void matches.refetch();
                  }}
                />
              </div>
            ) : null}
          </section>
        ) : (
          <p className="text-sm text-ink-muted">Select a donation above to compute matches.</p>
        )}
      </div>
    </RoleGuard>
  );
}
