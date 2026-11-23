/** Typed Zod contracts for every important API response (docs/API_CONTRACTS.md). */

import { z } from "zod";

export const isoTimestamp = z.string();

/** Quantities travel as exact 3-decimal strings ("120.000"). */
export const quantityKg = z.string().regex(/^\d+\.\d{3}$/);

export const uuidString = z.string().uuid();

export const roleSchema = z.enum([
  "donor",
  "recipient",
  "transport",
  "coordinator",
  "admin",
  "analyst",
]);

export const userSummarySchema = z.object({
  id: uuidString,
  role: roleSchema,
  organization_id: uuidString.nullable(),
  display_name: z.string(),
  email: z.string(),
});

export const errorBodySchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.string(), z.unknown()).optional().default({}),
  request_id: z.string(),
});

export const meResponseSchema = z.object({ user: userSummarySchema });

export const donationSummarySchema = z.object({
  id: uuidString,
  donor_org_id: uuidString,
  donor_org_name: z.string(),
  category: z.enum(["produce", "baked", "dairy", "canned", "prepared"]),
  quantity_kg: quantityKg,
  available_kg: quantityKg.nullable(),
  committed_kg: quantityKg.nullable(),
  handling_tags: z.array(z.string()),
  pickup_start: isoTimestamp,
  pickup_end: isoTimestamp,
  deadline: isoTimestamp,
  status: z.enum([
    "DRAFT",
    "AVAILABLE",
    "PARTIALLY_RESERVED",
    "FULLY_RESERVED",
    "CLOSED",
    "EXPIRED",
    "WITHDRAWN",
  ]),
  location_label: z.string(),
  notes: z.string().nullable(),
  version: z.number().int(),
  created_at: isoTimestamp,
  updated_at: isoTimestamp,
  published_at: isoTimestamp.nullable(),
});

