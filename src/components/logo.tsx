// Logo provvisorio (proposta A "Loto"). I file SVG ufficiali sono in public/brand/.
export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden>
      <defs>
        <linearGradient id="lm1" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#0B3B8C" />
          <stop offset="1" stopColor="#2F7BEA" />
        </linearGradient>
        <linearGradient id="lm2" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#2F7BEA" />
          <stop offset="1" stopColor="#8CC4FF" />
        </linearGradient>
      </defs>
      <path d="M50 92 C30 70 32 40 50 18 C68 40 70 70 50 92Z" fill="url(#lm2)" opacity=".85" transform="rotate(-38 50 92)" />
      <path d="M50 92 C30 70 32 40 50 18 C68 40 70 70 50 92Z" fill="url(#lm2)" opacity=".85" transform="rotate(38 50 92)" />
      <path d="M50 92 C30 70 32 40 50 8 C68 40 70 70 50 92Z" fill="url(#lm1)" />
    </svg>
  );
}

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <LogoMark />
      <span className="text-xl tracking-tight">
        <span className="font-extrabold text-brand-900">blu</span>
        <span className="font-light text-brand-500">beauty</span>
      </span>
    </span>
  );
}
