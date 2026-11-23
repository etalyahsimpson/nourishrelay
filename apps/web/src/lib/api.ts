/** Single typed API client: cookie session, CSRF double-submit header,
 *  Idempotency-Key on mutations, Zod validation for important contracts.
 *
 *  NEXT_PUBLIC_API_URL defaults to `/api/v1` (same-origin proxy mode; the
 *  web app forwards to the FastAPI backend server-side — see
 *  src/app/api/v1/[...path]/route.ts and docs/DEPLOYMENT_RUNBOOK.md).
 */

import {
  auditListSchema,
  donationDetailSchema,
  donationListSchema,
  matchListSchema,
  meResponseSchema,
  operationsReportSchema,
  organizationSummarySchema,
  pickupListSchema,
  recipientProfileSchema,
  reservationListSchema,
} from "./contracts";

export const API_BASE =
  (process.env.NEXT_PUBLIC_API_URL ?? "/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith("nourishrelay_csrf="));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

/** Key generator: stable across a retry of the SAME action, unique per action. */
export function idempotencyKey(scope: string): string {
  const existing = keys.get(scope);
  if (existing) return existing;
  const key =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${scope}-${Math.random().toString(36).slice(2)}`;
  keys.set(scope, key);
  return key;
}
const keys = new Map<string, string>();

export function resetIdempotencyKey(scope: string): void {
  keys.delete(scope);
}

type Json = Record<string, unknown>;

/** Default coordinator proposal lifetime: 12 hours from now. */
function defaultProposalExpiry(): string {
  return new Date(Date.now() + 12 * 3600_000).toISOString();
}

async function request<T>(
  method: "GET" | "POST" | "PATCH",
  path: string,
  options: { json?: Json; idempotencyScope?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: string | undefined;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  if (method !== "GET") {
    const csrf = readCsrfCookie();
    if (csrf) headers["X-CSRF-Token"] = csrf;
    headers["Idempotency-Key"] = idempotencyKey(
      options.idempotencyScope ?? `${method} ${path}`,
    );
  }
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body,
    credentials: "same-origin",
    cache: "no-store",
  });
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { raw: text };
    }
  }
  if (!response.ok) {
    const errorBody = (parsed as { error?: Record<string, unknown> } | null)?.error;
    throw new ApiError(
      response.status,
      typeof errorBody?.code === "string" ? errorBody.code : "HTTP_ERROR",
      typeof errorBody?.message === "string"
        ? errorBody.message
        : `Request failed with HTTP ${response.status}`,
      (errorBody?.details as Record<string, unknown>) ?? {},
    );
  }
  return parsed as T;
}

export const api = {
  async login(email: string, password: string) {
    return request<never>("POST", "/auth/login", { json: { email, password } });
  },
  async logout() {
    return request<never>("POST", "/auth/logout", {
      json: {},
      idempotencyScope: "logout",
    });
  },
  async me() {
    const body = await request<{ user: unknown }>("GET", "/auth/me");
    return meResponseSchema.parse(body);
  },
  async donations(query: Record<string, string> = {}) {
    const qs = new URLSearchParams(query).toString();
    const body = await request<unknown>("GET", `/donations${qs ? `?${qs}` : ""}`);
    return donationListSchema.parse(body);
  },
  async donation(id: string) {
    const body = await request<unknown>("GET", `/donations/${id}`);
    return donationDetailSchema.parse(body);
  },
  async matches(id: string) {
    const body = await request<unknown>("GET", `/donations/${id}/matches`);
    return matchListSchema.parse(body);
  },
  async createDonation(payload: Json) {
    return request<never>("POST", "/donations", {
      json: payload,
      idempotencyScope: "create-donation",
    });
  },
  async updateDonation(id: string, payload: Json) {
    return request<never>("PATCH", `/donations/${id}`, {
      json: payload,
      idempotencyScope: `update-donation-${id}`,
    });
  },
  async publishDonation(id: string) {
    return request<never>("POST", `/donations/${id}/publish`, {
      json: { attested: true },
      idempotencyScope: `publish-${id}`,
    });
  },
  async withdrawDonation(id: string, reason?: string) {
    return request<never>("POST", `/donations/${id}/withdraw`, {
      json: { reason: reason ?? null },
      idempotencyScope: `withdraw-${id}`,
    });
  },
  async reservations(query: Record<string, string> = {}) {
    const qs = new URLSearchParams(query).toString();
    const body = await request<unknown>("GET", `/reservations${qs ? `?${qs}` : ""}`);
    return reservationListSchema.parse(body);
  },
  async proposeReservation(payload: Json) {
    const body = { proposal_expires_at: defaultProposalExpiry(), ...payload };
    return request<never>("POST", "/reservations", {
      json: body,
      idempotencyScope: "propose-reservation",
    });
  },
  async acceptReservation(id: string) {
    return request<never>("POST", `/reservations/${id}/accept`, {
      json: { accepted: true },
      idempotencyScope: `accept-${id}`,
    });
  },
  async declineReservation(id: string, reason?: string) {
    return request<never>("POST", `/reservations/${id}/decline`, {
      json: { reason: reason ?? null },
      idempotencyScope: `decline-${id}`,
    });
  },
  async cancelReservation(id: string, reason?: string) {
    return request<never>("POST", `/reservations/${id}/cancel`, {
      json: { reason: reason ?? null },
      idempotencyScope: `cancel-${id}`,
    });
  },
  async pickups(query: Record<string, string> = {}) {
    const qs = new URLSearchParams(query).toString();
    const body = await request<unknown>("GET", `/pickups${qs ? `?${qs}` : ""}`);
    return pickupListSchema.parse(body);
  },
  async createPickup(payload: Json) {
    return request<never>("POST", "/pickups", {
      json: payload,
      idempotencyScope: "create-pickup",
    });
  },
  async pickupEvent(id: string, payload: Json) {
    return request<never>("POST", `/pickups/${id}/events`, {
      json: payload,
      idempotencyScope: `event-${id}-${(payload.event_type as string) ?? ""}`,
    });
  },
  async confirmReceipt(id: string, payload: Json) {
    return request<never>("POST", `/pickups/${id}/receipt`, {
      json: payload,
      idempotencyScope: `receipt-${id}`,
    });
  },
  async organizations() {
    const body = await request<unknown>("GET", "/organizations");
    return organizationSummarySchema.array().parse(
      ((body as { items?: unknown }).items ?? body) as unknown,
    );
  },
  async recipients() {
    const body = await request<unknown>("GET", "/recipients");
    return recipientProfileSchema.array().parse(
      ((body as { items?: unknown }).items ?? body) as unknown,
    );
  },
  async operationsReport(query: Record<string, string>) {
    const qs = new URLSearchParams(query).toString();
    const body = await request<unknown>("GET", `/reports/operations?${qs}`);
    return operationsReportSchema.parse(body);
  },
  operationsCsvUrl(query: Record<string, string>) {
    const qs = new URLSearchParams(query).toString();
    return `${API_BASE}/reports/operations.csv?${qs}`;
  },
  async audit(query: Record<string, string> = {}) {
    const qs = new URLSearchParams(query).toString();
    const body = await request<unknown>("GET", `/audit${qs ? `?${qs}` : ""}`);
    return auditListSchema.parse(body);
  },
};
