import Link from "next/link";
import { Logo } from "@/components/logo";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 bg-gradient-to-b from-brand-50 to-white px-6 text-center">
      <Logo className="scale-150" />
      <div className="max-w-xl space-y-3">
        <h1 className="text-3xl font-bold tracking-tight text-brand-900 sm:text-4xl">
          Il gestionale per parrucchieri e centri estetici
        </h1>
        <p className="text-slate-600">
          Agenda, clienti, schede tecniche, pacchetti, cassa e magazzino. Tutto in un posto, da ogni dispositivo.
        </p>
      </div>
      <Link
        href="/login"
        className="rounded-xl bg-brand-600 px-6 py-3 font-semibold text-white shadow-sm transition hover:bg-brand-700"
      >
        Accedi
      </Link>
      <p className="text-xs text-slate-400">© Blu Code Informatica</p>
    </main>
  );
}
