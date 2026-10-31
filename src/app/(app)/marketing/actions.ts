"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { segmentClients } from "@/lib/marketing";
import { appUrl, fillTemplate, sendMessage } from "@/lib/messaging";

export async function toggleAutomation(id: string, enabled: boolean) {
  const user = await getCurrentUser();
  await db.automation.updateMany({ where: { id, organizationId: user.organizationId }, data: { enabled } });
  revalidatePath("/marketing");
}

const schema = z.object({
  name: z.string().trim().min(1, "Dai un nome alla campagna"),
  segment: z.enum(["ALL", "INACTIVE_60", "BIRTHDAY_MONTH", "WITH_PACKAGE"]),
  body: z.string().trim().min(10, "Scrivi il messaggio"),
});

export async function sendCampaign(input: z.input<typeof schema>): Promise<{ error?: string; sent?: number }> {
  const user = await getCurrentUser();
  const parsed = schema.safeParse(input);
  if (!parsed.success) return { error: parsed.error.issues[0]?.message };
  const org = await db.organization.findUniqueOrThrow({ where: { id: user.organizationId } });
  const recipients = await segmentClients(org.id, parsed.data.segment);
  if (recipients.length === 0) return { error: "Nessun destinatario in questo segmento" };

  const campaign = await db.campaign.create({
    data: { organizationId: org.id, ...parsed.data, status: "SENT", sentAt: new Date() },
  });
  for (const c of recipients) {
    await sendMessage({
      organizationId: org.id,
      clientId: c.id,
      campaignId: campaign.id,
      kind: "CAMPAIGN",
      to: c.phone!,
      body: fillTemplate(parsed.data.body, { nome: c.firstName, salone: org.name, link: appUrl(`/prenota/${org.slug}`) }),
    });
  }
  revalidatePath("/marketing");
  return { sent: recipients.length };
}
