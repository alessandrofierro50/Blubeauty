"use client";

import { useState, useTransition } from "react";
import { WhatsAppPhone } from "@/components/whatsapp";
import { sendCampaign } from "./actions";

type Segment = { id: "ALL" | "INACTIVE_60" | "BIRTHDAY_MONTH" | "WITH_PACKAGE"; label: string; count: number };

const IDEAS = [
  {
    name: "Promo martedì e mercoledì",
    body: "Ciao {nome}! 💙 Solo martedì e mercoledì da {salone}: piega a 15 €. Posti limitati, prenota dal telefono in 30 secondi 👉 {link}",
  },
  {
    name: "Novità trattamento viso",
    body: "Ciao {nome}, è arrivato il nuovo trattamento viso illuminante ✨ Per te la prima seduta al 30% di sconto. Prenota qui: {link}",
  },
];

export function CampaignForm({ segments, salonName, bookingUrl }: { segments: Segment[]; salonName: string; bookingUrl: string }) {
  const [name, setName] = useState("");
  const [segment, setSegment] = useState<Segment["id"]>("ALL");
  const [body, setBody] = useState("");
  const [result, setResult] = useState<{ error?: string; sent?: number } | null>(null);
  const [pending, start] = useTransition();

  const preview = body.replace(/\{nome\}/g, "Laura").replace(/\{salone\}/g, salonName).replace(/\{link\}/g, bookingUrl);
  const count = segments.find((s) => s.id === segment)?.count ?? 0;

  return (
    <section className="card grid gap-6 lg:grid-cols-[1fr_320px]">
      <div className="space-y-4">
        <div>
          <h2 className="font-semibold text-slate-800">Nuova campagna WhatsApp</h2>
          <p className="text-sm text-slate-500">Scegli a chi scrivere: il messaggio viene personalizzato con il nome di ogni cliente.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {IDEAS.map((i) => (
            <button
              key={i.name}
              type="button"
              onClick={() => {
                setName(i.name);
                setBody(i.body);
              }}
              className="rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700 hover:bg-brand-100"
            >
              💡 {i.name}
            </button>
          ))}
        </div>
        <input name="campaignName" className="input" placeholder="Nome campagna" value={name} onChange={(e) => setName(e.target.value)} />
        <div className="grid gap-2 sm:grid-cols-2">
          {segments.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setSegment(s.id)}
              className={`rounded-xl border p-3 text-left text-sm transition ${
                segment === s.id ? "border-brand-600 bg-brand-50 ring-2 ring-brand-100" : "border-slate-200 hover:border-brand-300"
              }`}
            >
              <span className="block font-semibold text-slate-800">{s.label}</span>
              <span className="text-slate-500">{s.count} clienti</span>
            </button>
          ))}
        </div>
        <div className="space-y-1">
          <textarea
            name="body"
            rows={4}
            className="input"
            placeholder="Scrivi il messaggio…"
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <p className="text-xs text-slate-400">
            Segnaposto: <code>{"{nome}"}</code> <code>{"{salone}"}</code> <code>{"{link}"}</code> (link di prenotazione)
          </p>
        </div>
        {result?.error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{result.error}</p>}
        {result?.sent != null && (
          <p data-testid="campaign-sent" className="rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-700">
            ✓ Campagna inviata a {result.sent} clienti su WhatsApp
          </p>
        )}
        <button
          disabled={pending || count === 0}
          className="btn-primary"
          onClick={() =>
            start(async () => {
              setResult(await sendCampaign({ name, segment, body }));
            })
          }
        >
          {pending ? "Invio in corso…" : `Invia a ${count} clienti`}
        </button>
      </div>
      <div className="space-y-2">
        <p className="text-center text-xs font-semibold uppercase tracking-wide text-slate-400">Anteprima</p>
        <WhatsAppPhone title={salonName} messages={preview ? [{ id: "p", body: preview, at: "10:30", status: "READ" }] : []} />
      </div>
    </section>
  );
}
