"use client";

/** Status chip: color + text label (never color-only). */

import { type ReactNode } from "react";

const STATUS_META: Record<string, { tone: string; label: string }> = {
  // donations
  DRAFT: { tone: "bg-stone-100 text-stone-700 border-stone-300", label: "Draft" },
  AVAILABLE: { tone: "bg-emerald-100 text-emerald-800 border-emerald-300", label: "Available" },
  PARTIALLY_RESERVED: { tone: "bg-amber-100 text-amber-800 border-amber-300", label: "Partly reserved" },
  FULLY_RESERVED: { tone: "bg-amber-100 text-amber-900 border-amber-400", label: "Fully reserved" },
  CLOSED: { tone: "bg-teal-100 text-teal-800 border-teal-300", label: "Closed" },
  EXPIRED: { tone: "bg-stone-200 text-stone-700 border-stone-400", label: "Expired" },
  WITHDRAWN: { tone: "bg-rose-100 text-rose-800 border-rose-300", label: "Withdrawn" },
  // reservations
  PROPOSED: { tone: "bg-sky-100 text-sky-800 border-sky-300", label: "Proposed" },
  ACCEPTED: { tone: "bg-emerald-100 text-emerald-800 border-emerald-300", label: "Accepted" },
  DECLINED: { tone: "bg-stone-100 text-stone-600 border-stone-300", label: "Declined" },
  CANCELLED: { tone: "bg-rose-100 text-rose-800 border-rose-300", label: "Cancelled" },
  PICKUP_ASSIGNED: { tone: "bg-indigo-0 bg-teal-50 text-teal-800 border-teal-300", label: "Pickup assigned" },
  COLLECTED: { tone: "bg-cyan-100 text-cyan-900 border-cyan-300", label: "Collected" },
  DELIVERED: { tone: "bg-teal-100 text-teal-800 border-teal-300", label: "Delivered" },
  RECEIVED: { tone: "bg-emerald-200 text-emerald-900 border-emerald-400", label: "Received" },
  FAILED: { tone: "bg-rose-100 text-rose-800 border-rose-300", label: "Failed" },
  // pickups
  SCHEDULED: { tone: "bg-sky-100 text-sky-800 border-sky-300", label: "Scheduled" },
};

export function StatusBadge({ status, children }: { status: string; children?: ReactNode }) {
  const meta = STATUS_META[status] ?? {
    tone: "bg-stone-100 text-stone-700 border-stone-300",
    label: status,
  };
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold ${meta.tone}`}
      data-status={status}
    >
      {children ?? meta.label}
    </span>
  );
}

export function statusLabel(status: string): string {
  return (STATUS_META[status] ?? { label: status }).label;
}
