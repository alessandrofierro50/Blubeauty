import { Button } from '@mantine/core'
import { IconPrinter } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro } from '../../api'
import { Loading, notifyError } from '../../components'
import { PrintFooter, PrintHeader } from '../app/CompanySettings'
import { S, TITLE } from './shared'

const n = (v: any) => Number(v).toLocaleString('it-IT', { maximumFractionDigits: 3 })

export default function SalesPrint() {
  const { id } = useParams()
  const [p, setP] = useState<any>(null)
  const [c, setC] = useState<any>(null)
  useEffect(() => {
    Promise.all([S(`/documenti/${id}/stampa`), appApi('/api/app/intestazione')]).then(([a, b]) => { setP(a); setC(b) }).catch(notifyError)
  }, [id])
  useEffect(() => { if (p) document.title = `${TITLE[p.document.doc_type]} ${p.document.number_label ?? 'bozza'} – ${p.party.name}` }, [p])
  if (!p || !c) return <Loading />
  const d = p.document
  const t = d.doc_type
  const po = d.print_options ?? {}
  const prices = t !== 'DDT' || po.show_prices
  const color = c.print_settings?.primary_color || '#2340a8'
  const party = p.party
  const addr = (x: any) => [x.address && `${x.address}${x.street_number ? ' ' + x.street_number : ''}`, [x.zip_code, x.city, x.province && `(${x.province})`].filter(Boolean).join(' '), x.country && x.country !== 'IT' ? x.country : ''].filter(Boolean)
  const tr = d.transport ?? {}
  const css = `
    @page { size: A4; margin: 12mm 12mm 14mm; }
    body { background: #fff !important; }
    .sp { font-family: Inter, Arial, sans-serif; color: #1b2b45; max-width: 190mm; margin: 0 auto; padding: 16px; font-size: 12px; }
    .sp .boxes { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
    .sp .box { border: 1px solid #dfe5ef; border-radius: 6px; padding: 8px 10px; line-height: 1.45; }
    .sp .lbl { font-size: 9px; text-transform: uppercase; letter-spacing: .04em; color: #4a5b75; font-weight: 700; margin-bottom: 2px; }
    .sp .meta { display: flex; flex-wrap: wrap; gap: 4px 18px; margin-bottom: 10px; font-size: 11px; }
    .sp table.lines { width: 100%; border-collapse: collapse; }
    .sp table.lines th { background: ${color}; color: #fff; font-size: 10px; text-align: left; padding: 5px 6px; font-weight: 700; }
    .sp table.lines td { padding: 5px 6px; border-bottom: 1px solid #eef1f6; vertical-align: top; }
    .sp .r, .sp table.lines th.r { text-align: right; white-space: nowrap; }
    .sp .c, .sp table.lines th.c { text-align: center; }
    .sp .code { font-family: monospace; font-size: 10px; color: #4a5b75; }
    .sp .long { font-size: 10.5px; color: #4a5a72; white-space: pre-line; margin-top: 3px; }
    .sp .thumb { width: 54px; height: 54px; object-fit: contain; border-radius: 4px; background: #f4f6fa; }
    .sp tr { break-inside: avoid; }
    .sp .tot { margin-left: auto; width: 270px; margin-top: 10px; }
    .sp .tot div { display: flex; justify-content: space-between; padding: 2px 0; }
    .sp .grand { border-top: 2px solid ${color}; margin-top: 4px; padding-top: 5px !important; font-size: 15px; font-weight: 800; }
    .sp .sign { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 26px; font-size: 10px; color: #4a5b75; }
    .sp .sign div { border-top: 1px solid #b8c2d3; padding-top: 4px; text-align: center; }
    .sp .att a { color: ${color}; }
    @media print { .noprint { display: none; } }
  `
  const subtitle = [d.number ? `n. ${d.number_label} del ${fmtDate(d.doc_date)}` : `del ${fmtDate(d.doc_date)}`, t === 'PRV' && d.valid_until ? `valido fino al ${fmtDate(d.valid_until)}` : ''].filter(Boolean).join(' · ')
  return (
    <div className="sp">
      <style>{css}</style>
      <div className="noprint" style={{ textAlign: 'right', marginBottom: 8 }}><Button size="xs" leftSection={<IconPrinter size={14} />} onClick={() => window.print()}>Stampa / Salva PDF</Button></div>
      <PrintHeader c={c} title={`${TITLE[t]}${d.status === 'bozza' ? ' (bozza)' : ''}`} subtitle={subtitle} />
      <div className="boxes">
        <div className="box">
          <div className="lbl">{t === 'DDT' ? 'Destinatario' : 'Spett.le'}</div>
          <div style={{ fontWeight: 700, fontSize: 13 }}>{party.name}</div>
          {addr(party).map((l: string) => <div key={l}>{l}</div>)}
          {(party.vat_number || party.tax_code) && <div>{party.vat_number ? `P.IVA ${party.vat_number}` : ''}{party.tax_code && party.tax_code !== party.vat_number ? ` · C.F. ${party.tax_code}` : ''}</div>}
          {['FTI', 'FTD', 'NC'].includes(t) && (party.sdi_code || party.pec) && <div>{party.sdi_code ? `Cod. destinatario ${party.sdi_code}` : `PEC ${party.pec}`}</div>}
        </div>
        <div className="box">
          <div className="lbl">{p.destination ? 'Luogo di consegna' : 'Condizioni'}</div>
          {p.destination && <><div style={{ fontWeight: 600 }}>{p.destination.label}</div>{addr(p.destination).map((l: string) => <div key={l}>{l}</div>)}</>}
          {p.payment_term && <div style={{ marginTop: p.destination ? 4 : 0 }}><b>Pagamento:</b> {p.payment_term}</div>}
          {d.reference && <div><b>Riferimento:</b> {d.reference}</div>}
          {p.origins?.length > 0 && <div><b>Rif. nostri documenti:</b> {p.origins.map((o: any) => `${o.label} n. ${o.number_label} del ${fmtDate(o.date)}`).join(' · ')}</div>}
          {!p.destination && !p.payment_term && !d.reference && !p.origins?.length && <div style={{ color: '#4a5b75' }}>—</div>}
        </div>
      </div>
      {(t === 'DDT' || (t === 'FTI' && d.moves_stock)) && (
        <div className="meta">
          {tr.causale && <span><b>Causale:</b> {tr.causale}</span>}
          {tr.a_cura && <span><b>Trasporto a cura del:</b> {tr.a_cura}</span>}
          {tr.vettore && <span><b>Vettore:</b> {tr.vettore}</span>}
          {tr.porto && <span><b>Porto:</b> {tr.porto}</span>}
          {tr.aspetto && <span><b>Aspetto beni:</b> {tr.aspetto}</span>}
          {tr.colli && <span><b>Colli:</b> {tr.colli}</span>}
          {tr.peso && <span><b>Peso:</b> {n(tr.peso)} kg</span>}
          {tr.inizio && <span><b>Inizio trasporto:</b> {new Date(tr.inizio).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</span>}
        </div>
      )}
      <table className="lines">
        <thead><tr>
          {po.images && <th style={{ width: 60 }} />}
          <th>Descrizione</th><th className="r" style={{ width: '11%' }}>Q.tà</th>
          {prices && <><th className="r" style={{ width: '13%' }}>Prezzo</th><th className="r" style={{ width: '10%' }}>Sconti</th><th className="r" style={{ width: '14%' }}>Importo</th><th className="c" style={{ width: '8%' }}>IVA</th></>}
        </tr></thead>
        <tbody>
          {d.lines.map((l: any) => {
            const ex = l.item_id ? p.items[l.item_id] : null
            const text = !l.item_id && !Number(l.quantity)
            const disc = [l.discount1, l.discount2, l.discount3].filter((x: any) => x && Number(x)).map((x: any) => n(x) + '%').join('+')
            return (
              <tr key={l.id}>
                {po.images && <td>{ex?.image && <img className="thumb" src={ex.image} alt="" />}</td>}
                <td colSpan={text ? (prices ? 6 : 2) : 1}>
                  {l.item_code && <div className="code">{l.item_code}{l.variant_code ? ` · ${l.variant_code}` : ''}</div>}
                  <div style={{ fontWeight: text ? 700 : 500 }}>{l.description}</div>
                  {po.long_descriptions && ex?.long_description && <div className="long">{ex.long_description}</div>}
                  {l.lot_number && <div className="code">Lotto {l.lot_number}</div>}
                  {l.serials?.length > 0 && <div className="code">Matricole {l.serials.join(', ')}</div>}
                </td>
                {!text && <td className="r">{n(l.quantity)} {l.unit ?? ''}</td>}
                {!text && prices && <><td className="r">{fmtEuro(l.unit_price)}</td><td className="r">{disc}</td><td className="r" style={{ fontWeight: 600 }}>{fmtEuro(l.line_total)}</td><td className="c">{l.vat_nature ?? n(l.vat_rate) + '%'}</td></>}
              </tr>
            )
          })}
        </tbody>
      </table>
      {prices && (
        <div className="tot">
          <div><span>Imponibile</span><b>{fmtEuro(d.taxable_total)}</b></div>
          {d.vat_summary.map((v: any) => <div key={v.rate + (v.nature ?? '')}><span>{v.nature ? `Esente ${v.nature}` : `IVA ${n(v.rate)}%`} su {fmtEuro(v.taxable)}</span><span>{fmtEuro(v.vat)}</span></div>)}
          {Number(d.stamp_duty) > 0 && (Math.abs(Number(d.total) - Number(d.taxable_total) - Number(d.vat_total) - Number(d.stamp_duty)) < 0.005
            ? <div><span>Imposta di bollo</span><span>{fmtEuro(d.stamp_duty)}</span></div>
            : <div><span>Imposta di bollo (a nostro carico)</span><span>{fmtEuro(d.stamp_duty)}</span></div>)}
          <div className="grand"><span>Totale {t === 'NC' ? 'nota di credito' : 'documento'}</span><span>{fmtEuro(d.total)}</span></div>
        </div>
      )}
      {prices && Number(d.stamp_duty) > 0 && <div style={{ fontSize: 10, color: '#4a5b75', marginTop: 6, textAlign: 'right' }}>Imposta di bollo assolta in modo virtuale ai sensi del D.M. 17/06/2014</div>}
      {d.notes && <div className="box" style={{ marginTop: 12, whiteSpace: 'pre-line' }}><div className="lbl">Note</div>{d.notes}</div>}
      {p.attachments.length > 0 && (
        <div className="box att" style={{ marginTop: 10 }}>
          <div className="lbl">Allegati</div>
          {p.attachments.map((a: any) => <div key={a.id}><a href={a.url} target="_blank" rel="noreferrer">{a.title}</a></div>)}
        </div>
      )}
      {d.delivery?.signature_url ? (
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginTop: 18, border: '1px solid #dfe5ef', borderRadius: 6, padding: '8px 10px', breakInside: 'avoid' }}>
          <div style={{ flex: 1, fontSize: 11, lineHeight: 1.5 }}>
            <div className="lbl">{t === 'NC' ? 'Merce resa da' : 'Ricevuto da'}</div>
            <b>{d.delivery.signer_name}</b>{d.delivery.signed_at && <> · {new Date(d.delivery.signed_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</>}
            {d.delivery.lat && <div style={{ color: '#4a5b75' }}>Posizione {Number(d.delivery.lat).toFixed(5)}, {Number(d.delivery.lon).toFixed(5)}</div>}
          </div>
          <img src={d.delivery.signature_url} alt="Firma del cliente" style={{ height: 70, maxWidth: 260, objectFit: 'contain' }} />
        </div>
      ) : t === 'DDT' && <div className="sign"><div>Firma del conducente</div><div>Firma del vettore</div><div>Firma del destinatario</div></div>}
      {t === 'PRV' && <div className="sign"><div style={{ visibility: 'hidden' }}>.</div><div style={{ visibility: 'hidden' }}>.</div><div>Timbro e firma per accettazione</div></div>}
      <PrintFooter c={c} />
    </div>
  )
}
