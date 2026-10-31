import "server-only";
import { db } from "./db";
import type { FiscalDocType } from "@/generated/prisma/enums";

/**
 * Numerazione documenti.
 * - Documento commerciale (RT): "CCCC-NNNN" (n. chiusura giornaliera - progressivo).
 * - Fattura: "AAAA/NNNN".
 * In produzione il numero del documento commerciale lo assegna il registratore telematico.
 */
export async function nextDocNumber(organizationId: string, type: FiscalDocType, at = new Date()) {
  const yearStart = new Date(at.getFullYear(), 0, 1);
  const count = await db.sale.count({
    where: { organizationId, fiscalDocType: type, fiscalDocAt: { gte: yearStart } },
  });
  if (type === "INVOICE") return `${at.getFullYear()}/${String(count + 1).padStart(4, "0")}`;
  const dayOfYear = Math.floor((+at - +yearStart) / 86_400_000) + 1;
  return `${String(dayOfYear).padStart(4, "0")}-${String(count + 1).padStart(4, "0")}`;
}

type Line = { description: string; quantity: number; unitPrice: number; vatRate: number };

/** Ripartizione IVA: i prezzi al pubblico sono IVA inclusa. */
export function vatBreakdown(lines: Line[], discount = 0) {
  const gross = lines.reduce((s, l) => s + l.quantity * l.unitPrice, 0);
  const factor = gross > 0 ? (gross - discount) / gross : 1;
  const byRate = new Map<number, { taxable: number; vat: number; gross: number }>();
  for (const l of lines) {
    const g = l.quantity * l.unitPrice * factor;
    const taxable = g / (1 + l.vatRate / 100);
    const r = byRate.get(l.vatRate) ?? { taxable: 0, vat: 0, gross: 0 };
    r.gross += g;
    r.taxable += taxable;
    r.vat += g - taxable;
    byRate.set(l.vatRate, r);
  }
  return [...byRate.entries()].map(([rate, v]) => ({
    rate,
    taxable: round(v.taxable),
    vat: round(v.vat),
    gross: round(v.gross),
  }));
}

export const round = (n: number) => Math.round(n * 100) / 100;

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const n2 = (n: number) => n.toFixed(2);

