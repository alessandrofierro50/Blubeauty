"use client";

import { useActionState, useEffect, useRef } from "react";
import { createClient } from "./actions";

export function ClientForm() {
  const [state, action, pending] = useActionState(createClient, undefined);
  const ref = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state?.ok) ref.current?.reset();
  }, [state]);

  return (
    <form ref={ref} action={action} className="card space-y-3">
      <h2 className="font-semibold text-slate-800">Nuovo cliente</h2>
      <div className="grid grid-cols-2 gap-2">
        <input name="firstName" placeholder="Nome" required className="input" />
        <input name="lastName" placeholder="Cognome" required className="input" />
      </div>
      <input name="phone" placeholder="Cellulare" className="input" />
      <input name="email" type="email" placeholder="Email" className="input" />
      <label className="flex items-center gap-2 text-sm text-slate-600">
        <input type="checkbox" name="privacy" /> Consenso privacy (GDPR)
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-600">
        <input type="checkbox" name="marketing" /> Consenso marketing (SMS / WhatsApp / email)
      </label>
      {state?.error && <p className="text-sm text-red-600">{state.error}</p>}
      {state?.ok && <p className="text-sm text-emerald-600">Cliente salvato.</p>}
      <button disabled={pending} className="btn-primary w-full">
        {pending ? "Salvataggio…" : "Salva cliente"}
      </button>
    </form>
  );
}
