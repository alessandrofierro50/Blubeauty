import type { Metadata } from "next";
import Link from "next/link";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { dayRange, euro, time } from "@/lib/format";

export const metadata: Metadata = { title: "Cassa" };

const METHOD: Record<string, string> = { CASH: "Contanti", CARD: "Carta", SATISPAY: "Satispay", BANK_TRANSFER: "Bonifico" };

export default async function CassaPage() {
  const user = await getCurrentUser();
  const { start, end } = dayRange();
  const org = { organizationId: user.organizationId };
  const [toCollect, sales] = await Promise.all([
    db.appointment.findMany({
      where: { ...org, startsAt: { gte: start, lt: end }, status: { notIn: ["PAID", "CANCELLED", "NO_SHOW"] } },
      include: { client: true, items: { include: { service: true } } },
      orderBy: { startsAt: "asc" },
    }),
    db.sale.findMany({
      where: { ...org, createdAt: { gte: start, lt: end }, status: "PAID" },
      include: { client: true, payments: true },
      orderBy: { createdAt: "desc" },
    }),
  ]);
  const totals = new Map<string, number>();
  for (const s of sales) for (const p of s.payments) totals.set(p.method, (totals.get(p.method) ?? 0) + Number(p.amount));
  const dayTotal = sales.reduce((s, x) => s + Number(x.total), 0);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-brand-900">Cassa</h1>
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="card">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Incasso di oggi</p>
          <p className="mt-1 text-2xl font-bold text-brand-900">{euro(dayTotal)}</p>
        </div>
        {[...totals.entries()].map(([m, v]) => (
          <div key={m} className="card">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{METHOD[m] ?? m}</p>
            <p className="mt-1 text-2xl font-bold text-slate-800">{euro(v)}</p>
          </div>
        ))}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card">
          <h2 className="mb-3 font-semibold text-slate-800">Da incassare oggi</h2>
          {toCollect.length === 0 && <p className="text-sm text-slate-500">Tutto incassato 🎉</p>}
          <ul className="divide-y divide-slate-100 text-sm">
            {toCollect.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 py-2">
                <span className="w-12 font-mono text-slate-500">{time(a.startsAt)}</span>
                <span className="flex-1">
                  <span className="font-medium">{a.client ? `${a.client.firstName} ${a.client.lastName}` : "Occasionale"}</span>
                  <span className="block text-slate-500">{a.items.map((i) => i.service.name).join(", ")}</span>
                </span>
                <Link href={`/cassa/${a.id}`} className="btn-primary px-3 py-1.5">
                  Incassa
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section className="card">
          <h2 className="mb-3 font-semibold text-slate-800">Documenti emessi oggi</h2>
          {sales.length === 0 && <p className="text-sm text-slate-500">Nessun documento.</p>}
          <ul className="divide-y divide-slate-100 text-sm">
            {sales.map((s) => (
              <li key={s.id}>
                <Link href={`/cassa/documento/${s.id}`} className="flex justify-between py-2 hover:text-brand-700">
                  <span>
                    {s.fiscalDocType === "INVOICE" ? "🧾 Fattura" : "🧾 Doc. commerciale"} {s.fiscalDocRef} ·{" "}
                    {s.client ? `${s.client.firstName} ${s.client.lastName}` : "—"}
                  </span>
                  <span className="font-semibold">{euro(s.total)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
