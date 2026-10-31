// Componenti grafici WhatsApp: icona e anteprima chat in un telefono.

export function WhatsAppIcon({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="#25D366" aria-hidden>
      <path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm5.8 14.2c-.2.7-1.4 1.3-2 1.4-.5.1-1.2.1-1.9-.1a17 17 0 0 1-1.7-.6 13.4 13.4 0 0 1-5.1-4.5c-.4-.5-1-1.5-1-2.8s.7-2 1-2.3c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 2c.1.2.1.3 0 .5l-.3.5-.4.4c-.1.1-.3.3-.1.6.2.3.7 1.2 1.6 2 1.1 1 2 1.3 2.3 1.4.3.1.4.1.6-.1l.8-1c.2-.3.4-.2.6-.1l1.9.9c.3.1.5.2.5.3.1.2.1.7-.1 1.3Z" />
    </svg>
  );
}

export type ChatMessage = { id: string; body: string; at: string; inbound?: boolean; status?: string };

/** Anteprima di una conversazione WhatsApp dentro la sagoma di uno smartphone. */
export function WhatsAppPhone({
  title,
  subtitle = "Account aziendale",
  messages,
  className = "",
}: {
  title: string;
  subtitle?: string;
  messages: ChatMessage[];
  className?: string;
}) {
  return (
    <div className={`mx-auto w-full max-w-[300px] rounded-[2.2rem] bg-slate-900 p-2.5 shadow-xl ${className}`}>
      <div className="overflow-hidden rounded-[1.7rem] bg-[#efeae2]">
        <div className="flex items-center gap-2 bg-[#075e54] px-3 py-2.5 text-white">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-xs font-bold text-brand-700">bb</span>
          <div className="leading-tight">
            <p className="text-sm font-semibold">{title}</p>
            <p className="text-[10px] text-white/70">{subtitle}</p>
          </div>
        </div>
        <div className="flex h-[380px] flex-col justify-end gap-2 overflow-y-auto p-3">
          {messages.length === 0 && <p className="text-center text-xs text-slate-500">Nessun messaggio</p>}
          {messages.map((m) => (
            <div
              key={m.id}
              className={`max-w-[85%] whitespace-pre-line rounded-lg px-2.5 py-1.5 text-[12.5px] leading-snug text-slate-800 shadow-sm ${
                m.inbound ? "self-end bg-[#d9fdd3]" : "self-start bg-white"
              }`}
            >
              {linkify(m.body)}
              <span className="mt-0.5 block text-right text-[10px] text-slate-400">
                {m.at} {!m.inbound && m.status && (m.status === "READ" ? <span className="text-sky-500">✓✓</span> : "✓✓")}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function linkify(text: string) {
  return text.split(/(https?:\/\/\S+)/g).map((part, i) =>
    /^https?:\/\//.test(part) ? (
      <span key={i} className="break-all text-sky-600 underline">
        {part}
      </span>
    ) : (
      part
    ),
  );
}
