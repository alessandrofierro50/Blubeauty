// Stampe dal browser: ricevuta non fiscale da 80 mm e tessera fedeltà formato carta di credito.
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { appApi } from '../../api'
import { Barcode, Qr, ReceiptLines } from '../pos/ReceiptLines'

export { ReceiptLines }

function PrintPage({ lines }: { lines: any[] | null }) {
  useEffect(() => { if (lines) setTimeout(() => window.print(), 400) }, [lines])
  if (!lines) return null
  return (
    <>
      <style>{'@page { size: 80mm auto; margin: 0 } @media print { body { margin: 0 } }'}</style>
      <ReceiptLines lines={lines} />
    </>
  )
}

/** Ricevuta dell'appuntamento 80 mm: stesse righe che vanno alla termica o al registratore. */
export function ReceiptPrint() {
  const { id } = useParams()
  const [lines, setLines] = useState<any[] | null>(null)
  useEffect(() => { appApi(`/api/agenda/appuntamenti/${id}/ricevuta`).then((r) => setLines(r.lines)) }, [id])
  return <PrintPage lines={lines} />
}

/** Ricevuta di uno scontrino della cassa (copia di cortesia o ricevuta non fiscale) stampata dal computer. */
export function SaleReceiptPrint() {
  const { id } = useParams()
  const [lines, setLines] = useState<any[] | null>(null)
  useEffect(() => { appApi(`/api/pos/scontrini/${id}/ricevuta`).then((r) => setLines(r.lines)) }, [id])
  return <PrintPage lines={lines} />
}

/** Tessera fedeltà (85,6 × 54 mm) da stampare su cartoncino o da mostrare sul telefono. */
export function CardPrint() {
  const { id } = useParams()
  const [c, setC] = useState<any>(null)
  useEffect(() => { appApi(`/api/marketing/fidelity/clienti/${id}/tessera`, { body: {} }).then(setC) }, [id])
  useEffect(() => { if (c) setTimeout(() => window.print(), 400) }, [c])
  if (!c) return null
  return (
    <div style={{ padding: 20 }}>
      <style>{'@page { size: 85.6mm 54mm; margin: 0 } @media print { body { margin: 0 } .card { box-shadow: none !important; margin: 0 !important } }'}</style>
      <div className="card" style={{ width: '85.6mm', height: '54mm', borderRadius: '3mm', background: 'linear-gradient(140deg,#2340a8,#0b2147)', color: '#fff',
        padding: '4mm 5mm', boxSizing: 'border-box', fontFamily: "'Source Sans 3', sans-serif", display: 'flex', flexDirection: 'column', justifyContent: 'space-between', boxShadow: '0 8px 30px rgba(0,0,0,.2)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <b style={{ fontFamily: 'Archivo, sans-serif', fontSize: 15 }}>{c.salon}</b>
          <span style={{ background: '#ffc83d', color: '#0b2147', borderRadius: 20, padding: '1px 8px', fontSize: 10, fontWeight: 700 }}>CARTA FEDELTÀ</span>
        </div>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{c.name}</div>
        <div style={{ background: '#fff', borderRadius: '2mm', padding: '1.5mm 3mm', textAlign: 'center', color: '#0b2147' }}>
          <Barcode value={c.number} height={28} />
          <div style={{ fontSize: 10, letterSpacing: 2 }}>{c.number}</div>
        </div>
      </div>
    </div>
  )
}

/** Biglietto del buono regalo (A6, da stampare su cartoncino) con QR che apre il buono sul telefono; in alternativa 80 mm. */
export function VoucherPrint() {
  const { id } = useParams()
  const [v, setV] = useState<any>(null)
  const [co, setCo] = useState<any>(null)
  const [lines, setLines] = useState<any[] | null>(null)
  const thermal = new URLSearchParams(window.location.search).get('formato') === '80mm'
  useEffect(() => {
    appApi(`/api/prepagati/buoni/${id}`).then(setV)
    appApi('/api/agenda/impostazioni').then(setCo).catch(() => {})
    if (thermal) appApi(`/api/prepagati/buoni/${id}/stampa`).then((r) => setLines(r.lines))
  }, [id])
  useEffect(() => { if (v && (!thermal || lines)) setTimeout(() => window.print(), 600) }, [v, lines])
  if (!v) return null
  if (thermal) return lines ? <><style>{'@page { size: 80mm auto; margin: 0 }'}</style><ReceiptLines lines={lines} /></> : null
  const eur = (x: string) => Number(x).toLocaleString('it-IT', { style: 'currency', currency: 'EUR' })
  return (
    <div style={{ padding: 20, fontFamily: "'Source Sans 3', sans-serif" }}>
      <style>{'@page { size: 148mm 105mm; margin: 0 } @media print { body { margin: 0 } .card { box-shadow: none !important; margin: 0 !important } .noprint { display: none } }'}</style>
      <div className="noprint" style={{ marginBottom: 12 }}><a href="?formato=80mm">Stampa invece su rotolo da 80 mm</a></div>
      <div className="card" style={{ width: '148mm', height: '105mm', boxSizing: 'border-box', borderRadius: '4mm', overflow: 'hidden', display: 'flex',
        boxShadow: '0 10px 40px rgba(0,0,0,.25)', background: '#fff' }}>
        <div style={{ width: '58%', padding: '9mm 8mm', background: 'linear-gradient(150deg,#0b2147,#2340a8)', color: '#fff', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 13, letterSpacing: 3, textTransform: 'uppercase', color: '#6ec1e4' }}>Buono regalo</div>
            <div style={{ fontFamily: 'Archivo, sans-serif', fontWeight: 800, fontSize: 24, marginTop: 4 }}>{co?.display_name ?? ''}</div>
          </div>
          <div>
            {v.beneficiary_name && <div style={{ fontSize: 16, opacity: 0.85 }}>Per {v.beneficiary_name}</div>}
            <div style={{ fontFamily: 'Archivo, sans-serif', fontWeight: 800, fontSize: v.service ? 26 : 44, lineHeight: 1.05 }}>{v.service ?? eur(v.initial_amount)}</div>
            {v.message && <div style={{ fontStyle: 'italic', marginTop: 8, fontSize: 14 }}>«{v.message}»</div>}
          </div>
          <div style={{ height: 3, width: 46, background: '#f2b413' }} />
        </div>
        <div style={{ flex: 1, padding: '8mm 6mm', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'space-between', color: '#0b2147', textAlign: 'center' }}>
          <Qr value={v.public_url} />
          <div>
            <div style={{ fontSize: 11, color: '#5b6578' }}>Codice</div>
            <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 17, letterSpacing: 1 }}>{v.code}</div>
          </div>
          <div style={{ fontSize: 11, color: '#5b6578', lineHeight: 1.35 }}>
            {v.expires_on ? <>Valido fino al {new Date(v.expires_on + 'T12:00').toLocaleDateString('it-IT')}<br /></> : null}
            Utilizzabile anche in più volte.<br />Non convertibile in denaro.
          </div>
        </div>
      </div>
    </div>
  )
}
