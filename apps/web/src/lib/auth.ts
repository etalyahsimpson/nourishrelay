"use client";

/** Session context: server-derived identity via /auth/me, client caching. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { UserSummary } from "./contracts";

export const sessionKey = ["session"] as const;

export function useSession() {
  const query = useQuery({
    queryKey: sessionKey,
    queryFn: () => api.me().then((r) => r.user),
    retry: false,
    staleTime: 60_000,
  });
  return {
    user: query.data ?? null,
    loading: query.isLoading,
    error: query.error ?? null,
  };
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return async function signOut() {
    try {
      await api.logout();
    } catch {
      // cookie is cleared server-side or already gone; proceed locally
    }
    queryClient.resetQueries();
    queryClient.setQueryData(sessionKey, null);
  };
}

export function useRole(): string | null {
  const { user } = useSession();
  return user?.role ?? null;
}

export function isPlatform(user: UserSummary | null): boolean {
  return !!user && ["coordinator", "admin", "analyst"].includes(user.role);
}

export function canPropose(user: UserSummary | null): boolean {
  return !!user && ["coordinator", "admin"].includes(user.role);
}
