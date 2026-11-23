"use client";

/** Role guard: gates page content by session role with a helpful fallback. */

import Link from "next/link";
import { useSession } from "@/lib/auth";

export function RoleGuard({
  allow,
  children,
  title = "Restricted view",
}: {
  allow: string[];
  children: React.ReactNode;
  title?: string;
}) {
  const { user, loading } = useSession();
  if (loading) {
    return (
      <p className="text-ink-muted" aria-live="polite">
        Loading…
      </p>
    );
  }
  if (!user) {
    return (
      <div className="rounded-lg border border-line bg-surface-raised p-6">
        <h2 className="text-lg font-semibold text-ink">Sign in required</h2>
        <p className="mt-2 text-sm text-ink-muted">
          {title} is available to signed-in demo accounts.
        </p>
        <Link
          href="/login"
          className="mt-4 inline-block rounded-md bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700"
        >
          Sign in to demo
        </Link>
      </div>
    );
  }
  if (!allow.includes(user.role)) {
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-6">
        <h2 className="text-lg font-semibold text-amber-900">{title}</h2>
        <p className="mt-2 text-sm text-amber-800">
          Your role ({user.role}) does not have access to this view. Allowed roles:{" "}
          {allow.join(", ")}.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
