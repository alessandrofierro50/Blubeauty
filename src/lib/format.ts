const TZ = "Europe/Rome";

export const euro = (v: number | string | { toString(): string }) =>
  new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(Number(v.toString()));

export const time = (d: Date) =>
  new Intl.DateTimeFormat("it-IT", { hour: "2-digit", minute: "2-digit", timeZone: TZ }).format(d);

export const longDate = (d: Date) =>
  new Intl.DateTimeFormat("it-IT", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: TZ }).format(d);

export const shortDate = (d: Date) =>
  new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: TZ }).format(d);

/** "YYYY-MM-DD" → inizio e fine giornata (ora locale del server, impostare TZ=Europe/Rome) */
export function dayRange(isoDay?: string) {
  const base = isoDay && /^\d{4}-\d{2}-\d{2}$/.test(isoDay) ? new Date(`${isoDay}T00:00:00`) : new Date();
  const start = new Date(base);
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { start, end };
}

export const isoDay = (d: Date) => {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};
