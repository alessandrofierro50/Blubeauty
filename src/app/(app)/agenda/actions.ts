"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";
import { getCurrentUser } from "@/lib/auth";
import { getAvailableSlots } from "@/lib/availability";
import { BookingError, bookAppointment, cancelAppointment } from "@/lib/booking";
import { db } from "@/lib/db";
import type { AppointmentStatus } from "@/generated/prisma/enums";

export async function staffSlots(input: { serviceId: string; staffId: string | null; day: string }) {
  const user = await getCurrentUser();
  const slots = await getAvailableSlots({ organizationId: user.organizationId, ...input, minLeadMinutes: 0 });
  return slots.map((s) => s.time);
}

const schema = z.object({
  clientId: z.string().min(1, "Scegli il cliente"),
  serviceId: z.string().min(1, "Scegli il servizio"),
  staffId: z.string().nullable(),
  day: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  time: z.string().regex(/^\d{2}:\d{2}$/, "Scegli l'orario"),
  notes: z.string().optional(),
});

export async function createStaffAppointment(input: z.input<typeof schema>): Promise<{ error?: string }> {
  const user = await getCurrentUser();
  const parsed = schema.safeParse(input);
  if (!parsed.success) return { error: parsed.error.issues[0]?.message };
  const client = await db.client.findFirst({ where: { id: parsed.data.clientId, organizationId: user.organizationId } });
  if (!client) return { error: "Cliente non valido" };
  let id: string;
  try {
    const a = await bookAppointment({ organizationId: user.organizationId, channel: "STAFF", ...parsed.data });
    id = a.id;
  } catch (e) {
    if (e instanceof BookingError) return { error: e.message };
    throw e;
  }
  revalidatePath("/agenda");
  redirect(`/agenda/${id}`);
}

const NEXT: AppointmentStatus[] = ["CONFIRMED", "ARRIVED", "COMPLETED", "NO_SHOW"];

export async function setAppointmentStatus(id: string, status: AppointmentStatus) {
  const user = await getCurrentUser();
  if (!NEXT.includes(status)) throw new Error("Stato non consentito");
  await db.appointment.updateMany({ where: { id, organizationId: user.organizationId }, data: { status } });
  revalidatePath(`/agenda/${id}`);
}

export async function cancelByStaff(id: string) {
  const user = await getCurrentUser();
  const a = await db.appointment.findFirst({ where: { id, organizationId: user.organizationId } });
  if (!a) return;
  await cancelAppointment(a.id, { byClient: false });
  revalidatePath(`/agenda/${id}`);
}
