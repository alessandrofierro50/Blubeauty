import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { euro, isoDay, longDate, time } from "@/lib/format";
import { KIND_LABEL } from "@/lib/messaging";
import { WhatsAppPhone } from "@/components/whatsapp";
import { StatusActions } from "./status-actions";

export const metadata: Metadata = { title: "Appuntamento" };

const STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  BOOKED: { label: "Prenotato", cls: "bg-slate-100 text-slate-700" },
  CONFIRMED: { label: "Confermato", cls: "bg-brand-50 text-brand-700" },
  ARRIVED: { label: "In salone", cls: "bg-amber-50 text-amber-700" },
  COMPLETED: { label: "Concluso", cls: "bg-violet-50 text-violet-700" },
  PAID: { label: "Pagato", cls: "bg-emerald-50 text-emerald-700" },
  CANCELLED: { label: "Disdetto", cls: "bg-red-50 text-red-700" },
  NO_SHOW: { label: "Non presentato", cls: "bg-red-50 text-red-700" },
};

const CHANNEL: Record<string, string> = {
  STAFF: "Inserito dal salone",
  ONLINE: "Prenotazione online (smartphone)",
  PHONE: "Telefono",
  WHATSAPP: "WhatsApp",
  AI: "Receptionist AI",
};

export default async function AppointmentPage({ params }: PageProps<"/agenda/[id]">) {
  const user = await getCurrentUser();
  const { id } = await params;
  const a = await db.appointment.findFirst({
    where: { id, organizationId: user.organizationId },
    include: {
      client: true,
      items: { include: { service: true, staff: true, resource: true } },
      messages: { orderBy: { createdAt: "asc" } },
      sale: true,
    },
  });
  if (!a) notFound();
  const total = a.items.reduce((s, i) => s + Number(i.price), 0);
  const st = STATUS_LABEL[a.status];

  return (
    <div className="space-y-4">
      <Link href={`/agenda?data=${isoDay(a.startsAt)}`} className="text-sm text-brand-600 hover:underline">
        ← Agenda
      </Link>
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <section className="card space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm capitalize text-slate-500">{longDate(a.startsAt)}</p>
                <h1 className="text-3xl font-bold text-brand-900">
                  {time(a.startsAt)} – {time(a.endsAt)}
                </h1>
                <p className="mt-1 text-sm text-slate-500">{CHANNEL[a.channel]}</p>
              </div>
              <span data-testid="status" className={`rounded-full px-3 py-1 text-sm font-semibold ${st.cls}`}>
                {st.label}
              </span>
            </div>
            {a.client && (
              <Link href={`/clienti/${a.client.id}`} className="block rounded-xl bg-slate-50 p-3 hover:bg-slate-100">
                <p className="font-semibold">
                  {a.client.firstName} {a.client.lastName}
                </p>
                <p className="text-sm text-slate-500">{a.client.phone}</p>
              </Link>
            )}
            <ul className="divide-y divide-slate-100 text-sm">
              {a.items.map((i) => (
                <li key={i.id} className="flex justify-between py-2">
                  <span>
                    <span className="font-medium">{i.service.name}</span>
                    <span className="text-slate-500">
                      {i.staff ? ` · ${i.staff.firstName}` : ""}
                      {i.resource ? ` · ${i.resource.name}` : ""}
                    </span>
                  </span>
                  <span className="font-semibold">{euro(i.price)}</span>
                </li>
              ))}
              <li className="flex justify-between py-2 text-base font-bold">
                <span>Totale</span>
                <span>{euro(total)}</span>
              </li>
            </ul>
            {a.notes && <p className="text-sm text-slate-600">📝 {a.notes}</p>}
          </section>

          <StatusActions id={a.id} status={a.status} saleId={a.sale?.id ?? null} />
        </div>

        <aside className="space-y-2">
          <p className="text-sm font-semibold text-slate-700">Messaggi WhatsApp al cliente</p>
          <WhatsAppPhone
            title={user.organizationName}
            messages={a.messages.map((m) => ({
              id: m.id,
              body: m.body,
              at: time(m.createdAt),
              status: m.status,
              inbound: m.inbound,
            }))}
          />
          <p className="text-center text-xs text-slate-400">
            {a.messages.map((m) => KIND_LABEL[m.kind]).join(" · ") || "Nessun messaggio"}
          </p>
        </aside>
      </div>
    </div>
  );
}
