"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { DonationForm } from "@/components/DonationForm";
import { RoleGuard } from "@/components/RoleGuard";

export default function NewDonationPage() {
  const router = useRouter();
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <header>
        <Link href="/donations" className="text-sm text-primary-700 hover:underline">← Donations</Link>
        <h1 className="mt-2 text-2xl font-bold text-ink">New donation</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Creates a DRAFT offer for your donor organization. Publish it from the donation
          detail view after completing your donor-side handling review.
        </p>
      </header>
      <RoleGuard allow={["donor"]} title="Donor-only form">
        <section className="rounded-lg border border-line bg-surface-raised p-6">
          <DonationForm
            onCreated={(result) => {
              if (result.status === "created" && result.id) {
                router.push(`/donations/${result.id}`);
              }
            }}
          />
        </section>
      </RoleGuard>
    </div>
  );
}
