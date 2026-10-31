import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { db } from "@/lib/db";
import { BookingApp } from "./booking-app";

export const metadata: Metadata = { title: "Prenota online" };

export default function PrenotaPage({ params }: PageProps<"/prenota/[slug]">) {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-brand-900" />}>
      <Booking params={params} />
    </Suspense>
  );
}

async function Booking({ params }: { params: PageProps<"/prenota/[slug]">["params"] }) {
  const { slug } = await params;
  const org = await db.organization.findUnique({
    where: { slug },
    include: {
      locations: { take: 1 },
      services: {
        where: { active: true, bookableOnline: true },
        include: { category: true, staff: true },
        orderBy: [{ category: { sortOrder: "asc" } }, { name: "asc" }],
      },
      staff: { where: { active: true }, orderBy: { firstName: "asc" } },
    },
  });
  if (!org) notFound();

  return (
    <BookingApp
      org={{
        name: org.name,
        slug: org.slug,
        phone: org.phone,
        address: [org.locations[0]?.address, org.locations[0]?.city].filter(Boolean).join(", "),
        cancelHoursBefore: org.cancelHoursBefore,
      }}
      services={org.services.map((s) => ({
        id: s.id,
        name: s.name,
        description: s.description,
        category: s.category?.name ?? "Altro",
        price: Number(s.price),
        durationMin: s.durationMin,
        staffIds: s.staff.map((x) => x.staffId),
      }))}
      staff={org.staff.map((s) => ({ id: s.id, firstName: s.firstName, color: s.color }))}
    />
  );
}
