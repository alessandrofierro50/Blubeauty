// Vendita al banco: chiamate, calcoli in centesimi (come il server) e coda offline degli scontrini.

import { appApi } from '../../api'
import type { PPromo } from './promos'

export const P = (path: string, opts?: { method?: string; body?: unknown }) => appApi('/api/pos' + path, opts)

export const METHODS: { value: string; label: string; short: string }[] = [
  { value: 'contanti', label: 'Contanti', short: 'Contanti' },
  { value: 'carta', label: 'Carta di credito', short: 'Carta' },
  { value: 'bancomat', label: 'Bancomat', short: 'Bancomat' },
  { value: 'satispay', label: 'Satispay', short: 'Satispay' },
  { value: 'buono_pasto', label: 'Buoni pasto', short: 'Buoni pasto' },
  { value: 'buono', label: 'Buono / gift card', short: 'Buono' },
  { value: 'altro', label: 'Altro', short: 'Altro' },
]
export const methodLabel = (m: string) => METHODS.find((x) => x.value === m)?.label ?? m

export type CatItem = {
  id: string; code: string; description: string; unit: string; plu: string | null; price: string | null; list_price: string | null
  promo: string | null; vat_rate: string; vat_rate_id: string | null; department_id: string | null; sold_by_weight: boolean
  has_variants: boolean; variants: { id: string; code: string; label: string; price: string | null }[]
  barcodes: { code: string; variant_id: string | null; quantity: string }[]; lot_managed: boolean; serial_managed: boolean
  stock_managed: boolean; image: string | null; categories?: string[]
}
export type Dept = { id: string; code: string; name: string; vat_rate: string; vat_rate_id: string | null; color: string | null; rt_department?: number | null }
export type Catalog = { generated_at: string; items: CatItem[]; departments: Dept[]; settings: any; price_list: string | null; promotions?: PPromo[]; vat_rates?: { id: string; rate: string }[] }

export type CartLine = {
  key: string; item_id?: string; variant_id?: string; department_id?: string; description: string; detail?: string
  quantity: number; price: number /* IVA inclusa, in euro */; discount?: number; vat_rate: string; unit?: string
  promo?: string | null; lot_number?: string; serials?: string[]; origin_line_id?: string
}

// ----------------------------------------------------------------- calcoli (centesimi interi, arrotondamento commerciale)

const roundHalfUp = (x: number) => Math.sign(x) * Math.round(Math.abs(x) + 1e-9)

/** Importo della riga in centesimi: prezzo scontato a 4 decimali × quantità, come documenti/service.gross_amount. */
export function lineCents(l: { price: number; quantity: number; discount?: number }) {
  const p4 = roundHalfUp(l.price * 10000 * (100 - (l.discount || 0)) / 100)
  const qMilli = roundHalfUp(l.quantity * 1000)
  return roundHalfUp((p4 * qMilli) / 1e5)
}
export const cartCents = (lines: CartLine[]) => lines.reduce((a, l) => a + lineCents(l), 0)
export const euro = (cents: number) => (cents / 100).toLocaleString('it-IT', { style: 'currency', currency: 'EUR' })
export const toCents = (v: string | number | null | undefined) => roundHalfUp(Number(String(v ?? '0').replace(',', '.')) * 100)
export const centsStr = (c: number) => (c / 100).toFixed(2)
export const qtyFmt = (q: number) => q.toLocaleString('it-IT', { maximumFractionDigits: 3 })
export const parseNum = (s: string) => {
  const n = Number(s.trim().replace(',', '.'))
  return Number.isFinite(n) ? n : NaN
}
/** Importo digitato: "2,50" o "2.50" sono euro; in modalità supermercato un intero sono centesimi ("250" = 2,50 €). */
export function parseAmount(s: string, centsMode: boolean) {
  const t = s.trim()
  if (!t) return NaN
  if (centsMode && /^\d+$/.test(t)) return Number(t) / 100
  return Number(t.replace(',', '.'))
}

// ----------------------------------------------------------------- codici (anche della bilancia), risolti in locale

export type Resolved = { item: CatItem; variant_id?: string; quantity?: number; amount?: number }

