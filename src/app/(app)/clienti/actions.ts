"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";

const schema = z.object({
  firstName: z.string().trim().min(1, "Nome obbligatorio"),
  lastName: z.string().trim().min(1, "Cognome obbligatorio"),
  phone: z.string().trim().optional(),
  email: z.union([z.literal(""), z.string().trim().email("Email non valida")]).optional(),
  privacy: z.literal("on").optional(),
  marketing: z.literal("on").optional(),
});

export type ClientFormState = { error?: string; ok?: boolean } | undefined;

export async function createClient(_prev: ClientFormState, formData: FormData): Promise<ClientFormState> {
  const user = await getCurrentUser();
  const parsed = schema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? "Dati non validi" };

  const d = parsed.data;
  const now = new Date();
  await db.client.create({
    data: {
      organizationId: user.organizationId,
      firstName: d.firstName,
      lastName: d.lastName,
      phone: d.phone || null,
      email: d.email || null,
      privacyConsentAt: d.privacy ? now : null,
      marketingConsentAt: d.marketing ? now : null,
    },
  });
  revalidatePath("/clienti");
  return { ok: true };
}
