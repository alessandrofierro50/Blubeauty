import type { Metadata } from "next";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { isoDay } from "@/lib/format";
import { NewAppointmentForm } from "./form";

export const metadata: Metadata = { title: "Nuovo appuntamento" };

export default async function NuovoAppuntamentoPage({ searchParams }: PageProps<"/agenda/nuovo">) {
  const user = await getCurrentUser();
  const { data, cliente } = await searchParams;
  const org = { organizationId: user.organizationId };
  const [clients, services, staff] = await Promise.all([
    db.client.findMany({ where: org, orderBy: [{ lastName: "asc" }, { firstName: "asc" }] }),
    db.service.findMany({ where: { ...org, active: true }, include: { staff: true, category: true }, orderBy: { name: "asc" } }),
    db.staffMember.findMany({ where: { ...org, active: true }, orderBy: { firstName: "asc" } }),
  ]);
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-bold text-brand-900">Nuovo appuntamento</h1>
      <NewAppointmentForm
        defaultDay={typeof data === "string" ? data : isoDay(new Date())}
        defaultClientId={typeof cliente === "string" ? cliente : ""}
        clients={clients.map((c) => ({ id: c.id, label: `${c.lastName} ${c.firstName}`, phone: c.phone }))}
        services={services.map((s) => ({
          id: s.id,
          label: `${s.name} · ${s.durationMin} min · ${Number(s.price).toFixed(2)} €`,
          staffIds: s.staff.map((x) => x.staffId),
        }))}
        staff={staff.map((s) => ({ id: s.id, label: s.firstName, color: s.color }))}
      />
    </div>
  );
}
