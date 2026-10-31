import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { longDate, time } from "@/lib/format";
import { CheckoutForm } from "./checkout-form";

export const metadata: Metadata = { title: "Incasso" };

export default async function CheckoutPage({ params }: PageProps<"/cassa/[appointmentId]">) {
  const user = await getCurrentUser();
  const { appointmentId } = await params;
  const a = await db.appointment.findFirst({
    where: { id: appointmentId, organizationId: user.organizationId },
    include: { client: true, sale: true, items: { include: { service: true, staff: true } } },
  });
  if (!a) notFound();
  if (a.sale) redirect(`/cassa/documento/${a.sale.id}`);
  const products = await db.product.findMany({
    where: { organizationId: user.organizationId, active: true, usage: { in: ["RETAIL", "BOTH"] } },
    orderBy: { name: "asc" },
  });
  const c = a.client;
  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-brand-900">Incasso</h1>
        <p className="text-sm text-slate-500">
          {c ? `${c.firstName} ${c.lastName}` : "Cliente occasionale"} · <span className="capitalize">{longDate(a.startsAt)}</span>{" "}
          {time(a.startsAt)}
        </p>
      </div>
      <CheckoutForm
        appointmentId={a.id}
        services={a.items.map((i) => ({
          id: i.id,
          name: i.service.name,
          staff: i.staff?.firstName ?? "",
          price: Number(i.price),
        }))}
        products={products.map((p) => ({ id: p.id, name: p.name, brand: p.brand, price: Number(p.price ?? 0), stock: Number(p.stock) }))}
        billing={{
          fiscalCode: c?.fiscalCode ?? "",
          vatNumber: c?.vatNumber ?? "",
          address: c?.address ?? "",
          zip: c?.zip ?? "",
          city: c?.city ?? "",
          province: c?.province ?? "",
          sdiCode: c?.sdiCode ?? "",
          pec: c?.pec ?? "",
        }}
      />
    </div>
  );
}
