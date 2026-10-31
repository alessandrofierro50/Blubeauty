"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/dashboard", label: "Dashboard", icon: "◧" },
  { href: "/agenda", label: "Agenda", icon: "▦" },
  { href: "/clienti", label: "Clienti", icon: "☺" },
  { href: "/cassa", label: "Cassa", icon: "€" },
  { href: "/marketing", label: "Marketing", icon: "✆" },
  { href: "/servizi", label: "Servizi", icon: "✂" },
];

const soon = ["Magazzino", "Pacchetti", "Statistiche", "Impostazioni"];

export function Nav() {
  return <NavLinks pathname={usePathname()} />;
}

/** Versione senza stato attivo, usata come fallback statico durante lo streaming. */
export function NavLinks({ pathname = "" }: { pathname?: string }) {
  return (
    <nav className="flex flex-col gap-1 text-sm">
      {items.map((i) => {
        const active = pathname.startsWith(i.href);
        return (
          <Link
            key={i.href}
            href={i.href}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 font-medium transition ${
              active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            <span className="w-4 text-center">{i.icon}</span>
            {i.label}
          </Link>
        );
      })}
      <p className="mt-4 px-3 text-xs font-semibold uppercase tracking-wide text-slate-400">In arrivo</p>
      {soon.map((s) => (
        <span key={s} className="px-3 py-1.5 text-slate-400">
          {s}
        </span>
      ))}
    </nav>
  );
}
