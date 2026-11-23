"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { StatusBadge } from "@/components/StatusBadge";
import { formatKg } from "@/components/MetricCard";
import { formatDateTime, relativeTime } from "@/lib/dates";

const STATES = [
  "", "PROPOSED", "ACCEPTED", "PICKUP_ASSIGNED", "COLLECTED", "DELIVERED",
  "RECEIVED", "DECLINED", "CANCELLED", "EXPIRED", "FAILED",
];

export default function ReservationsPage() {
  const { user } = useSession();
  const queryClient = useQueryClient();
  const [state, setState] = useState(user?.role === "recipient" ? "PROPOSED" : "");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const query: Record<string, string> = { limit: "50" };
  if (state) query.state = state;

  const reservations = useQuery({
    queryKey: ["reservations", "list", state],
    queryFn: () => api.reservations(query),
  });

  async function decide(action: "accept" | "decline", id: string, reason?: string) {
    setBusyId(id);
    setError(null);
    try {
      if (action === "accept") await api.acceptReservation(id);
      else await api.declineReservation(id, reason);
      await queryClient.invalidateQueries({ queryKey: ["reservations"] });
      await queryClient.invalidateQueries({ queryKey: ["donations"] });
    } catch (err) {
      const apiError = err as ApiError;
      if (apiError.code === "STOCK_CONFLICT") {
        setError(
          `STOCK_CONFLICT: ${apiError.message} Remaining availability: ${
            (apiError.details as { available_kg?: string })?.available_kg ?? "?"
          } kg. Refresh to see the live state.`,
        );
      } else {
        setError(`${apiError.code ?? "ERROR"}: ${apiError.message ?? String(err)}`);
      }
      await queryClient.invalidateQueries({ queryKey: ["reservations"] });
    } finally {
      setBusyId(null);
    }
  }

  async function cancel(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await api.cancelReservation(id, "Cancelled from reservations view");
      await queryClient.invalidateQueries({ queryKey: ["reservations"] });
    } catch (err) {
      const apiError = err as ApiError;
      setError(`${apiError.code ?? "ERROR"}: ${apiError.message ?? String(err)}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-ink">Reservations</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {user?.role === "recipient"
            ? "Proposals awaiting your decision and your reservation history. A stale acceptance shows the honest 409 with live availability."
            : "Reservation pipeline for your scope. Cancellation releases uncollected stock exactly once."}
        </p>
      </header>

      <form className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface-raised p-4" onSubmit={(e) => e.preventDefault()}>
        <div>
          <label htmlFor="state-filter" className="block text-xs font-medium text-ink-muted">State</label>
          <select
            id="state-filter"
            className="mt-1 rounded-md border border-line bg-white px-2 py-1.5 text-sm"
            value={state}
            onChange={(e) => setState(e.target.value)}
          >
            {STATES.map((s) => <option key={s} value={s}>{s || "All states"}</option>)}
          </select>
        </div>
        <p className="text-xs text-ink-muted">{reservations.data?.total ?? 0} results</p>
      </form>

      {error ? (
        <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {error}
        </p>
      ) : null}

      {reservations.isLoading ? (
        <p className="text-sm text-ink-muted" aria-live="polite">Loading reservations…</p>
      ) : reservations.isError ? (
        <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {(reservations.error as Error).message}
        </p>
      ) : (
        <div className="nr-scroll overflow-x-auto rounded-lg border border-line bg-surface-raised">
          <table className="w-full min-w-[900px] text-sm">
            <caption className="sr-only">Reservations with state and actions</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase text-ink-muted">
                <th scope="col" className="px-3 py-2">Quantity</th>
                <th scope="col" className="px-3 py-2">Donation</th>
                <th scope="col" className="px-3 py-2">Recipient</th>
                <th scope="col" className="px-3 py-2">State</th>
                <th scope="col" className="px-3 py-2">Donation available</th>
                <th scope="col" className="px-3 py-2">Proposal expiry</th>
                <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {(reservations.data?.items ?? []).map((r) => (
                <tr key={r.id} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 font-medium tabular-nums" data-testid="res-quantity">
                    {formatKg(r.quantity_kg)} kg
                  </td>
                  <td className="px-3 py-2">
                    <span className="capitalize">{r.donation_category}</span>
                    <span className="ml-1 text-xs text-ink-muted">from {r.donor_org_name}</span>
                  </td>
                  <td className="px-3 py-2">{r.recipient_org_name}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={r.state} />
                    {r.failure_stage ? (
                      <span className="ml-1 text-xs text-rose-700">{r.failure_stage.toLowerCase().replace("_", " ")}</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-xs text-ink-muted">
                    {r.donation_available_kg ? `${formatKg(r.donation_available_kg)} kg` : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs text-ink-muted">
                    {r.proposal_expires_at
                      ? `${formatDateTime(r.proposal_expires_at)} (${relativeTime(r.proposal_expires_at)})`
                      : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-2">
                      {r.allowed_actions.includes("accept") ? (
                        <button
                          type="button"
                          disabled={busyId === r.id}
                          onClick={() => void decide("accept", r.id)}
                          className="rounded bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                        >
                          Accept {formatKg(r.quantity_kg)} kg
                        </button>
                      ) : null}
                      {r.allowed_actions.includes("decline") ? (
                        <button
                          type="button"
                          disabled={busyId === r.id}
                          onClick={() => void decide("decline", r.id, "Not needed right now")}
                          className="rounded border border-line px-2.5 py-1 text-xs font-semibold text-ink hover:bg-stone-50 disabled:opacity-50"
                        >
                          Decline
                        </button>
                      ) : null}
                      {r.allowed_actions.includes("cancel") ? (
                        <button
                          type="button"
                          disabled={busyId === r.id}
                          onClick={() => void cancel(r.id)}
                          className="rounded border border-rose-300 px-2.5 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
              {(reservations.data?.items ?? []).length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-8 text-center text-ink-muted">
                    No reservations in this view.
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
