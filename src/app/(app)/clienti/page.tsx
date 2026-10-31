import type { Metadata } from "next";
import Link from "next/link";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { ClientForm } from "./client-form";

export const metadata: Metadata = { title: "Clienti" };

export default async function ClientiPage({ searchParams }: PageProps<"/clienti">) {
  const user = await getCurrentUser();
  const { q } = await searchParams;
  const query = typeof q === "string" ? q.trim() : "";

  const clients = await db.client.findMany({
    where: {
      organizationId: user.organizationId,
      ...(query && {
        OR: [
          { firstName: { contains: query, mode: "insensitive" } },
          { lastName: { contains: query, mode: "insensitive" } },
          { phone: { contains: query } },
          { email: { contains: query, mode: "insensitive" } },
        ],
      }),
    },
    orderBy: [{ lastName: "asc" }, { firstName: "asc" }],
    take: 100,
  });

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-brand-900">Clienti</h1>
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <section className="space-y-3">
          <form className="flex gap-2">
            <input name="q" defaultValue={query} placeholder="Cerca per nome, telefono, email…" className="input" />
            <button className="btn-secondary">Cerca</button>
          </form>
          <div className="card p-0">
            {clients.length === 0 ? (
              <p className="p-5 text-sm text-slate-500">Nessun cliente trovato.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {clients.map((c) => (
                  <li key={c.id}>
                    <Link href={`/clienti/${c.id}`} className="flex items-center justify-between px-5 py-3 hover:bg-slate-50">
                      <span className="font-medium">
                        {c.lastName} {c.firstName}
                      </span>
                      <span className="text-sm text-slate-500">{c.phone ?? c.email ?? ""}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
        <ClientForm />
      </div>
    </div>
  );
}
