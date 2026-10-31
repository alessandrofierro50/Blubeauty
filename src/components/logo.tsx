// Logo ufficiale BluBeauty: monogramma "bb" a farfalla.
// File sorgente e varianti in public/brand/ (vedi docs/brand/BRAND.md).
import { useId } from "react";

export function LogoMark({ className = "h-8 w-8", light = false }: { className?: string; light?: boolean }) {
  const id = useId();
  const [from, to] = light ? ["#8CC4FF", "#3B8BFF"] : ["#3B8BFF", "#0B2A5B"];
  return (
    <svg viewBox="2 -1 110 110" className={className} aria-hidden>
      <defs>
        <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="0" y1="10" x2="0" y2="100">
          <stop offset="0" stopColor={from} />
          <stop offset="1" stopColor={to} />
        </linearGradient>
      </defs>
      <g fill="none" stroke={`url(#${id})`} strokeWidth="9" strokeLinecap="round">
        <path d="M51 24V96" />
        <path d="M63 24V96" />
        <circle cx="84" cy="74" r="20" />
        <circle cx="30" cy="74" r="20" />
        <path d="M63 24C66 14 74 10 82 12" strokeWidth="4.5" />
        <path d="M51 24C48 14 40 10 32 12" strokeWidth="4.5" />
      </g>
    </svg>
  );
}

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <LogoMark />
      <span className="text-xl tracking-tight">
        <span className="font-extrabold text-brand-900">Blu</span>
        <span className="font-light text-brand-600">Beauty</span>
      </span>
    </span>
  );
}
