"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { cancelByToken } from "../../actions";

export function CancelButton({ token }: { token: string }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  if (!confirming) {
    return (
      <button
        onClick={() => setConfirming(true)}
        className="w-full rounded-2xl border border-red-200 py-3 font-semibold text-red-600"
      >
        Disdici appuntamento
      </button>
    );
  }
  return (
    <div className="space-y-3 rounded-2xl border border-red-200 bg-red-50 p-4">
      <p className="text-sm text-red-800">Vuoi davvero disdire? Lo spazio tornerà disponibile per altri clienti.</p>
      {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
      <div className="grid grid-cols-2 gap-2">
        <button onClick={() => setConfirming(false)} className="rounded-xl bg-white py-2.5 font-semibold text-slate-700">
          No, tengo
        </button>
        <button
          disabled={pending}
          onClick={() =>
            start(async () => {
              const r = await cancelByToken(token);
              if (!r.ok) setError(r.error ?? "Errore");
              else router.refresh();
            })
          }
          className="rounded-xl bg-red-600 py-2.5 font-semibold text-white disabled:opacity-60"
        >
          {pending ? "Attendi…" : "Sì, disdici"}
        </button>
      </div>
    </div>
  );
}
