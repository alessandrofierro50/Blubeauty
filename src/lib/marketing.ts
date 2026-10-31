import "server-only";
import { db } from "./db";
import type { CampaignSegment } from "@/generated/prisma/enums";

export const SEGMENT_LABEL: Record<CampaignSegment, string> = {
  ALL: "Tutti i clienti con consenso",
  INACTIVE_60: "Clienti che non vengono da 60+ giorni",
  BIRTHDAY_MONTH: "Compleanno questo mese",
  WITH_PACKAGE: "Clienti con pacchetto attivo",
};

/** Destinatari di un segmento: solo clienti con consenso marketing e numero di cellulare. */
export async function segmentClients(organizationId: string, segment: CampaignSegment) {
  const clients = await db.client.findMany({
    where: { organizationId, marketingConsentAt: { not: null }, phone: { not: null } },
    include: {
      appointments: { where: { status: { notIn: ["CANCELLED", "NO_SHOW"] } }, orderBy: { startsAt: "desc" }, take: 1 },
      packages: true,
    },
  });
  const now = new Date();
  const limit = new Date(now.getTime() - 60 * 86_400_000);
  return clients.filter((c) => {
    switch (segment) {
      case "ALL":
        return true;
      case "INACTIVE_60":
        return !c.appointments[0] || c.appointments[0].startsAt < limit;
      case "BIRTHDAY_MONTH":
        return c.birthDate?.getMonth() === now.getMonth();
      case "WITH_PACKAGE":
        return c.packages.some((p) => p.sessionsUsed < p.sessionsTotal);
    }
  });
}
