"use client";

import { useEffect, useState, useTransition } from "react";
import { createStaffAppointment, staffSlots } from "../actions";

type Opt = { id: string; label: string };

export function NewAppointmentForm(props: {
  defaultDay: string;
  defaultClientId: string;
  clients: (Opt & { phone: string | null })[];
  services: (Opt & { staffIds: string[] })[];
  staff: (Opt & { color: string })[];
}) {
  const [clientId, setClientId] = useState(props.defaultClientId);
  const [serviceId, setServiceId] = useState("");
  const [staffId, setStaffId] = useState<string | null>(null);
  const [day, setDay] = useState(props.defaultDay);
  const [result, setResult] = useState<{ key: string; slots: string[] } | null>(null);
  const [time, setTime] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const service = props.services.find((s) => s.id === serviceId);
  const eligibleStaff = props.staff.filter((s) => service?.staffIds.includes(s.id));

  // Orari liberi: ricalcolati quando cambiano servizio, operatore o giorno
  const key = `${serviceId}|${staffId}|${day}`;
  const slots = result?.key === key ? result.slots : null;
  useEffect(() => {
    if (!serviceId) return;
    let on = true;
    staffSlots({ serviceId, staffId, day }).then((s) => on && setResult({ key: `${serviceId}|${staffId}|${day}`, slots: s }));
    return () => {
      on = false;
    };
  }, [serviceId, staffId, day]);

  return (
    <div className="card space-y-5">
      <Field label="Cliente">
        <select name="clientId" className="input" value={clientId} onChange={(e) => setClientId(e.target.value)}>
          <option value="">— Seleziona —</option>
          {props.clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label} {c.phone ? `· ${c.phone}` : ""}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Servizio">
        <select
          name="serviceId"
          className="input"
          value={serviceId}
          onChange={(e) => {
            setServiceId(e.target.value);
            setStaffId(null);
            setTime("");
          }}
        >
          <option value="">— Seleziona —</option>
          {props.services.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </Field>

      {service && (
        <Field label="Operatore">
          <div className="flex flex-wrap gap-2">
            <Chip
              active={staffId === null}
              onClick={() => {
                setStaffId(null);
                setTime("");
              }}
            >
              Primo disponibile
            </Chip>
            {eligibleStaff.map((s) => (
              <Chip
                key={s.id}
                active={staffId === s.id}
                onClick={() => {
                  setStaffId(s.id);
                  setTime("");
                }}
                color={s.color}
              >
                {s.label}
              </Chip>
            ))}
          </div>
        </Field>
      )}

      {service && (
        <Field label="Giorno">
          <input type="date" name="day" className="input max-w-xs" value={day} onChange={(e) => {
              setDay(e.target.value);
              setTime("");
            }}
          />
        </Field>
      )}

      {service && (
        <Field label="Orari liberi">
          {slots === null ? (
            <p className="text-sm text-slate-400">Calcolo disponibilità…</p>
          ) : slots.length === 0 ? (
            <p className="text-sm text-amber-700">Nessun orario libero: scegli un altro giorno o operatore.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {slots.map((t) => (
                <Chip key={t} active={time === t} onClick={() => setTime(t)}>
                  {t}
                </Chip>
              ))}
            </div>
          )}
        </Field>
      )}

      <Field label="Note">
        <input name="notes" className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Facoltative" />
      </Field>

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <div className="flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
        <p className="text-xs text-slate-500">Al salvataggio il cliente riceve la conferma su WhatsApp.</p>
        <button
          className="btn-primary"
          disabled={pending}
          onClick={() =>
            start(async () => {
              setError(null);
              const r = await createStaffAppointment({ clientId, serviceId, staffId, day, time, notes });
              if (r?.error) setError(r.error);
            })
          }
        >
          {pending ? "Salvataggio…" : "Salva appuntamento"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-sm font-medium text-slate-700">{label}</p>
      {children}
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
  color,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  color?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium transition ${
        active ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 bg-white text-slate-700 hover:border-brand-400"
      }`}
    >
      {color && <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />}
      {children}
    </button>
  );
}
