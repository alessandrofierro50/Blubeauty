import { Badge, Select } from '@mantine/core'
import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'

import { appApi } from '../../api'
import type { AppCtx } from '../app/AppLayout'

export const S = (path: string, opts?: { method?: string; body?: unknown }) => appApi('/api/vendite' + path, opts)

export const TITLE: Record<string, string> = {
  PRV: 'Preventivo', ORC: 'Ordine cliente', DDT: 'DDT', FTI: 'Fattura', FTD: 'Fattura differita', NC: 'Nota di credito', SCO: 'Scontrino', RSO: 'Reso al banco',
}
export const SHORT: Record<string, string> = { PRV: 'Preventivo', ORC: 'Ordine', DDT: 'DDT', FTI: 'Fattura', FTD: 'Fatt. differita', NC: 'Nota credito', SCO: 'Scontrino', RSO: 'Reso banco' }
export const TYPE_COLOR: Record<string, string> = { PRV: 'grape', ORC: 'orange', DDT: 'teal', FTI: 'blue', FTD: 'blue', NC: 'red', SCO: 'cyan', RSO: 'red' }

/** Stato con le parole giuste per ogni tipo di documento. */
export function statusLabel(d: { doc_type: string; status: string; settled?: boolean }) {
  const t = d.doc_type
  if (d.status === 'bozza') return 'bozza'
  if (d.status === 'annullato') return t === 'PRV' ? 'rifiutato/annullato' : 'annullato'
  if (t === 'PRV') return d.status === 'evaso' ? 'accettato' : 'inviato'
  if (t === 'ORC') return d.status === 'evaso' ? 'evaso' : 'aperto'
  if (t === 'DDT') return d.status === 'evaso' ? 'fatturato' : 'da fatturare'
  return d.settled ? 'incassata' : 'emessa'
}
export function StatusBadge({ d }: { d: any }) {
  const l = statusLabel(d)
  const color = d.status === 'bozza' ? 'gray' : d.status === 'annullato' ? 'red' : l === 'incassata' || d.status === 'evaso' ? 'green' : 'blue'
  return <Badge color={color} variant="dot">{l}</Badge>
}

export const docNumber = (d: any) => (d.number ? `n. ${d.number_label ?? `${d.number}${d.series ? '/' + d.series : ''}/${d.year}`}` : 'bozza')

export function useMe() {
  return useOutletContext<AppCtx>()?.me
}

/** Scelta del cliente con ricerca remota (anche migliaia di clienti). */
export function CustomerPicker({ value, label, onChange, disabled, w, required, tipo = 'clienti', placeholder, clearable }: {
  value: string | null; label?: string; onChange: (id: string | null, name?: string) => void; disabled?: boolean; w?: number | string; required?: boolean
  tipo?: 'clienti' | 'fornitori' | 'tutti'; placeholder?: string; clearable?: boolean
}) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<any[]>([])
  const [current, setCurrent] = useState<any>(null)
  useEffect(() => {
    if (value && current?.id !== value) appApi(`/api/anagrafiche/soggetti/${value}`).then(setCurrent).catch(() => {})
  }, [value])
  useEffect(() => {
    const t = setTimeout(() => appApi(`/api/anagrafiche/soggetti?tipo=${tipo}&page_size=30${q ? '&q=' + encodeURIComponent(q) : ''}`)
      .then((r) => setRows(r.rows)).catch(() => {}), 200)
    return () => clearTimeout(t)
  }, [q])
  const data = [...(current ? [{ value: current.id, label: current.name }] : []),
    ...rows.filter((r) => r.id !== current?.id).map((r) => ({ value: r.id, label: r.name + (r.city ? ` · ${r.city}` : '') }))]
  return (
    <Select label={label} placeholder={placeholder ?? (tipo === 'fornitori' ? 'Cerca fornitore' : tipo === 'tutti' ? 'Cerca cliente o fornitore' : 'Cerca cliente')} searchable data={data} value={value} w={w} required={required} clearable={clearable}
      searchValue={q} onSearchChange={setQ} filter={({ options }) => options} disabled={disabled}
      nothingFoundMessage="Nessun risultato" onChange={(v) => { const r = rows.find((x) => x.id === v); if (r) setCurrent(r); onChange(v, r?.name) }} />
  )
}
