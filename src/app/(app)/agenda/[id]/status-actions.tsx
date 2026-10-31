"use client";

import Link from "next/link";
import { useTransition } from "react";
import { cancelByStaff, setAppointmentStatus } from "../actions";
import type { AppointmentStatus } from "@/generated/prisma/enums";

export function StatusActions({ id, status, saleId }: { id: string; status: AppointmentStatus; saleId: string | null }) {
  const [pending, start] = useTransition();
  const go = (s: AppointmentStatus) => start(() => setAppointmentStatus(id, s));

  if (status === "PAID" && saleId) {
    return (
      <Link href={`/cassa/documento/${saleId}`} className="btn-secondary w-full py-3">
        Vedi documento fiscale
      </Link>
    );
  }
  if (status === "CANCELLED" || status === "NO_SHOW") return null;

  return (
    <div className="flex flex-wrap gap-2">
      {(status === "BOOKED" || status === "CONFIRMED") && (
        <button disabled={pending} onClick={() => go("ARRIVED")} className="btn-secondary">
          ✓ Cliente arrivato
        </button>
      )}
      {status === "ARRIVED" && (
        <button disabled={pending} onClick={() => go("COMPLETED")} className="btn-secondary">
          ✓ Servizio concluso
        </button>
      )}
      <Link href={`/cassa/${id}`} className="btn-primary">
        💳 Vai alla cassa
      </Link>
      {(status === "BOOKED" || status === "CONFIRMED") && (
        <>
          <button disabled={pending} onClick={() => go("NO_SHOW")} className="btn-secondary text-red-600">
            Non presentato
          </button>
          <button disabled={pending} onClick={() => start(() => cancelByStaff(id))} className="btn-secondary text-red-600">
            Disdici
          </button>
        </>
      )}
    </div>
  );
}
