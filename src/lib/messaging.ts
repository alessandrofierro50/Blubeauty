import "server-only";
import { db } from "./db";
import type { MessageChannel, MessageKind } from "@/generated/prisma/enums";
import { longDate, time } from "./format";

/** Testi predefiniti. Segnaposto: {nome} {salone} {data} {ora} {servizio} {link} {telefono} */
export const DEFAULT_TEMPLATES: Record<MessageKind, string> = {
  CONFIRMATION:
    "Ciao {nome}! ✨ Il tuo appuntamento da {salone} è confermato per {data} alle {ora} ({servizio}).\nPer vederlo o disdirlo: {link}",
  REMINDER:
    "Ciao {nome}, ti ricordiamo l'appuntamento di domani alle {ora} da {salone} ({servizio}). Ti aspettiamo! 💙\nNon puoi venire? Disdici qui: {link}",
  CANCELLATION: "Ciao {nome}, il tuo appuntamento del {data} alle {ora} è stato disdetto. Prenota di nuovo quando vuoi: {link}",
  THANK_YOU:
    "Grazie {nome} per essere passata da {salone}! 🌸 Se ti sei trovata bene, ci lasci una recensione? Ci aiuta tantissimo: {link}",
  RECALL: "Ciao {nome}, sono passate 5 settimane dal tuo ultimo colore 🎨 È il momento giusto per il ritocco! Prenota in un tap: {link}",
  BIRTHDAY: "Tanti auguri {nome}! 🎂 Per il tuo compleanno hai il 20% di sconto su un trattamento a scelta questo mese. Prenota: {link}",
  WIN_BACK: "Ciao {nome}, ci manchi! 💙 Torna a trovarci entro fine mese: per te una piega in omaggio con qualsiasi servizio. Prenota: {link}",
  CAMPAIGN: "",
};

export const KIND_LABEL: Record<MessageKind, string> = {
  CONFIRMATION: "Conferma prenotazione",
  REMINDER: "Promemoria",
  CANCELLATION: "Conferma disdetta",
  THANK_YOU: "Grazie + recensione",
  RECALL: "Richiamo colore",
  BIRTHDAY: "Compleanno",
  WIN_BACK: "Clienti persi",
  CAMPAIGN: "Campagna",
};

export function appUrl(path = "") {
  return `${process.env.APP_URL ?? "http://localhost:3000"}${path}`;
}

export function fillTemplate(template: string, vars: Record<string, string | undefined>) {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => vars[k] ?? m);
}

export function appointmentVars(a: { startsAt: Date; publicToken: string }, org: { name: string; slug: string }) {
  return {
    salone: org.name,
    data: longDate(a.startsAt),
    ora: time(a.startsAt),
    link: appUrl(`/prenota/${org.slug}/a/${a.publicToken}`),
  };
}

/**
 * Invio di un messaggio. In questa versione il provider è SIMULATO: il messaggio viene
 * registrato come consegnato. Per la produzione si collega WhatsApp Business Cloud API
 * (Meta) o un BSP italiano implementando `deliver()`.
 */
async function deliver(channel: MessageChannel, to: string, body: string): Promise<{ providerId: string }> {
  void [channel, to, body];
  return { providerId: `sim_${Date.now().toString(36)}` };
}

export async function sendMessage(input: {
  organizationId: string;
  clientId?: string | null;
  appointmentId?: string | null;
  campaignId?: string | null;
  kind: MessageKind;
  channel?: MessageChannel;
  to: string;
  body: string;
}) {
  const channel = input.channel ?? "WHATSAPP";
  const { providerId } = await deliver(channel, input.to, input.body);
  return db.message.create({
    data: {
      organizationId: input.organizationId,
      clientId: input.clientId ?? null,
      appointmentId: input.appointmentId ?? null,
      campaignId: input.campaignId ?? null,
      channel,
      kind: input.kind,
      to: input.to,
      body: input.body,
      status: "DELIVERED",
      providerId,
      sentAt: new Date(),
    },
  });
}

/** Invia il messaggio automatico `kind` se l'automazione è attiva. */
export async function sendAutomatic(
  organizationId: string,
  kind: MessageKind,
  client: { id: string; firstName: string; phone: string | null } | null,
  vars: Record<string, string | undefined>,
  appointmentId?: string,
) {
  if (!client?.phone) return null;
  const automation = await db.automation.findUnique({ where: { organizationId_kind: { organizationId, kind } } });
  if (automation && !automation.enabled) return null;
  const template = automation?.template ?? DEFAULT_TEMPLATES[kind];
  return sendMessage({
    organizationId,
    clientId: client.id,
    appointmentId,
    kind,
    channel: automation?.channel ?? "WHATSAPP",
    to: client.phone,
    body: fillTemplate(template, { nome: client.firstName, ...vars }),
  });
}
