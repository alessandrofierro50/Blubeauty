import "server-only";
import { db } from "./db";
import { getAvailableSlots, localDate, pickFreeResource } from "./availability";
import { appointmentVars, sendAutomatic } from "./messaging";
import { isoDay } from "./format";
import type { BookingChannel } from "@/generated/prisma/enums";

export class BookingError extends Error {}

/**
 * Crea un appuntamento verificando la disponibilità di operatore e risorse.
 * Usato sia dall'agenda del salone sia dalla prenotazione online del cliente.
 */
export async function bookAppointment(input: {
  organizationId: string;
  clientId: string;
  serviceId: string;
  staffId?: string | null; // null = primo operatore disponibile
  day: string;
  time: string;
  channel: BookingChannel;
  notes?: string;
  allowPast?: boolean;
}) {
  const slots = await getAvailableSlots({
    organizationId: input.organizationId,
    serviceId: input.serviceId,
    staffId: input.staffId,
    day: input.day,
    minLeadMinutes: input.allowPast ? -24 * 60 : 30,
  });
  const slot = slots.find((s) => s.time === input.time);
  if (!slot) throw new BookingError("L'orario scelto non è più disponibile.");
  const staffId = input.staffId ?? slot.staffIds[0];

  const service = await db.service.findUniqueOrThrow({ where: { id: input.serviceId } });
  const startsAt = localDate(input.day, input.time);
  const endsAt = new Date(startsAt.getTime() + service.durationMin * 60_000);
  const resourceId = await pickFreeResource(input.organizationId, service.id, startsAt, endsAt);
  if (resourceId === undefined) throw new BookingError("Nessuna cabina libera in quell'orario.");

  const location = await db.location.findFirstOrThrow({ where: { organizationId: input.organizationId } });
  const appointment = await db.appointment.create({
    data: {
      organizationId: input.organizationId,
      locationId: location.id,
      clientId: input.clientId,
      startsAt,
      endsAt,
      channel: input.channel,
      status: input.channel === "ONLINE" ? "CONFIRMED" : "BOOKED",
      notes: input.notes,
      items: {
        create: { serviceId: service.id, staffId, resourceId, startsAt, endsAt, price: service.price },
      },
    },
    include: { client: true, organization: true },
  });

  await sendAutomatic(
    input.organizationId,
    "CONFIRMATION",
    appointment.client,
    { ...appointmentVars(appointment, appointment.organization), servizio: service.name },
    appointment.id,
  );
  return appointment;
}

export async function cancelAppointment(appointmentId: string, opts: { byClient: boolean }) {
  const a = await db.appointment.findUniqueOrThrow({
    where: { id: appointmentId },
    include: { organization: true, client: true, items: { include: { service: true } } },
  });
  if (a.status === "CANCELLED") return a;
  if (opts.byClient) {
    const limit = a.startsAt.getTime() - a.organization.cancelHoursBefore * 3_600_000;
    if (Date.now() > limit) {
      throw new BookingError(
        `La disdetta online è possibile fino a ${a.organization.cancelHoursBefore} ore prima. Contatta il salone.`,
      );
    }
  }
  const updated = await db.appointment.update({
    where: { id: a.id },
    data: { status: "CANCELLED", cancelledAt: new Date() },
  });
  await sendAutomatic(
    a.organizationId,
    "CANCELLATION",
    a.client,
    {
      ...appointmentVars(a, a.organization),
      link: `${process.env.APP_URL ?? "http://localhost:3000"}/prenota/${a.organization.slug}`,
      servizio: a.items.map((i) => i.service.name).join(", "),
    },
    a.id,
  );
  return updated;
}

/** Trova o crea il cliente dal numero di telefono (prenotazione online). */
export async function findOrCreateClientByPhone(
  organizationId: string,
  data: { firstName: string; lastName: string; phone: string; email?: string; marketing: boolean },
) {
  const phone = data.phone.replace(/[^\d+]/g, "");
  const existing = await db.client.findFirst({ where: { organizationId, phone } });
  if (existing) {
    if (data.marketing && !existing.marketingConsentAt) {
      return db.client.update({ where: { id: existing.id }, data: { marketingConsentAt: new Date() } });
    }
    return existing;
  }
  return db.client.create({
    data: {
      organizationId,
      firstName: data.firstName,
      lastName: data.lastName,
      phone,
      email: data.email || null,
      privacyConsentAt: new Date(),
      marketingConsentAt: data.marketing ? new Date() : null,
    },
  });
}

export const todayIso = () => isoDay(new Date());
