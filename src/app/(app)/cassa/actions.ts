"use server";

import { redirect } from "next/navigation";
import { z } from "zod";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { nextDocNumber, round } from "@/lib/fiscal";
import { appUrl, sendAutomatic } from "@/lib/messaging";

const schema = z.object({
  appointmentId: z.string(),
  products: z.array(z.object({ productId: z.string(), quantity: z.number().int().min(1).max(20) })),
  discount: z.number().min(0),
  method: z.enum(["CASH", "CARD", "SATISPAY", "BANK_TRANSFER"]),
  docType: z.enum(["RECEIPT", "INVOICE"]),
  billing: z
    .object({
      fiscalCode: z.string().trim().min(11, "Codice fiscale non valido").max(16),
      vatNumber: z.string().trim().optional(),
      address: z.string().trim().min(1, "Indirizzo obbligatorio"),
      zip: z.string().trim().regex(/^\d{5}$/, "CAP non valido"),
      city: z.string().trim().min(1, "Comune obbligatorio"),
      province: z.string().trim().length(2, "Provincia: 2 lettere"),
      sdiCode: z.string().trim().optional(),
      pec: z.string().trim().optional(),
    })
    .optional(),
});

export async function checkout(input: z.input<typeof schema>): Promise<{ error?: string }> {
  const user = await getCurrentUser();
  const parsed = schema.safeParse(input);
  if (!parsed.success) return { error: parsed.error.issues[0]?.message };
  const p = parsed.data;
  if (p.docType === "INVOICE" && !p.billing) return { error: "Per la fattura servono i dati di fatturazione" };

  const a = await db.appointment.findFirst({
    where: { id: p.appointmentId, organizationId: user.organizationId },
    include: { client: true, organization: true, items: { include: { service: true } }, sale: true },
  });
  if (!a) return { error: "Appuntamento non trovato" };
  if (a.sale) redirect(`/cassa/documento/${a.sale.id}`);

  const products = await db.product.findMany({
    where: { organizationId: user.organizationId, id: { in: p.products.map((x) => x.productId) } },
  });

  const lines = [
    ...a.items.map((i) => ({
      kind: "SERVICE" as const,
      description: i.service.name,
      staffId: i.staffId,
      productId: null,
      quantity: 1,
      unitPrice: Number(i.price),
      vatRate: Number(i.service.vatRate),
    })),
    ...p.products.map((x) => {
      const prod = products.find((pp) => pp.id === x.productId)!;
      return {
        kind: "PRODUCT" as const,
        description: prod.name,
        staffId: null,
        productId: prod.id,
        quantity: x.quantity,
        unitPrice: Number(prod.price ?? 0),
        vatRate: Number(prod.vatRate),
      };
    }),
  ];
  const gross = lines.reduce((s, l) => s + l.quantity * l.unitPrice, 0);
  const discount = Math.min(p.discount, gross);
  const total = round(gross - discount);
  const now = new Date();
  const docRef = await nextDocNumber(user.organizationId, p.docType, now);

  const sale = await db.$transaction(async (tx) => {
    if (p.docType === "INVOICE" && p.billing && a.clientId) {
      await tx.client.update({ where: { id: a.clientId }, data: { ...p.billing } });
    }
    const sale = await tx.sale.create({
      data: {
        organizationId: user.organizationId,
        locationId: a.locationId,
        clientId: a.clientId,
        appointmentId: a.id,
        status: "PAID",
        total,
        discount,
        fiscalDocType: p.docType,
        fiscalDocRef: docRef,
        fiscalDocAt: now,
        closedAt: now,
        lines: { create: lines },
        payments: { create: { method: p.method, amount: total } },
      },
    });
    for (const x of p.products) {
      await tx.product.update({ where: { id: x.productId }, data: { stock: { decrement: x.quantity } } });
    }
    await tx.appointment.update({ where: { id: a.id }, data: { status: "PAID" } });
    if (a.clientId) {
      await tx.client.update({ where: { id: a.clientId }, data: { loyaltyPoints: { increment: Math.floor(total) } } });
    }
    return sale;
  });

  // Messaggio di ringraziamento con richiesta recensione
  await sendAutomatic(
    user.organizationId,
    "THANK_YOU",
    a.client,
    { salone: a.organization.name, link: appUrl(`/r/${a.organization.slug}`) },
    a.id,
  );

  redirect(`/cassa/documento/${sale.id}`);
}
