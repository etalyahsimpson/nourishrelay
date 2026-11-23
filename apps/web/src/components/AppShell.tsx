"use client";

/** App shell: header with role-aware navigation, main content, sticky footer
 *  with the mandatory synthetic-data label. Semantic landmarks throughout. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession, useSignOut } from "@/lib/auth";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useSession();
  const signOut = useSignOut();
  const pathname = usePathname();

  const nav: { href: string; label: string; roles?: string[] }[] = [
    { href: "/dashboard", label: "Dashboard" },
    { href: "/donations", label: "Donations", roles: ["donor", "recipient", "coordinator", "admin", "analyst"] },
    { href: "/matching", label: "Matching", roles: ["coordinator", "admin"] },
    { href: "/reservations", label: "Reservations", roles: ["recipient", "donor", "coordinator", "admin", "analyst"] },
    { href: "/pickups", label: "Pickups", roles: ["transport", "recipient", "donor", "coordinator", "admin", "analyst"] },
    { href: "/reports", label: "Reports", roles: ["coordinator", "analyst", "admin", "donor", "recipient", "transport"] },
    { href: "/audit", label: "Audit", roles: ["coordinator", "admin"] },
    { href: "/about", label: "About" },
  ];
  const visible = nav.filter(
    (item) => !item.roles || (user && item.roles.includes(user.role)),
  );

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary-600 focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to main content
      </a>
      <header className="border-b border-line bg-surface-raised">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <Link
            href="/"
            className="flex items-center gap-2 text-lg font-bold tracking-tight text-primary-800"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-7 w-7 fill-primary-600">
              <path d="M12 2a2.5 2.5 0 0 0-2.5 2.5v7.7L6.8 9.5a2.3 2.3 0 0 0-3.3 3.2l6.9 7.2A5.2 5.2 0 0 0 13.6 22H18a4 4 0 0 0 4-4v-5.9a2.4 2.4 0 0 0-4.8 0v1.1l-2.7-2.9V4.5A2.5 2.5 0 0 0 12 2Z" />
            </svg>
            NourishRelay
          </Link>
          <nav aria-label="Primary" className="nr-noprint flex flex-wrap items-center gap-1 text-sm">
            {visible.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-1.5 font-medium transition-colors ${
                    active
                      ? "bg-primary-100 text-primary-800"
                      : "text-ink-muted hover:bg-primary-50 hover:text-primary-800"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto nr-noprint flex items-center gap-3 text-sm">
            {loading ? (
              <span className="text-ink-muted" aria-live="polite">
                Checking session…
              </span>
            ) : user ? (
              <>
                <span className="hidden text-ink-muted sm:inline" data-testid="session-user">
                  {user.display_name}
                  <span className="ml-2 rounded bg-primary-100 px-1.5 py-0.5 font-mono text-xs uppercase text-primary-800">
                    {user.role}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => void signOut()}
                  className="rounded-md border border-line px-3 py-1.5 font-medium text-ink hover:bg-primary-50"
                >
                  Sign out
                </button>
              </>
            ) : (
              <Link
                href="/login"
                className="rounded-md bg-primary-600 px-4 py-1.5 font-semibold text-white hover:bg-primary-700"
              >
                Sign in to demo
              </Link>
            )}
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
        {children}
      </main>
      <footer className="mt-auto border-t border-line bg-surface-raised">
        <div className="mx-auto w-full max-w-6xl px-4 py-4 text-xs leading-relaxed text-ink-muted">
          <p>
            Portfolio demonstration · Synthetic organizations and records · Not for real
            food-safety or dispatch decisions.
          </p>
          <p className="mt-1">
            NourishRelay v0.1.0 —{" "}
            <a
              className="underline hover:text-primary-700"
              href="https://github.com/etalyahsimpson/nourishrelay"
              rel="noopener noreferrer"
              target="_blank"
            >
              source code
            </a>{" "}
            · all quantities in kilograms (kg) · times shown in your local timezone
          </p>
        </div>
      </footer>
    </div>
  );
}
