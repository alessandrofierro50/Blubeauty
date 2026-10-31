// Stampe in formato scontrino (80 mm): ricevuta di cortesia, riepilogo X e chiusura Z.
// Lo scontrino fiscale vero lo emette il registratore telematico (fase 3c): questa è solo una cortesia.

import { methodLabel, qtyFmt } from './shared'

const money = (v: string | number | null | undefined) => Number(v ?? 0).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const PRINT_CSS = `
#pos-print { display: none; }
@media print {
  @page { size: 80mm auto; margin: 3mm; }
  body * { visibility: hidden !important; }
  #pos-print, #pos-print * { visibility: visible !important; }
  #pos-print { display: block; position: absolute; left: 0; top: 0; width: 72mm; }
}
.rcpt { font-family: 'Courier New', ui-monospace, monospace; font-size: 12px; color: #000; line-height: 1.35; }
.rcpt .c { text-align: center; }
.rcpt .row { display: flex; justify-content: space-between; gap: 6px; }
.rcpt .big { font-size: 16px; font-weight: 700; }
.rcpt hr { border: none; border-top: 1px dashed #000; margin: 6px 0; }
.rcpt .muted { font-size: 11px; }
`

function Header({ company }: { company: any }) {
  if (!company) return null
  return (
    <div className="c">
      {company.logo_url && <img src={company.logo_url} alt="" style={{ maxWidth: '50mm', maxHeight: '18mm', marginBottom: 4 }} />}
      <div style={{ fontWeight: 700 }}>{company.name}</div>
      <div className="muted">{[company.address, [company.zip_code, company.city, company.province && `(${company.province})`].filter(Boolean).join(' ')].filter(Boolean).join(' - ')}</div>
      {company.vat_number && <div className="muted">P.IVA {company.vat_number}</div>}
      {company.phone && <div className="muted">Tel. {company.phone}</div>}
    </div>
  )
}

export function ReceiptPrint({ r, company, register }: { r: any; company: any; register?: string }) {
  const isReturn = r.doc_type === 'RSO'
  const when = r.created_at ? new Date(r.created_at) : new Date()
  return (
    <div className="rcpt">
      <Header company={company} />
      <hr />
      <div className="c" style={{ fontWeight: 700 }}>
        {r.doc_type === 'FTI' ? `FATTURA N. ${r.number}/${r.year}` : isReturn ? (r.fiscal?.kind === 'annullo' ? 'DOCUMENTO DI ANNULLO' : 'DOCUMENTO DI RESO') : 'RICEVUTA DI CORTESIA'}
      </div>
      {r.doc_type === 'SCO' && <div className="c muted">non valida ai fini fiscali</div>}
      {r.doc_type === 'FTI' && <div className="c muted">intestata a {r.party_name}</div>}
      <hr />
      {r.lines.map((l: any) => (
        <div key={l.id}>
          <div className="row"><span>{l.description}</span><span>{money(l.total)}</span></div>
          {(Number(l.quantity) !== 1 || l.discount) && (
            <div className="muted">&nbsp;&nbsp;{qtyFmt(Number(l.quantity))}{l.unit ? ` ${l.unit}` : ''} x {money(l.unit_price_gross ?? l.unit_price)}{l.discount ? `  sconto ${Number(l.discount)}%` : ''}</div>
          )}
        </div>
      ))}
      <hr />
      <div className="row big"><span>{isReturn ? 'RIMBORSO' : 'TOTALE'} EURO</span><span>{money(r.total)}</span></div>
      {r.vat_summary.map((v: any) => (
        <div key={v.rate + (v.nature ?? '')} className="row muted"><span>di cui IVA {Number(v.rate)}%</span><span>{money(v.vat)}</span></div>
      ))}
      <hr />
      {r.payments.map((p: any, i: number) => (
        <div key={i} className="row"><span>{methodLabel(p.method)}</span><span>{money(p.tendered ?? Math.abs(Number(p.amount)))}</span></div>
      ))}
      {Number(r.change) > 0 && <div className="row"><span>Resto</span><span>{money(r.change)}</span></div>}
      <hr />
      {r.reference && <div className="muted">{r.reference}</div>}
      {r.fiscal?.lottery && <div className="muted">Codice lotteria: {r.fiscal.lottery}</div>}
      {r.fiscal?.rt?.status === 'emesso' && <div className="muted">Documento commerciale n. {r.fiscal.rt.z}-{r.fiscal.rt.number}</div>}
      <div className="row muted"><span>{when.toLocaleDateString('it-IT')} {when.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}</span><span>{register ?? ''} n. {r.number ?? '—'}</span></div>
      {company?.print_settings?.footer && <div className="c muted" style={{ marginTop: 6 }}>{company.print_settings.footer}</div>}
      <div className="c" style={{ marginTop: 6 }}>Grazie e arrivederci</div>
    </div>
  )
}

export function SessionPrint({ ses, company, register }: { ses: any; company: any; register?: string }) {
  const s = ses.summary || {}
  const closed = ses.status === 'chiusa'
  return (
    <div className="rcpt">
      <Header company={company} />
      <hr />
      <div className="c" style={{ fontWeight: 700 }}>{closed ? 'CHIUSURA DI CASSA' : 'RIEPILOGO DI CASSA (X)'}</div>
      <div className="c muted">{register} · aperta il {new Date(ses.opened_at).toLocaleString('it-IT')}</div>
      {closed && <div className="c muted">chiusa il {new Date(ses.closed_at).toLocaleString('it-IT')}{ses.z_number ? ` · Z n. ${ses.z_number}` : ''}</div>}
      <hr />
      <div className="row"><span>Scontrini</span><span>{s.receipts ?? 0}</span></div>
      <div className="row"><span>Vendite</span><span>{money(s.sales_total)}</span></div>
      <div className="row"><span>Resi</span><span>-{money(s.returns_total)}</span></div>
      <div className="row big"><span>NETTO</span><span>{money(s.net_total)}</span></div>
      <div className="row muted"><span>Scontrino medio</span><span>{money(s.average)}</span></div>
      <hr />
      {Object.entries(s.by_method || {}).map(([m, v]: any) => <div key={m} className="row"><span>{v.label} ({v.count})</span><span>{money(v.amount)}</span></div>)}
      <hr />
      {(s.vat || []).map((v: any) => <div key={v.rate} className="row muted"><span>IVA {Number(v.rate)}% su {money(v.taxable)}</span><span>{money(v.vat)}</span></div>)}
      <hr />
      <div className="row"><span>Fondo cassa</span><span>{money(s.opening_float)}</span></div>
      <div className="row"><span>Versamenti</span><span>{money(s.deposits)}</span></div>
      <div className="row"><span>Prelievi</span><span>-{money(s.withdrawals)}</span></div>
      <div className="row" style={{ fontWeight: 700 }}><span>Contante atteso</span><span>{money(s.expected_cash)}</span></div>
      {closed && (
        <>
          <div className="row"><span>Contante contato</span><span>{money(ses.counted_cash)}</span></div>
          <div className="row" style={{ fontWeight: 700 }}><span>Differenza</span><span>{money(ses.difference)}</span></div>
        </>
      )}
    </div>
  )
}
