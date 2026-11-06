// Vendita al banco a tutto schermo. Due modalità: "negozio" (touch, tasti rapidi grandi) e "supermercato"
// (tastiera e lettore: campo codice sempre attivo, moltiplicatore 3*, importi dei reparti in centesimi).
// Funziona anche senza rete: catalogo in memoria locale e scontrini in coda, inviati appena torna la connessione.

import {
  ActionIcon, Alert, Badge, Box, Button, Center, Divider, Group, Kbd, Loader, Menu, Modal, NumberInput, Paper, ScrollArea, SegmentedControl,
  Select, SimpleGrid, Stack, Switch, Table, Text, TextInput, Title, Tooltip, UnstyledButton,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  IconArrowBackUp, IconArrowLeft, IconBackspace, IconCash, IconCloudOff, IconCreditCard, IconDeviceDesktop, IconDiscount, IconDoorExit, IconFileInvoice,
  IconGift, IconLock, IconMinus, IconPackage, IconPercentage, IconPlus, IconPrinter, IconReceipt, IconRefresh, IconSearch, IconTrash, IconUser, IconX,
} from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi } from '../../api'
import { Logo, notifyError } from '../../components'
import { PRINT_CSS, ReceiptPrint, SessionPrint } from './Receipt'
import { computePromos, promoLabel } from './promos'
import { DisplayState, displayChannel } from './Display'
import { SellPackage, SellVoucher } from '../salone/Prepaid'
import { CashPanel, CashVerify, CashWait } from './CashMachine'
import {
  CartLine, CatItem, Catalog, Dept, METHODS, P, Pending, Periph, Resolved, buildIndex, localAgent, rtPayload, cartCents, catalogKey, centsStr, euro, isNetworkError,
  lineCents, local, methodLabel, outboxKey, parseAmount, parseNum, qtyFmt, resolveLocal, toCents, uuid4,
} from './shared'

type Prompt = { title: string; label: string; initial?: string; hint?: string; onOk: (v: string) => void; action?: { label: string; auto?: boolean; run: () => Promise<string> } }

