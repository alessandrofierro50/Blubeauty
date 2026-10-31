"use client";

import { useMemo, useState, useTransition } from "react";
import { checkout } from "../actions";

type Billing = {
  fiscalCode: string;
  vatNumber: string;
  address: string;
  zip: string;
  city: string;
  province: string;
  sdiCode: string;
  pec: string;
};
type Method = "CASH" | "CARD" | "SATISPAY" | "BANK_TRANSFER";

const euro = (n: number) => new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(n);
const METHODS: { id: Method; label: string; icon: string }[] = [
  { id: "CARD", label: "Carta / POS", icon: "💳" },
  { id: "CASH", label: "Contanti", icon: "💶" },
  { id: "SATISPAY", label: "Satispay", icon: "📲" },
  { id: "BANK_TRANSFER", label: "Bonifico", icon: "🏦" },
];

export function CheckoutForm(props: {
  appointmentId: string;
  services: { id: string; name: string; staff: string; price: number }[];
  products: { id: string; name: string; brand: string | null; price: number; stock: number }[];
  billing: Billing;
}) {
  const [cart, setCart] = useState<Record<string, number>>({});
  const [discount, setDiscount] = useState(0);
  const [method, setMethod] = useState<Method>("CARD");
  const [docType, setDocType] = useState<"RECEIPT" | "INVOICE">("RECEIPT");
  const [billing, setBilling] = useState<Billing>(props.billing);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const gross = useMemo(
    () =>
      props.services.reduce((s, x) => s + x.price, 0) +
      Object.entries(cart).reduce((s, [id, q]) => s + q * (props.products.find((p) => p.id === id)?.price ?? 0), 0),
    [cart, props.services, props.products],
  );
  const total = Math.max(0, gross - discount);

  const add = (id: string, d: number) =>
    setCart((c) => {
      const q = Math.max(0, (c[id] ?? 0) + d);
      const next = { ...c, [id]: q };
      if (q === 0) delete next[id];
      return next;
    });

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="space-y-4">
        <section className="card space-y-2">
          <h2 className="font-semibold text-slate-800">Servizi</h2>
          {props.services.map((s) => (
            <div key={s.id} className="flex justify-between text-sm">
              <span>
                {s.name} <span className="text-slate-400">· {s.staff}</span>
              </span>
              <span className="font-semibold">{euro(s.price)}</span>
            </div>
          ))}
        </section>

        <section className="card space-y-3">
          <h2 className="font-semibold text-slate-800">Aggiungi prodotti</h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {props.products.map((p) => (
              <div key={p.id} className="flex items-center justify-between rounded-xl border border-slate-200 p-3 text-sm">
                <span>
                  <span className="block font-medium">{p.name}</span>
                  <span className="text-slate-500">
                    {euro(p.price)} · {p.stock} disp.
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  {cart[p.id] ? (
                    <>
                      <button className="btn-secondary px-2 py-1" onClick={() => add(p.id, -1)}>
                        −
                      </button>
                      <span className="w-4 text-center font-semibold">{cart[p.id]}</span>
                    </>
                  ) : null}
                  <button data-testid="add-product" className="btn-secondary px-2 py-1" onClick={() => add(p.id, 1)}>
                    +
                  </button>
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="card space-y-3">
          <h2 className="font-semibold text-slate-800">Documento</h2>
          <div className="grid grid-cols-2 gap-2">
            <Choice active={docType === "RECEIPT"} onClick={() => setDocType("RECEIPT")} testId="doc-receipt">
              🧾 Scontrino
              <small className="block font-normal text-slate-500">Documento commerciale (RT)</small>
            </Choice>
            <Choice active={docType === "INVOICE"} onClick={() => setDocType("INVOICE")} testId="doc-invoice">
              📄 Fattura elettronica
              <small className="block font-normal text-slate-500">Invio allo SDI</small>
            </Choice>
          </div>
          {docType === "INVOICE" && (
            <div className="grid gap-2 sm:grid-cols-2">
              {(
                [
                  ["fiscalCode", "Codice fiscale"],
                  ["vatNumber", "Partita IVA (se azienda)"],
                  ["address", "Indirizzo"],
                  ["zip", "CAP"],
                  ["city", "Comune"],
                  ["province", "Provincia (es. RM)"],
                  ["sdiCode", "Codice destinatario SDI"],
                  ["pec", "PEC"],
                ] as [keyof Billing, string][]
              ).map(([k, label]) => (
                <input
                  key={k}
                  name={k}
                  placeholder={label}
                  className="input"
                  value={billing[k]}
                  onChange={(e) => setBilling({ ...billing, [k]: e.target.value })}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      <aside className="card h-fit space-y-4 lg:sticky lg:top-8">
        <h2 className="font-semibold text-slate-800">Pagamento</h2>
        <div className="grid grid-cols-2 gap-2">
          {METHODS.map((m) => (
            <Choice key={m.id} active={method === m.id} onClick={() => setMethod(m.id)}>
              {m.icon} {m.label}
            </Choice>
          ))}
        </div>
        <label className="flex items-center justify-between gap-2 text-sm">
          <span>Sconto (€)</span>
          <input
            type="number"
            min={0}
            step="0.5"
            className="input w-28 text-right"
            value={discount}
            onChange={(e) => setDiscount(Number(e.target.value) || 0)}
          />
        </label>
        <div className="space-y-1 border-t border-slate-100 pt-3 text-sm">
          <div className="flex justify-between text-slate-500">
            <span>Subtotale</span>
            <span>{euro(gross)}</span>
          </div>
          {discount > 0 && (
            <div className="flex justify-between text-slate-500">
              <span>Sconto</span>
              <span>−{euro(discount)}</span>
            </div>
          )}
          <div className="flex justify-between text-2xl font-bold text-brand-900">
            <span>Totale</span>
            <span data-testid="total">{euro(total)}</span>
          </div>
        </div>
        {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        <button
          disabled={pending}
          className="btn-primary w-full py-3 text-base"
          onClick={() =>
            start(async () => {
              setError(null);
              const r = await checkout({
                appointmentId: props.appointmentId,
                products: Object.entries(cart).map(([productId, quantity]) => ({ productId, quantity })),
                discount,
                method,
                docType,
                billing: docType === "INVOICE" ? billing : undefined,
              });
              if (r?.error) setError(r.error);
            })
          }
        >
          {pending ? "Emissione in corso…" : docType === "INVOICE" ? "Incassa ed emetti fattura" : "Incassa ed emetti scontrino"}
        </button>
      </aside>
    </div>
  );
}

function Choice({
  active,
  onClick,
  children,
  testId,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      className={`rounded-xl border p-3 text-left text-sm font-semibold transition ${
        active ? "border-brand-600 bg-brand-50 text-brand-800 ring-2 ring-brand-100" : "border-slate-200 text-slate-700 hover:border-brand-300"
      }`}
    >
      {children}
    </button>
  );
}
