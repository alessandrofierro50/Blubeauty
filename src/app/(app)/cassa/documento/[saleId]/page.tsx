import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { euro, shortDate, time } from "@/lib/format";
import { vatBreakdown } from "@/lib/fiscal";
import { loadSale } from "./load";
import { PrintButton } from "./print-button";

export const metadata: Metadata = { title: "Documento fiscale" };

const METHOD: Record<string, string> = {
  CASH: "Pagamento contante",
  CARD: "Pagamento elettronico",
  SATISPAY: "Pagamento elettronico",
  BANK_TRANSFER: "Bonifico",
};

export default async function DocumentoPage({ params }: PageProps<"/cassa/documento/[saleId]">) {
  const user = await getCurrentUser();
  const { saleId } = await params;
  const sale = await loadSale(user.organizationId, saleId);
  if (!sale) notFound();

  const lines = sale.lines.map((l) => ({
    description: l.description,
    quantity: Number(l.quantity),
    unitPrice: Number(l.unitPrice),
    vatRate: Number(l.vatRate),
  }));
  const vat = vatBreakdown(lines, Number(sale.discount));
  const at = sale.fiscalDocAt ?? sale.createdAt;
  const org = sale.organization;
  const isInvoice = sale.fiscalDocType === "INVOICE";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <div>
          <p className="text-sm font-semibold text-emerald-700">✓ Pagamento registrato · {euro(sale.total)}</p>
          <h1 className="text-2xl font-bold text-brand-900">
            {isInvoice ? `Fattura n. ${sale.fiscalDocRef}` : `Documento commerciale n. ${sale.fiscalDocRef}`}
          </h1>
        </div>
        <div className="flex gap-2">
          {isInvoice && (
            <a href={`/cassa/documento/${sale.id}/xml`} className="btn-secondary">
              ⬇ XML FatturaPA
            </a>
          )}
          <PrintButton />
          <Link href="/cassa" className="btn-primary">
            Torna alla cassa
          </Link>
        </div>
      </div>

      {!isInvoice ? (
        <div className="flex justify-center py-4">
          <div
            data-testid="receipt"
            className="w-[340px] bg-white px-6 py-8 font-mono text-[12.5px] leading-relaxed text-slate-900 shadow-lg [clip-path:polygon(0_0,100%_0,100%_calc(100%-8px),95%_100%,90%_calc(100%-8px),85%_100%,80%_calc(100%-8px),75%_100%,70%_calc(100%-8px),65%_100%,60%_calc(100%-8px),55%_100%,50%_calc(100%-8px),45%_100%,40%_calc(100%-8px),35%_100%,30%_calc(100%-8px),25%_100%,20%_calc(100%-8px),15%_100%,10%_calc(100%-8px),5%_100%,0_calc(100%-8px))]"
          >
            <div className="text-center">
              <p className="text-sm font-bold">{org.name.toUpperCase()}</p>
              <p>{org.address}</p>
              <p>
                {org.zip} {org.city} ({org.province})
              </p>
              <p>P.IVA {org.vatNumber}</p>
              <p className="mt-3 font-bold">DOCUMENTO COMMERCIALE</p>
              <p>di vendita o prestazione</p>
            </div>
            <div className="my-3 border-t border-dashed border-slate-400" />
            <div className="flex justify-between text-[11px] font-bold">
              <span>DESCRIZIONE</span>
              <span>IVA PREZZO(€)</span>
            </div>
            {sale.lines.map((l) => (
              <div key={l.id} className="flex justify-between gap-2">
                <span className="truncate">
                  {Number(l.quantity) > 1 ? `${Number(l.quantity)} x ` : ""}
                  {l.description}
                </span>
                <span className="whitespace-nowrap">
                  {Number(l.vatRate)}% {(Number(l.quantity) * Number(l.unitPrice)).toFixed(2).replace(".", ",")}
                </span>
              </div>
            ))}
            {Number(sale.discount) > 0 && (
              <div className="flex justify-between">
                <span>SCONTO</span>
                <span>-{Number(sale.discount).toFixed(2).replace(".", ",")}</span>
              </div>
            )}
            <div className="my-3 border-t border-dashed border-slate-400" />
            <div className="flex justify-between text-base font-bold">
              <span>TOTALE COMPLESSIVO</span>
              <span>{Number(sale.total).toFixed(2).replace(".", ",")}</span>
            </div>
            <div className="flex justify-between">
              <span>di cui IVA</span>
              <span>{vat.reduce((s, v) => s + v.vat, 0).toFixed(2).replace(".", ",")}</span>
            </div>
            {sale.payments.map((p) => (
              <div key={p.id} className="flex justify-between">
                <span>{METHOD[p.method]}</span>
                <span>{Number(p.amount).toFixed(2).replace(".", ",")}</span>
              </div>
            ))}
            <div className="flex justify-between">
              <span>Importo pagato</span>
              <span>{Number(sale.total).toFixed(2).replace(".", ",")}</span>
            </div>
            <div className="my-3 border-t border-dashed border-slate-400" />
            <p className="text-center">
              {shortDate(at)} {time(at)}
            </p>
            <p className="text-center">DOCUMENTO N. {sale.fiscalDocRef}</p>
            <p className="text-center">RT 99MEX000001</p>
            {sale.client && (
              <p className="mt-2 text-center">
                Cliente: {sale.client.firstName} {sale.client.lastName} · Punti fidelity: {sale.client.loyaltyPoints}
              </p>
            )}
            <p className="mt-4 text-center font-sans text-[10px] font-semibold uppercase tracking-wide text-amber-700">
              Simulazione · registratore telematico non collegato
            </p>
          </div>
        </div>
      ) : (
        <div data-testid="invoice" className="mx-auto max-w-3xl space-y-6 bg-white p-10 text-sm shadow-lg">
          <div className="flex justify-between gap-6">
            <div>
              <p className="text-lg font-bold text-brand-900">{org.name}</p>
              <p>{org.address}</p>
              <p>
                {org.zip} {org.city} ({org.province})
              </p>
              <p>P.IVA {org.vatNumber}</p>
            </div>
            <div className="text-right">
              <p className="text-2xl font-bold text-brand-900">FATTURA</p>
              <p>
                n. <strong>{sale.fiscalDocRef}</strong> del {shortDate(at)}
              </p>
              <p className="mt-1 inline-block rounded bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                Pronta per l&apos;invio allo SDI
              </p>
            </div>
          </div>
          {sale.client && (
            <div className="rounded-lg bg-slate-50 p-4">
              <p className="text-xs uppercase tracking-wide text-slate-400">Cliente</p>
              <p className="font-semibold">
                {sale.client.firstName} {sale.client.lastName}
              </p>
              <p>
                {sale.client.address}, {sale.client.zip} {sale.client.city} ({sale.client.province})
              </p>
              <p>
                C.F. {sale.client.fiscalCode}
                {sale.client.vatNumber ? ` · P.IVA ${sale.client.vatNumber}` : ""}
              </p>
              <p>Cod. destinatario {sale.client.sdiCode || "0000000"}</p>
            </div>
          )}
          <table className="w-full">
            <thead className="border-b text-left text-xs uppercase text-slate-400">
              <tr>
                <th className="py-2">Descrizione</th>
                <th className="py-2 text-right">Q.tà</th>
                <th className="py-2 text-right">Prezzo</th>
                <th className="py-2 text-right">IVA</th>
                <th className="py-2 text-right">Importo</th>
              </tr>
            </thead>
            <tbody>
              {sale.lines.map((l) => (
                <tr key={l.id} className="border-b border-slate-100">
                  <td className="py-2">{l.description}</td>
                  <td className="py-2 text-right">{Number(l.quantity)}</td>
                  <td className="py-2 text-right">{euro(l.unitPrice)}</td>
                  <td className="py-2 text-right">{Number(l.vatRate)}%</td>
                  <td className="py-2 text-right">{euro(Number(l.quantity) * Number(l.unitPrice))}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="ml-auto w-72 space-y-1">
            {vat.map((v) => (
              <div key={v.rate} className="flex justify-between text-slate-600">
                <span>
                  Imponibile {v.rate}% {euro(v.taxable)}
                </span>
                <span>IVA {euro(v.vat)}</span>
              </div>
            ))}
            {Number(sale.discount) > 0 && (
              <div className="flex justify-between text-slate-600">
                <span>Sconto</span>
                <span>−{euro(sale.discount)}</span>
              </div>
            )}
            <div className="flex justify-between border-t pt-2 text-lg font-bold text-brand-900">
              <span>Totale documento</span>
              <span>{euro(sale.total)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
