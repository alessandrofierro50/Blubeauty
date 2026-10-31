// Controlla che il motore promozioni della cassa (TypeScript) dia gli stessi centesimi di quello del server (Python)
// sui casi condivisi in backend/tests/fixtures/pos_promos.json.  Uso: npm run check:promos
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { transformSync } from 'esbuild'

const here = dirname(fileURLToPath(import.meta.url))
const ts = readFileSync(resolve(here, '../src/pages/pos/promos.ts'), 'utf8')
const js = transformSync(ts, { loader: 'ts', format: 'esm' }).code
const mod = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'))
const { cases } = JSON.parse(readFileSync(resolve(here, '../../backend/tests/fixtures/pos_promos.json'), 'utf8'))

const p4 = (price, d) => mod.rhu(Number(price) * 10000 * (100 - Number(d || 0)) / 100)
let failed = 0
for (const c of cases) {
  const lines = c.lines.map((l) => ({
    item_id: l.item_id, price_cents: mod.rhu(Number(l.price) * 100), quantity: Number(l.quantity),
    amount_cents: mod.rhu(p4(l.price, l.discount) * mod.rhu(Number(l.quantity) * 1000) / 1e5), vat_rate_id: l.vat,
    categories: l.categories ?? [], manual_discount: !!l.discount,
  }))
  const promos = c.promos.map((p) => ({ item_ids: [], category_ids: [], buy_qty: null, pay_qty: null, threshold: null, ...p }))
  const got = mod.computePromos(lines, promos).map(({ promotion_id, vat_rate_id, amount_cents }) => ({ promotion_id, vat_rate_id, amount_cents }))
  const ok = JSON.stringify(got) === JSON.stringify(c.expected)
  if (!ok) { failed++; console.log('DIVERSO:', c.name, '\n  atteso', JSON.stringify(c.expected), '\n  ottenuto', JSON.stringify(got)) }
}
console.log(failed ? `${failed} casi diversi su ${cases.length}` : `Promozioni: ${cases.length} casi uguali al server`)
process.exit(failed ? 1 : 0)
