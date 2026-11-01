// Stampe dal browser: ricevuta non fiscale da 80 mm e tessera fedeltà formato carta di credito.
import JsBarcode from 'jsbarcode'
import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

import { appApi } from '../../api'

function Barcode({ value, height = 40 }: { value: string; height?: number }) {
  const ref = useRef<SVGSVGElement>(null)
  useEffect(() => { if (ref.current) JsBarcode(ref.current, value, { format: 'CODE128', height, displayValue: false, margin: 0 }) }, [value])
  return <svg ref={ref} style={{ maxWidth: '100%' }} />
}

function Qr({ value }: { value: string }) {
  const [src, setSrc] = useState('')
  useEffect(() => { QRCode.toDataURL(value, { margin: 0, width: 140 }).then(setSrc) }, [value])
  return src ? <img src={src} width={110} height={110} alt="" /> : null
}

/** Righe di una ricevuta (formato neutro dell'agent) disegnate come lo scontrino: carattere a spaziatura fissa,
 *  colonne a destra, logo in alto. Le usano la stampa dal computer e l'anteprima delle impostazioni «Ricevute». */
export function ReceiptLines({ lines, width = '72mm' }: { lines: any[]; width?: string }) {
  return (
    <div style={{ width, margin: '0 auto', fontFamily: "'DejaVu Sans Mono', 'Consolas', 'Courier New', monospace", fontSize: 12, lineHeight: 1.35, color: '#000', padding: '4mm 0' }}>
      {lines.map((ln, i) => {
        const t = ln.type ?? 'text'
        if (t === 'cut') return null
        if (t === 'feed') return <div key={i} style={{ height: 8 }} />
        if (t === 'line') return <div key={i} style={{ borderTop: '1px dashed #000', margin: '5px 0' }} />
        if (t === 'image') return ln.logo_url ? <div key={i} style={{ textAlign: 'center', marginBottom: 6 }}><img src={ln.logo_url} alt="" style={{ maxWidth: '100%', maxHeight: 90, objectFit: 'contain', filter: 'grayscale(1)' }} /></div> : null
        if (t === 'barcode') return <div key={i} style={{ textAlign: 'center' }}><Barcode value={ln.data} /><div style={{ fontSize: 11 }}>{ln.label ?? ln.data}</div></div>
        if (t === 'qr') return <div key={i} style={{ textAlign: 'center' }}><Qr value={ln.data} /></div>
        return (
          <div key={i} style={{ display: 'flex', gap: 8, justifyContent: ln.right ? 'space-between' : ln.align === 'center' ? 'center' : ln.align === 'right' ? 'flex-end' : 'flex-start',
            fontWeight: ln.bold ? 700 : 400, fontSize: ln.size >= 2 ? 17 : 12, textAlign: ln.align ?? 'left' }}>
            <span style={{ whiteSpace: 'pre-wrap' }}>{ln.text}</span>{ln.right && <span style={{ whiteSpace: 'pre', flexShrink: 0 }}>{ln.right}</span>}
          </div>
        )
      })}
    </div>
  )
}

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
