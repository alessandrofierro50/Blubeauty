import type { Metadata } from "next";
import Link from "next/link";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { dayRange, euro, longDate, time } from "@/lib/format";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  const user = await getCurrentUser();
  const { start, end } = dayRange();
  const org = { organizationId: user.organizationId };

  const [appointments, clientsCount, lowStock] = await Promise.all([
    db.appointment.findMany({
      where: { ...org, startsAt: { gte: start, lt: end }, status: { notIn: ["CANCELLED"] } },
      include: { client: true, items: { include: { service: true, staff: true } } },
      orderBy: { startsAt: "asc" },
    }),
    db.client.count({ where: org }),
    db.product.count({ where: { ...org, active: true, minStock: { not: null } } }),
  ]);

  const expected = appointments.flatMap((a) => a.items).reduce((s, i) => s + Number(i.price), 0);
  const next = appointments.filter((a) => a.startsAt >= new Date()).slice(0, 6);

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm capitalize text-slate-500">{longDate(new Date())}</p>
        <h1 className="text-2xl font-bold text-brand-900">Ciao {user.name.split(" ")[0]} 👋</h1>
      </header>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Appuntamenti oggi" value={String(appointments.length)} />
        <Kpi label="Incasso previsto" value={euro(expected)} />
        <Kpi label="Clienti in archivio" value={String(clientsCount)} />
        <Kpi label="Prodotti monitorati" value={String(lowStock)} />
      </section>

      <section className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold text-slate-800">Prossimi appuntamenti</h2>
          <Link href="/agenda" className="text-sm font-medium text-brand-600 hover:underline">
            Apri agenda →
          </Link>
        </div>
        {next.length === 0 ? (
          <p className="text-sm text-slate-500">Nessun altro appuntamento per oggi.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {next.map((a) => (
              <li key={a.id} className="flex items-center justify-between py-2 text-sm">
                <span className="w-14 font-mono text-slate-500">{time(a.startsAt)}</span>
                <span className="flex-1 font-medium">
                  {a.client ? `${a.client.firstName} ${a.client.lastName}` : "Cliente occasionale"}
                </span>
                <span className="text-slate-500">
                  {a.items.map((i) => `${i.service.name}${i.staff ? ` · ${i.staff.firstName}` : ""}`).join(", ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-bold text-brand-900">{value}</p>
    </div>
  );
}
