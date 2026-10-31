"use server";

import bcrypt from "bcryptjs";
import { redirect } from "next/navigation";
import { z } from "zod";
import { db } from "@/lib/db";
import { destroySession, saveSession } from "@/lib/session";

const schema = z.object({
  email: z.string().trim().toLowerCase().email(),
  password: z.string().min(1),
});

export type LoginState = { error?: string } | undefined;

export async function login(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const parsed = schema.safeParse({ email: formData.get("email"), password: formData.get("password") });
  if (!parsed.success) return { error: "Inserisci email e password." };

  const user = await db.user.findUnique({
    where: { email: parsed.data.email },
    include: { memberships: { orderBy: { createdAt: "asc" }, take: 1 } },
  });
  const ok = user && (await bcrypt.compare(parsed.data.password, user.passwordHash));
  if (!ok || user.memberships.length === 0) return { error: "Credenziali non valide." };

  await saveSession({ userId: user.id, organizationId: user.memberships[0].organizationId });
  redirect("/dashboard");
}

export async function logout() {
  await destroySession();
  redirect("/login");
}
