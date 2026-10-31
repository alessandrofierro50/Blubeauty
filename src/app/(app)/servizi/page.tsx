import type { Metadata } from "next";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { euro } from "@/lib/format";

export const metadata: Metadata = { title: "Servizi" };

export default async function ServiziPage() {
  const user = await getCurrentUser();
  const categories = await db.serviceCategory.findMany({
    where: { organizationId: user.organizationId },
    orderBy: { sortOrder: "asc" },
    include: {
      services: {
        where: { active: true },
        orderBy: { name: "asc" },
        include: { staff: { include: { staff: true } }, requiredResources: true },
      },
    },
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-brand-900">Servizi</h1>
      {categories.map((c) => (
        <section key={c.id} className="card p-0">
          <h2 className="border-b border-slate-100 px-5 py-3 font-semibold text-slate-800">{c.name}</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-5 py-2">Servizio</th>
                  <th className="px-5 py-2">Durata</th>
                  <th className="px-5 py-2">Posa</th>
                  <th className="px-5 py-2">Operatori</th>
                  <th className="px-5 py-2 text-right">Prezzo</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {c.services.map((s) => (
                  <tr key={s.id}>
                    <td className="px-5 py-2 font-medium">
                      {s.name}
                      {s.requiredResources.length > 0 && (
                        <span className="ml-2 text-xs text-slate-400">
                          ({s.requiredResources.map((r) => r.name).join(", ")})
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-2">{s.durationMin} min</td>
                    <td className="px-5 py-2 text-slate-500">{s.processingMin ? `${s.processingMin} min` : "—"}</td>
                    <td className="px-5 py-2 text-slate-500">{s.staff.map((x) => x.staff.firstName).join(", ")}</td>
                    <td className="px-5 py-2 text-right font-semibold">{euro(s.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
