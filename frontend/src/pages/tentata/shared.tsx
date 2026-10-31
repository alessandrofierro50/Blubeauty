// Tentata vendita: chiamate API, riquadro firma (dito o penna), etichette e piccoli aiuti comuni a ufficio e app dell'agente.

import { Badge, Button, Group, Paper, Text, TextInput } from '@mantine/core'
import { IconEraser } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'

import { appApi } from '../../api'

export const TV = <T = any,>(p: string, opts?: { method?: string; body?: unknown }) => appApi<T>('/api/tentata' + p, opts)

export const STATUS_COLOR: Record<string, string> = { preparazione: 'gray', in_corso: 'blue', rientro: 'orange', chiuso: 'teal' }
export const DOC_LABEL: Record<string, string> = { DDT: 'DDT', FTI: 'Fattura', ORC: 'Ordine', NC: 'Reso / nota di credito' }
export const WEEKDAYS = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']

export const qtyFmt = (v: any) => (v === null || v === undefined || v === '' ? '—' : Number(v).toLocaleString('it-IT', { maximumFractionDigits: 3 }))

export function StatusBadge({ trip }: { trip: { status: string; status_label: string } }) {
  return <Badge color={STATUS_COLOR[trip.status] ?? 'gray'} variant="light">{trip.status_label}</Badge>
}

export type SignatureValue = { signer_name: string; signature_png: string | null; signed_at?: string }

/** Riquadro firma: si firma col dito o con la penna; restituisce un PNG (data URL) già ritagliato sullo scarabocchio. */
export function SignaturePad({ value, onChange, label = 'Firma', nameLabel = 'Nome e cognome di chi firma', height = 180, withName = true }: {
  value: SignatureValue; onChange: (v: SignatureValue) => void; label?: string; nameLabel?: string; height?: number; withName?: boolean
}) {
  const ref = useRef<HTMLCanvasElement>(null)
  const drawing = useRef(false)
  const last = useRef<{ x: number; y: number } | null>(null)
  const dirty = useRef(false)
  const [empty, setEmpty] = useState(!value.signature_png)

  useEffect(() => {
    const c = ref.current
    if (!c) return
    const ratio = window.devicePixelRatio || 1
    const w = c.clientWidth
    c.width = w * ratio
    c.height = height * ratio
    const ctx = c.getContext('2d')!
    ctx.scale(ratio, ratio)
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.strokeStyle = '#10213f'
    ctx.lineWidth = 2.4
    if (value.signature_png) {
      const img = new Image()
      img.onload = () => ctx.drawImage(img, 0, 0, w, height)
      img.src = value.signature_png
    }
  }, [height])

  const pos = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }
  const down = (e: React.PointerEvent) => {
    e.preventDefault()
    ref.current!.setPointerCapture(e.pointerId)
    drawing.current = true
    last.current = pos(e)
    const ctx = ref.current!.getContext('2d')!
    ctx.beginPath()
    ctx.arc(last.current.x, last.current.y, 1.1, 0, Math.PI * 2)
    ctx.fillStyle = '#10213f'
    ctx.fill()
  }
  const move = (e: React.PointerEvent) => {
    if (!drawing.current || !last.current) return
    const p = pos(e)
    const ctx = ref.current!.getContext('2d')!
    const pressure = e.pressure && e.pointerType === 'pen' ? 1.2 + e.pressure * 2 : 2.4
    ctx.lineWidth = pressure
    ctx.beginPath()
    ctx.moveTo(last.current.x, last.current.y)
    ctx.lineTo(p.x, p.y)
    ctx.stroke()
    last.current = p
    dirty.current = true
  }
  const up = () => {
    if (!drawing.current) return
    drawing.current = false
    last.current = null
    setEmpty(false)
    onChange({ ...value, signature_png: trimmed(ref.current!), signed_at: new Date().toISOString() })
  }
  const clear = () => {
    const c = ref.current!
    c.getContext('2d')!.clearRect(0, 0, c.width, c.height)
    setEmpty(true)
    dirty.current = false
    onChange({ ...value, signature_png: null })
  }
  return (
    <div>
      {withName && <TextInput label={nameLabel} value={value.signer_name} onChange={(e) => onChange({ ...value, signer_name: e.currentTarget.value })} mb="xs" size="md" />}
      <Group justify="space-between" mb={4}>
        <Text size="sm" fw={500}>{label}</Text>
        <Button size="compact-sm" variant="subtle" leftSection={<IconEraser size={14} />} onClick={clear} disabled={empty}>Cancella</Button>
      </Group>
      <Paper withBorder radius="md" style={{ position: 'relative', background: '#fff', touchAction: 'none' }}>
        <canvas ref={ref} style={{ width: '100%', height, display: 'block', cursor: 'crosshair', touchAction: 'none' }}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onPointerLeave={up} />
        {empty && <Text c="dimmed" size="sm" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>Firma qui con il dito</Text>}
        <div style={{ position: 'absolute', left: 16, right: 16, bottom: 28, borderBottom: '1px dashed #c5cdda', pointerEvents: 'none' }} />
      </Paper>
    </div>
  )
}

/** PNG ritagliato sull'area firmata (meno peso da inviare, firma ben centrata nella stampa). */
function trimmed(c: HTMLCanvasElement): string {
  const ctx = c.getContext('2d')!
  const { width, height } = c
  const data = ctx.getImageData(0, 0, width, height).data
  let x0 = width, y0 = height, x1 = 0, y1 = 0
  for (let y = 0; y < height; y += 2) {
    for (let x = 0; x < width; x += 2) {
      if (data[(y * width + x) * 4 + 3] > 10) {
        if (x < x0) x0 = x
        if (y < y0) y0 = y
        if (x > x1) x1 = x
        if (y > y1) y1 = y
      }
    }
  }
  if (x1 <= x0 || y1 <= y0) return c.toDataURL('image/png')
  const pad = 12
  x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad); x1 = Math.min(width, x1 + pad); y1 = Math.min(height, y1 + pad)
  const out = document.createElement('canvas')
  const scale = Math.min(1, 600 / (x1 - x0))
  out.width = Math.round((x1 - x0) * scale)
  out.height = Math.round((y1 - y0) * scale)
  out.getContext('2d')!.drawImage(c, x0, y0, x1 - x0, y1 - y0, 0, 0, out.width, out.height)
  return out.toDataURL('image/png')
}

export const emptySignature = (name = ''): SignatureValue => ({ signer_name: name, signature_png: null })
export const signatureReady = (s: SignatureValue, needName = true) => !!s.signature_png && (!needName || s.signer_name.trim().length > 1)

/** Apre il PDF firmato di un documento (serve il token: si scarica e si apre come file locale). */
export async function openPdf(docId: string) {
  const { tokens } = await import('../../api')
  const w = window.open('', '_blank')
  const res = await fetch(`/api/tentata/documenti/${docId}/pdf`, { headers: { Authorization: `Bearer ${tokens.get('user')}` } })
  if (!res.ok) { w?.close(); throw new Error('PDF non disponibile') }
  const url = URL.createObjectURL(await res.blob())
  if (w) w.location.href = url
  else window.location.href = url
}
