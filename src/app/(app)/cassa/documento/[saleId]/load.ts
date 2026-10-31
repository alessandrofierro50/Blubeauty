import "server-only";
import { db } from "@/lib/db";

export async function loadSale(organizationId: string, saleId: string) {
  return db.sale.findFirst({
    where: { id: saleId, organizationId },
    include: {
      organization: true,
      location: true,
      client: true,
      lines: true,
      payments: true,
    },
  });
}
