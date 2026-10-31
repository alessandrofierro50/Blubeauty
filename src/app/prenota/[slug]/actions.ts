"use server";

import { z } from "zod";
import { db } from "@/lib/db";
import { getAvailableSlots } from "@/lib/availability";
import { BookingError, bookAppointment, cancelAppointment, findOrCreateClientByPhone } from "@/lib/booking";

// Azioni PUBBLICHE (nessun login): validare sempre tutto e lavorare solo sull'organizzazione dello slug.
// TODO produzione: rate limiting e verifica OTP del numero via WhatsApp.

async function orgBySlug(slug: string) {
  const org = await db.organization.findUnique({ where: { slug } });
  if (!org) throw new BookingError("Salone non trovato.");
  return org;
}

const slotsSchema = z.object({
  slug: z.string(),
  serviceId: z.string(),
  staffId: z.string().nullable(),
  day: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
});

export async function fetchSlots(input: z.infer<typeof slotsSchema>) {
  const p = slotsSchema.parse(input);
  const org = await orgBySlug(p.slug);
  const slots = await getAvailableSlots({ organizationId: org.id, serviceId: p.serviceId, staffId: p.staffId, day: p.day });
  return slots.map((s) => s.time);
}

const bookingSchema = z.object({
  slug: z.string(),
  serviceId: z.string(),
  staffId: z.string().nullable(),
  day: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  time: z.string().regex(/^\d{2}:\d{2}$/),
  firstName: z.string().trim().min(1, "Inserisci il nome"),
  lastName: z.string().trim().min(1, "Inserisci il cognome"),
  phone: z.string().trim().regex(/^\+?[\d\s]{8,16}$/, "Numero di cellulare non valido"),
  privacy: z.literal(true, { message: "Serve il consenso privacy per prenotare" }),
  marketing: z.boolean(),
});

export type BookingResult = { ok: true; token: string } | { ok: false; error: string };

export async function createBooking(input: z.input<typeof bookingSchema> | (Omit<z.input<typeof bookingSchema>, "privacy"> & { privacy: boolean })): Promise<BookingResult> {
  const parsed = bookingSchema.safeParse(input);
  if (!parsed.success) return { ok: false, error: parsed.error.issues[0]?.message ?? "Dati non validi" };
  const p = parsed.data;
  try {
    const org = await orgBySlug(p.slug);
    const client = await findOrCreateClientByPhone(org.id, {
      firstName: p.firstName,
      lastName: p.lastName,
      phone: p.phone,
      marketing: p.marketing,
    });
    const a = await bookAppointment({
      organizationId: org.id,
      clientId: client.id,
      serviceId: p.serviceId,
      staffId: p.staffId,
      day: p.day,
      time: p.time,
      channel: "ONLINE",
    });
    return { ok: true, token: a.publicToken };
  } catch (e) {
    if (e instanceof BookingError) return { ok: false, error: e.message };
    throw e;
  }
}

export async function cancelByToken(token: string): Promise<{ ok: boolean; error?: string }> {
  const a = await db.appointment.findUnique({ where: { publicToken: token } });
  if (!a) return { ok: false, error: "Appuntamento non trovato." };
  try {
    await cancelAppointment(a.id, { byClient: true });
    return { ok: true };
  } catch (e) {
    if (e instanceof BookingError) return { ok: false, error: e.message };
    throw e;
  }
}
