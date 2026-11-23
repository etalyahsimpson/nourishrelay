"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { StatusBadge } from "@/components/StatusBadge";
import { PickupTimeline } from "@/components/PickupTimeline";
import { formatKg } from "@/components/MetricCard";
import { formatDateTime } from "@/lib/dates";
import type { ReservationSummary } from "@/lib/contracts";

const STATUSES = ["", "SCHEDULED", "COLLECTED", "DELIVERED", "FAILED"];

export default function PickupsPage() {
  const { user } = useSession();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [forms, setForms] = useState<Record<string, { quantity?: string; reason?: string; receiptQty?: string; receiptReason?: string }>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const pickups = useQuery({
    queryKey: ["pickups", "list", status],
    queryFn: () => api.pickups(status ? { status } : { limit: "50" }),
  });

  // accepted reservations without a pickup, for transport scheduling
  const accepted = useQuery({
    queryKey: ["reservations", "accepted-for-scheduling"],
    queryFn: () => api.reservations({ state: "ACCEPTED", limit: "50" }),
    enabled: !!user && ["transport", "coordinator", "admin"].includes(user.role),
  });

  function formFor(id: string) {
    return forms[id] ?? {};
  }
  function setForm(id: string, patch: Partial<{ quantity: string; reason: string; receiptQty: string; receiptReason: string }>) {
    setForms((f) => ({ ...f, [id]: { ...f[id], ...patch } }));
  }

  async function invalidate() {
    await queryClient.invalidateQueries({ queryKey: ["pickups"] });
    await queryClient.invalidateQueries({ queryKey: ["reservations"] });
    await queryClient.invalidateQueries({ queryKey: ["donations"] });
  }

  async function run(label: string, fn: () => Promise<unknown>, pickupId: string) {
    setBusy(pickupId);
    setError(null);
    try {
      await fn();
      await invalidate();
    } catch (err) {
      const apiError = err as ApiError;
      setError(`${label}: ${apiError.code ?? "ERROR"} — ${apiError.message ?? String(err)}`);
    } finally {
      setBusy(null);
    }
  }

  async function schedulePickup(r: ReservationSummary) {
    // Schedule inside the donation's own pickup window (validated server-side).
    const start = new Date(r.pickup_start);
    const end = new Date(Math.min(start.getTime() + 3600_000, new Date(r.pickup_end).getTime()));
    setBusy(r.id);
    setError(null);
    try {
      await api.createPickup({
        reservation_id: r.id,
        pickup_window_start: start.toISOString(),
        pickup_window_end: end.toISOString(),
      });
      await invalidate();
    } catch (err) {
      const apiError = err as ApiError;
      setError(`Schedule: ${apiError.code ?? "ERROR"} — ${apiError.message ?? String(err)}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-ink">Pickups</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-muted">
          The physical handoff trail: collection (donor handover), delivery (recorded
          transport) and recipient-confirmed receipt. Delivered is NOT received until the
          recipient confirms the quantity; failures after collection never reoffer stock.
        </p>
      </header>

      {error ? (
        <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {error}
        </p>
      ) : null}

      {accepted.data?.items.length ? (
        <section aria-labelledby="schedule-heading" className="rounded-lg border border-primary-200 bg-primary-50/40 p-4">
          <h2 id="schedule-heading" className="text-sm font-semibold text-ink">
            Accepted reservations awaiting pickup scheduling
          </h2>
          <ul className="mt-2 space-y-2 text-sm">
            {accepted.data.items.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2">
                <span className="tabular-nums font-medium">{formatKg(r.quantity_kg)} kg</span>
                <span className="text-ink-muted">{r.donation_category} → {r.recipient_org_name}</span>
                <span className="text-xs text-ink-muted">
                  window {formatDateTime(r.pickup_start)} → {formatDateTime(r.pickup_end)}
                </span>
                <button
                  type="button"
                  disabled={busy === r.id}
                  onClick={() => void schedulePickup(r)}
                  className="rounded bg-primary-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
                >
                  Schedule pickup (next hour window)
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <form className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface-raised p-4" onSubmit={(e) => e.preventDefault()}>
        <div>
          <label htmlFor="status-filter" className="block text-xs font-medium text-ink-muted">Status</label>
          <select
            id="status-filter"
            className="mt-1 rounded-md border border-line bg-white px-2 py-1.5 text-sm"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {STATUSES.map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
          </select>
        </div>
        <p className="text-xs text-ink-muted">{pickups.data?.total ?? 0} results</p>
      </form>

      {pickups.isLoading ? (
        <p className="text-sm text-ink-muted" aria-live="polite">Loading pickups…</p>
      ) : (
        <ul className="space-y-4">
          {(pickups.data?.items ?? []).map((p) => (
            <li key={p.id} className="rounded-lg border border-line bg-surface-raised p-4">
              <div className="flex flex-wrap items-center gap-3">
                <span className="tabular-nums text-lg font-bold text-ink">{formatKg(p.reserved_quantity_kg)} kg</span>
                <span className="capitalize text-sm text-ink-muted">{p.donation_category}</span>
                <StatusBadge status={p.status} />
                <span className="text-xs text-ink-muted">
                  {p.donor_org_name} → {p.recipient_org_name}
                  {p.assigned_transport_org_name ? ` via ${p.assigned_transport_org_name}` : ""}
                </span>
                <span className="ml-auto text-xs text-ink-muted">
                  window {formatDateTime(p.pickup_window_start)} → {formatDateTime(p.pickup_window_end)}
                </span>
              </div>
              <div className="mt-3">
                <PickupTimeline pickup={p} />
              </div>

              {p.allowed_actions.includes("collect") ? (
                <form
                  className="mt-3 flex flex-wrap items-end gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run("Collect", () => api.pickupEvent(p.id, {
                      event_type: "COLLECTED",
                      quantity_kg: formFor(p.id).quantity ?? p.reserved_quantity_kg,
                    }), p.id);
                  }}
                >
                  <div>
                    <label htmlFor={`qty-${p.id}`} className="block text-xs font-medium text-ink-muted">
                      Collected kg (≤ accepted {p.reserved_quantity_kg})
                    </label>
                    <input
                      id={`qty-${p.id}`}
                      inputMode="decimal"
                      className="mt-1 w-28 rounded border border-line px-2 py-1 text-sm tabular-nums"
                      placeholder={p.reserved_quantity_kg}
                      value={formFor(p.id).quantity ?? ""}
                      onChange={(e) => setForm(p.id, { quantity: e.target.value })}
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={busy === p.id}
                    className="rounded bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-800 disabled:opacity-50"
                  >
                    Record collection
                  </button>
                </form>
              ) : null}

              {p.allowed_actions.includes("deliver") ? (
                <button
                  type="button"
                  disabled={busy === p.id}
                  onClick={() => void run("Deliver", () => api.pickupEvent(p.id, { event_type: "DELIVERED" }), p.id)}
                  className="mt-3 rounded bg-teal-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-teal-800 disabled:opacity-50"
                >
                  Record delivery
                </button>
              ) : null}

              {p.allowed_actions.includes("fail") ? (
                <form
                  className="mt-3 flex flex-wrap items-end gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run("Fail", () => api.pickupEvent(p.id, {
                      event_type: "FAILED",
                      reason: formFor(p.id).reason || "Reported from pickups view",
                    }), p.id);
                  }}
                >
                  <div>
                    <label htmlFor={`reason-${p.id}`} className="block text-xs font-medium text-ink-muted">
                      Failure reason (required)
                    </label>
                    <input
                      id={`reason-${p.id}`}
                      className="mt-1 w-72 rounded border border-line px-2 py-1 text-sm"
                      value={formFor(p.id).reason ?? ""}
                      onChange={(e) => setForm(p.id, { reason: e.target.value })}
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={busy === p.id}
                    className="rounded border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                  >
                    {p.status === "SCHEDULED" ? "Report failure (before collection)" : "Report failure (after collection)"}
                  </button>
                </form>
              ) : null}

              {p.allowed_actions.includes("receipt") ? (
                <form
                  className="mt-3 flex flex-wrap items-end gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const qty = formFor(p.id).receiptQty ?? p.collected_quantity_kg ?? p.reserved_quantity_kg;
                    const reason = formFor(p.id).receiptReason?.trim();
                    void run("Receipt", () => api.confirmReceipt(p.id, {
                      received_quantity_kg: qty,
                      exception_reason: reason || null,
                    }), p.id);
                  }}
                >
                  <div>
                    <label htmlFor={`rq-${p.id}`} className="block text-xs font-medium text-ink-muted">
                      Received kg (≤ collected {p.collected_quantity_kg ?? "—"})
                    </label>
                    <input
                      id={`rq-${p.id}`}
                      inputMode="decimal"
                      className="mt-1 w-28 rounded border border-line px-2 py-1 text-sm tabular-nums"
                      placeholder={p.collected_quantity_kg ?? ""}
                      value={formFor(p.id).receiptQty ?? ""}
                      onChange={(e) => setForm(p.id, { receiptQty: e.target.value })}
                    />
                  </div>
                  <div>
                    <label htmlFor={`rr-${p.id}`} className="block text-xs font-medium text-ink-muted">
                      Exception reason (required if less than collected)
                    </label>
                    <input
                      id={`rr-${p.id}`}
                      className="mt-1 w-72 rounded border border-line px-2 py-1 text-sm"
                      value={formFor(p.id).receiptReason ?? ""}
                      onChange={(e) => setForm(p.id, { receiptReason: e.target.value })}
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={busy === p.id}
                    className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                  >
                    Confirm receipt
                  </button>
                </form>
              ) : null}
            </li>
          ))}
          {(pickups.data?.items ?? []).length === 0 ? (
            <li className="rounded-lg border border-line bg-surface-raised p-6 text-center text-sm text-ink-muted">
              No pickups in this view{user?.role === "transport" ? " — accepted reservations appear above for scheduling" : ""}.
            </li>
          ) : null}
        </ul>
      )}
    </div>
  );
}