export function buildIndex(cat: Catalog) {
  const byCode = new Map<string, Resolved>()
  for (const it of cat.items) {
    byCode.set(it.code.toUpperCase(), { item: it })
    if (it.plu) byCode.set('PLU:' + it.plu, { item: it })
    for (const b of it.barcodes) byCode.set(b.code, { item: it, variant_id: b.variant_id ?? undefined, quantity: Number(b.quantity) || 1 })
    for (const v of it.variants) byCode.set(v.code.toUpperCase(), { item: it, variant_id: v.id })
  }
  return byCode
}

export function resolveLocal(index: Map<string, Resolved>, settings: any, raw: string): Resolved | null {
  const code = raw.trim()
  const hit = index.get(code) ?? index.get(code.toUpperCase()) ?? index.get('PLU:' + code)
  if (hit) return hit
  const sc = settings?.scale_barcode
  if (sc?.enabled && /^\d{13}$/.test(code) && (sc.prefixes || []).some((p: string) => code.startsWith(p))) {
    const pd = Number(sc.plu_digits || 5), vd = Number(sc.value_digits || 5)
    const plu = code.slice(2, 2 + pd).replace(/^0+/, '') || '0'
    const val = Number(code.slice(2 + pd, 2 + pd + vd))
    const it = index.get('PLU:' + plu) ?? index.get('PLU:' + plu.padStart(5, '0'))
    if (!it) return null
    return sc.value === 'prezzo' ? { item: it.item, amount: val / 100 } : { item: it.item, quantity: val / 1000 }
  }
  return null
}

// ----------------------------------------------------------------- memoria locale (catalogo e scontrini da inviare)

function ls() { try { return window.localStorage } catch { return null } }
export const local = {
  get<T>(k: string, d: T): T { try { const v = ls()?.getItem(k); return v ? JSON.parse(v) as T : d } catch { return d } },
  set(k: string, v: unknown) { try { ls()?.setItem(k, JSON.stringify(v)) } catch { /* memoria piena o non disponibile */ } },
}
export const outboxKey = (reg: string) => `blubeauty_pos_outbox_${reg}`
export const catalogKey = (reg: string) => `blubeauty_pos_catalog_${reg}`

export type Pending = { kind: 'vendita' | 'reso'; body: any; total: number; at: string; error?: string }

export function uuid4() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

export const isNetworkError = (e: any) => !e?.status || e.status >= 500

// ----------------------------------------------------------------- registratore telematico tramite l'agent locale (senza internet)

export type Periph = { devices: Record<string, any>; local_port: number } | null

/** Stesso documento che il server prepara per il registratore (periferiche/service.py receipt_payload), costruito dalla cassa. */
export function rtPayload(cat: Catalog, lines: CartLine[], promos: { description: string; vat_rate_id: string | null; amount_cents: number }[],
  payments: { method: string; amount: number }[], lottery: string | null, lineDescription: (l: CartLine) => string) {
  const items = new Map(cat.items.map((i) => [i.id, i]))
  const deps = new Map(cat.departments.map((d) => [d.id, d]))
  const rates = new Map((cat.vat_rates ?? []).map((v) => [v.id, v.rate]))
  return {
    lines: lines.map((l) => {
      const it = l.item_id ? items.get(l.item_id) : undefined
      const dep = l.department_id ? deps.get(l.department_id) : it?.department_id ? deps.get(it.department_id) : undefined
      return { description: lineDescription(l).slice(0, 60), quantity: String(l.quantity), unit_price: centsStr(toCents(l.price)),
        full_amount: centsStr(lineCents({ price: l.price, quantity: l.quantity })), amount: centsStr(lineCents(l)),
        vat_rate: l.vat_rate, department: dep?.rt_department ?? null }
    }),
    adjustments: promos.map((p) => ({ description: p.description.slice(0, 60), amount: centsStr(-p.amount_cents), vat_rate: (p.vat_rate_id && rates.get(p.vat_rate_id)) || '22', department: null })),
    payments: payments.map((p) => ({ method: p.method, amount: centsStr(p.amount) })), lottery,
  }
}

export async function localAgent(per: Periph, role: string, kind: string, payload: any): Promise<any> {
  const dev = per?.devices?.[role]
  if (!dev?.local_key) throw new Error('Agent locale non configurato')
  const r = await fetch(`http://127.0.0.1:${per!.local_port}/lavoro`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Agent-Key': dev.local_key },
    body: JSON.stringify({ device_id: dev.id, kind, payload }),
  })
  const data = await r.json()
  if (!data.ok) throw new Error(data.error || 'Errore del registratore')
  return data.result
}
