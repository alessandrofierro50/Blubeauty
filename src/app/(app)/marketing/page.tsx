import type { Metadata } from "next";
import QRCode from "qrcode";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { nowMs, shortDate, time } from "@/lib/format";
import { SEGMENT_LABEL, segmentClients } from "@/lib/marketing";
import { appUrl, KIND_LABEL } from "@/lib/messaging";
import { WhatsAppIcon } from "@/components/whatsapp";
import { AutomationToggle } from "./automation-toggle";
import { CampaignForm } from "./campaign-form";
import type { CampaignSegment } from "@/generated/prisma/enums";

export const metadata: Metadata = { title: "Marketing" };

const STATUS: Record<string, string> = { QUEUED: "In coda", SENT: "Inviato", DELIVERED: "Consegnato", READ: "Letto", FAILED: "Errore" };

export default async function MarketingPage() {
  const user = await getCurrentUser();
  const org = await db.organization.findUniqueOrThrow({ where: { id: user.organizationId } });
  const since = new Date(nowMs() - 30 * 86_400_000);
  const where = { organizationId: org.id };

  const [automations, campaigns, messages, sent30, read30, online30, consent, clientsTotal] = await Promise.all([
    db.automation.findMany({ where, orderBy: { kind: "asc" } }),
    db.campaign.findMany({ where, orderBy: { createdAt: "desc" }, take: 5, include: { _count: { select: { messages: true } } } }),
    db.message.findMany({ where, orderBy: { createdAt: "desc" }, take: 8, include: { client: true } }),
    db.message.count({ where: { ...where, createdAt: { gte: since }, inbound: false } }),
    db.message.count({ where: { ...where, createdAt: { gte: since }, status: "READ" } }),
    db.appointment.count({ where: { ...where, createdAt: { gte: since }, channel: "ONLINE" } }),
    db.client.count({ where: { ...where, marketingConsentAt: { not: null } } }),
    db.client.count({ where }),
  ]);

  const segments = Object.keys(SEGMENT_LABEL) as CampaignSegment[];
  const counts = Object.fromEntries(
    await Promise.all(segments.map(async (s) => [s, (await segmentClients(org.id, s)).length] as const)),
  ) as Record<CampaignSegment, number>;

  const bookingUrl = appUrl(`/prenota/${org.slug}`);
  const qr = await QRCode.toString(bookingUrl, { type: "svg", margin: 1, color: { dark: "#0B2A5B", light: "#FFFFFF" } });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-brand-900">
            Marketing e WhatsApp <WhatsAppIcon className="h-6 w-6" />
          </h1>
          <p className="text-sm text-slate-500">Messaggi automatici, campagne e prenotazioni online da smartphone</p>
        </div>
      </header>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Messaggi WhatsApp (30 gg)" value={String(sent30)} />
        <Kpi label="Letti" value={sent30 ? `${Math.round((read30 / sent30) * 100)}%` : "—"} />
        <Kpi label="Prenotazioni online (30 gg)" value={String(online30)} />
        <Kpi label="Consenso marketing" value={`${consent} / ${clientsTotal}`} />
      </section>

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <section className="card space-y-3">
          <h2 className="font-semibold text-slate-800">Messaggi automatici</h2>
          <p className="text-sm text-slate-500">Partono da soli su WhatsApp: il salone non deve fare nulla.</p>
          <ul className="divide-y divide-slate-100">
            {automations.map((a) => (
              <li key={a.id} className="flex gap-4 py-3">
                <div className="flex-1">
                  <p className="font-medium text-slate-800">
                    {KIND_LABEL[a.kind]}
                    {a.offset != null && (
                      <span className="ml-2 text-xs font-normal text-slate-400">
                        {a.kind === "REMINDER"
                          ? `${a.offset} ore prima`
                          : a.kind === "BIRTHDAY"
                            ? "il giorno del compleanno"
                            : `dopo ${a.offset} giorni`}
                      </span>
                    )}
                  </p>
                  <p className="mt-0.5 line-clamp-2 text-sm text-slate-500">{a.template}</p>
                </div>
                <AutomationToggle id={a.id} enabled={a.enabled} />
              </li>
            ))}
          </ul>
        </section>

        <section className="card space-y-3">
          <h2 className="font-semibold text-slate-800">Prenotazioni da smartphone</h2>
          <p className="text-sm text-slate-500">
            I clienti prenotano e disdicono da soli, 24 ore su 24. Condividi il link su Instagram, Facebook, Google e WhatsApp, o
            stampa il QR code per la vetrina.
          </p>
          <div className="mx-auto w-44" dangerouslySetInnerHTML={{ __html: qr }} />
          <a href={`/prenota/${org.slug}`} target="_blank" className="block break-all rounded-lg bg-brand-50 p-2 text-center text-sm font-medium text-brand-700">
            {bookingUrl}
          </a>
        </section>
      </div>

      <CampaignForm segments={segments.map((s) => ({ id: s, label: SEGMENT_LABEL[s], count: counts[s] }))} salonName={org.name} bookingUrl={bookingUrl} />

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card">
          <h2 className="mb-3 font-semibold text-slate-800">Campagne inviate</h2>
          {campaigns.length === 0 && <p className="text-sm text-slate-500">Nessuna campagna.</p>}
          <ul className="divide-y divide-slate-100 text-sm">
            {campaigns.map((c) => (
              <li key={c.id} className="flex justify-between py-2">
                <span>
                  <span className="font-medium">{c.name}</span>
                  <span className="block text-slate-500">{SEGMENT_LABEL[c.segment]}</span>
                </span>
                <span className="text-right text-slate-500">
                  {c._count.messages} invii
                  <span className="block">{c.sentAt ? shortDate(c.sentAt) : "bozza"}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h2 className="mb-3 font-semibold text-slate-800">Ultimi messaggi</h2>
          <ul className="divide-y divide-slate-100 text-sm">
            {messages.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-2 py-2">
                <span className="flex-1 truncate">
                  <span className="font-medium">{m.client ? `${m.client.firstName} ${m.client.lastName}` : m.to}</span>
                  <span className="text-slate-500"> · {KIND_LABEL[m.kind]}</span>
                </span>
                <span className="whitespace-nowrap text-xs text-slate-400">
                  {shortDate(m.createdAt)} {time(m.createdAt)} · {STATUS[m.status]}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
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
