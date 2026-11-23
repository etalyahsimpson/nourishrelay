"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { StatusBadge } from "@/components/StatusBadge";
import { formatKg } from "@/components/MetricCard";
import { formatDate, formatDateTime, relativeTime } from "@/lib/dates";

const STATUSES = ["", "DRAFT", "AVAILABLE", "PARTIALLY_RESERVED", "FULLY_RESERVED", "CLOSED", "EXPIRED", "WITHDRAWN"];
const CATEGORIES = ["", "produce", "baked", "dairy", "canned", "prepared"];

export default function DonationsPage() {
  const { user } = useSession();
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const query: Record<string, string> = { limit: "50" };
  if (status) query.status = status;
  if (category) query.category = category;

  const donations = useQuery({
    queryKey: ["donations", "list", status, category],
    queryFn: () => api.donations(query),
    enabled: !!user,
  });

  const canCreate = user?.role === "donor";

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-ink">Donations</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {user?.role === "donor"
              ? "Your organization's offers, including drafts."
              : "Published offers visible to your role with derived availability."}
          </p>
        </div>
        {canCreate ? (
          <Link
            href="/donations/new"
            className="rounded-md bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700"
          >
            New donation
          </Link>
        ) : null}
      </header>

      <form className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface-raised p-4" onSubmit={(e) => e.preventDefault()}>
        <div>
          <label htmlFor="status-filter" className="block text-xs font-medium text-ink-muted">Status</label>
          <select
            id="status-filter"
            className="mt-1 rounded-md border border-line bg-white px-2 py-1.5 text-sm"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s || "All statuses"}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="category-filter" className="block text-xs font-medium text-ink-muted">Category</label>
          <select
            id="category-filter"
            className="mt-1 rounded-md border border-line bg-white px-2 py-1.5 text-sm"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{c || "All categories"}</option>
            ))}
          </select>
        </div>
        <p className="text-xs text-ink-muted">{donations.data?.total ?? 0} results</p>
      </form>

      {donations.isLoading ? (
        <p className="text-sm text-ink-muted" aria-live="polite">Loading donations…</p>
      ) : donations.isError ? (
        <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {(donations.error as Error)?.message ?? "Failed to load donations."}
        </p>
      ) : (
        <div className="nr-scroll overflow-x-auto rounded-lg border border-line bg-surface-raised">
          <table className="w-full min-w-[820px] text-sm">
            <caption className="sr-only">Donations with availability and deadlines</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase text-ink-muted">
                <th scope="col" className="px-3 py-2">Donor</th>
                <th scope="col" className="px-3 py-2">Category</th>
                <th scope="col" className="px-3 py-2">Quantity</th>
                <th scope="col" className="px-3 py-2">Available</th>
                <th scope="col" className="px-3 py-2">Status</th>
                <th scope="col" className="px-3 py-2">Pickup window</th>
                <th scope="col" className="px-3 py-2">Deadline</th>
                <th scope="col" className="px-3 py-2"><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody>
              {(donations.data?.items ?? []).map((d) => (
                <tr key={d.id} className="border-b border-line last:border-0 hover:bg-primary-50/40">
                  <td className="px-3 py-2">{d.donor_org_name}</td>
                  <td className="px-3 py-2 capitalize">{d.category}</td>
                  <td className="px-3 py-2 tabular-nums">{formatKg(d.quantity_kg)} kg</td>
                  <td className="px-3 py-2 tabular-nums" data-testid="available-kg">{formatKg(d.available_kg)} kg</td>
                  <td className="px-3 py-2"><StatusBadge status={d.status} /></td>
                  <td className="px-3 py-2 text-xs text-ink-muted">
                    {formatDateTime(d.pickup_start)} → {formatDateTime(d.pickup_end)}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    <span className="text-ink-muted">{formatDate(d.deadline)}</span>{" "}
                    <span className="text-ink-muted">({relativeTime(d.deadline)})</span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link href={`/donations/${d.id}`} className="font-medium text-primary-700 hover:underline">
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
              {(donations.data?.items ?? []).length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-3 py-8 text-center text-ink-muted">
                    No donations match the current filters.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
