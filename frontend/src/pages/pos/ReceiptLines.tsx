// Righe di una ricevuta (formato neutro dell'agent) disegnate come lo scontrino, per la stampa dal computer e le anteprime.
import JsBarcode from 'jsbarcode'
import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'

export function Barcode({ value, height = 40 }: { value: string; height?: number }) {
  const ref = useRef<SVGSVGElement>(null)
  useEffect(() => { if (ref.current) JsBarcode(ref.current, value, { format: 'CODE128', height, displayValue: false, margin: 0 }) }, [value])
  return <svg ref={ref} style={{ maxWidth: '100%' }} />
}

export function Qr({ value }: { value: string }) {
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
