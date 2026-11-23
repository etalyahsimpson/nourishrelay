"use client";

/** KPI tile for DB-derived metrics. Value + unit + provenance hint. */

import { type ReactNode } from "react";

export function MetricCard({
  label,
  value,
  unit,
  hint,
  children,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface-raised p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums text-ink" data-testid="metric-value">
        {value}
        {unit ? <span className="ml-1 text-sm font-medium text-ink-muted">{unit}</span> : null}
      </p>
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
      {children}
    </div>
  );
}

/** Formats "N/A" for null ratios — never a fake 0%/100%. */
export function formatRatio(value: string | null): string {
  return value === null || value === undefined ? "N/A" : `${(Number(value) * 100).toFixed(1)}%`;
}

/** Formats a quantity string ("120.000") for display. */
export function formatKg(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 3 }) : value;
}
