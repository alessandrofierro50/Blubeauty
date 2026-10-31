import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { euro, shortDate, time } from "@/lib/format";

export const metadata: Metadata = { title: "Scheda cliente" };

const cardType: Record<string, string> = {
  COLOR: "Formula colore",
  TREATMENT: "Trattamento",
  ANAMNESIS: "Anamnesi",
  CONSENT: "Consenso informato",
};

export default async function ClientePage({ params }: PageProps<"/clienti/[id]">) {
  const user = await getCurrentUser();
  const { id } = await params;

  const client = await db.client.findFirst({
    where: { id, organizationId: user.organizationId },
    include: {
      technicalCards: { orderBy: { createdAt: "desc" } },
      packages: { include: { packageTemplate: true } },
      appointments: {
        orderBy: { startsAt: "desc" },
        take: 20,
        include: { items: { include: { service: true, staff: true } } },
      },
    },
  });
  if (!client) notFound();

  return (
    <div className="space-y-6">
      <Link href="/clienti" className="text-sm text-brand-600 hover:underline">
        ← Clienti
      </Link>
      <header className="card flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-brand-900">
            {client.firstName} {client.lastName}
          </h1>
          <p className="text-sm text-slate-500">
            {[client.phone, client.email].filter(Boolean).join(" · ") || "Nessun contatto"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge ok={!!client.privacyConsentAt}>Privacy</Badge>
          <Badge ok={!!client.marketingConsentAt}>Marketing</Badge>
          <span className="rounded-full bg-brand-50 px-3 py-1 font-semibold text-brand-700">
            {client.loyaltyPoints} punti fidelity
          </span>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card space-y-3">
          <h2 className="font-semibold text-slate-800">Schede tecniche</h2>
          {client.technicalCards.length === 0 && <p className="text-sm text-slate-500">Nessuna scheda.</p>}
          {client.technicalCards.map((t) => (
            <div key={t.id} className="rounded-xl bg-slate-50 p-3 text-sm">
              <p className="font-medium">
                {cardType[t.type]} — {t.title}
              </p>
              <dl className="mt-1 grid grid-cols-2 gap-x-4 text-slate-600">
                {Object.entries(t.data as Record<string, unknown>).map(([k, v]) => (
                  <div key={k} className="flex gap-1">
                    <dt className="text-slate-400">{k}:</dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </section>

        <section className="card space-y-3">
          <h2 className="font-semibold text-slate-800">Pacchetti</h2>
          {client.packages.length === 0 && <p className="text-sm text-slate-500">Nessun pacchetto attivo.</p>}
          {client.packages.map((p) => {
            const left = p.sessionsTotal - p.sessionsUsed;
            return (
              <div key={p.id} className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="font-medium">{p.packageTemplate.name}</span>
                  <span className="text-slate-500">
                    {left} di {p.sessionsTotal} sedute rimaste
                  </span>
                </div>
                <div className="h-2 rounded-full bg-slate-100">
                  <div
                    className="h-2 rounded-full bg-brand-500"
                    style={{ width: `${(p.sessionsUsed / p.sessionsTotal) * 100}%` }}
                  />
                </div>
              </div>
            );
          })}
        </section>
      </div>

      <section className="card">
        <h2 className="mb-3 font-semibold text-slate-800">Storico appuntamenti</h2>
        <ul className="divide-y divide-slate-100 text-sm">
          {client.appointments.map((a) => (
            <li key={a.id} className="flex flex-wrap justify-between gap-2 py-2">
              <span className="text-slate-500">
                {shortDate(a.startsAt)} {time(a.startsAt)}
              </span>
              <span className="flex-1 px-4">
                {a.items.map((i) => `${i.service.name}${i.staff ? ` (${i.staff.firstName})` : ""}`).join(", ")}
              </span>
              <span className="font-medium">{euro(a.items.reduce((s, i) => s + Number(i.price), 0))}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Badge({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span className={`rounded-full px-3 py-1 font-semibold ${ok ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
      {ok ? "✓" : "!"} {children}
    </span>
  );
}
