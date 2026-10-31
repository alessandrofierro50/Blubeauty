import "server-only";
import { db } from "./db";

const STEP_MIN = 15;
const DAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const;

type Interval = [number, number]; // millisecondi epoch

const overlaps = (a: Interval, b: Interval) => a[0] < b[1] && b[0] < a[1];
const min = (n: number) => n * 60_000;

type ServiceShape = { durationMin: number; processingStartMin: number | null; processingMin: number | null };

/** Intervalli in cui l'operatore è impegnato: il tempo di posa resta libero. */
export function staffBusySegments(start: number, s: ServiceShape): Interval[] {
  const end = start + min(s.durationMin);
  if (s.processingStartMin == null || !s.processingMin) return [[start, end]];
  const pStart = start + min(s.processingStartMin);
  const pEnd = pStart + min(s.processingMin);
  return [
    [start, pStart],
    [pEnd, end],
  ].filter(([a, b]) => b > a) as Interval[];
}

export function localDate(day: string, hhmm: string) {
  return new Date(`${day}T${hhmm}:00`);
}

async function loadDay(organizationId: string, day: string) {
  const start = localDate(day, "00:00");
  const end = new Date(start.getTime() + min(24 * 60));
  const items = await db.appointmentItem.findMany({
    where: {
      appointment: { organizationId, status: { notIn: ["CANCELLED", "NO_SHOW"] } },
      startsAt: { gte: start, lt: end },
    },
    include: { service: true },
  });
  return items;
}

export type Slot = { time: string; staffIds: string[] };

/** Orari disponibili per un servizio in un giorno, per uno o tutti gli operatori abilitati. */
export async function getAvailableSlots(opts: {
  organizationId: string;
  serviceId: string;
  staffId?: string | null;
  day: string; // YYYY-MM-DD
  minLeadMinutes?: number;
}): Promise<Slot[]> {
  const service = await db.service.findFirst({
    where: { id: opts.serviceId, organizationId: opts.organizationId, active: true },
    include: { staff: { include: { staff: true } }, requiredResources: true },
  });
  if (!service) return [];
  const location = await db.location.findFirst({ where: { organizationId: opts.organizationId } });
  const hours = (location?.openingHours ?? {}) as Record<string, [string, string][]>;
  const weekday = DAY_KEYS[localDate(opts.day, "12:00").getDay()];
  const windows = (hours[weekday] ?? []).map(([a, b]) => [+localDate(opts.day, a), +localDate(opts.day, b)] as Interval);
  if (windows.length === 0) return [];

  const staff = service.staff
    .map((s) => s.staff)
    .filter((s) => s.active && (!opts.staffId || s.id === opts.staffId));
  const items = await loadDay(opts.organizationId, opts.day);

  const busyByStaff = new Map<string, Interval[]>();
  const busyByResource = new Map<string, Interval[]>();
  for (const i of items) {
    if (i.staffId) {
      const list = busyByStaff.get(i.staffId) ?? [];
      list.push(...staffBusySegments(+i.startsAt, i.service));
      busyByStaff.set(i.staffId, list);
    }
    if (i.resourceId) {
      const list = busyByResource.get(i.resourceId) ?? [];
      list.push([+i.startsAt, +i.endsAt]);
      busyByResource.set(i.resourceId, list);
    }
  }

  const earliest = Date.now() + min(opts.minLeadMinutes ?? 30);
  const slots: Slot[] = [];
  for (const [wStart, wEnd] of windows) {
    for (let t = wStart; t + min(service.durationMin) <= wEnd; t += min(STEP_MIN)) {
      if (t < earliest) continue;
      const whole: Interval = [t, t + min(service.durationMin)];
      if (
        service.requiredResources.length > 0 &&
        !service.requiredResources.some((r) => !(busyByResource.get(r.id) ?? []).some((b) => overlaps(b, whole)))
      )
        continue;
      const segs = staffBusySegments(t, service);
      const free = staff
        .filter((s) => !(busyByStaff.get(s.id) ?? []).some((b) => segs.some((seg) => overlaps(b, seg))))
        .map((s) => s.id);
      if (free.length) {
        const d = new Date(t);
        slots.push({ time: `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, staffIds: free });
      }
    }
  }
  return slots;
}

/** Sceglie una risorsa libera tra quelle richieste dal servizio (es. una cabina). */
export async function pickFreeResource(organizationId: string, serviceId: string, start: Date, end: Date) {
  const service = await db.service.findUnique({ where: { id: serviceId }, include: { requiredResources: true } });
  if (!service || service.requiredResources.length === 0) return null;
  for (const r of service.requiredResources) {
    const clash = await db.appointmentItem.count({
      where: {
        resourceId: r.id,
        appointment: { organizationId, status: { notIn: ["CANCELLED", "NO_SHOW"] } },
        startsAt: { lt: end },
        endsAt: { gt: start },
      },
    });
    if (clash === 0) return r.id;
  }
  return undefined; // nessuna risorsa libera
}
