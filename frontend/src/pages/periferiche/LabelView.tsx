// Disegno di un'etichetta in HTML (millimetri veri): lo stesso modello che diventa ZPL per la stampante di etichette.
// Serve all'editor, all'anteprima e alla stampa su foglio A4 con una stampante normale.

import JsBarcode from 'jsbarcode'
import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'

import { appApi } from '../../api'

export const PER = (path: string, opts?: { method?: string; body?: unknown }) => appApi('/api/periferiche' + path, opts)

export type LabelEl = {
  type: 'text' | 'barcode' | 'qr' | 'box'; field?: string; text?: string; prefix?: string; x: number; y: number; w?: number; h?: number
  size?: number; lines?: number; align?: 'left' | 'center' | 'right'; bold?: boolean; module?: number; symbology?: string; thickness?: number
}
export type Template = { id?: string; name: string; width_mm: number; height_mm: number; dpi: number; gap_mm: number; elements: LabelEl[]; is_default?: boolean }

export function elementValue(el: LabelEl, fields: Record<string, string>) {
  const v = el.field === 'custom' ? el.text ?? '' : fields[el.field ?? ''] ?? ''
  return v ? `${el.prefix ?? ''}${v}` : ''
}

const eanOk = (s: string) => {
  if (!/^\d{13}$/.test(s)) return false
  const d = s.split('').map(Number)
  const c = d.pop()!
  const t = d.reduce((a, x, i) => a + x * (i % 2 ? 3 : 1), 0)
  return (10 - (t % 10)) % 10 === c
}

function Barcode({ value, el }: { value: string; el: LabelEl }) {
  const ref = useRef<SVGSVGElement>(null)
  useEffect(() => {
    if (!ref.current) return
    try {
      const ean = (el.symbology ?? 'auto') !== 'code128' && eanOk(value)
      const h = (el.h ?? 10) * 10
      JsBarcode(ref.current, value, { format: ean ? 'EAN13' : 'CODE128', displayValue: el.text !== undefined ? !!el.text : true, margin: 0,
        height: h, width: 2, fontSize: 26, textMargin: 2, flat: true })
      ref.current.setAttribute('preserveAspectRatio', 'none')
      // JsBarcode riscrive lo stile dell'SVG: le misure in millimetri si rimettono dopo
      const withText = el.text !== undefined ? !!el.text : true
      Object.assign(ref.current.style, { height: `${(el.h ?? 10) + (withText ? 2.8 : 0)}mm`, width: 'auto', maxWidth: '100%', display: 'block' })
    } catch { /* codice non rappresentabile */ }
  }, [value, el.symbology, el.text, el.h])
  // come in ZPL: l'altezza è quella delle barre, i numeri stanno sotto (circa 2,8 mm)
  const withText = el.text !== undefined ? !!el.text : true
  return <svg ref={ref} style={{ height: `${(el.h ?? 10) + (withText ? 2.8 : 0)}mm`, width: 'auto', maxWidth: '100%', display: 'block' }} />
}

function Qr({ value, el }: { value: string; el: LabelEl }) {
  const [src, setSrc] = useState('')
  useEffect(() => { QRCode.toDataURL(value, { margin: 0, width: 200 }).then(setSrc).catch(() => setSrc('')) }, [value])
  const mm = ((el.size ?? 4) * 25 * 25.4) / 203  // stessa dimensione del QR in ZPL (circa 25 moduli)
  return src ? <img src={src} alt="" style={{ width: `${mm}mm`, height: `${mm}mm`, display: 'block' }} /> : null
}

