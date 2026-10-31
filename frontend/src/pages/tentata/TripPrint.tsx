// Stampe del giro: documento di carico (accompagna la merce), foglio di conta (alla cieca: senza quantità attese),
// documento di rientro con atteso, contato, differenze motivate, quadratura di cassa e firme di agente e magazziniere.

import { Button } from '@mantine/core'
import { IconPrinter } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro } from '../../api'
import { Loading, notifyError } from '../../components'
import { PrintFooter, PrintHeader } from '../app/CompanySettings'
import { TV, qtyFmt } from './shared'

const TITLES: Record<string, string> = { carico: 'Documento di carico del furgone', merce: 'Merce rimasta sul mezzo al rientro', conta: 'Foglio di conta al rientro', rientro: 'Documento di rientro del furgone' }

export default function TripPrint() {
  const { id, kind = 'carico' } = useParams()
  const [data, setData] = useState<any>(null)
  useEffect(() => {
    const sheet = kind === 'carico' ? TV(`/giri/${id}/carico`) : TV(`/giri/${id}/rientro`)
    Promise.all([TV(`/giri/${id}`), sheet, appApi('/api/app/intestazione')]).then(([t, s, c]) => setData({ t, s, c })).catch(notifyError)
  }, [id, kind])
  useEffect(() => { if (data) document.title = `${TITLES[kind]} ${data.t.van} ${fmtDate(data.t.trip_date)}` }, [data])
  if (!data) return <Loading />
  const { t, s, c } = data
  const color = c.print_settings?.primary_color || '#2340a8'
  const blind = kind === 'conta'
  const rows = kind === 'carico' ? s.lines : s.rows
  const css = `
    @page { size: A4; margin: 12mm 12mm 14mm; }
    body { background: #fff !important; }
    .tp { font-family: Inter, Arial, sans-serif; color: #1b2b45; max-width: 190mm; margin: 0 auto; padding: 16px; font-size: 12px; }
    .tp .boxes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 12px; }
    .tp .box { border: 1px solid #dfe5ef; border-radius: 6px; padding: 8px 10px; line-height: 1.45; }
    .tp .lbl { font-size: 9px; text-transform: uppercase; letter-spacing: .04em; color: #4a5b75; font-weight: 700; margin-bottom: 2px; }
    .tp table { width: 100%; border-collapse: collapse; }
    .tp th { background: ${color}; color: #fff; font-size: 10px; text-align: left; padding: 5px 6px; }
    .tp td { padding: 6px; border-bottom: 1px solid #eef1f6; vertical-align: top; }
    .tp .r, .tp th.r { text-align: right; white-space: nowrap; }
    .tp .write { border-bottom: 1px solid #8a96a8; min-width: 70px; height: 18px; }
    .tp .diff { background: #fff4e6; }
    .tp tr { break-inside: avoid; }
    .tp .signs { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 28px; break-inside: avoid; }
    .tp .sig { border-top: 1px solid #b8c2d3; padding-top: 4px; font-size: 10px; color: #4a5b75; text-align: center; min-height: 80px; }
    .tp .sig img { height: 60px; max-width: 100%; object-fit: contain; display: block; margin: 0 auto 4px; }
    @media print { .noprint { display: none; } }
  `
  const sub = `${t.van} · ${t.weekday} ${fmtDate(t.trip_date)} · agente ${t.agent ?? '—'}`
  return (
    <div className="tp">
      <style>{css}</style>
      <div className="noprint" style={{ textAlign: 'right', marginBottom: 8 }}><Button size="xs" leftSection={<IconPrinter size={14} />} onClick={() => window.print()}>Stampa / Salva PDF</Button></div>
      <PrintHeader c={c} title={TITLES[kind]} subtitle={sub} />
      <div className="boxes">
        <div className="box"><div className="lbl">Furgone</div>{t.van}<br />Sezionale documenti /{t.series}</div>
        <div className="box"><div className="lbl">Agente</div>{t.agent ?? '—'}<br />{t.km_start != null && `Km partenza ${t.km_start}`}{t.km_end != null && ` · rientro ${t.km_end}`}</div>
        <div className="box"><div className="lbl">{kind === 'carico' ? 'Carico' : 'Rientro'}</div>
          {kind === 'carico' ? `${t.loads} operazioni di carico` : t.returned_at ? `Rientrato ${new Date(t.returned_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}` : 'Non ancora rientrato'}
          {kind === 'rientro' && t.checked_at && <><br />Verificato da {t.checked_by}</>}</div>
      </div>
      {kind === 'merce' && <p style={{ fontSize: 11, color: '#4a5a72' }}>Merce che secondo i documenti del giro deve trovarsi sul furgone (carico − venduto + resi). La verifica del magazziniere conferma o rettifica le quantità.</p>}
      {blind && <p style={{ fontSize: 11, color: '#4a5a72' }}>Conta la merce presente sul furgone e scrivi la quantità. Le quantità attese non sono indicate di proposito: le differenze si vedono alla conferma in BluBeauty.</p>}
      <table>
        <thead><tr><th>Codice</th><th>Articolo</th><th>Lotto</th>
          {kind === 'carico' && <th className="r">Quantità caricata</th>}
          {kind === 'merce' && <><th className="r">Quantità a bordo</th><th className="r" style={{ width: 90 }}>Verifica</th></>}
          {blind && <th className="r" style={{ width: 110 }}>Quantità contata</th>}
          {kind === 'rientro' && <><th className="r">Atteso</th><th className="r">Contato</th><th className="r">Diff.</th><th>Motivo</th></>}
        </tr></thead>
        <tbody>
          {rows.map((r: any, i: number) => (
            <tr key={i} className={kind === 'rientro' && Number(r.difference) ? 'diff' : ''}>
              <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{r.code}</td>
              <td>{r.description}{r.variant && ` · ${r.variant}`}</td>
              <td>{r.lot_number ?? ''}{r.expiry_date && <span style={{ color: '#4a5b75' }}> scad. {fmtDate(r.expiry_date)}</span>}</td>
              {kind === 'carico' && <td className="r">{qtyFmt(r.quantity)} {r.unit}</td>}
              {kind === 'merce' && <><td className="r">{qtyFmt(r.expected)} {r.unit}</td><td className="r"><div className="write" /></td></>}
              {blind && <td className="r"><div className="write" /></td>}
              {kind === 'rientro' && <>
                <td className="r">{qtyFmt(r.expected)}</td><td className="r">{qtyFmt(r.counted)}</td>
                <td className="r" style={{ fontWeight: Number(r.difference) ? 700 : 400 }}>{Number(r.difference) > 0 ? '+' : ''}{qtyFmt(r.difference)}</td>
                <td>{r.reason_label ?? ''}{r.notes && <div style={{ fontSize: 10, color: '#4a5b75' }}>{r.notes}</div>}</td>
              </>}
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={7} style={{ textAlign: 'center', color: '#4a5b75', padding: 16 }}>Nessuna merce</td></tr>}
          {blind && [0, 1, 2].map((n) => <tr key={'e' + n}><td /><td><div className="write" /></td><td /><td className="r"><div className="write" /></td></tr>)}
        </tbody>
      </table>
      {kind === 'rientro' && (
        <>
          <p style={{ marginTop: 10 }}>{t.remaining === 'resta' ? 'La merce contata resta sul furgone per il giro successivo.' : 'La merce contata è rientrata in magazzino.'}</p>
          {t.summary.cash.length > 0 && (
            <>
              <div className="lbl" style={{ marginTop: 14 }}>Quadratura di cassa</div>
              <table>
                <thead><tr><th>Metodo</th><th className="r">Incassato</th><th className="r">Consegnato</th><th className="r">Differenza</th></tr></thead>
                <tbody>{t.summary.cash.map((x: any) => <tr key={x.method}><td>{x.label}</td><td className="r">{fmtEuro(x.collected)}</td>
                  <td className="r">{x.declared !== null ? fmtEuro(x.declared) : '—'}</td><td className="r">{x.difference !== null ? fmtEuro(x.difference) : ''}</td></tr>)}</tbody>
              </table>
            </>
          )}
        </>
      )}
      <div className="signs">
        {kind === 'carico' ? <>
          <div className="sig">Il magazziniere</div><div className="sig">L'agente (per ricevuta della merce)</div>
        </> : kind === 'merce' ? <>
          <div className="sig">{t.signatures?.agente?.url && <img src={t.signatures.agente.url} alt="" />}L'agente{t.signatures?.agente?.signer_name ? ` · ${t.signatures.agente.signer_name}` : ''}</div>
          <div className="sig">Il magazziniere (merce verificata)</div>
        </> : <>
          <div className="sig">{t.signatures?.agente?.url && <img src={t.signatures.agente.url} alt="" />}L'agente{t.signatures?.agente?.signer_name ? ` · ${t.signatures.agente.signer_name}` : ''}</div>
          <div className="sig">{t.signatures?.magazziniere?.url && <img src={t.signatures.magazziniere.url} alt="" />}Il magazziniere{t.signatures?.magazziniere?.signer_name ? ` · ${t.signatures.magazziniere.signer_name}` : ''}</div>
        </>}
      </div>
      <PrintFooter c={c} />
    </div>
  )
}