export const donationListSchema = z.object({
  items: z.array(donationSummarySchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});

export const donationDetailSchema = donationSummarySchema.extend({
  revisions: z.array(
    z.object({
      version: z.number().int(),
      actor_id: uuidString,
      changed_at: isoTimestamp,
      before: z.record(z.string(), z.unknown()),
      after: z.record(z.string(), z.unknown()),
    }),
  ),
  reservations: z.array(
    z.object({
      id: uuidString,
      state: z.string(),
      quantity_kg: quantityKg,
      recipient_org_id: uuidString,
      created_at: isoTimestamp,
    }),
  ),
  allowed_actions: z.array(z.string()),
  available_transitions: z.array(z.string()),
  timeline: z.array(z.unknown()).optional(),
});

export const matchFactorSchema = z.object({
  factor: z.string(),
  raw: z.string().nullable(),
  normalized: z.number().nullable(),
  known: z.boolean(),
  weight: z.number(),
  contribution: z.number(),
});

export const matchCandidateSchema = z.object({
  recipient_id: uuidString,
  recipient_name: z.string(),
  max_feasible_kg: quantityKg,
  score: z.number(),
  score_breakdown: z.array(matchFactorSchema),
  reasons: z.array(z.string()),
  zero_history: z.boolean(),
});

export const matchListSchema = z.object({
  donation_id: uuidString,
  available_kg: quantityKg,
  weights: z.record(z.string(), z.number()),
  eligible: z.array(matchCandidateSchema),
  excluded: z.array(
    z.object({
      recipient_id: uuidString,
      recipient_name: z.string(),
      reasons: z.array(z.string()),
    }),
  ),
  generated_at: isoTimestamp,
  note: z.string(),
});

export const reservationSummarySchema = z.object({
  id: uuidString,
  donation_id: uuidString,
  donation_category: z.string(),
  donation_status: z.string(),
  donor_org_id: uuidString,
  donor_org_name: z.string(),
  recipient_org_id: uuidString,
  recipient_org_name: z.string(),
  proposed_by: uuidString,
  quantity_kg: quantityKg,
  state: z.enum([
    "PROPOSED",
    "ACCEPTED",
    "DECLINED",
    "CANCELLED",
    "EXPIRED",
    "PICKUP_ASSIGNED",
    "COLLECTED",
    "DELIVERED",
    "RECEIVED",
    "FAILED",
  ]),
  failure_stage: z.enum(["BEFORE_COLLECTION", "AFTER_COLLECTION"]).nullable(),
  proposal_expires_at: isoTimestamp.nullable(),
  accepted_at: isoTimestamp.nullable(),
  released_at: isoTimestamp.nullable(),
  decline_reason: z.string().nullable(),
  cancel_reason: z.string().nullable(),
  failure_reason: z.string().nullable(),
  created_at: isoTimestamp,
  updated_at: isoTimestamp,
  pickup_start: isoTimestamp,
  pickup_end: isoTimestamp,
  deadline: isoTimestamp,
  donation_available_kg: quantityKg.nullable(),
  allowed_actions: z.array(z.string()),
});

export const reservationListSchema = z.object({
  items: z.array(reservationSummarySchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});

export const receiptSummarySchema = z.object({
  id: uuidString,
  pickup_id: uuidString,
  recipient_user_id: uuidString,
  received_quantity_kg: quantityKg,
  exception_reason: z.string().nullable(),
  confirmed_at: isoTimestamp,
});

export const pickupSummarySchema = z.object({
  id: uuidString,
  reservation_id: uuidString,
  reservation_state: z.string(),
  assigned_transport_org_id: uuidString.nullable(),
  assigned_transport_org_name: z.string().nullable(),
  recipient_org_id: uuidString,
  recipient_org_name: z.string(),
  donor_org_name: z.string(),
  donation_category: z.string(),
  reserved_quantity_kg: quantityKg,
  pickup_window_start: isoTimestamp,
  pickup_window_end: isoTimestamp,
  status: z.enum(["SCHEDULED", "COLLECTED", "DELIVERED", "FAILED"]),
  collected_quantity_kg: quantityKg.nullable(),
  collected_at: isoTimestamp.nullable(),
  delivered_at: isoTimestamp.nullable(),
  receipt: receiptSummarySchema.nullable(),
  failure_reason: z.string().nullable(),
  created_at: isoTimestamp,
  updated_at: isoTimestamp,
  allowed_actions: z.array(z.string()),
});

export const pickupListSchema = z.object({
  items: z.array(pickupSummarySchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});

export const operationsReportSchema = z.object({
  window_from: isoTimestamp,
  window_to: isoTimestamp,
  scope_organization_id: uuidString.nullable(),
  scope_organization_name: z.string().nullable(),
  offered_kg: quantityKg,
  committed_kg: quantityKg,
  collected_kg: quantityKg,
  received_kg: quantityKg,
  offers: z.number().int(),
  reservations: z.number().int(),
  pickups: z.number().int(),
  failures: z.number().int(),
  cancellations: z.number().int(),
  median_pickup_lead_time_minutes: z.number().nullable(),
  ratios: z.array(
    z.object({
      label: z.string(),
      numerator: z.string(),
      denominator: z.string(),
      value: z.string().nullable(),
      unit: z.string(),
    }),
  ),
  cancellation_reasons: z.array(
    z.object({ kind: z.string(), count: z.number().int(), quantity_kg: z.string().nullable() }),
  ),
  failure_reasons: z.array(
    z.object({ kind: z.string(), count: z.number().int(), quantity_kg: z.string().nullable() }),
  ),
  categories: z.array(
    z.object({ category: z.string(), offers: z.number().int(), offered_kg: z.string() }),
  ),
  note: z.string(),
});

export const auditEntrySchema = z.object({
  id: uuidString,
  actor_id: uuidString.nullable(),
  actor_display_name: z.string().nullable(),
  actor_role: z.string().nullable(),
  organization_id: uuidString.nullable(),
  action: z.string(),
  resource_type: z.string(),
  resource_id: uuidString.nullable(),
  outcome: z.string(),
  safe_summary: z.record(z.string(), z.unknown()),
  created_at: isoTimestamp,
});

export const auditListSchema = z.object({
  items: z.array(auditEntrySchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
});

export const organizationSummarySchema = z.object({
  id: uuidString,
  name: z.string(),
  kind: z.enum(["donor", "recipient", "transport", "platform"]),
  verified: z.boolean(),
  service_area: z.string().nullable(),
  created_at: isoTimestamp,
});

export const recipientProfileSchema = z.object({
  organization_id: uuidString,
  name: z.string(),
  verified: z.boolean(),
  active: z.boolean(),
  accepted_categories: z.array(z.string()),
  handling_acknowledged: z.array(z.string()),
  receiving_start: z.string(),
  receiving_end: z.string(),
  timezone: z.string(),
  service_area: z.string().nullable(),
  capacity: z.object({
    date: z.string(),
    max_kg_per_day: z.string().nullable(),
    committed_kg: z.string(),
    remaining_kg: z.string().nullable(),
    capacity_status: z.enum(["OK", "EXHAUSTED", "UNKNOWN"]),
  }),
});

export type UserSummary = z.infer<typeof userSummarySchema>;
export type DonationSummary = z.infer<typeof donationSummarySchema>;
export type DonationDetail = z.infer<typeof donationDetailSchema>;
export type MatchList = z.infer<typeof matchListSchema>;
export type MatchCandidate = z.infer<typeof matchCandidateSchema>;
export type ReservationSummary = z.infer<typeof reservationSummarySchema>;
export type PickupSummary = z.infer<typeof pickupSummarySchema>;
export type OperationsReport = z.infer<typeof operationsReportSchema>;
export type AuditEntry = z.infer<typeof auditEntrySchema>;
export type RecipientProfile = z.infer<typeof recipientProfileSchema>;
export type OrganizationSummary = z.infer<typeof organizationSummarySchema>;
