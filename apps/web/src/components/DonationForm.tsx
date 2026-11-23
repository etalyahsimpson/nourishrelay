"use client";

/** Validated donor donation form (React Hook Form + Zod).
 *  Quantities are kg-only (documented); windows are validated client-side
 *  and re-validated server-side. */

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState } from "react";
import { ApiError, api, resetIdempotencyKey } from "@/lib/api";
import { localInputToUtc, nextHourLocal } from "@/lib/dates";

const CATEGORIES = ["produce", "baked", "dairy", "canned", "prepared"] as const;
const HANDLING_TAGS = ["ambient", "requires_cold", "contains_allergens"] as const;

const formSchema = z
  .object({
    category: z.enum(CATEGORIES),
    quantity_kg: z
      .string()
      .min(1, "Quantity is required")
      .refine((v) => /^\d+(\.\d{1,3})?$/.test(v.trim()), "Up to 3 decimal digits")
      .refine((v) => Number(v) > 0, "Must be greater than zero")
      .refine((v) => Number(v) <= 999999999.999, "Too large"),
    handling_tags: z.array(z.enum(HANDLING_TAGS)).max(3, "At most 3 tags"),
    pickup_start: z.string().min(1, "Pickup start is required"),
    pickup_end: z.string().min(1, "Pickup end is required"),
    deadline: z.string().min(1, "Deadline is required"),
    location_label: z.string().min(1, "Location label is required").max(200),
    notes: z.string().max(2000).optional().or(z.literal("")),
  })
  .refine(
    (v) => new Date(v.pickup_start).getTime() < new Date(v.pickup_end).getTime(),
    { path: ["pickup_end"], message: "Pickup end must be after pickup start" },
  )
  .refine((v) => new Date(v.pickup_start).getTime() < new Date(v.deadline).getTime(), {
    path: ["deadline"],
    message: "Deadline must be after pickup start",
  })
  .refine((v) => new Date(v.deadline).getTime() <= new Date(v.pickup_end).getTime(), {
    path: ["deadline"],
    message: "Deadline cannot be after pickup end",
  });

type FormValues = z.infer<typeof formSchema>;

export type DonationFormResult =
  | { status: "created"; id: string }
  | { status: "error"; code: string; message: string };

export function DonationForm({
  onCreated,
}: {
  onCreated?: (result: DonationFormResult) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      category: "produce",
      quantity_kg: "25.000",
      handling_tags: ["ambient"],
      pickup_start: nextHourLocal(),
      pickup_end: (() => {
        const d = new Date(nextHourLocal());
        d.setHours(d.getHours() + 2);
        return d.toISOString().slice(0, 16);
      })(),
      deadline: "",
      location_label: "",
      notes: "",
    },
  });

  async function submit(values: FormValues) {
    setSubmitting(true);
    setServerError(null);
    try {
      const payload = {
        category: values.category,
        quantity_kg: values.quantity_kg.trim(),
        handling_tags: values.handling_tags,
        pickup_start: localInputToUtc(values.pickup_start),
        pickup_end: localInputToUtc(values.pickup_end),
        deadline: localInputToUtc(values.deadline),
        location_label: values.location_label,
        notes: values.notes || null,
      };
      const response = await api.createDonation(payload as Record<string, unknown>);
      const id = (response as unknown as { id?: string })?.id ?? "";
      onCreated?.({ status: "created", id });
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Unexpected error creating the donation.";
      const code = err instanceof ApiError ? err.code : "UNKNOWN";
      setServerError(`${code}: ${message}`);
      onCreated?.({ status: "error", code, message });
      resetIdempotencyKey("create-donation");
    } finally {
      setSubmitting(false);
    }
  }

  const field = (name: keyof FormValues, label: string, input: React.ReactNode, hint?: string) => (
    <div>
      <label htmlFor={name} className="block text-sm font-medium text-ink">
        {label}
      </label>
      <div className="mt-1">{input}</div>
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
      {errors[name] ? (
        <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
          {String(errors[name]?.message)}
        </p>
      ) : null}
    </div>
  );

  const inputClass =
    "w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink shadow-sm focus:border-primary-500";

  return (
    <form noValidate onSubmit={handleSubmit(submit)} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {field(
          "category",
          "Category",
          <select id="category" className={inputClass} {...register("category")}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>,
        )}
        {field(
          "quantity_kg",
          "Quantity (kg)",
          <input
            id="quantity_kg"
            inputMode="decimal"
            className={inputClass}
            placeholder="120.000"
            {...register("quantity_kg")}
          />,
          "Kilograms with up to 3 decimals — the only unit supported in this MVP.",
        )}
      </div>
      <fieldset>
        <legend className="text-sm font-medium text-ink">Handling tags</legend>
        <div className="mt-1 flex flex-wrap gap-4">
          {HANDLING_TAGS.map((tag) => (
            <label key={tag} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                value={tag}
                className="h-4 w-4 accent-primary-600"
                {...register("handling_tags")}
              />
              {tag}
            </label>
          ))}
        </div>
        {errors.handling_tags ? (
          <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
            {String(errors.handling_tags?.message)}
          </p>
        ) : null}
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-3">
        {field(
          "pickup_start",
          "Pickup window start",
          <input type="datetime-local" id="pickup_start" className={inputClass} {...register("pickup_start")} />,
        )}
        {field(
          "pickup_end",
          "Pickup window end",
          <input type="datetime-local" id="pickup_end" className={inputClass} {...register("pickup_end")} />,
        )}
        {field(
          "deadline",
          "Reservation deadline",
          <input type="datetime-local" id="deadline" className={inputClass} {...register("deadline")} />,
          "Last moment a recipient can accept. Must be inside the pickup window.",
        )}
      </div>
      {field(
        "location_label",
        "Location label (synthetic)",
        <input id="location_label" className={inputClass} placeholder="Demo District A — loading dock" {...register("location_label")} />,
      )}
      {field(
        "notes",
        "Notes",
        <textarea id="notes" rows={3} className={inputClass} {...register("notes")} />,
      )}
      {serverError ? (
        <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {serverError}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-primary-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-primary-700 disabled:opacity-60"
      >
        {submitting ? "Creating…" : "Create draft donation"}
      </button>
      <p className="text-xs text-ink-muted">
        Draft donations stay private until you attest handling review and publish them.
      </p>
    </form>
  );
}
