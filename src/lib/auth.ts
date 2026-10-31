import "server-only";
import { redirect } from "next/navigation";
import { db } from "./db";
import { getSession } from "./session";
import type { Role } from "@/generated/prisma/enums";

export type CurrentUser = {
  id: string;
  name: string;
  email: string;
  organizationId: string;
  organizationName: string;
  role: Role;
};

/**
 * Data Access Layer: unico punto in cui si legge la sessione.
 * Ogni query di business deve filtrare per `organizationId` restituito da qui.
 */
export async function getCurrentUser(): Promise<CurrentUser> {
  const { userId, organizationId } = await getSession();
  if (!userId || !organizationId) redirect("/login");

  const membership = await db.membership.findUnique({
    where: { userId_organizationId: { userId, organizationId } },
    include: { user: true, organization: true },
  });
  if (!membership) redirect("/login");

  return {
    id: membership.user.id,
    name: membership.user.name,
    email: membership.user.email,
    organizationId: membership.organizationId,
    organizationName: membership.organization.name,
    role: membership.role,
  };
}