/** FatturaPA (FPR12) semplificata, da trasmettere allo SDI tramite intermediario. */
export function fatturaPAXml(input: {
  number: string;
  date: Date;
  seller: { name: string; vatNumber: string; fiscalCode?: string | null; address: string; zip: string; city: string; province: string };
  buyer: {
    firstName: string;
    lastName: string;
    fiscalCode?: string | null;
    vatNumber?: string | null;
    address: string;
    zip: string;
    city: string;
    province: string;
    sdiCode?: string | null;
    pec?: string | null;
  };
  lines: Line[];
  discount: number;
  paymentMethod: string;
}) {
  const vat = vatBreakdown(input.lines, input.discount);
  const total = round(vat.reduce((s, v) => s + v.gross, 0));
  const factor = (() => {
    const g = input.lines.reduce((s, l) => s + l.quantity * l.unitPrice, 0);
    return g > 0 ? (g - input.discount) / g : 1;
  })();
  const mp: Record<string, string> = { CASH: "MP01", CARD: "MP08", SATISPAY: "MP08", BANK_TRANSFER: "MP05" };
  const d = input.date.toISOString().slice(0, 10);
  const lines = input.lines
    .map((l, i) => {
      const net = (l.unitPrice * factor) / (1 + l.vatRate / 100);
      return `      <DettaglioLinee>
        <NumeroLinea>${i + 1}</NumeroLinea>
        <Descrizione>${esc(l.description)}</Descrizione>
        <Quantita>${n2(l.quantity)}</Quantita>
        <PrezzoUnitario>${n2(net)}</PrezzoUnitario>
        <PrezzoTotale>${n2(net * l.quantity)}</PrezzoTotale>
        <AliquotaIVA>${n2(l.vatRate)}</AliquotaIVA>
      </DettaglioLinee>`;
    })
    .join("\n");
  const riepilogo = vat
    .map(
      (v) => `      <DatiRiepilogo>
        <AliquotaIVA>${n2(v.rate)}</AliquotaIVA>
        <ImponibileImporto>${n2(v.taxable)}</ImponibileImporto>
        <Imposta>${n2(v.vat)}</Imposta>
        <EsigibilitaIVA>I</EsigibilitaIVA>
      </DatiRiepilogo>`,
    )
    .join("\n");
  const b = input.buyer;
  const s = input.seller;
  return `<?xml version="1.0" encoding="UTF-8"?>
<p:FatturaElettronica versione="FPR12" xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">
  <FatturaElettronicaHeader>
    <DatiTrasmissione>
      <IdTrasmittente><IdPaese>IT</IdPaese><IdCodice>${esc(s.vatNumber)}</IdCodice></IdTrasmittente>
      <ProgressivoInvio>${esc(input.number.replace("/", ""))}</ProgressivoInvio>
      <FormatoTrasmissione>FPR12</FormatoTrasmissione>
      <CodiceDestinatario>${esc(b.sdiCode || "0000000")}</CodiceDestinatario>${b.pec ? `\n      <PECDestinatario>${esc(b.pec)}</PECDestinatario>` : ""}
    </DatiTrasmissione>
    <CedentePrestatore>
      <DatiAnagrafici>
        <IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>${esc(s.vatNumber)}</IdCodice></IdFiscaleIVA>
        <Anagrafica><Denominazione>${esc(s.name)}</Denominazione></Anagrafica>
        <RegimeFiscale>RF01</RegimeFiscale>
      </DatiAnagrafici>
      <Sede><Indirizzo>${esc(s.address)}</Indirizzo><CAP>${esc(s.zip)}</CAP><Comune>${esc(s.city)}</Comune><Provincia>${esc(s.province)}</Provincia><Nazione>IT</Nazione></Sede>
    </CedentePrestatore>
    <CessionarioCommittente>
      <DatiAnagrafici>${b.vatNumber ? `\n        <IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>${esc(b.vatNumber)}</IdCodice></IdFiscaleIVA>` : ""}${b.fiscalCode ? `\n        <CodiceFiscale>${esc(b.fiscalCode)}</CodiceFiscale>` : ""}
        <Anagrafica><Nome>${esc(b.firstName)}</Nome><Cognome>${esc(b.lastName)}</Cognome></Anagrafica>
      </DatiAnagrafici>
      <Sede><Indirizzo>${esc(b.address)}</Indirizzo><CAP>${esc(b.zip)}</CAP><Comune>${esc(b.city)}</Comune><Provincia>${esc(b.province)}</Provincia><Nazione>IT</Nazione></Sede>
    </CessionarioCommittente>
  </FatturaElettronicaHeader>
  <FatturaElettronicaBody>
    <DatiGenerali>
      <DatiGeneraliDocumento>
        <TipoDocumento>TD01</TipoDocumento>
        <Divisa>EUR</Divisa>
        <Data>${d}</Data>
        <Numero>${esc(input.number)}</Numero>
        <ImportoTotaleDocumento>${n2(total)}</ImportoTotaleDocumento>
      </DatiGeneraliDocumento>
    </DatiGenerali>
    <DatiBeniServizi>
${lines}
${riepilogo}
    </DatiBeniServizi>
    <DatiPagamento>
      <CondizioniPagamento>TP02</CondizioniPagamento>
      <DettaglioPagamento><ModalitaPagamento>${mp[input.paymentMethod] ?? "MP01"}</ModalitaPagamento><ImportoPagamento>${n2(total)}</ImportoPagamento></DettaglioPagamento>
    </DatiPagamento>
  </FatturaElettronicaBody>
</p:FatturaElettronica>
`;
}
