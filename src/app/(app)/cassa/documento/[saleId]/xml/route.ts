import { getCurrentUser } from "@/lib/auth";
import { fatturaPAXml } from "@/lib/fiscal";
import { loadSale } from "../load";

export async function GET(_req: Request, ctx: RouteContext<"/cassa/documento/[saleId]/xml">) {
  const user = await getCurrentUser();
  const { saleId } = await ctx.params;
  const sale = await loadSale(user.organizationId, saleId);
  if (!sale || sale.fiscalDocType !== "INVOICE" || !sale.client) return new Response("Non trovato", { status: 404 });
  const o = sale.organization;
  const c = sale.client;
  const xml = fatturaPAXml({
    number: sale.fiscalDocRef ?? "",
    date: sale.fiscalDocAt ?? sale.createdAt,
    seller: {
      name: o.name,
      vatNumber: o.vatNumber ?? "",
      fiscalCode: o.fiscalCode,
      address: o.address ?? "",
      zip: o.zip ?? "",
      city: o.city ?? "",
      province: o.province ?? "",
    },
    buyer: {
      firstName: c.firstName,
      lastName: c.lastName,
      fiscalCode: c.fiscalCode,
      vatNumber: c.vatNumber,
      address: c.address ?? "",
      zip: c.zip ?? "",
      city: c.city ?? "",
      province: c.province ?? "",
      sdiCode: c.sdiCode,
      pec: c.pec,
    },
    lines: sale.lines.map((l) => ({
      description: l.description,
      quantity: Number(l.quantity),
      unitPrice: Number(l.unitPrice),
      vatRate: Number(l.vatRate),
    })),
    discount: Number(sale.discount),
    paymentMethod: sale.payments[0]?.method ?? "CASH",
  });
  const file = `IT${o.vatNumber}_${(sale.fiscalDocRef ?? "").replace("/", "")}.xml`;
  return new Response(xml, {
    headers: { "Content-Type": "application/xml; charset=utf-8", "Content-Disposition": `attachment; filename="${file}"` },
  });
}
