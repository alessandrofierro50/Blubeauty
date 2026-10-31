import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { LogoMark } from "@/components/logo";
import { db } from "@/lib/db";
import { euro, longDate, nowMs, time } from "@/lib/format";
import { CancelButton } from "./cancel-button";

export const metadata: Metadata = { title: "Il tuo appuntamento", robots: { index: false } };

export default function AppuntamentoPage({ params }: PageProps<"/prenota/[slug]/a/[token]">) {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-slate-100" />}>
      <Appuntamento params={params} />
    </Suspense>
  );
}

async function Appuntamento({ params }: { params: PageProps<"/prenota/[slug]/a/[token]">["params"] }) {
  const { slug, token } = await params;
  const a = await db.appointment.findUnique({
    where: { publicToken: token },
    include: {
      organization: true,
      client: true,
      location: true,
      items: { include: { service: true, staff: true } },
    },
  });
  if (!a || a.organization.slug !== slug) notFound();

  const cancelled = a.status === "CANCELLED";
  const past = +a.startsAt < nowMs();
  const canCancel = !cancelled && !past && nowMs() < +a.startsAt - a.organization.cancelHoursBefore * 3_600_000;

  return (
    <div className="min-h-dvh bg-slate-100 sm:py-6">
      <div className="mx-auto flex min-h-dvh max-w-[430px] flex-col bg-white shadow-xl sm:min-h-[calc(100dvh-3rem)] sm:overflow-hidden sm:rounded-[2rem]">
        <header className="bg-gradient-to-br from-brand-500 to-brand-900 px-5 pb-6 pt-5 text-white">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/95 px-2.5 py-1 text-xs font-semibold text-brand-900">
            <LogoMark className="h-4 w-4" /> BluBeauty
          </span>
          <h1 className="mt-4 text-2xl font-bold">{a.organization.name}</h1>
          <p className="text-sm text-white/80">Ciao {a.client?.firstName}, ecco il tuo appuntamento</p>
        </header>
        <main className="flex-1 space-y-4 px-5 py-5">
          <div className={`rounded-2xl p-5 ${cancelled ? "bg-slate-100 text-slate-500" : "bg-brand-50"}`}>
            <p className={`text-xs font-semibold uppercase tracking-wide ${cancelled ? "text-red-600" : "text-brand-600"}`}>
              {cancelled ? "Disdetto" : past ? "Concluso" : "Confermato"}
            </p>
            <p className="mt-1 text-xl font-bold capitalize text-slate-900">{longDate(a.startsAt)}</p>
            <p className="text-3xl font-bold text-brand-700">{time(a.startsAt)}</p>
            <ul className="mt-3 space-y-1 text-sm">
              {a.items.map((i) => (
                <li key={i.id} className="flex justify-between">
                  <span>
                    {i.service.name}
                    {i.staff ? ` · con ${i.staff.firstName}` : ""}
                  </span>
                  <span className="font-semibold">{euro(i.price)}</span>
                </li>
              ))}
            </ul>
            {a.location.address && (
              <p className="mt-3 text-sm text-slate-500">
                📍 {a.location.address}, {a.location.city}
              </p>
            )}
          </div>

          {canCancel && <CancelButton token={token} />}
          {!cancelled && !past && !canCancel && (
            <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
              Mancano meno di {a.organization.cancelHoursBefore} ore: per disdire chiama il salone
              {a.organization.phone ? ` al ${a.organization.phone}` : ""}.
            </p>
          )}
          <Link
            href={`/prenota/${slug}`}
            className="block w-full rounded-2xl bg-brand-600 py-4 text-center font-semibold text-white shadow-lg shadow-brand-600/30"
          >
            {cancelled ? "Prenota un nuovo appuntamento" : "Prenota un altro servizio"}
          </Link>
        </main>
      </div>
    </div>
  );
}
