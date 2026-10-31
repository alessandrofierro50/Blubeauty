"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";
import { LogoMark } from "@/components/logo";
import { WhatsAppIcon } from "@/components/whatsapp";
import { createBooking, fetchSlots } from "./actions";

type Org = { name: string; slug: string; phone: string | null; address: string; cancelHoursBefore: number };
type Service = {
  id: string;
  name: string;
  description: string | null;
  category: string;
  price: number;
  durationMin: number;
  staffIds: string[];
};
type Staff = { id: string; firstName: string; color: string };

type Step = "service" | "staff" | "time" | "details" | "done";

const euro = (n: number) => new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(n);
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const STORAGE_KEY = "bb_cliente";

export function BookingApp({ org, services, staff }: { org: Org; services: Service[]; staff: Staff[] }) {
  const [step, setStep] = useState<Step>("service");
  const [service, setService] = useState<Service | null>(null);
  const [staffId, setStaffId] = useState<string | null>(null); // null = indifferente
  const [day, setDay] = useState(() => iso(new Date()));
  const [result, setResult] = useState<{ key: string; slots: string[] } | null>(null);
  const [time, setTime] = useState<string | null>(null);
  const [form, setForm] = useState({ firstName: "", lastName: "", phone: "", privacy: false, marketing: false });
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // Ricorda i dati del cliente su questo telefono per le prossime prenotazioni
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      // Lettura una tantum di localStorage dopo l'idratazione (non disponibile sul server)
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (saved) setForm((f) => ({ ...f, ...JSON.parse(saved), privacy: false }));
    } catch {}
  }, []);

  const days = useMemo(() => {
    const out: Date[] = [];
    const d = new Date();
    for (let i = 0; i < 21; i++) {
      out.push(new Date(d.getFullYear(), d.getMonth(), d.getDate() + i));
    }
    return out;
  }, []);

  const slotKey = `${service?.id}|${staffId}|${day}`;
  const slots = result?.key === slotKey ? result.slots : null;
  useEffect(() => {
    if (step !== "time" || !service) return;
    let active = true;
    fetchSlots({ slug: org.slug, serviceId: service.id, staffId, day }).then(
      (s) => active && setResult({ key: `${service.id}|${staffId}|${day}`, slots: s }),
    );
    return () => {
      active = false;
    };
  }, [step, service, staffId, day, org.slug]);

  const categories = useMemo(() => {
    const map = new Map<string, Service[]>();
    for (const s of services) map.set(s.category, [...(map.get(s.category) ?? []), s]);
    return [...map.entries()];
  }, [services]);

  const chosenStaff = staff.find((s) => s.id === staffId);
  const dayLabel = new Date(`${day}T12:00:00`).toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long" });

  function confirm() {
    if (!service || !time) return;
    setError(null);
    startTransition(async () => {
      const res = await createBooking({ slug: org.slug, serviceId: service.id, staffId, day, time, ...form });
      if (!res.ok) {
        setError(res.error);
        return;
      }
      try {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ firstName: form.firstName, lastName: form.lastName, phone: form.phone }),
        );
      } catch {}
      setToken(res.token);
      setStep("done");
    });
  }

  const back = () =>
    setStep((s) => (s === "staff" ? "service" : s === "time" ? "staff" : s === "details" ? "time" : s));

  return (
    <div className="min-h-dvh bg-slate-100 sm:py-6">
      <div className="mx-auto flex min-h-dvh max-w-[430px] flex-col bg-white shadow-xl sm:min-h-[calc(100dvh-3rem)] sm:rounded-[2rem] sm:overflow-hidden">
        {/* Header app */}
        <header className="relative bg-gradient-to-br from-brand-500 to-brand-900 px-5 pb-6 pt-5 text-white">
          <div className="flex items-center justify-between">
            {step !== "service" && step !== "done" ? (
              <button onClick={back} className="rounded-full bg-white/15 px-3 py-1 text-sm" aria-label="Indietro">
                ← Indietro
              </button>
            ) : (
              <span className="flex items-center gap-1.5 rounded-full bg-white/95 px-2.5 py-1 text-xs font-semibold text-brand-900">
                <LogoMark className="h-4 w-4" /> BluBeauty
              </span>
            )}
            {org.phone && (
              <a href={`tel:${org.phone}`} className="rounded-full bg-white/15 px-3 py-1 text-sm">
                📞 Chiama
              </a>
            )}
          </div>
          <h1 className="mt-4 text-2xl font-bold">{org.name}</h1>
          {org.address && <p className="text-sm text-white/80">{org.address}</p>}
          {step !== "done" && <Progress step={step} />}
        </header>

        <main className="flex-1 px-5 py-5">
          {step === "service" && (
            <section className="space-y-5">
              <h2 className="text-lg font-semibold text-slate-900">Cosa desideri prenotare?</h2>
              {categories.map(([cat, list]) => (
                <div key={cat} className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{cat}</p>
                  {list.map((s) => (
                    <button
                      key={s.id}
                      data-testid="service"
                      onClick={() => {
                        setService(s);
                        setStaffId(null);
                        setTime(null);
                        setStep("staff");
                      }}
                      className="flex w-full items-center justify-between rounded-2xl border border-slate-200 p-4 text-left transition active:scale-[.98] hover:border-brand-300 hover:bg-brand-50"
                    >
                      <span>
                        <span className="block font-semibold text-slate-900">{s.name}</span>
                        <span className="text-sm text-slate-500">{s.durationMin} min</span>
                      </span>
                      <span className="font-semibold text-brand-700">{euro(s.price)}</span>
                    </button>
                  ))}
                </div>
              ))}
            </section>
          )}

          {step === "staff" && service && (
            <section className="space-y-4">
              <h2 className="text-lg font-semibold text-slate-900">Con chi?</h2>
              <div className="grid grid-cols-2 gap-3">
                <StaffCard
                  name="Prima disponibile"
                  initial="★"
                  color="#1E5BD8"
                  onClick={() => {
                    setStaffId(null);
                    setStep("time");
                  }}
                />
                {staff
                  .filter((s) => service.staffIds.includes(s.id))
                  .map((s) => (
                    <StaffCard
                      key={s.id}
                      name={s.firstName}
                      initial={s.firstName[0]}
                      color={s.color}
                      onClick={() => {
                        setStaffId(s.id);
                        setStep("time");
                      }}
                    />
                  ))}
              </div>
            </section>
          )}

          {step === "time" && service && (
            <section className="space-y-4">
              <h2 className="text-lg font-semibold text-slate-900">Quando?</h2>
              <div className="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1">
                {days.map((d) => {
                  const v = iso(d);
                  const active = v === day;
                  return (
                    <button
                      key={v}
                      data-testid="day"
                      onClick={() => {
                        setDay(v);
                        setTime(null);
                      }}
                      className={`flex w-14 shrink-0 flex-col items-center rounded-2xl py-2 transition ${
                        active ? "bg-brand-600 text-white shadow-md" : "bg-slate-100 text-slate-700"
                      }`}
                    >
                      <span className="text-[11px] uppercase">{d.toLocaleDateString("it-IT", { weekday: "short" })}</span>
                      <span className="text-lg font-bold">{d.getDate()}</span>
                      <span className="text-[11px]">{d.toLocaleDateString("it-IT", { month: "short" })}</span>
                    </button>
                  );
                })}
              </div>
              <p className="text-sm capitalize text-slate-500">{dayLabel}</p>
              {slots === null ? (
                <div className="grid grid-cols-4 gap-2">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="h-10 animate-pulse rounded-xl bg-slate-100" />
                  ))}
                </div>
              ) : slots.length === 0 ? (
                <p className="rounded-2xl bg-amber-50 p-4 text-sm text-amber-800">
                  Nessun orario libero in questa giornata. Prova un altro giorno 🙂
                </p>
              ) : (
                <div className="grid grid-cols-4 gap-2">
                  {slots.map((t) => (
                    <button
                      key={t}
                      data-testid="slot"
                      onClick={() => {
                        setTime(t);
                        setStep("details");
                      }}
                      className="rounded-xl border border-brand-200 py-2 text-sm font-semibold text-brand-700 transition active:scale-95 hover:bg-brand-50"
                    >
                      {t}
                    </button>
                  ))}
                </div>
              )}
            </section>
          )}

          {step === "details" && service && time && (
            <section className="space-y-4">
              <div className="rounded-2xl bg-brand-50 p-4 text-sm">
                <p className="font-semibold text-brand-900">{service.name}</p>
                <p className="capitalize text-slate-600">
                  {dayLabel} · ore {time}
                </p>
                <p className="text-slate-600">
                  {chosenStaff ? `con ${chosenStaff.firstName}` : "Primo operatore disponibile"} · {euro(service.price)}
                </p>
              </div>
              <h2 className="text-lg font-semibold text-slate-900">I tuoi dati</h2>
              <div className="grid grid-cols-2 gap-2">
                <input
                  className="input py-3"
                  placeholder="Nome"
                  name="firstName"
                  value={form.firstName}
                  onChange={(e) => setForm({ ...form, firstName: e.target.value })}
                />
                <input
                  className="input py-3"
                  placeholder="Cognome"
                  name="lastName"
                  value={form.lastName}
                  onChange={(e) => setForm({ ...form, lastName: e.target.value })}
                />
              </div>
              <input
                className="input py-3"
                placeholder="Cellulare (WhatsApp)"
                name="phone"
                inputMode="tel"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
              />
              <label className="flex gap-3 text-sm text-slate-600">
                <input
                  type="checkbox"
                  name="privacy"
                  checked={form.privacy}
                  onChange={(e) => setForm({ ...form, privacy: e.target.checked })}
                  className="mt-0.5 h-5 w-5 accent-brand-600"
                />
                Accetto l&apos;informativa privacy per la gestione della prenotazione
              </label>
              <label className="flex gap-3 text-sm text-slate-600">
                <input
                  type="checkbox"
                  name="marketing"
                  checked={form.marketing}
                  onChange={(e) => setForm({ ...form, marketing: e.target.checked })}
                  className="mt-0.5 h-5 w-5 accent-brand-600"
                />
                Voglio ricevere offerte e novità su WhatsApp
              </label>
              {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
            </section>
          )}

          {step === "done" && service && time && token && (
            <section className="flex flex-col items-center gap-4 pt-6 text-center">
              <div className="flex h-20 w-20 items-center justify-center rounded-full bg-emerald-100 text-4xl text-emerald-600">
                ✓
              </div>
              <h2 className="text-2xl font-bold text-slate-900">Prenotazione confermata!</h2>
              <p className="text-slate-600">
                <span className="font-semibold">{service.name}</span>
                <br />
                <span className="capitalize">{dayLabel}</span> alle {time}
              </p>
              <p className="flex items-center gap-2 rounded-2xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                <WhatsAppIcon /> Ti abbiamo inviato la conferma su WhatsApp
              </p>
              <Link
                href={`/prenota/${org.slug}/a/${token}`}
                className="w-full rounded-2xl border border-slate-200 py-3 font-semibold text-slate-700"
              >
                Gestisci o disdici l&apos;appuntamento
              </Link>
              <button
                onClick={() => {
                  setStep("service");
                  setService(null);
                  setTime(null);
                }}
                className="text-sm font-medium text-brand-600"
              >
                Prenota un altro servizio
              </button>
            </section>
          )}
        </main>

        {step === "details" && (
          <footer className="sticky bottom-0 border-t border-slate-100 bg-white p-4">
            <button
              onClick={confirm}
              disabled={pending}
              className="w-full rounded-2xl bg-brand-600 py-4 text-base font-semibold text-white shadow-lg shadow-brand-600/30 transition active:scale-[.98] disabled:opacity-60"
            >
              {pending ? "Conferma in corso…" : "Conferma prenotazione"}
            </button>
            <p className="mt-2 text-center text-xs text-slate-400">
              Puoi disdire gratis fino a {org.cancelHoursBefore} ore prima
            </p>
          </footer>
        )}
      </div>
    </div>
  );
}

function Progress({ step }: { step: Step }) {
  const steps: Step[] = ["service", "staff", "time", "details"];
  const idx = steps.indexOf(step);
  return (
    <div className="mt-4 flex gap-1.5">
      {steps.map((s, i) => (
        <span key={s} className={`h-1.5 flex-1 rounded-full ${i <= idx ? "bg-white" : "bg-white/25"}`} />
      ))}
    </div>
  );
}

function StaffCard({ name, initial, color, onClick }: { name: string; initial: string; color: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      data-testid="staff"
      className="flex flex-col items-center gap-2 rounded-2xl border border-slate-200 p-4 transition active:scale-[.98] hover:border-brand-300 hover:bg-brand-50"
    >
      <span
        className="flex h-14 w-14 items-center justify-center rounded-full text-xl font-bold text-white"
        style={{ background: color }}
      >
        {initial}
      </span>
      <span className="text-sm font-semibold text-slate-800">{name}</span>
    </button>
  );
}
