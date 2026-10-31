// Promozioni di cassa: gemello di backend/app/pos/promos.py (stesso algoritmo, stessi centesimi).
// La cassa le calcola per mostrare il totale anche senza rete; il server le ricalcola e fa fede.
// I casi condivisi in backend/tests/fixtures/pos_promos.json si controllano con `npm run check:promos`.

export type PLine = { item_id: string | null; price_cents: number; quantity: number; amount_cents: number; vat_rate_id: string | null; categories: string[]; manual_discount: boolean }
export type PPromo = {
  id: string; name: string; mechanic: string; item_scope: string; item_ids: string[]; category_ids: string[]
  buy_qty: number | null; pay_qty: number | null; value: string; price_type: string; threshold: string | null
}
export type PromoLine = { promotion_id: string; description: string; vat_rate_id: string | null; amount_cents: number }

/** Arrotondamento commerciale all'intero, come ROUND_HALF_UP di Python (lavorando in decimi di centesimo per evitare errori binari). */
export const rhu = (x: number) => Math.sign(x) * Math.round(Math.abs(Math.round(x * 1e6) / 1e6) + 1e-9)

const inScope = (p: PPromo, l: PLine) =>
  p.item_scope === 'tutti' ? true : !l.item_id ? false : p.item_scope === 'articoli' ? p.item_ids.includes(l.item_id) : l.categories.some((c) => p.category_ids.includes(c))

const order = (p: PPromo): [number, string, string] => [({ nxm: 0, nesimo: 1, soglia: 2 } as any)[p.mechanic] ?? 9, p.name.toLowerCase(), p.id]
const cmp = (a: PPromo, b: PPromo) => {
  const x = order(a), y = order(b)
  return x[0] - y[0] || (x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0) || (x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0)
}
const str = (v: string | null) => (v === null ? 'None' : v)  // come str() di Python per ordinare le aliquote
const normalize = (v: string) => String(Number(v))
const euroIt = (v: string) => Number(v).toFixed(2).replace('.', ',')

export function computePromos(lines: PLine[], promos: PPromo[]): PromoLine[] {
  const units: [number, number, number][] = []
  lines.forEach((l, i) => {
    if (l.item_id && !l.manual_discount && l.price_cents > 0 && l.quantity > 0 && Number.isInteger(l.quantity)) {
      for (let n = 0; n < l.quantity; n++) units.push([l.price_cents, i, n])
    }
  })
  const used = new Set<string>()
  const out: PromoLine[] = []
  const unitDisc = new Map<number, number>()
  for (const p of promos.filter((p) => p.mechanic === 'nxm' || p.mechanic === 'nesimo').sort(cmp)) {
    const n = Number(p.buy_qty || 0)
    if (n < 2 || (p.mechanic === 'nxm' && !(Number(p.pay_qty || 0) > 0 && Number(p.pay_qty) < n))) continue
    const pool = units.filter((u) => !used.has(`${u[1]}:${u[2]}`) && inScope(p, lines[u[1]])).sort((a, b) => b[0] - a[0] || a[1] - b[1] || a[2] - b[2])
    const groups = Math.floor(pool.length / n)
    if (!groups) continue
    const perVat = new Map<string | null, number>()
    for (let g = 0; g < groups; g++) {
      const block = pool.slice(g * n, (g + 1) * n)
      for (const u of block) used.add(`${u[1]}:${u[2]}`)
      const free = p.mechanic === 'nxm' ? block.slice(-(n - Number(p.pay_qty))) : block.slice(-1)
      for (const [price, li] of free) {
        const d = p.mechanic === 'nxm' ? price : rhu((price * Number(p.value)) / 100)
        const vat = lines[li].vat_rate_id
        perVat.set(vat, (perVat.get(vat) ?? 0) + d)
        unitDisc.set(li, (unitDisc.get(li) ?? 0) + d)
      }
    }
    const label = p.mechanic === 'nxm' ? `${n}x${p.pay_qty}` : `${n}° pezzo −${normalize(p.value)}%`
    for (const [vat, amount] of [...perVat.entries()].sort((a, b) => (str(a[0]) < str(b[0]) ? -1 : 1))) {
      if (amount) out.push({ promotion_id: p.id, description: `Promo ${label} · ${p.name}`, vat_rate_id: vat, amount_cents: -amount })
    }
  }
  let best: { disc: number; p: PPromo; base: Map<string | null, number>; total: number } | null = null
  for (const p of promos.filter((p) => p.mechanic === 'soglia').sort(cmp)) {
    const base = new Map<string | null, number>()
    lines.forEach((l, i) => {
      if (l.amount_cents > 0 && inScope(p, l)) base.set(l.vat_rate_id, (base.get(l.vat_rate_id) ?? 0) + l.amount_cents - (unitDisc.get(i) ?? 0))
    })
    const total = [...base.values()].reduce((a, b) => a + b, 0)
    const threshold = p.threshold ? rhu(Number(p.threshold) * 100) : 0
    if (total <= 0 || total < threshold) continue
    const disc = p.price_type === 'sconto' ? rhu((total * Number(p.value)) / 100) : Math.min(total, rhu(Number(p.value) * 100))
    if (disc > 0 && (!best || disc > best.disc)) best = { disc, p, base, total }
  }
  if (best) {
    const { disc, p, base, total } = best
    const keys = [...base.entries()].filter(([, v]) => v).map(([k]) => k).sort((a, b) => (str(a) < str(b) ? -1 : 1))
    let left = disc
    keys.forEach((vat, n) => {
      const share = n === keys.length - 1 ? left : rhu((disc * (base.get(vat) ?? 0)) / total)
      left -= share
      const what = p.price_type === 'sconto' ? `−${normalize(p.value)}%` : `−${euroIt(p.value)} €`
      if (share) out.push({ promotion_id: p.id, description: `Sconto ${what} sulla spesa · ${p.name}`, vat_rate_id: vat, amount_cents: -share })
    })
  }
  return out
}

/** Descrizione breve della promozione per i badge della cassa e dell'elenco. */
export function promoLabel(p: { mechanic: string; buy_qty?: number | null; pay_qty?: number | null; value: string | number; price_type: string; threshold?: string | number | null }) {
  if (p.mechanic === 'nxm') return `${p.buy_qty}x${p.pay_qty}`
  if (p.mechanic === 'nesimo') return `${p.buy_qty}° pezzo −${Number(p.value)}%`
  if (p.mechanic === 'soglia') return `${p.price_type === 'sconto' ? `−${Number(p.value)}%` : `−${euroIt(String(p.value))} €`} da ${euroIt(String(p.threshold ?? 0))} €`
  return ''
}
