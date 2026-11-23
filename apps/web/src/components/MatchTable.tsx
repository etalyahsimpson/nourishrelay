"use client";

/** Matching table: ranked eligible recipients with per-factor explanations,
 *  excluded recipients with machine-readable reasons, and proposal creation. */

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { formatKg } from "./MetricCard";
import type { MatchList } from "@/lib/contracts";

const REASON_LABELS: Record<string, string> = {
  RECIPIENT_NOT_VERIFIED: "Recipient not verified",
  RECIPIENT_INACTIVE: "Recipient inactive",
  CATEGORY_NOT_ACCEPTED: "Does not accept this category",
  HANDLING_NOT_ACKNOWLEDGED: "Handling not acknowledged",
  RECEIVING_WINDOW_MISMATCH: "No receiving-window overlap",
  CAPACITY_UNKNOWN: "Capacity unknown (human review)",
  DAILY_CAPACITY_EXHAUSTED: "Daily capacity exhausted",
  DONATION_NOT_AVAILABLE: "Donation not open",
  DEADLINE_PASSED: "Deadline passed",
  STOCK_EXHAUSTED: "No stock available",
};

export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason;
}

export function MatchTable({
  matches,
  onPropose,
  proposeEnabled,
}: {
  matches: MatchList;
  onPropose?: (result: { status: "proposed" | "error"; message?: string }) => void;
  proposeEnabled?: boolean;
}) {
  const [proposing, setProposing] = useState<string | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});

  async function propose(recipientId: string, quantity: string) {
    if (!onPropose) return;
    setProposing(recipientId);
    try {
      await api.proposeReservation({
        donation_id: matches.donation_id,
        recipient_org_id: recipientId,
        quantity_kg: quantity,
        // proposal_expires_at defaults to +12h inside the api client
      });
      onPropose({ status: "proposed" });
    } catch (err) {
      onPropose({
        status: "error",
        message:
          err instanceof ApiError
            ? `${err.code}: ${err.message}`
            : "Unexpected error proposing the reservation.",
      });
    } finally {
      setProposing(null);
    }
  }

  return (
    <div className="space-y-6">
      <section aria-labelledby="eligible-heading">
        <h3 id="eligible-heading" className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Eligible recipients ({matches.eligible.length}) — ranked by demonstration scoring
        </h3>
        <div className="nr-scroll mt-2 overflow-x-auto rounded-lg border border-line bg-surface-raised">
          <table className="w-full min-w-[720px] text-sm">
            <caption className="sr-only">
              Eligible recipients ranked by score with explanations
            </caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase text-ink-muted">
                <th scope="col" className="px-3 py-2">Recipient</th>
                <th scope="col" className="px-3 py-2">Max feasible</th>
                <th scope="col" className="px-3 py-2">Score</th>
                <th scope="col" className="px-3 py-2">Reasons / factor breakdown</th>
                {proposeEnabled ? <th scope="col" className="px-3 py-2">Propose</th> : null}
              </tr>
            </thead>
            <tbody>
              {matches.eligible.map((c) => (
                <tr key={c.recipient_id} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 font-medium text-ink">{c.recipient_name}</td>
                  <td className="px-3 py-2 tabular-nums">{formatKg(c.max_feasible_kg)} kg</td>
                  <td className="px-3 py-2 tabular-nums" title="Demonstration scoring — not a transport or safety guarantee">
                    {c.score.toFixed(3)}
                    {c.zero_history ? (
                      <span className="ml-2 rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-700" title="Fewer than 3 concluded pickups: neutral 0.5 reliability, marked NOT_AVAILABLE">
                        zero history
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2">
                    <ul className="list-disc space-y-1 pl-4 text-xs text-ink-muted">
                      {c.score_breakdown.map((f) => (
                        <li key={f.factor}>
                          <span className="font-medium text-ink">{f.factor}</span> weight{" "}
                          {f.weight.toFixed(2)} · {f.known ? `normalized ${f.normalized?.toFixed(3)}` : "NOT_AVAILABLE (neutral 0.5)"}
                          {f.raw !== null ? ` · raw ${f.raw}` : ""}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-1 text-xs text-ink-muted">{c.reasons.slice(0, 3).join(" · ")}</p>
                  </td>
                  {proposeEnabled ? (
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <label className="sr-only" htmlFor={`qty-${c.recipient_id}`}>
                          Quantity for {c.recipient_name}
                        </label>
                        <input
                          id={`qty-${c.recipient_id}`}
                          inputMode="decimal"
                          className="w-24 rounded border border-line px-2 py-1 text-sm tabular-nums"
                          placeholder={c.max_feasible_kg}
                          value={quantities[c.recipient_id] ?? ""}
                          onChange={(e) =>
                            setQuantities((q) => ({ ...q, [c.recipient_id]: e.target.value }))
                          }
                        />
                        <button
                          type="button"
                          className="rounded bg-primary-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
                          disabled={
                            proposing === c.recipient_id ||
                            !(quantities[c.recipient_id] ?? "").trim()
                          }
                          onClick={() => void propose(c.recipient_id, quantities[c.recipient_id])}
                        >
                          {proposing === c.recipient_id ? "Proposing…" : "Propose"}
                        </button>
                      </div>
                    </td>
                  ) : null}
                </tr>
              ))}
              {matches.eligible.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-ink-muted">
                    No eligible recipients for this donation right now.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          Weights: capacity {matches.weights.capacity} · reliability {matches.weights.reliability} ·
          fairness {matches.weights.fairness} · same-area {matches.weights.same_area}. Hard
          constraints always outrank the score; scoring never certifies transport or food safety.
        </p>
      </section>

      <section aria-labelledby="excluded-heading">
        <h3 id="excluded-heading" className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Excluded recipients ({matches.excluded.length}) — with reasons
        </h3>
        <ul className="mt-2 divide-y divide-line rounded-lg border border-line bg-surface-raised text-sm">
          {matches.excluded.map((x) => (
            <li key={x.recipient_id} className="flex flex-wrap items-center gap-2 px-3 py-2">
              <span className="font-medium text-ink">{x.recipient_name}</span>
              {x.reasons.map((reason) => (
                <span
                  key={reason}
                  className="rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-800"
                >
                  {reasonLabel(reason)}
                </span>
              ))}
            </li>
          ))}
          {matches.excluded.length === 0 ? (
            <li className="px-3 py-3 text-ink-muted">No excluded recipients.</li>
          ) : null}
        </ul>
      </section>
    </div>
  );
}
