"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, resetIdempotencyKey } from "@/lib/api";
import { sessionKey } from "@/lib/auth";
import type { UserSummary } from "@/lib/contracts";

const DEMO_ACCOUNTS: { label: string; email: string; description: string }[] = [
  { label: "Donor — Metro Grocery Exchange", email: "donor@metro.demo.nourishrelay.example", description: "Create, publish and withdraw offers" },
  { label: "Donor — Harvest Lane Market", email: "donor@harvestlane.demo.nourishrelay.example", description: "Second donor organization" },
  { label: "Recipient — Northside Community Kitchen", email: "recipient@northside.demo.nourishrelay.example", description: "Accept/decline proposals, confirm receipts" },
  { label: "Recipient — Riverside Shelter", email: "recipient@riverside.demo.nourishrelay.example", description: "80kg/day profile in District B" },
  { label: "Recipient — Eastview Pantry", email: "recipient@eastview.demo.nourishrelay.example", description: "Ambient-only handling (exclusion demos)" },
  { label: "Recipient — Hillside Community Center", email: "recipient@hillside.demo.nourishrelay.example", description: "Baked/canned, 30kg/day" },
  { label: "Transport — Swift Collective", email: "transport@swiftcollective.demo.nourishrelay.example", description: "Pickup queue, collect/deliver/fail" },
  { label: "Coordinator — Relay Network", email: "coordinator@relay.demo.nourishrelay.example", description: "Matching, proposals, cancellations, audit" },
  { label: "Analyst — Relay Network (read-only)", email: "analyst@relay.demo.nourishrelay.example", description: "Reports only" },
  { label: "Admin — Relay Network", email: "admin@relay.demo.nourishrelay.example", description: "Full platform administration" },
];

const DEMO_PASSWORD = "demo-password";

export default function LoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(targetEmail: string, targetPassword: string) {
    setBusy(true);
    setError(null);
    try {
      await api.login(targetEmail, targetPassword);
      const me = await api.me();
      queryClient.setQueryData(sessionKey, me.user satisfies UserSummary);
      queryClient.invalidateQueries();
      router.push("/dashboard");
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "ERROR";
      const message =
        err instanceof ApiError ? err.message : "Sign-in failed. Is the API running?";
      setError(`${code}: ${message}`);
      resetIdempotencyKey("logout");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-ink">Sign in to the demo</h1>
        <p className="mt-2 text-sm text-ink-muted">
          All accounts are synthetic demonstration fixtures with the public demo
          password from the repository README. No real credentials are involved.
        </p>
      </header>

      <section aria-labelledby="manual-heading" className="rounded-lg border border-line bg-surface-raised p-6">
        <h2 id="manual-heading" className="font-semibold text-ink">
          Email and password
        </h2>
        <form
          className="mt-4 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void signIn(email, password);
          }}
        >
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-ink">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              className="mt-1 w-full rounded-md border border-line bg-white px-3 py-2 text-sm shadow-sm focus:border-primary-500"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-ink">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              className="mt-1 w-full rounded-md border border-line bg-white px-3 py-2 text-sm shadow-sm focus:border-primary-500"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error ? (
            <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
              {error}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-primary-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-60"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>

      <section aria-labelledby="roles-heading" className="rounded-lg border border-line bg-surface-raised p-6">
        <h2 id="roles-heading" className="font-semibold text-ink">
          Or pick a demo role
        </h2>
        <p className="mt-1 text-xs text-ink-muted">
          One click signs you in with the synthetic fixture account (public demo
          password).
        </p>
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {DEMO_ACCOUNTS.map((account) => (
            <li key={account.email}>
              <button
                type="button"
                disabled={busy}
                onClick={() => void signIn(account.email, DEMO_PASSWORD)}
                className="w-full rounded-md border border-line px-3 py-2.5 text-left text-sm hover:border-primary-400 hover:bg-primary-50 disabled:opacity-50"
              >
                <span className="font-medium text-ink">{account.label}</span>
                <span className="mt-0.5 block text-xs text-ink-muted">{account.description}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
