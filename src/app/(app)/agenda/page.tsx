import type { Metadata } from "next";
import Link from "next/link";
import { getCurrentUser } from "@/lib/auth";
import { db } from "@/lib/db";
import { dayRange, isoDay, longDate, time } from "@/lib/format";

export const metadata: Metadata = { title: "Agenda" };

const DAY_START = 8; // 08:00
const DAY_END = 20; // 20:00
const PX_PER_MIN = 1.6;

const statusLabel: Record<string, string> = {
  BOOKED: "Prenotato",
  CONFIRMED: "Confermato",
  ARRIVED: "In salone",
  COMPLETED: "Concluso",
  PAID: "Pagato",
  CANCELLED: "Disdetto",
  NO_SHOW: "Non presentato",
};

type Timed = { startsAt: Date; endsAt: Date };

/** Affianca gli appuntamenti che si sovrappongono (es. una piega durante la posa del colore). */
function layoutLanes<T extends Timed>(items: T[]) {
  const out: { item: T; lane: number; lanes: number }[] = [];
  let cluster: { item: T; lane: number }[] = [];
  let laneEnds: number[] = [];
  let clusterEnd = 0;
  const flush = () => {
    for (const c of cluster) out.push({ ...c, lanes: laneEnds.length });
    cluster = [];
    laneEnds = [];
  };
  for (const item of [...items].sort((a, b) => +a.startsAt - +b.startsAt)) {
    if (cluster.length && +item.startsAt >= clusterEnd) flush();
    let lane = laneEnds.findIndex((end) => end <= +item.startsAt);
    if (lane === -1) lane = laneEnds.push(0) - 1;
    laneEnds[lane] = +item.endsAt;
    clusterEnd = Math.max(clusterEnd, +item.endsAt);
    cluster.push({ item, lane });
  }
  flush();
  return out;
}

export default async function AgendaPage({ searchParams }: PageProps<"/agenda">) {
  const user = await getCurrentUser();
  const { data } = await searchParams;
  const { start, end } = dayRange(typeof data === "string" ? data : undefined);

  const [staff, items] = await Promise.all([
    db.staffMember.findMany({
      where: { organizationId: user.organizationId, active: true },
      orderBy: { firstName: "asc" },
    }),
    db.appointmentItem.findMany({
      where: {
        appointment: { organizationId: user.organizationId, status: { not: "CANCELLED" } },
        startsAt: { gte: start, lt: end },
      },
      include: { service: true, appointment: { include: { client: true } }, resource: true },
      orderBy: { startsAt: "asc" },
    }),
  ]);

  const prev = new Date(start);
  prev.setDate(prev.getDate() - 1);
  const next = new Date(start);
  next.setDate(next.getDate() + 1);

  const gridStart = new Date(start);
  gridStart.setHours(DAY_START, 0, 0, 0);
  const minutesFromStart = (d: Date) => (d.getTime() - gridStart.getTime()) / 60_000;
  const hours = Array.from({ length: DAY_END - DAY_START }, (_, i) => DAY_START + i);
  const height = (DAY_END - DAY_START) * 60 * PX_PER_MIN;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-brand-900">Agenda</h1>
          <p className="text-sm capitalize text-slate-500">{longDate(start)}</p>
        </div>
        <div className="flex gap-2">
          <Link className="btn-secondary" href={`/agenda?data=${isoDay(prev)}`}>
            ←
          </Link>
          <Link className="btn-secondary" href="/agenda">
            Oggi
          </Link>
          <Link className="btn-secondary" href={`/agenda?data=${isoDay(next)}`}>
            →
          </Link>
          <button className="btn-primary" disabled title="In arrivo nella prossima iterazione">
            + Appuntamento
          </button>
        </div>
      </header>

      <div className="card overflow-x-auto p-0">
        {/* Intestazione operatori */}
        <div className="sticky top-0 z-10 flex border-b border-slate-200 bg-white">
          <div className="w-14 shrink-0" />
          {staff.map((s) => (
            <div key={s.id} className="flex min-w-44 flex-1 items-center gap-2 border-l border-slate-100 px-3 py-3 text-sm font-semibold">
              <span className="h-3 w-3 rounded-full" style={{ background: s.color }} />
              {s.firstName}
            </div>
          ))}
        </div>

        <div className="relative flex" style={{ height }}>
          {/* Colonna orari */}
          <div className="relative w-14 shrink-0">
            {hours.map((h) => (
              <span
                key={h}
                className="absolute right-2 -translate-y-2 text-xs text-slate-400"
                style={{ top: (h - DAY_START) * 60 * PX_PER_MIN }}
              >
                {String(h).padStart(2, "0")}:00
              </span>
            ))}
          </div>

          {staff.map((s) => (
            <div key={s.id} className="relative min-w-44 flex-1 border-l border-slate-100">
              {hours.map((h) => (
                <div
                  key={h}
                  className="absolute inset-x-0 border-t border-slate-100"
                  style={{ top: (h - DAY_START) * 60 * PX_PER_MIN }}
                />
              ))}
              {layoutLanes(items.filter((i) => i.staffId === s.id)).map(({ item: i, lane, lanes }) => {
                  const top = minutesFromStart(i.startsAt) * PX_PER_MIN;
                  const h = ((i.endsAt.getTime() - i.startsAt.getTime()) / 60_000) * PX_PER_MIN;
                  const c = i.appointment.client;
                  const proc =
                    i.service.processingStartMin != null && i.service.processingMin
                      ? { top: i.service.processingStartMin * PX_PER_MIN, h: i.service.processingMin * PX_PER_MIN }
                      : null;
                  return (
                    <div
                      key={i.id}
                      className="absolute overflow-hidden rounded-lg px-2 py-1 text-xs text-white shadow-sm ring-2 ring-white"
                      style={{
                        top,
                        height: h,
                        background: s.color,
                        left: `calc(${(lane / lanes) * 100}% + 4px)`,
                        width: `calc(${100 / lanes}% - 8px)`,
                      }}
                    >
                      {proc && (
                        <div
                          className="processing absolute inset-x-0 flex items-center justify-end pr-2 text-[10px] font-semibold text-white/90"
                          style={{ top: proc.top, height: proc.h }}
                        >
                          posa
                        </div>
                      )}
                      <div className="relative">
                        <p className="font-semibold">
                          {time(i.startsAt)} · {c ? `${c.firstName} ${c.lastName}` : "Occasionale"}
                        </p>
                        <p className="opacity-90">
                          {i.service.name}
                          {i.resource ? ` · ${i.resource.name}` : ""}
                        </p>
                        <p className="opacity-75">{statusLabel[i.appointment.status]}</p>
                      </div>
                    </div>
                  );
              })}
            </div>
          ))}
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Le fasce a righe indicano il <strong>tempo di posa</strong>: l&apos;operatore è libero e può servire un altro cliente.
      </p>
    </div>
  );
}