export function LabelView({ tpl, fields, selected, onSelect, onMove, scale = 1, border = true }: {
  tpl: Template; fields: Record<string, string>; selected?: number | null; onSelect?: (i: number | null) => void
  onMove?: (i: number, x: number, y: number) => void; scale?: number; border?: boolean
}) {
  const box = useRef<HTMLDivElement>(null)
  const drag = useRef<{ i: number; sx: number; sy: number; ox: number; oy: number } | null>(null)
  const pxPerMm = () => (box.current ? box.current.getBoundingClientRect().width / tpl.width_mm : 4)
  return (
    <div ref={box} onPointerDown={(e) => { if (e.target === box.current) onSelect?.(null) }}
      onPointerMove={(e) => {
        const d = drag.current
        if (!d || !onMove) return
        const k = pxPerMm()
        const nx = Math.max(0, Math.min(tpl.width_mm - 1, d.ox + (e.clientX - d.sx) / k))
        const ny = Math.max(0, Math.min(tpl.height_mm - 1, d.oy + (e.clientY - d.sy) / k))
        onMove(d.i, Math.round(nx * 2) / 2, Math.round(ny * 2) / 2)
      }}
      onPointerUp={() => { drag.current = null }}
      style={{ position: 'relative', width: `${tpl.width_mm}mm`, height: `${tpl.height_mm}mm`, background: 'white', color: 'black', overflow: 'hidden',
        outline: border ? '1px solid #ced4da' : undefined, transform: scale !== 1 ? `scale(${scale})` : undefined, transformOrigin: 'top left',
        fontFamily: 'Arial, Helvetica, sans-serif', touchAction: 'none', breakInside: 'avoid' }}>
      {tpl.elements.map((el, i) => {
        const value = elementValue(el, fields)
        const sel = selected === i
        const common: React.CSSProperties = { position: 'absolute', left: `${el.x}mm`, top: `${el.y}mm`, cursor: onMove ? 'move' : undefined,
          outline: sel ? '1px dashed #2340a8' : undefined, outlineOffset: 1 }
        const down = (e: React.PointerEvent) => {
          if (!onMove) return
          e.stopPropagation()
          ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
          onSelect?.(i)
          drag.current = { i, sx: e.clientX, sy: e.clientY, ox: el.x, oy: el.y }
        }
        if (el.type === 'box') {
          return <div key={i} onPointerDown={down} style={{ ...common, width: `${el.w ?? 10}mm`, height: `${el.h ?? 0.3}mm`,
            border: `${el.thickness ?? 0.3}mm solid black`, boxSizing: 'border-box' }} />
        }
        if (!value && !onMove) return null
        if (el.type === 'text') {
          const size = el.size ?? 3
          return (
            <div key={i} onPointerDown={down} style={{ ...common, width: `${el.w ?? tpl.width_mm - el.x}mm`, fontSize: `${size}mm`, lineHeight: 1.05,
              fontWeight: el.bold ? 700 : 400, textAlign: el.align ?? 'left', maxHeight: `${size * 1.05 * (el.lines ?? 1)}mm`, overflow: 'hidden',
              color: value ? undefined : '#adb5bd', fontStretch: 'condensed' }}>
              {value || `[${el.field}]`}
            </div>
          )
        }
        if (el.type === 'barcode') return <div key={i} onPointerDown={down} style={{ ...common, maxWidth: `${tpl.width_mm - el.x}mm` }}>{value ? <Barcode value={value} el={el} /> : <span style={{ fontSize: '2.5mm', color: '#adb5bd' }}>[codice a barre]</span>}</div>
        if (el.type === 'qr') return <div key={i} onPointerDown={down} style={common}>{value ? <Qr value={value} el={el} /> : <span style={{ fontSize: '2.5mm', color: '#adb5bd' }}>[QR]</span>}</div>
        return null
      })}
    </div>
  )
}

export const SAMPLE_FIELDS: Record<string, string> = {
  description: 'Felpa con cappuccio in cotone', code: 'ART00003', price: '€ 31,50', list_price: '€ 39,90', barcode: '8001234567897', unit: 'PZ',
  brand: 'BluBrand', category: 'Felpe', variant: 'Grigio M', plu: '123', date: new Date().toLocaleDateString('it-IT'),
}
