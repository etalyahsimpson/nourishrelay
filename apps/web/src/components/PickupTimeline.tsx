"use client";

/** Pickup lifecycle timeline: status trail with quantities and reasons. */

import { formatDateTime } from "@/lib/dates";
import { formatKg } from "./MetricCard";

const STEPS = ["SCHEDULED", "COLLECTED", "DELIVERED", "RECEIVED"] as const;

export function PickupTimeline({ pickup }: { pickup: PickupLike }) {
  const failed = pickup.status === "FAILED";
  const stepIndex = failed
    ? pickup.collected_at
      ? 1
      : 0
    : STEPS.indexOf(pickup.status as (typeof STEPS)[number]);

  return (
    <div>
      <ol className="flex flex-wrap items-center gap-2 text-xs" aria-label="Pickup progress">
        {STEPS.map((step, i) => {
          const state = failed && i > stepIndex ? "failed" : i < stepIndex ? "done" : i === stepIndex ? "current" : "todo";
          return (
            <li key={step} className="flex items-center gap-2">
              <span
                className={`inline-flex h-6 items-center rounded-full border px-2.5 font-semibold ${
                  state === "done"
                    ? "border-emerald-400 bg-emerald-100 text-emerald-800"
                    : state === "current"
                      ? "border-primary-500 bg-primary-100 text-primary-800"
                      : state === "failed"
                        ? "border-rose-300 bg-rose-50 text-rose-700"
                        : "border-line bg-white text-ink-muted"
                }`}
                data-step={step}
                data-state={state}
              >
                {step}
              </span>
              {i < STEPS.length - 1 ? <span aria-hidden="true" className="text-ink-muted">→</span> : null}
            </li>
          );
        })}
      </ol>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-ink-muted sm:grid-cols-3">
        <div>
          <dt className="font-medium text-ink">Reserved</dt>
          <dd className="tabular-nums">{formatKg(pickup.reserved_quantity_kg)} kg</dd>
        </div>
        <div>
          <dt className="font-medium text-ink">Collected</dt>
          <dd className="tabular-nums">
            {pickup.collected_quantity_kg ? `${formatKg(pickup.collected_quantity_kg)} kg` : "—"}
            {pickup.collected_at ? ` · ${formatDateTime(pickup.collected_at)}` : ""}
          </dd>
        </div>
        <div>
          <dt className="font-medium text-ink">Received</dt>
          <dd className="tabular-nums">
            {pickup.receipt
              ? `${formatKg(pickup.receipt.received_quantity_kg)} kg · ${formatDateTime(pickup.receipt.confirmed_at)}`
              : failed
                ? "none"
                : "pending"}
          </dd>
        </div>
        {pickup.failure_reason ? (
          <div className="col-span-2 sm:col-span-3">
            <dt className="font-medium text-rose-800">Failure reason</dt>
            <dd>{pickup.failure_reason}</dd>
          </div>
        ) : null}
        {pickup.receipt?.exception_reason ? (
          <div className="col-span-2 sm:col-span-3">
            <dt className="font-medium text-amber-800">Receipt exception</dt>
            <dd>{pickup.receipt.exception_reason}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

export type PickupLike = {
  status: string;
  reserved_quantity_kg: string;
  collected_quantity_kg: string | null;
  collected_at: string | null;
  reserved?: string;
  failure_reason: string | null;
  receipt: {
    received_quantity_kg: string;
    confirmed_at: string;
    exception_reason: string | null;
  } | null;
};
