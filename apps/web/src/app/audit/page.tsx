"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RoleGuard } from "@/components/RoleGuard";
import { formatDateTime } from "@/lib/dates";

const RESOURCE_TYPES = ["", "donation", "reservation", "pickup", "receipt", "database"];

export default function AuditPage() {
  const [resourceType, setResourceType] = useState("");
  const query: Record<string, string> = { limit: "50" };
  if (resourceType) query.resource_type = resourceType;

  const audit = useQuery({
    queryKey: ["audit", resourceType],
    queryFn: () => api.audit(query),
  });

  return (
    <RoleGuard allow={["coordinator", "admin"]} title="Audit trail">
      <div className="space-y-6">
        <header>
          <h1 className="text-2xl font-bold text-ink">Audit trail</h1>
          <p className="mt-1 max-w-3xl text-sm text-ink-muted">
            Append-only operational history written inside the same transaction as every
            state change. Safe summaries only — no credentials, no personal data, no
            cross-tenant payloads.
          </p>
        </header>

        <form className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface-raised p-4" onSubmit={(e) => e.preventDefault()}>
          <div>
            <label htmlFor="resource-filter" className="block text-xs font-medium text-ink-muted">Resource type</label>
            <select
              id="resource-filter"
              className="mt-1 rounded-md border border-line bg-white px-2 py-1.5 text-sm"
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
            >
              {RESOURCE_TYPES.map((t) => <option key={t} value={t}>{t || "All resources"}</option>)}
            </select>
          </div>
          <p className="text-xs text-ink-muted">{audit.data?.total ?? 0} entries</p>
        </form>

        {audit.isLoading ? (
          <p className="text-sm text-ink-muted" aria-live="polite">Loading audit trail…</p>
        ) : audit.isError ? (
          <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
            {(audit.error as Error).message}
          </p>
        ) : (
          <ol className="space-y-2">
            {(audit.data?.items ?? []).map((entry) => (
              <li key={entry.id} className="rounded-lg border border-line bg-surface-raised p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-stone-100 px-2 py-0.5 font-mono text-xs text-stone-700">
                    {entry.action}
                  </span>
                  <span className="text-ink-muted">
                    {entry.actor_display_name ?? "system worker"}
                    {entry.actor_role ? ` (${entry.actor_role})` : ""}
                  </span>
                  <span className="text-xs text-ink-muted">{entry.outcome}</span>
                  <span className="ml-auto text-xs text-ink-muted">{formatDateTime(entry.created_at)}</span>
                </div>
                <p className="mt-1 text-xs text-ink-muted">
                  resource: {entry.resource_type}
                  {entry.resource_id ? ` (${entry.resource_id.slice(0, 8)}…)` : ""}
                  {entry.safe_summary && Object.keys(entry.safe_summary).length
                    ? ` · ${JSON.stringify(entry.safe_summary)}`
                    : ""}
                </p>
              </li>
            ))}
            {(audit.data?.items ?? []).length === 0 ? (
              <li className="rounded-lg border border-line bg-surface-raised p-6 text-center text-sm text-ink-muted">
                No audit entries in this view.
              </li>
            ) : null}
          </ol>
        )}
      </div>
    </RoleGuard>
  );
}