export default function Cassa() {
  const { id } = useParams()
  const nav = useNavigate()
  const [regs, setRegs] = useState<any[] | null>(null)
  useEffect(() => {
    if (id) return
    P('/casse').then((r) => {
      const act = r.filter((x: any) => x.active)
      if (act.length === 1) nav(`/cassa/${act[0].id}`, { replace: true })
      setRegs(act)
    }).catch((e) => { notifyError(e); setRegs([]) })
  }, [id])
  if (id) return <Register id={id} />
  if (!regs) return <Center h="100vh"><Loader /></Center>
  return (
    <Center h="100vh" bg="var(--mantine-color-gray-0)">
      <Paper withBorder p="xl" w={460} radius="md">
        <Group justify="space-between" mb="lg"><Logo /><Button variant="subtle" leftSection={<IconArrowLeft size={16} />} onClick={() => nav('/')}>Gestionale</Button></Group>
        <Title order={3} mb="md">Scegli la cassa</Title>
        {regs.length === 0 && <Alert color="yellow">Nessuna cassa configurata. L'amministratore la crea in «Vendita al banco › Casse e reparti».</Alert>}
        <Stack>
          {regs.map((r) => (
            <Button key={r.id} size="lg" variant="light" justify="space-between" onClick={() => nav(`/cassa/${r.id}`)}
              rightSection={r.session ? <Badge color="green">aperta</Badge> : <Badge color="gray">chiusa</Badge>}>
              {r.name} {r.store_name ? `· ${r.store_name}` : ''}
            </Button>
          ))}
        </Stack>
      </Paper>
    </Center>
  )
}

// =====================================================================================================================

function Register({ id }: { id: string }) {
  const nav = useNavigate()
  const [reg, setReg] = useState<any>(null)
  const [me, setMe] = useState<any>(null)
  const [company, setCompany] = useState<any>(null)
  const [cat, setCat] = useState<Catalog | null>(() => local.get<Catalog | null>(catalogKey(id), null))
  const [session, setSession] = useState<any>(undefined)
  const [online, setOnline] = useState(true)
  const [outbox, setOutbox] = useState<Pending[]>(() => local.get<Pending[]>(outboxKey(id), []))
  const [printing, setPrinting] = useState<{ kind: 'receipt' | 'session'; data: any } | null>(null)
  const [periph, setPeriph] = useState<Periph>(() => local.get<Periph>(`blubeauty_pos_per_${id}`, null))
  useEffect(() => {
    appApi(`/api/periferiche/cassa/${id}`).then((p) => { setPeriph(p); local.set(`blubeauty_pos_per_${id}`, p) }).catch((e) => { if (!isNetworkError(e)) setPeriph(null) })
  }, [id])

  const loadCatalog = useCallback(async () => {
    try {
      const c = await P(`/casse/${id}/catalogo`)
      setCat(c)
      local.set(catalogKey(id), c)
      setOnline(true)
    } catch (e: any) {
      if (isNetworkError(e)) setOnline(false)
      else notifyError(e)
    }
  }, [id])

  useEffect(() => {
    P(`/casse/${id}`).then((r) => { setReg(r); setSession(r.session) }).catch((e) => {
      if (isNetworkError(e)) { setOnline(false); setReg(local.get(`blubeauty_pos_reg_${id}`, null)); setSession(local.get(`blubeauty_pos_ses_${id}`, null)) } else notifyError(e)
    })
    appApi('/api/auth/me').then(setMe).catch(() => {})
    appApi('/api/app/intestazione').then(setCompany).catch(() => {})
    loadCatalog()
    const t = setInterval(loadCatalog, 10 * 60 * 1000)
    return () => clearInterval(t)
  }, [id])
  useEffect(() => { if (reg) local.set(`blubeauty_pos_reg_${id}`, reg) }, [reg])
  useEffect(() => { if (session !== undefined) local.set(`blubeauty_pos_ses_${id}`, session) }, [session])
  useEffect(() => { local.set(outboxKey(id), outbox) }, [outbox])

  // invio della coda: all'avvio, ogni 20 secondi e quando torna la rete
  const flushing = useRef(false)
  const flush = useCallback(async () => {
    if (flushing.current) return
    const queue = local.get<Pending[]>(outboxKey(id), [])
    if (!queue.some((p) => !p.error)) return
    flushing.current = true
    const keep: Pending[] = []
    for (const p of queue) {
      if (p.error) { keep.push(p); continue }
      try {
        await P(`/casse/${id}/${p.kind === 'vendita' ? 'vendite' : 'resi'}`, { body: p.body })
        setOnline(true)
      } catch (e: any) {
        if (isNetworkError(e)) { setOnline(false); keep.push(p) } else keep.push({ ...p, error: e.message })
      }
    }
    setOutbox(keep)
    flushing.current = false
  }, [id])
  useEffect(() => {
    flush()
    const t = setInterval(flush, 20000)
    const on = () => flush()
    window.addEventListener('online', on)
    return () => { clearInterval(t); window.removeEventListener('online', on) }
  }, [flush])

  // copia di cortesia NON fiscale sul registratore telematico (come BluOrderScan: comandi Custom 4001/4003/4004)
  function courtesyOnRt(doc: any) {
    if (!doc?.id || doc.offline) { notifications.show({ color: 'orange', message: 'Lo scontrino non è ancora arrivato al gestionale: riprova tra poco' }); return }
    P(`/scontrini/${doc.id}/stampa`, { body: { where: 'registratore' } })
      .then(() => notifications.show({ message: 'Copia di cortesia inviata al registratore' })).catch(notifyError)
  }

  function print(kind: 'receipt' | 'session', data: any) {
    if (kind === 'receipt' && periph?.devices?.printer && data?.id && !data.offline) {  // stampante termica della cassa
      P(`/scontrini/${data.id}/stampa`, { method: 'POST' }).then(() => notifications.show({ message: 'Ricevuta inviata alla stampante' })).catch(notifyError)
      return
    }
    if (kind === 'receipt' && data?.id && !data.offline) {  // dal computer: stessa grafica della termica (logo, intestazione)
      window.open(`/stampa/scontrino/${data.id}`, 'ricevuta', 'popup,width=420,height=760')
      return
    }
    setPrinting({ kind, data })
    setTimeout(() => window.print(), 150)
  }

  if (!reg || session === undefined || !cat) {
    return <Center h="100vh"><Stack align="center"><Loader />{!online && <Text c="dimmed">Connessione assente: serve almeno un primo collegamento per scaricare il catalogo.</Text>}</Stack></Center>
  }
  return (
    <>
      <style>{PRINT_CSS}</style>
      <div id="pos-print">
        {printing?.kind === 'receipt' && <ReceiptPrint r={printing.data} company={company} register={reg.name} />}
        {printing?.kind === 'session' && <SessionPrint ses={printing.data} company={company} register={reg.name} />}
      </div>
      {!session
        ? <OpenScreen reg={reg} me={me} onOpen={setSession} onExit={() => nav('/')} />
        : <Till reg={reg} cat={cat} me={me} session={session} setSession={setSession} online={online} setOnline={setOnline}
            outbox={outbox} setOutbox={setOutbox} flush={flush} reloadCatalog={loadCatalog} print={print} courtesyOnRt={courtesyOnRt} periph={periph} />}
    </>
  )
}

function OpenScreen({ reg, me, onOpen, onExit }: { reg: any; me: any; onOpen: (s: any) => void; onExit: () => void }) {
  const [float, setFloat] = useState<string | number>(100)
  const [busy, setBusy] = useState(false)
  async function open() {
    setBusy(true)
    try { onOpen(await P(`/casse/${reg.id}/apri`, { body: { opening_float: String(float || 0) } })) } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Center h="100vh" bg="var(--mantine-color-gray-0)">
      <Paper withBorder p="xl" w={420} radius="md">
        <Group justify="space-between" mb="lg"><Logo /><Button variant="subtle" leftSection={<IconArrowLeft size={16} />} onClick={onExit}>Gestionale</Button></Group>
        <Title order={3}>{reg.name}</Title>
        <Text c="dimmed" mb="lg">{reg.store_name ?? reg.warehouse_name}{me ? ` · ${me.user.full_name}` : ''}</Text>
        <NumberInput label="Fondo cassa iniziale" description="Il contante presente nel cassetto all'apertura" size="lg" decimalScale={2} fixedDecimalScale
          decimalSeparator="," thousandSeparator="." min={0} suffix=" €" value={float} onChange={setFloat} autoFocus
          onKeyDown={(e) => { if (e.key === 'Enter') open() }} />
        <Button fullWidth size="lg" mt="lg" leftSection={<IconCash />} loading={busy} onClick={open}>Apri la cassa</Button>
      </Paper>
    </Center>
  )
}

// =====================================================================================================================

function Till({ reg, cat, me, session, setSession, online, setOnline, outbox, setOutbox, flush, reloadCatalog, print, courtesyOnRt, periph }: {
  reg: any; cat: Catalog; me: any; session: any; setSession: (s: any) => void; online: boolean; setOnline: (b: boolean) => void
  outbox: Pending[]; setOutbox: (p: Pending[]) => void; flush: () => void; reloadCatalog: () => void; print: (k: 'receipt' | 'session', d: any) => void
  periph: Periph
  courtesyOnRt: (doc: any) => void
}) {
  const nav = useNavigate()
  const market = reg.mode === 'supermercato'
  const index = useMemo(() => buildIndex(cat), [cat])
  const items = useMemo(() => new Map(cat.items.map((i) => [i.id, i])), [cat])
  const depts = useMemo(() => new Map(cat.departments.map((d) => [d.id, d])), [cat])
  const [lines, setLines] = useState<CartLine[]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [mult, setMult] = useState<number | null>(null)
  const [customer, setCustomer] = useState<any>(null)
  const [invoice, setInvoice] = useState(false)
  const [refundMode, setRefundMode] = useState(false)
  const [prompt, setPrompt] = useState<Prompt | null>(null)
  const [variantOf, setVariantOf] = useState<{ item: CatItem; quantity?: number } | null>(null)
  const [modal, setModal] = useState<null | 'pay' | 'search' | 'customer' | 'returns' | 'receipts' | 'move' | 'close' | 'outbox' | 'buono' | 'pacchetto'>(null)
  const [last, setLast] = useState<any>(null)
  // cassa automatica VNE: il pagamento in corso blocca il carrello finché la macchina dà l'esito
  const hasCash = !!periph?.devices?.cash
  const [cashPay, setCashPay] = useState<any>(null)
  const [cashVerify, setCashVerify] = useState<any[]>([])
  const [cashModal, setCashModal] = useState<null | 'panel' | 'verify'>(null)
  const canAdminCash = ['amministratore', 'amministrazione'].includes(me?.user?.role)
  const loadCash = useCallback(() => {
    if (!hasCash) return
    P(`/casse/${reg.id}/cassa-automatica`).then((o) => {
      const open = (o.payments || []).find((p: any) => p.status === 'in_corso')
      if (open) setCashPay((cur: any) => cur ?? open)  // pagamento lasciato in corso (pagina ricaricata): si riprende l'attesa
      setCashVerify((o.payments || []).filter((p: any) => p.status === 'da_verificare'))
    }).catch(() => {})
  }, [hasCash, reg.id])
  useEffect(() => { loadCash() }, [loadCash])
  const inputRef = useRef<HTMLInputElement>(null)
  // promozioni di cassa (3x2, N-esimo pezzo, soglia): calcolate qui per il totale, ricalcolate dal server che fa fede
  const promoLines = useMemo(() => (refundMode || !cat.promotions?.length ? [] : computePromos(lines.map((l) => {
    const it = l.item_id ? items.get(l.item_id) : undefined
    return { item_id: l.item_id ?? null, price_cents: toCents(l.price), quantity: l.quantity, amount_cents: lineCents(l),
      vat_rate_id: (it ? it.vat_rate_id : l.department_id ? depts.get(l.department_id)?.vat_rate_id : null) ?? null,
      categories: it?.categories ?? [], manual_discount: !!l.discount }
  }), cat.promotions)), [lines, cat, refundMode])
  const itemPromo = (itemId?: string) => {
    const it = itemId ? items.get(itemId) : undefined
    const p = it && cat.promotions?.find((p) => p.mechanic !== 'soglia' && (p.item_scope === 'tutti' || p.item_ids.includes(it.id) || (it.categories ?? []).some((c) => p.category_ids.includes(c))))
    return p ? promoLabel(p) : null
  }
  const total = cartCents(lines) + promoLines.reduce((a, p) => a + p.amount_cents, 0)

  // display cliente (seconda finestra sullo stesso computer)
  const chRef = useRef<BroadcastChannel | null>(null)
  const stateRef = useRef<DisplayState | null>(null)
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return
    const ch = new BroadcastChannel(displayChannel(reg.id))
    chRef.current = ch
    ch.onmessage = (e) => { if (e.data?.type === 'hello' && stateRef.current) ch.postMessage({ type: 'state', state: stateRef.current }) }
    return () => { ch.close(); chRef.current = null }
  }, [reg.id])
  useEffect(() => {
    const state: DisplayState = {
      lines: lines.map((l) => ({ description: l.description, detail: l.detail, quantity: l.quantity, unit: l.unit, amount: lineCents(l) })),
      promos: promoLines.map((p) => ({ description: p.description, amount: p.amount_cents })), total, refund: refundMode,
      last: last ? { total: toCents(last.total), change: last.change ? toCents(last.change) : 0 } : null,
      promotions: (cat.promotions ?? []).map((p) => `${p.name} · ${promoLabel(p)}`),
    }
    stateRef.current = state
    chRef.current?.postMessage({ type: 'state', state })
  }, [lines, promoLines, total, last, refundMode, cat])
  // torna sul campo codice, ma mai sopra una finestra aperta (rubarebbe la digitazione)
  const focus = () => setTimeout(() => { if (!document.querySelector('.mantine-Modal-root')) inputRef.current?.focus() }, 60)

  // ------------------------------------------------------------------ righe
  function addLine(l: Omit<CartLine, 'key'>) {
    setLast(null)
    setLines((cur) => {
      if (!market && l.item_id && !l.discount && !l.serials?.length) {
        const same = cur.find((x) => x.item_id === l.item_id && x.variant_id === l.variant_id && x.price === l.price && !x.discount && !items.get(l.item_id!)?.sold_by_weight)
        if (same) {
          setSel(same.key)
          return cur.map((x) => (x === same ? { ...x, quantity: x.quantity + l.quantity } : x))
        }
      }
      const key = uuid4()
      setSel(key)
      return [...cur, { ...l, key }]
    })
  }

  function addItem(r: Resolved, qty?: number) {
    const it = r.item
    const q = qty ?? r.quantity ?? 1
    if (it.has_variants && !r.variant_id && it.variants.length) { setVariantOf({ item: it, quantity: q }); return }
    if (it.sold_by_weight && qty === undefined && r.quantity === undefined && r.amount === undefined) {
      const scale = periph?.devices?.scale
      setPrompt({ title: it.description, label: `Peso (${it.unit || 'kg'})`, hint: scale ? 'Letto dalla bilancia: controlla e conferma' : 'es. 0,350',
        onOk: (v) => { const n = parseNum(v); if (n > 0) addItem(r, n) },
        action: scale ? { label: 'Leggi bilancia', auto: true, run: async () => {
          const w = await appApi(`/api/periferiche/bilancia/${scale.id}/leggi`, { method: 'POST' })
          if (!w.stable) notifications.show({ color: 'yellow', message: 'Peso non stabile: rileggi quando la bilancia è ferma' })
          return String(Number(w.weight)).replace('.', ',')
        } } : undefined })
      return
    }
    const variant = it.variants.find((v) => v.id === r.variant_id)
    const price = variant?.price ?? it.price
    const base = { item_id: it.id, variant_id: r.variant_id, description: it.description, detail: variant?.label, vat_rate: it.vat_rate, unit: it.unit, promo: it.promo }
    if (r.amount !== undefined) { addLine({ ...base, quantity: 1, price: r.amount, detail: [variant?.label, 'importo da bilancia'].filter(Boolean).join(' · ') }); return }
    if (price === null || price === undefined) {
      setPrompt({ title: it.description, label: 'Prezzo (IVA inclusa)', hint: 'Articolo senza prezzo nel listino della cassa', onOk: (v) => { const n = parseAmount(v, false); if (n >= 0) addLine({ ...base, quantity: q, price: n }) } })
      return
    }
    if (it.serial_managed) {  // una riga per pezzo, con la sua matricola (garanzia)
      setPrompt({ title: it.description, label: 'Matricola / numero di serie', hint: 'Leggila col lettore dall\'etichetta del prodotto',
        onOk: (v) => { if (v.trim()) addLine({ ...base, quantity: 1, price: Number(price), serials: [v.trim().toUpperCase()], detail: [variant?.label, `matr. ${v.trim().toUpperCase()}`].filter(Boolean).join(' · ') }) } })
      return
    }
    addLine({ ...base, quantity: q, price: Number(price) })
  }

  function addDept(d: Dept, amount?: number) {
    const go = (n: number) => { if (n > 0) addLine({ department_id: d.id, description: d.name, quantity: mult ?? 1, price: n, vat_rate: d.vat_rate }); setMult(null) }
    if (amount !== undefined && amount > 0) { go(amount); return }
    setPrompt({ title: `Reparto ${d.name}`, label: 'Importo (IVA inclusa)', hint: market ? 'Anche in centesimi: 250 = 2,50 €' : undefined, onOk: (v) => go(parseAmount(v, market)) })
  }

  async function scan(raw: string) {
    let code = raw.trim()
    let q: number | undefined = mult ?? undefined
    const m = code.match(/^(\d+(?:[.,]\d+)?)\s*[*xX]\s*(.+)$/)
    if (m) { q = parseNum(m[1]); code = m[2].trim() }
    if (!code) return
    let r = resolveLocal(index, cat.settings, code)
    if (!r && online) {
      try {
        const s = await P(`/casse/${reg.id}/codice?code=${encodeURIComponent(code)}`)
        const it = items.get(s.item_id)
        if (it) r = { item: it, variant_id: s.variant_id ?? undefined, quantity: s.quantity ? Number(s.quantity) : undefined, amount: s.amount ? Number(s.amount) : undefined }
        else { reloadCatalog(); notifications.show({ color: 'yellow', message: 'Articolo nuovo: aggiorno il catalogo, riprova tra un attimo' }); return }
      } catch (e: any) {
        if (isNetworkError(e)) setOnline(false)
      }
    }
    setMult(null)
    if (!r) { beep(); notifications.show({ color: 'red', title: 'Codice non trovato', message: code }); return }
    if (q !== undefined && r.quantity !== undefined && r.quantity !== 1 && !r.item.sold_by_weight) q = q * r.quantity  // es. 2 × cartone da 6
    addItem(r, q ?? (r.quantity !== undefined && r.quantity !== 1 ? r.quantity : r.item.sold_by_weight ? r.quantity : undefined))
  }

  function onInputKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (input.trim()) { const v = input; setInput(''); scan(v) } else if (lines.length) setModal('pay')
    } else if (e.key === '*' && /^\d+([.,]\d+)?$/.test(input.trim())) {
      e.preventDefault()
      setMult(parseNum(input)); setInput('')
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()
      const i = lines.findIndex((l) => l.key === sel)
      const n = e.key === 'ArrowUp' ? Math.max(0, (i < 0 ? lines.length : i) - 1) : Math.min(lines.length - 1, i + 1)
      if (lines[n]) setSel(lines[n].key)
    } else if (e.key === 'Escape') {
      setInput(''); setMult(null)
    }
  }

  const selected = lines.find((l) => l.key === sel) ?? lines[lines.length - 1]
  const update = (key: string, patch: Partial<CartLine>) => setLines((cur) => cur.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const remove = (key?: string) => { if (!key) return; setLines((cur) => cur.filter((l) => l.key !== key)); setSel(null) }
  const clearCart = () => { setLines([]); setSel(null); setCustomer(null); setInvoice(false); setRefundMode(false); setMult(null); setInput('') }

  function askQty() {
    if (!selected) return
    setPrompt({ title: selected.description, label: 'Quantità', initial: String(selected.quantity).replace('.', ','), onOk: (v) => { const n = parseNum(v); if (n > 0) update(selected.key, { quantity: n }) } })
  }
  function askDiscount() {
    if (!selected) return
    setPrompt({ title: selected.description, label: 'Sconto sulla riga (%)', initial: selected.discount ? String(selected.discount) : '', onOk: (v) => { const n = parseNum(v || '0'); if (n >= 0 && n <= 100) update(selected.key, { discount: n || undefined }) } })
  }
  function askPrice() {
    if (!selected) return
    setPrompt({ title: selected.description, label: 'Prezzo unitario (IVA inclusa)', initial: selected.price.toFixed(2).replace('.', ','), onOk: (v) => { const n = parseAmount(v, false); if (n >= 0) update(selected.key, { price: n }) } })
  }

  // copia di cortesia dell'ultimo scontrino (quello appena fatto o l'ultimo della sessione)
  const hasRt = !!periph?.devices?.rt
  async function courtesyCopy() {
    if (last && !last.offline) return courtesyOnRt(last)
    try {
      const rows = await P(`/scontrini?session_id=${session.id}&limit=5`)
      const doc = rows.find((r: any) => r.doc_type === 'SCO')
      if (!doc) { notifications.show({ color: 'orange', message: 'Nessuno scontrino in questa apertura di cassa' }); return }
      courtesyOnRt(doc)
    } catch (e) { notifyError(e) }
  }

  // tasti funzione (validi anche col cursore fuori dal campo codice)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (modal || prompt || variantOf) return
      const k = e.key
      const map: Record<string, () => void> = {
        F2: () => setModal('search'), F3: () => setModal('customer'), F4: askDiscount, F5: askQty, F6: () => setModal('returns'),
        F7: askPrice, F8: () => remove(selected?.key), F9: () => lines.length && setPrompt({ title: 'Annulla scontrino', label: 'Scrivi SI per svuotare lo scontrino in corso', onOk: (v) => { if (v.trim().toUpperCase() === 'SI') clearCart() } }),
        F10: () => setModal('move'), F12: () => lines.length && setModal('pay'), ...(hasRt ? { F1: courtesyCopy } : {}),
      }
      if (map[k]) { e.preventDefault(); map[k](); return }
      if (market && document.activeElement !== inputRef.current && k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) inputRef.current?.focus()
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  })
  useEffect(() => { if (!modal && !prompt && !variantOf) focus() }, [modal, prompt, variantOf])

  // documento commerciale: si segue l'esito del registratore finché arriva
  useEffect(() => {
    const st = last?.fiscal?.rt?.status
    if (!last?.id || last.offline || !['in_coda', 'inviato'].includes(st)) return
    let n = 0
    const t = setInterval(() => {
      n++
      P(`/scontrini/${last.id}`).then((r) => { if (r.fiscal?.rt?.status !== st || n > 40) setLast((x: any) => (x?.id === r.id ? r : x)) }).catch(() => {})
      if (n > 40) clearInterval(t)
    }, 1000)
    return () => clearInterval(t)
  }, [last?.id, last?.fiscal?.rt?.status])

  async function retryFiscal(force = false) {
    try { setLast(await P(`/scontrini/${last.id}/fiscale`, { body: { force } })) } catch (e: any) {
      if (e.status === 409 && !force && last?.fiscal?.rt?.status === 'inviato' && window.confirm(`${e.message}\n\nRipetere comunque?`)) retryFiscal(true)
      else notifyError(e)
    }
  }

  // ------------------------------------------------------------------ incasso
  function lineBody(l: CartLine) {
    return { item_id: l.item_id ?? null, variant_id: l.variant_id ?? null, department_id: l.department_id ?? null, description: l.description + (l.detail && !l.detail.includes('bilancia') && !l.serials?.length ? ` ${l.detail}` : ''),
      quantity: String(l.quantity), unit_price_gross: l.price.toFixed(4), discount: l.discount ? String(l.discount) : null, lot_number: l.lot_number ?? null,
      serials: l.serials ?? [], origin_line_id: l.origin_line_id ?? null, price_source: l.promo ? `Promo ${l.promo}`.slice(0, 60) : 'Banco' }
  }

  async function submit(kind: 'vendita' | 'reso', body: any, totalCents: number, changeCents = 0, rt?: any) {
    try {
      const r = await P(`/casse/${reg.id}/${kind === 'vendita' ? 'vendite' : 'resi'}`, { body })
      setOnline(true)
      setLast(r)
      if (reg.settings?.auto_print) print('receipt', r)
      return true
    } catch (e: any) {
      if (isNetworkError(e) && !body.invoice_party_id) {
        setOnline(false)
        let fiscal: any = null
        if (rt && periph?.devices?.rt && !body.nonfiscal_reason) {  // documento commerciale stampato tramite l'agent sul computer della cassa
          try {
            body.rt_result = await localAgent(periph, 'rt', kind === 'vendita' ? 'rt.receipt' : 'rt.refund', rt)
            fiscal = { rt: { status: 'emesso', offline: true, ...body.rt_result } }
          } catch (err: any) {
            fiscal = { rt: { status: 'errore', error: `Documento commerciale non stampato: ${err.message || 'agent locale non raggiungibile'}` } }
          }
        }
        const q = [...local.get<Pending[]>(outboxKey(reg.id), []), { kind, body, total: totalCents, at: new Date().toISOString() }]
        setOutbox(q)
        setLast({ offline: true, total: centsStr(totalCents), change: centsStr(changeCents), doc_type: kind === 'vendita' ? 'SCO' : 'RSO', fiscal })
        notifications.show({ color: 'orange', title: 'Senza connessione', message: 'Scontrino salvato: verrà registrato appena torna la rete' })
        return true
      }
      notifyError(e)
      return false
    }
  }

  async function pay(payments: { method: string; amount: number }[], lottery: string | null, nonfiscal: string | null = null, voucherCode: string | null = null) {
    const paid = payments.reduce((a, p) => a + p.amount, 0)
    const body: any = {
      client_uuid: uuid4(), session_id: session.id, lines: lines.map(lineBody), lottery_code: nonfiscal ? null : lottery, nonfiscal_reason: nonfiscal,
      payments: payments.map((p) => ({ method: p.method, amount: centsStr(p.amount) })),
      customer_id: customer && !invoice ? customer.id : null, invoice_party_id: customer && invoice ? customer.id : null,
      voucher_code: voucherCode,
    }
    const rt = !body.invoice_party_id && !nonfiscal ? rtPayload(cat, lines, promoLines, payments, lottery, (l) => lineBody(l).description) : undefined
    if (await submit('vendita', body, total, paid - total, rt)) { clearCart(); setModal(null) }
  }

  async function payWithMachine(others: { method: string; amount: number }[], lottery: string | null, nonfiscal: string | null, voucherCode: string | null) {
    const body: any = {
      client_uuid: uuid4(), session_id: session.id, lines: lines.map(lineBody), lottery_code: nonfiscal ? null : lottery, nonfiscal_reason: nonfiscal,
      payments: others.map((p) => ({ method: p.method, amount: centsStr(p.amount) })),
      customer_id: customer && !invoice ? customer.id : null, invoice_party_id: customer && invoice ? customer.id : null, voucher_code: voucherCode,
    }
    try {
      setCashPay(await P(`/casse/${reg.id}/cassa-automatica/pagamenti`, { body }))
      setModal(null)
    } catch (e) { notifyError(e) }
  }

  function cashDone(p: any) {
    setCashPay(null)
    if (p.status === 'pagato') {
      clearCart()
      if (p.receipt) { setLast(p.receipt); if (reg.settings?.auto_print) print('receipt', p.receipt) }
      notifications.show({ color: 'green', title: 'Pagato con la cassa automatica', message: p.message })
    } else if (p.status === 'da_verificare') {
      notifications.show({ color: 'orange', title: 'Cassa automatica: da verificare', message: p.message, autoClose: false })
      clearCart()  // la vendita resta sul server: si registra dalla verifica, mai con un nuovo incasso
      loadCash()
      setCashModal('verify')
    } else {
      notifications.show({ color: 'orange', title: 'Cassa automatica', message: `${p.message || p.status_label}: la vendita resta da incassare` })
      setModal('pay')
    }
  }

  async function refundCart(method: string, restock: boolean, reason: string) {
    const body = { client_uuid: uuid4(), session_id: session.id, lines: lines.map(lineBody), refund_method: method, restock, reason: reason || 'Reso senza scontrino' }
    const rt = { ...rtPayload(cat, lines, [], [{ method, amount: total }], null, (l) => lineBody(l).description), reference: null, void: false }
    if (await submit('reso', body, total, 0, rt)) { clearCart(); setModal(null) }
  }

  // ------------------------------------------------------------------ disegno
  const quick = (reg.quick_keys || []).map((k: any) => ({ ...k, ref: k.type === 'item' ? items.get(k.id) : depts.get(k.id) })).filter((k: any) => k.ref)
  const errors = outbox.filter((p) => p.error).length

  return (
    <Box h="100vh" style={{ display: 'flex', flexDirection: 'column', background: 'var(--mantine-color-gray-1)' }}>
      {/* barra superiore */}
      <Group px="md" py={6} justify="space-between" bg="var(--mantine-color-blue-9)" c="white" wrap="nowrap">
        <Group gap="sm" wrap="nowrap">
          <Text fw={700}>{reg.name}</Text>
          <Text size="sm" opacity={0.8}>{me?.user?.full_name} · aperta {new Date(session.opened_at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}</Text>
          {!online && <Badge color="orange" leftSection={<IconCloudOff size={12} />}>offline</Badge>}
          {outbox.length > 0 && <Badge color={errors ? 'red' : 'yellow'} style={{ cursor: 'pointer' }} onClick={() => setModal('outbox')}>{outbox.length} da inviare{errors ? ` · ${errors} con errore` : ''}</Badge>}
        </Group>
        <Group gap={4} wrap="nowrap">
          <Tooltip label="Apri il display per il cliente (trascinalo sul secondo schermo)"><Button size="xs" variant="subtle" color="white" leftSection={<IconDeviceDesktop size={16} />}
            onClick={() => window.open(`/cassa/${reg.id}/display`, `display-${reg.id}`, 'popup,width=1024,height=600')}>Display</Button></Tooltip>
          {hasRt && <Tooltip label="Stampa sul registratore la copia non fiscale dell'ultimo scontrino"><Button size="xs" variant="subtle" color="white"
            leftSection={<IconPrinter size={16} />} onClick={courtesyCopy}>Copia cortesia <Kbd ml={4} size="xs">F1</Kbd></Button></Tooltip>}
          {online && <Menu position="bottom-end">
            <Menu.Target><Button size="xs" variant="subtle" color="white" leftSection={<IconGift size={16} />} data-testid="cassa-prepagati">Buoni e pacchetti</Button></Menu.Target>
            <Menu.Dropdown>
              <Menu.Item leftSection={<IconGift size={16} />} onClick={() => setModal('buono')}>Vendi un buono regalo</Menu.Item>
              <Menu.Item leftSection={<IconPackage size={16} />} onClick={() => setModal('pacchetto')}>Vendi un pacchetto o abbonamento</Menu.Item>
            </Menu.Dropdown>
          </Menu>}
          {hasCash && cashVerify.length > 0 && <Badge color="orange" style={{ cursor: 'pointer' }} onClick={() => setCashModal('verify')}>{cashVerify.length} da verificare</Badge>}
          {hasCash && online && <Button size="xs" variant="subtle" color="white" leftSection={<IconCash size={16} />} onClick={() => setCashModal('panel')}
            data-testid="cassa-gestione-vne">Gestione cassa automatica</Button>}
          <Button size="xs" variant="subtle" color="white" leftSection={<IconReceipt size={16} />} onClick={() => setModal('receipts')}>Scontrini</Button>
          <Button size="xs" variant="subtle" color="white" leftSection={<IconCash size={16} />} onClick={() => setModal('move')}>Prelievi <Kbd ml={4} size="xs">F10</Kbd></Button>
          <Button size="xs" variant="subtle" color="white" leftSection={<IconLock size={16} />} onClick={() => setModal('close')}>Chiusura</Button>
          <Tooltip label="Aggiorna catalogo e prezzi"><ActionIcon variant="subtle" color="white" onClick={() => { reloadCatalog(); flush() }}><IconRefresh size={18} /></ActionIcon></Tooltip>
          <Tooltip label="Torna al gestionale"><ActionIcon variant="subtle" color="white" onClick={() => nav('/')}><IconDoorExit size={18} /></ActionIcon></Tooltip>
        </Group>
      </Group>

      <Box style={{ flex: 1, display: 'flex', minHeight: 0, gap: 12, padding: 12 }}>
        {/* scontrino in corso */}
        <Paper withBorder radius="md" style={{ flex: market ? 3 : 5, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Group px="md" pt="sm" pb={6} justify="space-between">
            <Group gap="xs">
              {refundMode ? <Badge color="red" size="lg">Reso senza scontrino</Badge> : <Text fw={600}>Scontrino</Text>}
              {customer && <Badge size="lg" variant="light" color={invoice ? 'grape' : 'blue'} leftSection={invoice ? <IconFileInvoice size={14} /> : <IconUser size={14} />}
                rightSection={<IconX size={12} style={{ cursor: 'pointer' }} onClick={() => { setCustomer(null); setInvoice(false) }} />}>{invoice ? 'Fattura a ' : ''}{customer.name}</Badge>}
            </Group>
            <Text size="sm" c="dimmed">{lines.length} righe · {qtyFmt(lines.reduce((a, l) => a + (items.get(l.item_id ?? '')?.sold_by_weight ? 1 : l.quantity), 0))} pezzi</Text>
          </Group>
          <ScrollArea style={{ flex: 1 }} px="xs">
            <Table verticalSpacing={6} highlightOnHover>
              <Table.Tbody>
                {lines.map((l) => (
                  <Table.Tr key={l.key} onClick={() => setSel(l.key)} style={{ cursor: 'pointer' }} bg={l.key === selected?.key ? 'var(--mantine-color-blue-0)' : undefined}>
                    <Table.Td>
                      <Text fw={500} lineClamp={1}>{l.description}</Text>
                      <Group gap={6}>
                        {l.detail && <Text size="xs" c="dimmed">{l.detail}</Text>}
                        {l.promo && <Badge size="xs" color="orange" variant="light">{l.promo}</Badge>}
                        {!refundMode && itemPromo(l.item_id) && <Badge size="xs" color="orange" variant="outline">{itemPromo(l.item_id)}</Badge>}
                        {l.discount ? <Badge size="xs" color="teal" variant="light">−{l.discount}%</Badge> : null}
                        {l.department_id && <Badge size="xs" variant="outline" color="gray">reparto</Badge>}
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right" style={{ whiteSpace: 'nowrap' }}><Text size="sm" c="dimmed">{qtyFmt(l.quantity)}{l.unit && l.unit !== 'PZ' ? ` ${l.unit.toLowerCase()}` : ''} × {euro(toCents(l.price))}</Text></Table.Td>
                    <Table.Td ta="right" w={110}><Text fw={700}>{euro(lineCents(l))}</Text></Table.Td>
                  </Table.Tr>
                ))}
                {promoLines.map((p, i) => (
                  <Table.Tr key={'promo' + i} bg="var(--mantine-color-orange-0)">
                    <Table.Td colSpan={2}><Group gap={6}><IconDiscount size={16} color="var(--mantine-color-orange-7)" /><Text size="sm" c="orange.9">{p.description}</Text></Group></Table.Td>
                    <Table.Td ta="right"><Text fw={700} c="orange.9">{euro(p.amount_cents)}</Text></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            {!lines.length && (
              <Center h={240}>
                {last ? <LastSale last={last} onPrint={() => print('receipt', last)} onRt={hasRt ? () => courtesyOnRt(last) : undefined} onRetry={() => retryFiscal()} /> : <Text c="dimmed">{market ? 'Passa i prodotti col lettore o digita il codice' : 'Tocca un prodotto o leggi il codice a barre'}</Text>}
              </Center>
            )}
          </ScrollArea>
          {/* azioni sulla riga selezionata */}
          <Group px="sm" py={6} gap={6} style={{ borderTop: '1px solid var(--mantine-color-gray-3)' }}>
            <Button variant="default" size={market ? 'xs' : 'sm'} leftSection={<IconMinus size={16} />} disabled={!selected} onClick={() => selected && (selected.quantity > 1 ? update(selected.key, { quantity: selected.quantity - 1 }) : remove(selected.key))}>1</Button>
            <Button variant="default" size={market ? 'xs' : 'sm'} leftSection={<IconPlus size={16} />} disabled={!selected} onClick={() => selected && update(selected.key, { quantity: selected.quantity + 1 })}>1</Button>
            <Button variant="default" size={market ? 'xs' : 'sm'} disabled={!selected} onClick={askQty}>Quantità <Kbd ml={6} size="xs">F5</Kbd></Button>
            <Button variant="default" size={market ? 'xs' : 'sm'} leftSection={<IconPercentage size={16} />} disabled={!selected} onClick={askDiscount}>Sconto <Kbd ml={6} size="xs">F4</Kbd></Button>
            <Button variant="default" size={market ? 'xs' : 'sm'} leftSection={<IconDiscount size={16} />} disabled={!selected} onClick={askPrice}>Prezzo <Kbd ml={6} size="xs">F7</Kbd></Button>
            <Button variant="light" color="red" size={market ? 'xs' : 'sm'} leftSection={<IconTrash size={16} />} disabled={!selected} onClick={() => remove(selected?.key)}>Storna <Kbd ml={6} size="xs">F8</Kbd></Button>
          </Group>
          {/* campo codice e totale */}
          <Group px="md" py="sm" gap="md" wrap="nowrap" bg="var(--mantine-color-dark-8)" style={{ borderRadius: '0 0 var(--mantine-radius-md) var(--mantine-radius-md)' }}>
            <TextInput ref={inputRef} style={{ flex: 1 }} size="lg" value={input} onChange={(e) => setInput(e.currentTarget.value)} onKeyDown={onInputKey}
              placeholder={mult ? `${qtyFmt(mult)} × … leggi il codice` : 'Codice, barcode o PLU (3*codice per la quantità)'} autoComplete="off"
              leftSection={mult ? <Badge size="lg" color="yellow">{qtyFmt(mult)}×</Badge> : <IconSearch size={18} />} leftSectionWidth={mult ? 64 : 40} />
            <Stack gap={0} align="flex-end">
              <Text c="gray.4" size="sm">{refundMode ? 'DA RIMBORSARE' : 'TOTALE'}</Text>
              <Text c={refundMode ? 'red.3' : 'green.3'} fw={800} style={{ fontSize: 40, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{euro(total)}</Text>
            </Stack>
          </Group>
        </Paper>

        {/* pulsantiera */}
        <Stack style={{ flex: market ? 2 : 4, minWidth: 0 }} gap="sm">
          <Paper withBorder radius="md" p="sm" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <Group justify="space-between" mb={6}>
              <Text fw={600} size="sm">Tasti rapidi</Text>
              <Button size="xs" variant="light" leftSection={<IconSearch size={14} />} onClick={() => setModal('search')}>Cerca articolo <Kbd ml={6} size="xs">F2</Kbd></Button>
            </Group>
            <ScrollArea style={{ flex: 1 }}>
              <SimpleGrid cols={market ? 3 : 4} spacing={8}>
                {quick.map((k: any) => (
                  <QuickKey key={k.type + k.id} label={k.label || k.ref.description || k.ref.name} color={k.color || (k.type === 'department' ? k.ref.color : null)}
                    sub={k.type === 'item' ? (k.ref.price ? euro(toCents(k.ref.price)) : 'prezzo libero') : 'reparto'} image={k.type === 'item' ? k.ref.image : null} big={!market}
                    onClick={() => {
                      if (k.type === 'item') addItem({ item: k.ref }, mult ?? undefined)
                      else addDept(k.ref, input.trim() ? parseAmount(input, market) : undefined)
                      setMult(null); setInput(''); focus()
                    }} />
                ))}
              </SimpleGrid>
              <Divider my="sm" label="Reparti" labelPosition="left" />
              <SimpleGrid cols={market ? 3 : 4} spacing={8}>
                {cat.departments.map((d) => (
                  <QuickKey key={d.id} label={d.name} sub={`IVA ${Number(d.vat_rate)}%`} color={d.color} big={!market}
                    onClick={() => { addDept(d, input.trim() ? parseAmount(input, market) : undefined); setInput(''); focus() }} />
                ))}
              </SimpleGrid>
              {!quick.length && !cat.departments.length && <Text c="dimmed" size="sm">Nessun tasto rapido: si configurano in «Casse e reparti».</Text>}
            </ScrollArea>
          </Paper>
          {!market && <Keypad onKey={(k) => { if (k === 'OK') { if (input.trim()) { const v = input; setInput(''); scan(v) } } else if (k === '⌫') setInput((x) => x.slice(0, -1)); else if (k === '×') { if (/^\d+([.,]\d+)?$/.test(input.trim())) { setMult(parseNum(input)); setInput('') } } else setInput((x) => x + k) }} />}
          <SimpleGrid cols={3} spacing={8}>
            <Button size="md" variant="default" leftSection={<IconUser size={18} />} onClick={() => setModal('customer')}>Cliente <Kbd ml={6} size="xs">F3</Kbd></Button>
            <Button size="md" variant="default" leftSection={<IconArrowBackUp size={18} />} onClick={() => setModal('returns')}>Reso <Kbd ml={6} size="xs">F6</Kbd></Button>
            <Button size="md" variant="default" color="red" leftSection={<IconX size={18} />} disabled={!lines.length} onClick={() => setPrompt({ title: 'Annulla scontrino', label: 'Scrivi SI per svuotare lo scontrino in corso', onOk: (v) => { if (v.trim().toUpperCase() === 'SI') clearCart() } })}>Annulla <Kbd ml={6} size="xs">F9</Kbd></Button>
          </SimpleGrid>
          <Button size="xl" h={72} color={refundMode ? 'red' : 'green'} disabled={!lines.length} onClick={() => setModal('pay')}
            leftSection={refundMode ? <IconArrowBackUp size={28} /> : <IconCash size={28} />} rightSection={<Kbd>F12</Kbd>}>
            {refundMode ? 'Rimborsa' : 'Incassa'} {lines.length ? euro(total) : ''}
          </Button>
        </Stack>
      </Box>

      {/* finestre */}
      <PromptModal p={prompt} market={market} onClose={() => setPrompt(null)} />
      <Modal opened={!!variantOf} onClose={() => setVariantOf(null)} title={variantOf?.item.description} size="lg">
        <SimpleGrid cols={3}>
          {variantOf?.item.variants.map((v) => (
            <Button key={v.id} variant="light" size="lg" h={64} onClick={() => { addItem({ item: variantOf.item, variant_id: v.id }, variantOf.quantity); setVariantOf(null) }}>
              <Stack gap={0} align="center"><span>{v.label}</span><Text size="xs">{v.price ? euro(toCents(v.price)) : ''}</Text></Stack>
            </Button>
          ))}
        </SimpleGrid>
      </Modal>
      {modal === 'pay' && !refundMode && <PayModal total={total} invoice={invoice ? customer : null} lottery={!!cat.settings?.lottery && !invoice}
        nonfiscalAllowed={!invoice && reg.settings?.nonfiscal_allowed !== false && online} onClose={() => setModal(null)} onPay={pay}
        onCashMachine={hasCash && online ? payWithMachine : undefined} />}
      {cashPay && <CashWait key={cashPay.id} payment={cashPay} onDone={cashDone} />}
      {cashModal === 'panel' && <CashPanel registerId={reg.id} canAdmin={canAdminCash} onClose={() => setCashModal(null)} />}
      {cashModal === 'verify' && <CashVerify payments={cashVerify} onClose={() => setCashModal(null)}
        onResolved={(p) => { if (p.receipt) setLast(p.receipt); notifications.show({ message: p.status === 'pagato' ? 'Vendita registrata' : 'Pagamento segnato come non pagato' }); loadCash() }} />}
      {modal === 'buono' && <SellVoucher registerId={reg.id} purchaser={customer ?? undefined} onClose={() => setModal(null)} />}
      {modal === 'pacchetto' && <SellPackage registerId={reg.id} client={customer ?? undefined} onClose={() => setModal(null)} />}
      {modal === 'pay' && refundMode && <RefundModal total={total} onClose={() => setModal(null)} onRefund={refundCart} />}
      {modal === 'search' && <SearchModal cat={cat} onClose={() => setModal(null)} onPick={(it) => { addItem({ item: it }, mult ?? undefined); setMult(null); setModal(null) }} />}
      {modal === 'customer' && <CustomerModal current={customer} invoice={invoice} onClose={() => setModal(null)} online={online}
        onPick={(c, inv) => { setCustomer(c); setInvoice(inv); setModal(null) }} />}
      {modal === 'returns' && <ReturnsModal reg={reg} session={session} online={online} onClose={() => setModal(null)}
        onFree={() => { setRefundMode(true); setModal(null) }} onDone={(r) => { setLast(r); setModal(null); if (reg.settings?.auto_print) print('receipt', r) }} />}
      {modal === 'receipts' && <ReceiptsModal reg={reg} session={session} onClose={() => setModal(null)} onPrint={(r) => print('receipt', r)} onRt={hasRt ? courtesyOnRt : undefined} />}
      {modal === 'move' && <MoveModal session={session} onClose={() => setModal(null)} onDone={(s) => { setSession(s); setModal(null) }} />}
      {modal === 'close' && <CloseModal session={session} pending={outbox.length} onClose={() => setModal(null)} onPrint={(s) => print('session', s)}
        onClosed={(s) => { print('session', s); setTimeout(() => setSession(null), 600) }} />}
      {modal === 'outbox' && <OutboxModal outbox={outbox} onClose={() => setModal(null)} onRetry={() => { setOutbox(outbox.map(({ error: _e, ...p }) => p)); setTimeout(flush, 50) }}
        onDiscard={(i) => setOutbox(outbox.filter((_, n) => n !== i))} />}
    </Box>
  )
}

function beep() {
  try {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)()
    const o = ctx.createOscillator()
    o.frequency.value = 220
    o.connect(ctx.destination)
    o.start(); o.stop(ctx.currentTime + 0.18)
  } catch { /* nessun audio */ }
}

function FiscalBadge({ rt, onRetry }: { rt: any; onRetry?: () => void }) {
  if (!rt) return null
  if (rt.status === 'emesso') return <Badge size="lg" color="green" variant="light">Documento commerciale {rt.z}-{rt.number}{rt.offline ? ' (senza rete)' : ''}{rt.simulated ? ' · simulato' : ''}</Badge>
  if (rt.status === 'errore') return (
    <Alert color="red" p="xs" mt={4} maw={420}>
      <Group gap="xs" wrap="nowrap"><Text size="sm">{rt.error || 'Errore del registratore'}</Text>{onRetry && <Button size="xs" color="red" onClick={onRetry}>Riprova</Button>}</Group>
    </Alert>
  )
  return (
    <Group gap={6}><Loader size="xs" /><Text size="sm" c="dimmed">{rt.status === 'inviato' ? 'Stampa del documento commerciale…' : 'Documento commerciale in coda per il registratore…'}</Text>
      {rt.status === 'inviato' && onRetry && <Button size="xs" variant="subtle" onClick={onRetry}>Riprova</Button>}</Group>
  )
}

function LastSale({ last, onPrint, onRt, onRetry }: { last: any; onPrint: () => void; onRt?: () => void; onRetry: () => void }) {
  return (
    <Stack align="center" gap={4}>
      <Text c="dimmed">{last.offline ? 'Ultimo scontrino (in attesa di invio)' : last.fiscal?.nonfiscal ? `Ricevuta non fiscale n. ${last.number} · ${last.fiscal.nonfiscal.reason}` : last.doc_type === 'RSO' ? `Reso n. ${last.number} registrato` : last.doc_type === 'FTI' ? `Fattura n. ${last.number}/${last.year} emessa` : `Scontrino n. ${last.number} registrato`}</Text>
      <Text fw={700} size="xl">Totale {euro(toCents(last.total))}</Text>
      {Number(last.change) > 0 && <Text fw={800} c="green.8" style={{ fontSize: 44 }}>Resto {euro(toCents(last.change))}</Text>}
      {last.fiscal?.nonfiscal ? <Badge size="lg" color="grape" variant="light">Ricevuta non fiscale</Badge> : <FiscalBadge rt={last.fiscal?.rt} onRetry={last.offline ? undefined : onRetry} />}
      {!last.offline && (
        <Group mt="sm" gap="xs">
          {onRt && last.doc_type === 'SCO' && <Button leftSection={<IconPrinter size={16} />} onClick={onRt}>Copia di cortesia sul registratore</Button>}
          <Button variant="light" leftSection={<IconPrinter size={16} />} onClick={onPrint}>{onRt ? 'Su stampante/PC' : 'Stampa ricevuta di cortesia'}</Button>
        </Group>
      )}
    </Stack>
  )
}

function QuickKey({ label, sub, color, image, big, onClick }: { label: string; sub?: string; color?: string | null; image?: string | null; big?: boolean; onClick: () => void }) {
  const c = color || 'blue'
  return (
    <UnstyledButton onClick={onClick} style={{
      height: big ? 86 : 58, borderRadius: 8, padding: 8, background: `var(--mantine-color-${c}-light)`, border: `1px solid var(--mantine-color-${c}-3)`,
      display: 'flex', gap: 8, alignItems: 'center', overflow: 'hidden',
    }}>
      {image && big && <img src={image} alt="" style={{ width: 52, height: 52, objectFit: 'cover', borderRadius: 6, flexShrink: 0 }} />}
      <Stack gap={0} style={{ minWidth: 0 }}>
        <Text fw={600} size={big ? 'sm' : 'xs'} lineClamp={2} c={`${c}.9`}>{label}</Text>
        {sub && <Text size="xs" c="dimmed">{sub}</Text>}
      </Stack>
    </UnstyledButton>
  )
}

function Keypad({ onKey }: { onKey: (k: string) => void }) {
  const keys = ['7', '8', '9', '4', '5', '6', '1', '2', '3', ',', '0', '⌫']
  return (
    <Paper withBorder radius="md" p={8}>
      <Group gap={8} align="stretch" wrap="nowrap">
        <SimpleGrid cols={3} spacing={6} style={{ flex: 1 }}>
          {keys.map((k) => <Button key={k} variant="default" size="lg" h={48} onClick={() => onKey(k)}>{k === '⌫' ? <IconBackspace size={20} /> : k}</Button>)}
        </SimpleGrid>
        <Stack gap={6} w={90}>
          <Button variant="light" color="yellow" h="100%" style={{ flex: 1 }} onClick={() => onKey('×')}>Q.tà ×</Button>
          <Button color="blue" style={{ flex: 1 }} h="100%" onClick={() => onKey('OK')}>Invio</Button>
        </Stack>
      </Group>
    </Paper>
  )
}

// =====================================================================================================================

function PromptModal({ p, market, onClose }: { p: Prompt | null; market: boolean; onClose: () => void }) {
  const [v, setV] = useState('')
  const [reading, setReading] = useState(false)
  const run = async () => {
    if (!p?.action) return
    setReading(true)
    try { setV(await p.action.run()) } catch (e) { notifyError(e) } finally { setReading(false) }
  }
  useEffect(() => { setV(p?.initial ?? ''); if (p?.action?.auto) run() }, [p])
  const ok = () => { const cb = p?.onOk; onClose(); cb?.(v) }
  return (
    <Modal opened={!!p} onClose={onClose} title={p?.title} centered>
      <TextInput label={p?.label} description={p?.hint} size="lg" value={v} onChange={(e) => setV(e.currentTarget.value)} data-autofocus
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); ok() } }}
        rightSection={p?.action ? <Button size="xs" variant="light" loading={reading} onClick={run}>{p.action.label}</Button> : undefined} rightSectionWidth={p?.action ? 140 : undefined} />
      {!market && (
        <SimpleGrid cols={3} spacing={6} mt="sm">
          {['7', '8', '9', '4', '5', '6', '1', '2', '3', ',', '0', '⌫'].map((k) => (
            <Button key={k} variant="default" size="lg" onClick={() => setV((x) => (k === '⌫' ? x.slice(0, -1) : x + k))}>{k}</Button>
          ))}
        </SimpleGrid>
      )}
      <Group justify="flex-end" mt="md"><Button variant="default" onClick={onClose}>Annulla</Button><Button onClick={ok}>OK</Button></Group>
    </Modal>
  )
}

const NONFISCAL_REASONS = ['Utilizzo di un buono regalo già pagato', 'Seduta di un pacchetto già pagato', 'Pagamento di una fattura già emessa', 'Altro motivo']

function PayModal({ total, invoice, lottery, nonfiscalAllowed, onClose, onPay, onCashMachine }: {
  total: number; invoice: any; lottery: boolean; nonfiscalAllowed: boolean; onClose: () => void
  onPay: (p: { method: string; amount: number }[], lottery: string | null, nonfiscal: string | null, voucherCode: string | null) => Promise<void>
  onCashMachine?: (others: { method: string; amount: number }[], lottery: string | null, nonfiscal: string | null, voucherCode: string | null) => Promise<void>
}) {
  // buono regalo multiuso: si scala dal credito, lo scontrino si emette ora pagato «con buono regalo» (non è un nuovo incasso)
  const [voucher, setVoucher] = useState<any>(null)
  const [askVoucher, setAskVoucher] = useState(false)
  const [vcode, setVcode] = useState('')
  const [doc, setDoc] = useState<'scontrino' | 'ricevuta'>('scontrino')
  const [reason, setReason] = useState(NONFISCAL_REASONS[0])
  const [other, setOther] = useState('')
  const nonfiscal = doc === 'ricevuta' ? (reason === 'Altro motivo' ? other.trim() : reason) : null
  const [pays, setPays] = useState<{ method: string; amount: number }[]>([])
  const [amount, setAmount] = useState('')
  const [lot, setLot] = useState('')
  const [busy, setBusy] = useState(false)
  const paid = pays.reduce((a, p) => a + p.amount, 0)
  const residual = total - paid
  const change = paid - total
  const cash = pays.filter((p) => p.method === 'contanti').reduce((a, p) => a + p.amount, 0)
  const valid = residual <= 0 && (change === 0 || cash >= change) && (!lot || /^[A-Z0-9]{8}$/i.test(lot)) && (doc === 'scontrino' || !!nonfiscal)
  const typed = amount.trim() ? toCents(parseAmount(amount, false)) : residual
  const add = (method: string, cents?: number) => {
    const c = cents ?? typed
    if (!(c > 0)) return
    if (method !== 'contanti' && c > residual) { notifications.show({ color: 'red', message: 'Con carta o buoni non si può superare il dovuto: il resto si dà solo in contanti' }); return }
    setPays((x) => [...x, { method, amount: c }])
    setAmount('')
  }
  // cassa automatica: la macchina incassa ciò che resta dopo carta o buoni già indicati (mai insieme ai contanti a mano)
  const machine = async () => {
    if (!onCashMachine || busy || residual <= 0 || cash > 0 || (doc === 'ricevuta' && !nonfiscal) || (lot && !/^[A-Z0-9]{8}$/i.test(lot))) return
    setBusy(true)
    await onCashMachine(pays, lot ? lot.toUpperCase() : null, nonfiscal, pays.some((p) => p.method === 'buono_regalo') ? voucher?.code ?? null : null)
    setBusy(false)
  }
  const confirm = async () => { if (!valid || busy) return; setBusy(true); await onPay(pays, lot ? lot.toUpperCase() : null, nonfiscal, pays.some((p) => p.method === 'buono_regalo') ? voucher?.code ?? null : null); setBusy(false) }
  const useVoucher = async () => {
    try {
      const v = await appApi(`/api/prepagati/buoni/codice/${encodeURIComponent(vcode.trim())}`)
      if (v.status !== 'attivo' || Number(v.balance) <= 0) throw new Error(`Il buono ${v.code} non è utilizzabile (${v.status})`)
      if (v.fiscal_mode !== 'multiuso') throw new Error(`Il buono ${v.code} è monouso: lo scontrino è già stato fatto alla vendita, usa la ricevuta non fiscale`)
      const c = Math.min(residual, toCents(Number(v.balance)))
      setVoucher(v); setDoc('scontrino'); setAskVoucher(false); setVcode('')
      setPays((x) => [...x.filter((p) => p.method !== 'buono_regalo'), { method: 'buono_regalo', amount: c }])
    } catch (e) { notifyError(e) }
  }
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && valid) { e.preventDefault(); confirm() }
      else if (e.key === 'F1') { e.preventDefault(); add('contanti') } else if (e.key === 'F2') { e.preventDefault(); add('carta') } else if (e.key === 'F3') { e.preventDefault(); add('bancomat') }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  })
  const notes = residual > 0 ? [500, 1000, 2000, 5000, 10000].filter((n) => n > residual).slice(0, 3) : []
  return (
    <Modal opened onClose={onClose} title={invoice ? `Incasso · fattura a ${invoice.name}` : 'Incasso'} size="lg" centered>
      <Group grow mb="md">
        <Paper withBorder p="sm" ta="center"><Text size="sm" c="dimmed">Totale</Text><Text fw={800} size="28px">{euro(total)}</Text></Paper>
        <Paper withBorder p="sm" ta="center" bg={residual > 0 ? 'yellow.0' : 'green.0'}>
          <Text size="sm" c="dimmed">{residual > 0 ? 'Da pagare' : 'Resto'}</Text>
          <Text fw={800} size="28px" c={residual > 0 ? undefined : 'green.8'}>{euro(residual > 0 ? residual : change)}</Text>
        </Paper>
      </Group>
      {residual > 0 && (
        <>
          <TextInput size="lg" label="Importo ricevuto" placeholder={centsStr(residual).replace('.', ',')} value={amount} onChange={(e) => setAmount(e.currentTarget.value)} data-autofocus
            description="Lascia vuoto per l'importo esatto · F1 contanti · F2 carta · F3 bancomat" />
          <Group mt="sm" gap={6}>
            <Button variant="light" color="green" onClick={() => add('contanti', residual)}>Contanti esatti</Button>
            {notes.map((n) => <Button key={n} variant="light" color="green" onClick={() => add('contanti', n)}>{euro(n)}</Button>)}
          </Group>
          {!voucher && (askVoucher ? (
            <Group mt="sm" align="flex-end">
              <TextInput style={{ flex: 1 }} label="Codice del buono regalo" placeholder="BR-XXXX-XXXX (o leggilo col lettore)" value={vcode} data-autofocus data-testid="cassa-codice-buono"
                onChange={(e) => setVcode(e.currentTarget.value.toUpperCase())} onKeyDown={(e) => { if (e.key === 'Enter' && vcode.trim()) { e.preventDefault(); e.stopPropagation(); useVoucher() } }} />
              <Button color="grape" disabled={!vcode.trim()} onClick={useVoucher}>Usa il buono</Button>
            </Group>
          ) : !invoice && <Button mt="sm" variant="light" color="grape" leftSection={<IconGift size={18} />} onClick={() => setAskVoucher(true)} data-testid="cassa-paga-buono">Paga con un buono regalo</Button>)}
          {onCashMachine && (
            <Button mt="sm" fullWidth size="lg" color="teal" leftSection={<IconCash size={22} />} loading={busy} disabled={cash > 0} onClick={machine}
              data-testid="cassa-automatica">Cassa automatica · {euro(residual)}</Button>
          )}
          <SimpleGrid cols={4} mt="sm" spacing={6}>
            {METHODS.map((m) => (
              <Button key={m.value} size="md" variant={m.value === 'contanti' ? 'filled' : 'light'} color={m.value === 'contanti' ? 'green' : 'blue'}
                leftSection={m.value === 'contanti' ? <IconCash size={18} /> : m.value === 'carta' || m.value === 'bancomat' ? <IconCreditCard size={18} /> : null}
                onClick={() => add(m.value)}>{m.short}</Button>
            ))}
          </SimpleGrid>
        </>
      )}
      {pays.length > 0 && (
        <Table mt="md" fz="md">
          <Table.Tbody>
            {pays.map((p, i) => (
              <Table.Tr key={i}><Table.Td>{p.method === 'buono_regalo' ? `Buono regalo ${voucher?.code ?? ''}` : methodLabel(p.method)}</Table.Td><Table.Td ta="right" fw={600}>{euro(p.amount)}</Table.Td>
                <Table.Td w={40}><ActionIcon variant="subtle" color="red" onClick={() => { if (p.method === 'buono_regalo') setVoucher(null); setPays(pays.filter((_, n) => n !== i)) }}><IconTrash size={16} /></ActionIcon></Table.Td></Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {change > 0 && cash < change && <Alert color="red" mt="sm">Il resto si dà solo sul contante: togli l'eccedenza su carta o buoni.</Alert>}
      {voucher && <Alert color="grape" mt="sm" icon={<IconGift />}>Buono {voucher.code}: dopo questo scontrino restano {euro(toCents(Number(voucher.balance)) - (pays.find((p) => p.method === 'buono_regalo')?.amount ?? 0))}.
        Lo scontrino è pagato «con buono regalo» (già incassato alla vendita); se resta credito esce anche la ricevuta del saldo.</Alert>}
      {nonfiscalAllowed && !voucher && (
        <Paper withBorder p="sm" mt="md" radius="md">
          <SegmentedControl fullWidth size="md" value={doc} onChange={(v) => setDoc(v as any)} data-testid="tipo-documento"
            data={[{ value: 'scontrino', label: 'Scontrino fiscale' }, { value: 'ricevuta', label: 'Ricevuta non fiscale' }]} />
          {doc === 'ricevuta' && (
            <Stack gap={6} mt="sm">
              <Select label="Motivo (stampato sulla ricevuta)" data={NONFISCAL_REASONS} value={reason} onChange={(v) => setReason(v || NONFISCAL_REASONS[0])} allowDeselect={false} />
              {reason === 'Altro motivo' && <TextInput placeholder="Scrivi il motivo" maxLength={120} value={other} onChange={(e) => setOther(e.currentTarget.value)} data-autofocus />}
              <Text size="xs" c="dimmed">Esce sul registratore come documento non fiscale. Usala solo quando lo scontrino non è dovuto:
                ogni incasso va certificato con scontrino o fattura.</Text>
            </Stack>
          )}
        </Paper>
      )}
      {lottery && doc === 'scontrino' && <TextInput mt="md" label="Codice lotteria degli scontrini (facoltativo)" maxLength={8} value={lot} onChange={(e) => setLot(e.currentTarget.value.toUpperCase())} />}
      <Group justify="space-between" mt="lg">
        <Button variant="default" onClick={onClose}>Indietro</Button>
        <Button size="lg" color="green" disabled={!valid} loading={busy} onClick={confirm} rightSection={<Kbd>Invio</Kbd>}>
          {invoice ? 'Emetti fattura' : doc === 'ricevuta' ? 'Stampa ricevuta non fiscale' : 'Chiudi scontrino'}
        </Button>
      </Group>
    </Modal>
  )
}

function RefundModal({ total, onClose, onRefund }: { total: number; onClose: () => void; onRefund: (m: string, restock: boolean, reason: string) => void }) {
  const [method, setMethod] = useState('contanti')
  const [restock, setRestock] = useState(true)
  const [reason, setReason] = useState('')
  return (
    <Modal opened onClose={onClose} title="Reso senza scontrino" centered>
      <Text fw={800} size="28px" c="red" ta="center" mb="md">Rimborso {euro(total)}</Text>
      <SegmentedControl fullWidth value={method} onChange={setMethod} data={METHODS.slice(0, 4).map((m) => ({ value: m.value, label: m.short }))} />
      <Switch mt="md" label="La merce rientra in magazzino" checked={restock} onChange={(e) => setRestock(e.currentTarget.checked)} />
      <TextInput mt="md" label="Motivo" value={reason} onChange={(e) => setReason(e.currentTarget.value)} placeholder="es. merce difettosa" />
      <Group justify="flex-end" mt="lg"><Button variant="default" onClick={onClose}>Indietro</Button><Button color="red" onClick={() => onRefund(method, restock, reason)}>Registra il reso</Button></Group>
    </Modal>
  )
}

function SearchModal({ cat, onClose, onPick }: { cat: Catalog; onClose: () => void; onPick: (it: CatItem) => void }) {
  const [q, setQ] = useState('')
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase()
    const words = t.split(/\s+/).filter(Boolean)
    return cat.items.filter((i) => !words.length || words.every((w) => i.description.toLowerCase().includes(w) || i.code.toLowerCase().includes(w))).slice(0, 60)
  }, [q, cat])
  return (
    <Modal opened onClose={onClose} title="Cerca articolo" size="xl">
      <TextInput size="lg" placeholder="Descrizione o codice" value={q} onChange={(e) => setQ(e.currentTarget.value)} data-autofocus
        onKeyDown={(e) => { if (e.key === 'Enter' && rows[0]) onPick(rows[0]) }} />
      <ScrollArea h={460} mt="sm">
        <SimpleGrid cols={3} spacing={8}>
          {rows.map((i) => (
            <UnstyledButton key={i.id} onClick={() => onPick(i)} style={{ border: '1px solid var(--mantine-color-gray-3)', borderRadius: 8, padding: 8, display: 'flex', gap: 8 }}>
              {i.image ? <img src={i.image} alt="" style={{ width: 48, height: 48, objectFit: 'cover', borderRadius: 6 }} /> : <Box w={48} h={48} bg="gray.1" style={{ borderRadius: 6 }} />}
              <Stack gap={0} style={{ minWidth: 0 }}>
                <Text size="sm" fw={600} lineClamp={2}>{i.description}</Text>
                <Group gap={6}><Text size="xs" c="dimmed" ff="monospace">{i.code}</Text>{i.price && <Text size="sm" fw={700}>{euro(toCents(i.price))}</Text>}{i.promo && <Badge size="xs" color="orange">promo</Badge>}</Group>
              </Stack>
            </UnstyledButton>
          ))}
        </SimpleGrid>
      </ScrollArea>
    </Modal>
  )
}

function CustomerModal({ current, invoice, online, onClose, onPick }: { current: any; invoice: boolean; online: boolean; onClose: () => void; onPick: (c: any, invoice: boolean) => void }) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<any[]>([])
  const [inv, setInv] = useState(invoice)
  useEffect(() => {
    if (!online) return
    const t = setTimeout(() => P(`/clienti?q=${encodeURIComponent(q)}`).then(setRows).catch(() => {}), 200)
    return () => clearTimeout(t)
  }, [q])
  return (
    <Modal opened onClose={onClose} title="Cliente" size="lg">
      {!online && <Alert color="orange" mb="sm">Senza connessione non si possono cercare i clienti né emettere fatture.</Alert>}
      <Switch mb="sm" label="Emetti fattura (invece dello scontrino)" description="Serve un cliente con dati fiscali e indirizzo completi" checked={inv} onChange={(e) => setInv(e.currentTarget.checked)} />
      <TextInput placeholder="Nome, partita IVA, codice fiscale o telefono" value={q} onChange={(e) => setQ(e.currentTarget.value)} data-autofocus leftSection={<IconSearch size={16} />} />
      <ScrollArea h={340} mt="sm">
        <Table highlightOnHover>
          <Table.Tbody>
            {rows.map((c) => (
              <Table.Tr key={c.id} style={{ cursor: c.can_invoice || !inv ? 'pointer' : 'not-allowed', opacity: !inv || c.can_invoice ? 1 : 0.5 }}
                onClick={() => { if (!inv || c.can_invoice) onPick(c, inv) }}>
                <Table.Td><Text fw={500}>{c.name}</Text><Text size="xs" c="dimmed">{[c.vat_number && `P.IVA ${c.vat_number}`, c.tax_code, c.city].filter(Boolean).join(' · ')}</Text></Table.Td>
                <Table.Td ta="right">{inv && !c.can_invoice && <Badge color="gray" variant="light">dati incompleti</Badge>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      <Group justify="space-between" mt="md">
        {current ? <Button variant="subtle" color="red" onClick={() => onPick(null, false)}>Togli il cliente</Button> : <span />}
        <Button variant="default" onClick={onClose}>Chiudi</Button>
      </Group>
    </Modal>
  )
}

function ReturnsModal({ reg, session, online, onClose, onFree, onDone }: { reg: any; session: any; online: boolean; onClose: () => void; onFree: () => void; onDone: (r: any) => void }) {
  const [rows, setRows] = useState<any[]>([])
  const [q, setQ] = useState('')
  const [doc, setDoc] = useState<any>(null)
  const [qty, setQty] = useState<Record<string, number>>({})
  const [method, setMethod] = useState('contanti')
  const [restock, setRestock] = useState(true)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (online) P(`/scontrini?register_id=${reg.id}&limit=40${q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ''}`).then((r) => setRows(r.filter((x: any) => x.doc_type === 'SCO'))).catch(notifyError) }, [q])
  async function pick(id: string) {
    try {
      const d = await P(`/scontrini/${id}`)
      setDoc(d)
      setQty({})
      const cash = d.payments.find((p: any) => p.method !== 'contanti')
      setMethod(cash ? cash.method : 'contanti')
    } catch (e) { notifyError(e) }
  }
  const sel = doc ? doc.lines.filter((l: any) => qty[l.id] > 0) : []
  const refund = sel.reduce((a: number, l: any) => a + lineCents({ price: Number(l.unit_price_gross), quantity: qty[l.id], discount: Number(l.discount || 0) }), 0)
  async function confirm(all = false) {
    const lines = (all ? doc.lines.map((l: any) => ({ ...l, q: Number(l.returnable) })) : sel.map((l: any) => ({ ...l, q: qty[l.id] }))).filter((l: any) => l.q > 0)
    if (!lines.length) return
    setBusy(true)
    try {
      const r = await P(`/casse/${reg.id}/resi`, { body: {
        client_uuid: uuid4(), session_id: session.id, original_id: doc.id, void: all, restock, reason: reason || null, refund_method: method,
        lines: lines.map((l: any) => ({ item_id: l.item_id, description: l.description, quantity: String(l.q), unit_price_gross: l.unit_price_gross, discount: l.discount, origin_line_id: l.id, lot_number: l.lot_number, serials: l.serials })),
      } })
      onDone(r)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Modal opened onClose={onClose} title={doc ? `Reso dallo scontrino n. ${doc.number} del ${new Date(doc.date).toLocaleDateString('it-IT')}` : 'Reso o annullo'} size="xl">
      {!online && <Alert color="orange" mb="sm">Senza connessione si può fare solo il reso senza scontrino.</Alert>}
      {!doc ? (
        <>
          <Group mb="sm">
            <TextInput style={{ flex: 1 }} placeholder="Numero dello scontrino" value={q} onChange={(e) => setQ(e.currentTarget.value)} data-autofocus leftSection={<IconSearch size={16} />} />
            <Button variant="light" color="red" onClick={onFree}>Reso senza scontrino</Button>
          </Group>
          <ScrollArea h={380}>
            <Table highlightOnHover>
              <Table.Thead><Table.Tr><Table.Th>N.</Table.Th><Table.Th>Data e ora</Table.Th><Table.Th>Righe</Table.Th><Table.Th ta="right">Totale</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((r) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => pick(r.id)}>
                    <Table.Td fw={600}>{r.number}</Table.Td><Table.Td>{new Date(r.created_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Table.Td>
                    <Table.Td>{r.lines}</Table.Td><Table.Td ta="right">{euro(toCents(r.total))}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </>
      ) : (
        <>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th ta="right">Venduto</Table.Th><Table.Th ta="right">Prezzo</Table.Th><Table.Th w={140}>Da rendere</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {doc.lines.map((l: any) => (
                <Table.Tr key={l.id}>
                  <Table.Td>{l.description}</Table.Td>
                  <Table.Td ta="right">{qtyFmt(Number(l.quantity))}{Number(l.returnable) < Number(l.quantity) && <Text size="xs" c="dimmed">già resi {qtyFmt(Number(l.quantity) - Number(l.returnable))}</Text>}</Table.Td>
                  <Table.Td ta="right">{euro(toCents(l.unit_price_gross))}{l.discount && <Text size="xs" c="dimmed">−{Number(l.discount)}%</Text>}</Table.Td>
                  <Table.Td><NumberInput size="sm" min={0} max={Number(l.returnable)} decimalScale={3} disabled={Number(l.returnable) <= 0}
                    value={qty[l.id] ?? ''} onChange={(v) => setQty({ ...qty, [l.id]: Number(v) || 0 })} /></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Group mt="md" align="flex-end">
            <SegmentedControl value={method} onChange={setMethod} data={METHODS.slice(0, 4).map((m) => ({ value: m.value, label: m.short }))} />
            <Switch label="Rientro in magazzino" checked={restock} onChange={(e) => setRestock(e.currentTarget.checked)} />
            <TextInput style={{ flex: 1 }} placeholder="Motivo (facoltativo)" value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          </Group>
          <Group justify="space-between" mt="lg">
            <Button variant="default" onClick={() => setDoc(null)}>Altro scontrino</Button>
            <Group>
              <Button variant="light" color="red" loading={busy} disabled={doc.lines.every((l: any) => Number(l.returnable) <= 0)} onClick={() => confirm(true)}>Annulla tutto lo scontrino</Button>
              <Button color="red" loading={busy} disabled={!sel.length} onClick={() => confirm(false)}>Rimborsa {euro(refund)}</Button>
            </Group>
          </Group>
        </>
      )}
    </Modal>
  )
}

function ReceiptsModal({ reg, session, onClose, onPrint, onRt }: { reg: any; session: any; onClose: () => void; onPrint: (r: any) => void; onRt?: (r: any) => void }) {
  const [rows, setRows] = useState<any[] | null>(null)
  const [doc, setDoc] = useState<any>(null)
  useEffect(() => { P(`/scontrini?session_id=${session.id}&limit=200`).then(setRows).catch(notifyError) }, [])
  const label: Record<string, string> = { SCO: 'Scontrino', RSO: 'Reso', FTI: 'Fattura' }
  return (
    <Modal opened onClose={onClose} title={`Documenti di questa apertura · ${reg.name}`} size="xl">
      {!rows ? <Loader /> : (
        <Group align="flex-start" wrap="nowrap">
          <ScrollArea h={480} style={{ flex: 1 }}>
            <Table highlightOnHover>
              <Table.Tbody>
                {rows.map((r) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} bg={doc?.id === r.id ? 'blue.0' : undefined} onClick={() => P(`/scontrini/${r.id}`).then(setDoc).catch(notifyError)}>
                    <Table.Td><Badge variant="light" color={r.doc_type === 'RSO' ? 'red' : r.doc_type === 'FTI' ? 'grape' : 'blue'}>{label[r.doc_type]} {r.number}</Badge></Table.Td>
                    <Table.Td>{new Date(r.created_at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}</Table.Td>
                    <Table.Td ta="right" fw={600}>{r.doc_type === 'RSO' ? '−' : ''}{euro(toCents(r.total))}</Table.Td>
                  </Table.Tr>
                ))}
                {!rows.length && <Table.Tr><Table.Td><Text c="dimmed" ta="center" py="lg">Nessun documento</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </ScrollArea>
          <Paper withBorder p="sm" w={320} mih={200}>
            {doc ? (
              <>
                <div style={{ maxHeight: 400, overflow: 'auto' }}><ReceiptPrint r={doc} company={null} register={reg.name} /></div>
                {onRt && doc.doc_type === 'SCO' && <Button fullWidth mt="sm" leftSection={<IconPrinter size={16} />} onClick={() => onRt(doc)}>Copia di cortesia sul registratore</Button>}
                <Button fullWidth mt="sm" variant="light" leftSection={<IconPrinter size={16} />} onClick={() => onPrint(doc)}>{onRt ? 'Ristampa cortesia (stampante/PC)' : 'Ristampa cortesia'}</Button>
              </>
            ) : <Text c="dimmed" size="sm">Scegli un documento per vederlo e ristamparlo</Text>}
          </Paper>
        </Group>
      )}
    </Modal>
  )
}

function MoveModal({ session, onClose, onDone }: { session: any; onClose: () => void; onDone: (s: any) => void }) {
  const [kind, setKind] = useState('prelievo')
  const [amount, setAmount] = useState<string | number>('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    try { onDone(await P(`/aperture/${session.id}/movimenti`, { body: { kind, amount: String(amount), reason: reason || null } })); notifications.show({ color: 'green', message: kind === 'prelievo' ? 'Prelievo registrato' : 'Versamento registrato' }) } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Modal opened onClose={onClose} title="Prelievo o versamento di contante" centered>
      <SegmentedControl fullWidth value={kind} onChange={setKind} data={[{ value: 'prelievo', label: 'Prelievo dal cassetto' }, { value: 'versamento', label: 'Versamento nel cassetto' }]} />
      <NumberInput mt="md" size="lg" label="Importo" decimalScale={2} decimalSeparator="," min={0} suffix=" €" value={amount} onChange={setAmount} data-autofocus />
      <TextInput mt="md" label="Motivo" placeholder={kind === 'prelievo' ? 'es. versamento in banca, pagamento fornitore' : 'es. cambio monete'} value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
      <Group justify="flex-end" mt="lg"><Button variant="default" onClick={onClose}>Annulla</Button><Button loading={busy} disabled={!(Number(amount) > 0)} onClick={save}>Registra</Button></Group>
    </Modal>
  )
}

function CloseModal({ session, pending, onClose, onPrint, onClosed }: { session: any; pending: number; onClose: () => void; onPrint: (s: any) => void; onClosed: (s: any) => void }) {
  const [ses, setSes] = useState<any>(null)
  const [counted, setCounted] = useState<string | number>('')
  const [z, setZ] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { P(`/aperture/${session.id}`).then(setSes).catch(notifyError) }, [])
  if (!ses) return <Modal opened onClose={onClose} title="Chiusura di cassa"><Loader /></Modal>
  const s = ses.summary
  const diff = counted === '' ? null : toCents(counted) - toCents(s.expected_cash)
  async function close() {
    setBusy(true)
    try { onClosed(await P(`/aperture/${session.id}/chiudi`, { body: { counted_cash: String(counted || 0), z_number: z || null, notes: notes || null } })) } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  const row = (l: string, v: any, strong = false) => <Group justify="space-between"><Text size="sm" fw={strong ? 700 : 400}>{l}</Text><Text size="sm" fw={strong ? 700 : 500}>{v}</Text></Group>
  return (
    <Modal opened onClose={onClose} title="Chiusura di cassa" size="lg">
      {pending > 0 && <Alert color="orange" mb="sm">Ci sono {pending} scontrini non ancora inviati: torna online prima di chiudere, altrimenti non entrano nel riepilogo.</Alert>}
      <SimpleGrid cols={2} spacing="lg">
        <Stack gap={4}>
          <Text fw={600}>Incassi</Text>
          {row('Scontrini', s.receipts)}
          {row('Vendite', euro(toCents(s.sales_total)))}
          {row('Resi', (toCents(s.returns_total) ? '−' : '') + euro(toCents(s.returns_total)))}
          {row('Netto', euro(toCents(s.net_total)), true)}
          <Divider my={4} />
          {Object.entries(s.by_method).map(([m, v]: any) => <div key={m}>{row(`${v.label} (${v.count})`, euro(toCents(v.amount)))}</div>)}
        </Stack>
        <Stack gap={4}>
          <Text fw={600}>Contante</Text>
          {row('Fondo iniziale', euro(toCents(s.opening_float)))}
          {row('Versamenti', euro(toCents(s.deposits)))}
          {row('Prelievi', (toCents(s.withdrawals) ? '−' : '') + euro(toCents(s.withdrawals)))}
          {row('Contante atteso', euro(toCents(s.expected_cash)), true)}
          <NumberInput mt="sm" size="md" label="Contante contato nel cassetto" decimalScale={2} decimalSeparator="," min={0} suffix=" €" value={counted} onChange={setCounted} data-autofocus />
          {diff !== null && <Text fw={700} c={diff === 0 ? 'green' : 'red'}>{diff === 0 ? 'Quadra' : `Differenza ${diff > 0 ? '+' : ''}${euro(diff)}`}</Text>}
        </Stack>
      </SimpleGrid>
      <Group grow mt="md">
        <TextInput label="Numero chiusura (Z) del registratore" value={z} onChange={(e) => setZ(e.currentTarget.value)} />
        <TextInput label="Note" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
      </Group>
      <Group justify="space-between" mt="lg">
        <Button variant="default" leftSection={<IconPrinter size={16} />} onClick={() => onPrint(ses)}>Stampa riepilogo (X)</Button>
        <Group><Button variant="default" onClick={onClose}>Annulla</Button><Button color="red" leftSection={<IconLock size={16} />} loading={busy} disabled={counted === ''} onClick={close}>Chiudi la cassa</Button></Group>
      </Group>
    </Modal>
  )
}

function OutboxModal({ outbox, onClose, onRetry, onDiscard }: { outbox: Pending[]; onClose: () => void; onRetry: () => void; onDiscard: (i: number) => void }) {
  return (
    <Modal opened onClose={onClose} title="Scontrini in attesa di invio" size="lg">
      <Text size="sm" c="dimmed" mb="sm">Registrati in cassa senza connessione: partono da soli appena torna la rete. Quelli con errore vanno controllati.</Text>
      <Table>
        <Table.Tbody>
          {outbox.map((p, i) => (
            <Table.Tr key={i}>
              <Table.Td>{p.kind === 'vendita' ? 'Scontrino' : 'Reso'} · {new Date(p.at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Table.Td>
              <Table.Td ta="right" fw={600}>{euro(p.total)}</Table.Td>
              <Table.Td>{p.error ? <Text size="xs" c="red">{p.error}</Text> : <Badge color="yellow" variant="light">in coda</Badge>}</Table.Td>
              <Table.Td w={40}>{p.error && <ActionIcon color="red" variant="subtle" onClick={() => onDiscard(i)}><IconTrash size={16} /></ActionIcon>}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group justify="flex-end" mt="md"><Button variant="default" onClick={onClose}>Chiudi</Button><Button onClick={onRetry}>Riprova ora</Button></Group>
    </Modal>
  )
}
