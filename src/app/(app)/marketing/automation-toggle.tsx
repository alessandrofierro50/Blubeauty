"use client";

import { useOptimistic, useTransition } from "react";
import { toggleAutomation } from "./actions";

export function AutomationToggle({ id, enabled }: { id: string; enabled: boolean }) {
  const [on, setOn] = useOptimistic(enabled);
  const [, start] = useTransition();
  return (
    <button
      role="switch"
      aria-checked={on}
      onClick={() =>
        start(async () => {
          setOn(!on);
          await toggleAutomation(id, !on);
        })
      }
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${on ? "bg-emerald-500" : "bg-slate-300"}`}
    >
      <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-6" : "left-1"}`} />
    </button>
  );
}
