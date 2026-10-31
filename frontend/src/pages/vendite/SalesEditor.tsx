import {
  ActionIcon, Alert, Anchor, Badge, Button, Checkbox, Collapse, Divider, Drawer, Group, Menu, Modal, NumberInput, Paper,
  Select, SimpleGrid, Stack, Switch, Table, TagsInput, Text, TextInput, Textarea, Title, Tooltip, UnstyledButton,
} from '@mantine/core'
import {
  IconAlertTriangle, IconArrowLeft, IconChevronDown, IconCopy, IconEye, IconFileDescription, IconInfoCircle, IconPlus, IconPrinter, IconTrash, IconTruck,
} from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { ApiError, appApi, fmtDate, fmtEuro } from '../../api'
import { Loading, notifyError, notifyOk } from '../../components'
import { dec, num, useLookups } from '../anagrafiche/shared'
import { ItemScanner } from '../magazzino/Operation'
import { useWarehouses } from '../magazzino/shared'
import SdiPanel from '../fatturapa/SdiPanel'
import { useModule } from '../fatturapa/shared'
import { CustomerPicker, S, TITLE, StatusBadge, docNumber, useMe } from './shared'

const EMPTY_LINE = { item_id: null, variant_id: null, description: '', unit: '', quantity: 1, unit_price: '', discount1: '', discount2: '', discount3: '', vat_rate_id: null, lot_number: '', serials: [] as string[], price_source: null, unit_cost: null }
// Passaggi successivi: [tipo, etichetta del pulsante]. Il primo è il pulsante principale, gli altri sono nel menu accanto.
const NEXT: Record<string, [string, string][]> = {
  PRV: [['ORC', 'Trasforma in ordine'], ['DDT', 'Trasforma in DDT'], ['FTI', 'Trasforma in fattura']],
  ORC: [['DDT', 'Crea DDT'], ['FTI', 'Crea fattura']],
  DDT: [['FTD', 'Crea fattura']],
}
const CAUSALI = ['Vendita', 'Conto visione', 'Conto lavorazione', 'Reso', 'Omaggio', 'Riparazione', 'Sostituzione in garanzia']

const net = (l: any) => {
  let p = Number(l.unit_price || 0)
  for (const x of [l.discount1, l.discount2, l.discount3]) if (x) p = (p * (100 - Number(x))) / 100
  return p
}
// Matricole solo sui documenti che muovono la merce: in preventivi e ordini la quantità si scrive normalmente
const NO_SERIALS = ['PRV', 'ORC']
const bySerials = (l: any, t?: string) => !!l.serial_managed && !NO_SERIALS.includes(t ?? '')
const lineQty = (l: any, t?: string) => Number(bySerials(l, t) ? (l.serials?.length ?? 0) : l.quantity || 0)
const lineTotal = (l: any, t?: string) => Math.round(net(l) * lineQty(l, t) * 100) / 100
const pct = (v: number) => `${v.toLocaleString('it-IT', { maximumFractionDigits: 1 })}%`

export default function SalesEditor() {
  const { id } = useParams()
  const isNew = id === 'nuovo'
  const [params] = useSearchParams()
  const nav = useNavigate()
  const me = useMe()
  const L = useLookups()
  const whs = useWarehouses()
  const [d, setD] = useState<any>(null)
  const [party, setParty] = useState<any>(null)
  const [credit, setCredit] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [infoLine, setInfoLine] = useState<number | null>(null)
  const [atts, setAtts] = useState<Record<string, any[]>>({})
  const [transformTo, setTransformTo] = useState<string | null>(null)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [cfg, setCfg] = useState<any>(null)
  const [creditBlock, setCreditBlock] = useState<string | null>(null)
  const [showTransport, setShowTransport] = useState(false)
  const isAdmin = ['amministratore', 'amministrazione'].includes(me?.user?.role)
  const fatturapa = useModule('fatturapa')

  useEffect(() => {
    if (isNew) {
      const t = params.get('tipo') || 'PRV'
      const valid = new Date(); valid.setDate(valid.getDate() + 30)
      setD({ doc_type: t, party_id: params.get('cliente'), doc_date: '', warehouse_id: null, destination_id: null, payment_term_id: null,
        moves_stock: t === 'DDT' || t === 'FTI', reference: '', notes: '', status: 'bozza', lines: [], related: [],
        valid_until: t === 'PRV' ? valid.toISOString().slice(0, 10) : '', transport: t === 'DDT' ? { causale: 'Vendita', porto: 'Franco', a_cura: 'Mittente' } : {},
        attachment_ids: [], print_options: { long_descriptions: t === 'PRV', images: false, show_prices: t !== 'DDT' } })
    } else S(`/documenti/${id}`).then(setD).catch(notifyError)
  }, [id])
  useEffect(() => { S('/impostazioni').then(setCfg).catch(() => setCfg(null)) }, [])
  useEffect(() => { if (d && !d.warehouse_id && whs?.length) setD((c: any) => ({ ...c, warehouse_id: whs[0].id })) }, [whs, d?.doc_type])
  // cliente: destinazioni, condizioni, fido
  useEffect(() => {
    if (!d?.party_id) { setParty(null); setCredit(null); return }
    appApi(`/api/anagrafiche/soggetti/${d.party_id}`).then((p) => {
      setParty(p)
      if (isNew || d.status === 'bozza') setD((c: any) => ({ ...c, payment_term_id: c.payment_term_id ?? p.payment_term_id, destination_id: c.destination_id ?? p.addresses?.find((a: any) => a.is_default)?.id ?? null }))
    }).catch(notifyError)
    S(`/clienti/${d.party_id}/fido`).then(setCredit).catch(() => setCredit(null))
  }, [d?.party_id])
  // schede tecniche degli articoli presenti (per allegarle a preventivi e ordini)
  useEffect(() => {
    if (!d) return
    const ids = [...new Set(d.lines.map((l: any) => l.item_id).filter(Boolean))] as string[]
    ids.filter((i) => !(i in atts)).forEach((i) => appApi(`/api/anagrafiche/articoli/${i}/allegati`).then((r) => setAtts((a) => ({ ...a, [i]: r }))).catch(() => {}))
  }, [d?.lines?.length])

  if (!d || !L || !whs) return <Loading />
  const draft = d.status === 'bozza'
  const t = d.doc_type
  const set = (k: string, v: any) => setD((c: any) => ({ ...c, [k]: v }))
  const setT = (k: string, v: any) => setD((c: any) => ({ ...c, transport: { ...c.transport, [k]: v } }))
  const setPO = (k: string, v: any) => setD((c: any) => ({ ...c, print_options: { ...c.print_options, [k]: v } }))
  const updLine = (i: number, patch: any) => setD((c: any) => ({ ...c, lines: c.lines.map((l: any, j: number) => (j === i ? { ...l, ...patch } : l)) }))
  const vatOf = (l: any) => Number(L.vat.find((v) => v.id === l.vat_rate_id)?.rate ?? l.vat_rate ?? 0)
  const taxable = d.lines.reduce((s: number, l: any) => s + lineTotal(l, t), 0)
  const groups: Record<string, number> = {}
  d.lines.forEach((l: any) => { const r = vatOf(l); groups[r] = (groups[r] ?? 0) + lineTotal(l, t) })
  const vat = Object.entries(groups).reduce((s, [r, v]) => s + Math.round(v * Number(r)) / 100, 0)
  // imposta di bollo: 2 € sulle fatture con importi senza IVA oltre 77,47 € (non per esportazioni, intra UE, reverse charge)
  const natureOf = (l: any) => L.vat.find((v) => v.id === l.vat_rate_id)?.nature ?? l.vat_nature ?? ''
  const stampBase = d.lines.reduce((s: number, l: any) => s + (!vatOf(l) && !/^(N3\.[1-4]|N6|N7)/.test(natureOf(l)) ? lineTotal(l, t) : 0), 0)
  const stamp = draft ? (cfg && cfg.bollo_mode !== 'no' && ['FTI', 'FTD', 'NC'].includes(t) && stampBase > 77.47 ? 2 : 0) : Number(d.stamp_duty || 0)
  const stampCharged = draft ? cfg?.bollo_mode === 'cliente' : Math.abs(Number(d.total) - Number(d.taxable_total) - Number(d.vat_total) - stamp) < 0.005
  const total = taxable + vat + (stampCharged ? stamp : 0)
  const seriesKey = ['FTI', 'FTD', 'NC'].includes(t) ? 'FT' : t
  const seriesOpts: any[] = cfg?.series?.[seriesKey] ?? []
  const series = d.series ?? cfg?.default_series?.[seriesKey] ?? ''
  const nextNo = cfg?.counters?.find((c: any) => c.key === seriesKey && c.series === series && c.year === Number((d.doc_date || new Date().toISOString()).slice(0, 4)))?.next_number
  const showCosts = d.lines.some((l: any) => l.unit_cost != null)
  const cost = d.lines.reduce((s: number, l: any) => s + (l.unit_cost != null ? Number(l.unit_cost) * lineQty(l, t) : 0), 0)
  const allAtts = Object.values(atts).flat()
  const creditAfter = credit?.limit != null ? Number(credit.exposure.total) + (draft && ['ORC', 'DDT', 'FTI'].includes(t) ? total : 0) : null

  async function priceFor(item_id: string, variant_id: string | null, qty: number) {
    const p = new URLSearchParams({ item_id, qty: String(qty || 1) })
    if (d.party_id) p.set('party_id', d.party_id)
    if (variant_id) p.set('variant_id', variant_id)
    if (d.doc_date) p.set('on', d.doc_date)
    return S('/info-riga?' + p)
  }

  async function addItem(it: any) {
    try {
      const info = await priceFor(it.id, it.variant_id ?? null, 1)
      const a = info.item
      const exemption = party?.vat_rate_id
      setD((c: any) => ({ ...c, lines: [...c.lines, {
        ...EMPTY_LINE, item_id: a.id, item_code: a.code, description: a.description, unit: a.unit, variant_id: it.variant_id ?? null,
        variants: it.variants, lot_managed: a.lot_managed, serial_managed: a.serial_managed, quantity: bySerials(a, t) ? 0 : 1,
        unit_price: Number(info.price.unit_price ?? 0), price_source: info.price.source_label, price_auto: true,
        vat_rate_id: exemption || a.vat_rate_id || L!.vat.find((v) => v.code === '22')?.id, unit_cost: info.costs?.cost ?? null,
      }] }))
      if (['PRV', 'ORC'].includes(t)) {
        const auto = info.attachments.filter((x: any) => x.attach_to_quotes).map((x: any) => x.id)
        if (auto.length) setD((c: any) => ({ ...c, attachment_ids: [...new Set([...(c.attachment_ids ?? []), ...auto])] }))
      }
      if (info.item.stock_managed && Number(info.stock.available) <= 0 && ['ORC', 'DDT', 'FTI'].includes(t)) {
        notifyError(new Error(`${a.code}: disponibilità ${Number(info.stock.available)} ${a.unit}${Number(info.stock.ordered) > 0 ? ` (in arrivo ${Number(info.stock.ordered)})` : ''}`))
      }
    } catch (e) { notifyError(e) }
  }

  async function repriceLine(i: number) {
    const l = d.lines[i]
    if (!l.item_id || !l.price_auto) return
    try {
      const info = await priceFor(l.item_id, l.variant_id, Number(l.quantity) || 1)
      updLine(i, { unit_price: Number(info.price.unit_price ?? 0), price_source: info.price.source_label, discount1: '', discount2: '', discount3: '' })
    } catch (e) { notifyError(e) }
  }

  function payload() {
    return {
      doc_type: t, party_id: d.party_id, doc_date: d.doc_date || null, warehouse_id: d.warehouse_id, destination_id: d.destination_id || null,
      payment_term_id: d.payment_term_id, moves_stock: d.moves_stock, valid_until: d.valid_until || null, reference: d.reference || null,
      notes: d.notes || null, series: d.series ?? null, transport: d.transport ?? {}, attachment_ids: d.attachment_ids ?? [], print_options: d.print_options ?? {},
      lines: d.lines.map((l: any) => ({ item_id: l.item_id, variant_id: l.variant_id, description: l.description, unit: l.unit || null,
        quantity: String(lineQty(l, t)), unit_price: String(l.unit_price || 0),
        discount1: dec(l.discount1), discount2: dec(l.discount2), discount3: dec(l.discount3), vat_rate_id: l.vat_rate_id,
        lot_number: l.lot_number || null, serials: bySerials(l, t) ? l.serials ?? [] : [], origin_line_id: l.origin_line_id ?? null,
        price_source: l.price_source ?? null, notes: l.notes ?? null })),
    }
  }

  async function save(andConfirm = false, force = false, quiet = false): Promise<any> {
    if (!d.party_id) { notifyError(new Error('Scegli il cliente')); return null }
    setBusy(true)
    let saved: any = null
    try {
      saved = isNew ? await S('/documenti', { body: payload() }) : draft ? await S(`/documenti/${id}`, { method: 'PUT', body: payload() }) : d
      if (isNew) nav(`/vendite/${saved.id}`, { replace: true })
      if (andConfirm) {
        const r = await S(`/documenti/${saved.id}/conferma`, { body: { force, number: d.manual_number || null } })
        r.warnings?.forEach((w: string) => notifyError(new Error(w)))
        saved = r
        notifyOk(`${TITLE[t]} n. ${r.number_label ?? r.number} emesso`)
      } else if (!quiet) notifyOk('Bozza salvata')
      setD(saved)
      setCreditBlock(null)
      return saved
    } catch (e) {
      if (saved) setD(saved)
      saved = null
      if (e instanceof ApiError && e.code === 'fido_superato') setCreditBlock(e.message)
      else notifyError(e)
      return null
    } finally { setBusy(false) }
  }
  async function preview() {
    // la bozza si salva prima, così l'anteprima mostra le ultime modifiche
    const doc = draft ? await save(false, false, true) : d
    if (doc?.id) setPreviewId(doc.id)
  }
  async function next(to: string) {
    // da una bozza: prima si emette il documento, poi si crea il successivo
    let doc = d
    if (draft) {
      if (!confirm(`Per proseguire ${t === 'ORC' ? "l'ordine va confermato" : 'il documento va emesso'}. Continuare?`)) return
      doc = await save(true)
      if (!doc || doc.status === 'bozza') return
    }
    if (doc.doc_type === 'ORC') setTransformTo(to)
    else transform(to, undefined, doc.id)
  }
  async function act(path: string, msg: string, body?: any) {
    try { setD(await S(`/documenti/${d.id}/${path}`, { body: body ?? {} })); notifyOk(msg) } catch (e) { notifyError(e) }
  }
  async function remove() {
    if (!confirm('Eliminare la bozza?')) return
    try { await S(`/documenti/${d.id}`, { method: 'DELETE' }); nav('/vendite') } catch (e) { notifyError(e) }
  }
  async function duplicate() {
    try { const r = await S(`/documenti/${d.id}/duplica`, { body: {} }); notifyOk('Copia creata'); nav(`/vendite/${r.id}`) } catch (e) { notifyError(e) }
  }
  async function transform(to: string, quantities?: Record<string, number | string>, docId?: string) {
    try {
      const r = await S(`/documenti/${docId ?? d.id}/trasforma`, { body: { to, quantities: quantities ? Object.fromEntries(Object.entries(quantities).map(([k, v]) => [k, String(v || 0)])) : null } })
      setTransformTo(null)
      notifyOk(`${TITLE[to]} creato in bozza: controlla e conferma`)
      nav(`/vendite/${r.id}`)
    } catch (e) { notifyError(e) }
  }

  const title = `${TITLE[t]}${d.number ? ` n. ${d.number_label ?? `${d.number}${d.series ? '/' + d.series : ''}/${d.year}`}` : ''}`
  const canPrint = !!d.id
  // trasformazioni: dal documento emesso e ancora aperto (o dalla bozza di preventivo/ordine, che prima si emette)
  const open = d.status !== 'annullato' && (d.status === 'confermato' || (draft && ['PRV', 'ORC'].includes(t)))
  const canCredit = ['FTI', 'FTD'].includes(t) && ['confermato', 'evaso'].includes(d.status)
  const nextSteps = (open && NEXT[t]) || []
  return (
    <>
      <Anchor size="sm" onClick={() => nav('/vendite')}><Group gap={4}><IconArrowLeft size={14} />Vendite</Group></Anchor>
      <Group justify="space-between" mt="xs" mb="md" wrap="wrap">
        <Group gap="xs"><Title order={2}>{title}</Title><StatusBadge d={d} />{d.contract_id && <Badge variant="outline">da contratto</Badge>}</Group>
        <Group gap="xs">
          {draft && !isNew && <Button variant="subtle" color="red" onClick={remove}>Elimina</Button>}
          <Button variant="default" leftSection={<IconEye size={16} />} onClick={preview} disabled={busy}>Anteprima</Button>
          {canPrint && <Button variant="default" leftSection={<IconPrinter size={16} />} component="a" href={`/stampa/vendita/${d.id}`} target="_blank">Stampa</Button>}
          {draft && <Button variant="default" onClick={() => save(false)} loading={busy}>Salva bozza</Button>}
          {draft && <Button onClick={() => save(true)} loading={busy}>{t === 'PRV' ? 'Emetti preventivo' : t === 'ORC' ? 'Conferma ordine' : 'Emetti'}</Button>}
          {nextSteps.length > 0 && (
            <Button.Group>
              <Button variant={draft ? 'light' : 'filled'} color="teal" onClick={() => next(nextSteps[0][0])} disabled={busy}>{nextSteps[0][1]}</Button>
              {nextSteps.length > 1 && (
                <Menu position="bottom-end"><Menu.Target><Button variant={draft ? 'light' : 'filled'} color="teal" px={8} disabled={busy}><IconChevronDown size={14} /></Button></Menu.Target>
                  <Menu.Dropdown>{nextSteps.slice(1).map(([to, label]) => <Menu.Item key={to} onClick={() => next(to)}>{label}</Menu.Item>)}</Menu.Dropdown></Menu>
              )}
            </Button.Group>
          )}
          {!isNew && (
            <Menu position="bottom-end">
              <Menu.Target><Button variant="default" px="xs"><IconChevronDown size={16} /></Button></Menu.Target>
              <Menu.Dropdown>
                <Menu.Item leftSection={<IconCopy size={14} />} onClick={duplicate}>Duplica</Menu.Item>
                {canCredit && <Menu.Item onClick={() => transform('NC')}>Nota di credito (storno)</Menu.Item>}
                {t === 'ORC' && d.status === 'confermato' && <Menu.Item onClick={() => confirm('Chiudere l\'ordine? La merce non consegnata non resterà più impegnata.') && act('chiudi', 'Ordine chiuso')}>Chiudi ordine (residuo non più da consegnare)</Menu.Item>}
                {['FTI', 'FTD', 'NC'].includes(t) && !draft && d.status !== 'annullato' && <Menu.Item onClick={() => act('incassata', d.settled ? 'Segnata da incassare' : 'Segnata come incassata', { settled: !d.settled })}>{d.settled ? 'Segna come da incassare' : 'Segna come incassata'}</Menu.Item>}
                {!draft && d.status !== 'annullato' && <Menu.Item color="red" onClick={() => confirm('Annullare il documento? Gli effetti su magazzino e impegni verranno stornati.') && act('annulla', 'Documento annullato')}>Annulla documento</Menu.Item>}
              </Menu.Dropdown>
            </Menu>
          )}
        </Group>
      </Group>

      {credit?.insolvent && ['ORC', 'DDT', 'FTI', 'PRV'].includes(t) && draft && (
        <Alert mb="xs" py="xs" color={credit.policy === 'blocca' ? 'red' : 'yellow'} icon={<IconAlertTriangle size={18} />}>
          <Text size="sm">Cliente in ritardo con i pagamenti: {fmtEuro(credit.exposure.overdue)} scaduti da {credit.exposure.overdue_days} giorni{credit.exposure.unpaid ? `, ${credit.exposure.unpaid} rate insolute` : ''}{credit.policy === 'blocca' ? ' — la conferma è bloccata' : ''}. <Anchor size="sm" onClick={() => nav(`/scadenzario?direzione=attiva&stato=aperte&party=${d.party_id}`)}>Vedi scadenze</Anchor></Text>
        </Alert>
      )}
      {credit?.limit != null && ['ORC', 'DDT', 'FTI', 'PRV'].includes(t) && d.status !== 'annullato' && (
        <Alert mb="md" py="xs" color={creditAfter! > Number(credit.limit) ? (credit.policy === 'blocca' ? 'red' : 'yellow') : 'gray'} icon={creditAfter! > Number(credit.limit) ? <IconAlertTriangle size={18} /> : <IconInfoCircle size={18} />}>
          <Text size="sm">Fido {fmtEuro(credit.limit)} · esposizione {fmtEuro(credit.exposure.total)} (fatture da incassare {fmtEuro(credit.exposure.invoices)}, DDT da fatturare {fmtEuro(credit.exposure.ddt)}, ordini aperti {fmtEuro(credit.exposure.orders)})
            {draft && ['ORC', 'DDT', 'FTI'].includes(t) && <> · con questo documento <b>{fmtEuro(creditAfter!)}</b></>}
            {creditAfter! > Number(credit.limit) && <b> — fido superato{credit.policy === 'blocca' ? ': la conferma è bloccata' : ''}</b>}</Text>
        </Alert>
      )}

      <Paper withBorder p="md" mb="md">
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
          <CustomerPicker label="Cliente" value={d.party_id} onChange={(v) => setD((c: any) => ({ ...c, party_id: v, destination_id: null, payment_term_id: null }))} disabled={!draft} required />
          <TextInput type="date" label="Data" value={d.doc_date ?? ''} onChange={(e) => set('doc_date', e.currentTarget.value)} disabled={!draft} placeholder="oggi" />
          {t === 'PRV' && <TextInput type="date" label="Valido fino al" value={d.valid_until ?? ''} onChange={(e) => set('valid_until', e.currentTarget.value)} disabled={!draft} />}
          <Select label="Pagamento" data={L.payments.map((p) => ({ value: p.id, label: p.description }))} value={d.payment_term_id} onChange={(v) => set('payment_term_id', v)} clearable disabled={!draft} />
          {party?.addresses?.length > 0 && <Select label="Destinazione merce" data={party.addresses.map((a: any) => ({ value: a.id, label: `${a.label} – ${a.address}, ${a.city ?? ''}` }))} value={d.destination_id} onChange={(v) => set('destination_id', v)} clearable placeholder="sede del cliente" disabled={!draft} />}
          {whs.length > 1 && t !== 'PRV' && <Select label="Magazzino" data={whs.map((w) => ({ value: w.id, label: w.name }))} value={d.warehouse_id} onChange={(v) => set('warehouse_id', v)} disabled={!draft} allowDeselect={false} />}
          {seriesOpts.length > 0 && <Select label="Sezionale" data={[{ value: '_', label: 'Principale' }, ...seriesOpts.map((x) => ({ value: x.code, label: `${x.code}${x.description ? ' – ' + x.description : ''}` }))]}
            value={series || '_'} onChange={(v) => set('series', v === '_' ? '' : v)} allowDeselect={false} disabled={!draft} />}
          {draft && isAdmin && <NumberInput label="Numero" placeholder={nextNo ? `automatico (n. ${nextNo})` : 'automatico'} value={d.manual_number ?? ''} onChange={(v) => set('manual_number', v || null)} min={1} allowDecimal={false} hideControls
            description="Vuoto = il prossimo della numerazione" />}
          <TextInput label="Riferimento cliente" placeholder="es. vs. ordine n. 45" value={d.reference ?? ''} onChange={(e) => set('reference', e.currentTarget.value)} disabled={!draft} />
          {['FTI', 'NC'].includes(t) && <Switch mt={28} label={t === 'NC' ? 'La merce rientra in magazzino' : 'Scarica il magazzino (fattura accompagnatoria)'} checked={d.moves_stock} onChange={(e) => set('moves_stock', e.currentTarget.checked)} disabled={!draft} />}
        </SimpleGrid>
        {party?.notes && <Text size="xs" c="orange" mt="xs">Nota cliente: {party.notes}</Text>}
        {(t === 'DDT' || (t === 'FTI' && d.moves_stock)) && (
          <>
            <UnstyledButton mt="sm" onClick={() => setShowTransport(!showTransport)}><Group gap={6}><IconTruck size={16} /><Text size="sm" fw={600}>Dati di trasporto</Text><Text size="xs" c="dimmed">{[d.transport?.causale, d.transport?.porto, d.transport?.colli && `${d.transport.colli} colli`].filter(Boolean).join(' · ')}</Text><IconChevronDown size={14} /></Group></UnstyledButton>
            <Collapse in={showTransport}>
              <SimpleGrid cols={{ base: 2, md: 4 }} mt="xs">
                <Select label="Causale del trasporto" data={CAUSALI} value={d.transport?.causale ?? null} onChange={(v) => setT('causale', v)} disabled={!draft} searchable />
                <Select label="Trasporto a cura del" data={['Mittente', 'Destinatario', 'Vettore']} value={d.transport?.a_cura ?? null} onChange={(v) => setT('a_cura', v)} disabled={!draft} />
                <TextInput label="Vettore" value={d.transport?.vettore ?? ''} onChange={(e) => setT('vettore', e.currentTarget.value)} disabled={!draft} />
                <Select label="Porto" data={['Franco', 'Assegnato']} value={d.transport?.porto ?? null} onChange={(v) => setT('porto', v)} disabled={!draft} />
                <TextInput label="Aspetto dei beni" placeholder="es. scatole" value={d.transport?.aspetto ?? ''} onChange={(e) => setT('aspetto', e.currentTarget.value)} disabled={!draft} />
                <NumberInput label="Colli" value={num(d.transport?.colli)} onChange={(v) => setT('colli', v)} min={0} disabled={!draft} />
                <NumberInput label="Peso (kg)" value={num(d.transport?.peso)} onChange={(v) => setT('peso', v)} min={0} decimalScale={2} disabled={!draft} />
                <TextInput type="datetime-local" label="Inizio trasporto" value={d.transport?.inizio ?? ''} onChange={(e) => setT('inizio', e.currentTarget.value)} disabled={!draft} />
              </SimpleGrid>
            </Collapse>
          </>
        )}
      </Paper>

      {draft && <div style={{ marginBottom: 12 }}><ItemScanner onPick={addItem} autoFocus={isNew} all /></div>}

      <Paper withBorder mb="md">
        <Table.ScrollContainer minWidth={980}>
          <Table verticalSpacing={6}>
            <Table.Thead><Table.Tr><Table.Th>Articolo / descrizione</Table.Th><Table.Th w={140}>Variante · lotto · matricole</Table.Th><Table.Th w={90}>Q.tà</Table.Th><Table.Th w={130}>Prezzo</Table.Th><Table.Th w={150}>Sconti %</Table.Th><Table.Th w={90}>IVA</Table.Th><Table.Th w={110} ta="right">Importo</Table.Th>{draft && <Table.Th w={40} />}</Table.Tr></Table.Thead>
            <Table.Tbody>
              {d.lines.map((l: any, i: number) => {
                const lt = lineTotal(l, t)
                const qty = lineQty(l, t)
                const m = l.unit_cost != null && lt ? ((lt - Number(l.unit_cost) * qty) / lt) * 100 : null
                const descriptive = !l.item_id && !Number(l.quantity)
                return (
                  <Table.Tr key={i} bg={descriptive ? 'var(--mantine-color-default-hover)' : undefined}>
                    <Table.Td>
                      {l.item_code && <Text size="xs" ff="monospace" c="dimmed">{l.item_code}{!draft && Number(l.qty_processed) > 0 && t === 'ORC' ? ` · evasi ${Number(l.qty_processed)} di ${Number(l.quantity)}` : ''}</Text>}
                      {draft ? <Textarea size="xs" autosize minRows={1} value={l.description} onChange={(e) => updLine(i, { description: e.currentTarget.value })} /> : <Text size="sm" fw={descriptive ? 600 : undefined}>{l.description}</Text>}
                    </Table.Td>
                    <Table.Td>
                      {l.variants?.length > 0 && <Select size="xs" placeholder="variante" data={l.variants.map((v: any) => ({ value: v.id, label: [v.color, v.size].filter(Boolean).join(' ') || v.code }))} value={l.variant_id} onChange={(v) => updLine(i, { variant_id: v })} disabled={!draft} />}
                      {!l.variants?.length && l.variant_code && <Text size="xs">{l.variant_code}</Text>}
                      {l.lot_managed && (draft ? <TextInput size="xs" placeholder={t === 'NC' ? 'lotto reso' : 'lotto (vuoto = FEFO)'} value={l.lot_number ?? ''} onChange={(e) => updLine(i, { lot_number: e.currentTarget.value })} /> : l.lot_number && <Text size="xs">lotto {l.lot_number}</Text>)}
                      {bySerials(l, t) && (draft ? <TagsInput size="xs" placeholder="matricole" value={l.serials ?? []} onChange={(v) => updLine(i, { serials: v })} /> : <Text size="xs">{(l.serials ?? []).join(', ')}</Text>)}
                    </Table.Td>
                    <Table.Td>{descriptive ? null : draft && !bySerials(l, t)
                      ? <NumberInput size="xs" hideControls value={num(l.quantity)} onChange={(v) => updLine(i, { quantity: v })} onBlur={() => repriceLine(i)} min={0} rightSection={<Text size="10px" c="dimmed">{l.unit}</Text>} />
                      : <Text size="sm">{qty} {l.unit}</Text>}</Table.Td>
                    <Table.Td>
                      {descriptive ? null : (
                        <Group gap={2} wrap="nowrap">
                          {draft ? <NumberInput size="xs" hideControls value={num(l.unit_price)} onChange={(v) => updLine(i, { unit_price: v, price_auto: false, price_source: 'Prezzo manuale' })} decimalScale={4} min={0} /> : <Text size="sm">{fmtEuro(l.unit_price)}</Text>}
                          {l.item_id && <Tooltip label="Prezzi, costi e ultimi prezzi al cliente"><ActionIcon variant="subtle" size="sm" onClick={() => setInfoLine(i)}><IconInfoCircle size={16} /></ActionIcon></Tooltip>}
                        </Group>
                      )}
                      {l.price_source && !descriptive && <Text size="10px" c="dimmed" truncate>{l.price_source}</Text>}
                    </Table.Td>
                    <Table.Td>{!descriptive && <Group gap={2} wrap="nowrap">{['discount1', 'discount2', 'discount3'].map((k) => draft ? <NumberInput key={k} size="xs" hideControls value={num(l[k])} onChange={(v) => updLine(i, { [k]: v, price_auto: false })} min={0} max={100} w={44} /> : l[k] ? <Text key={k} size="xs">{Number(l[k])}%</Text> : null)}</Group>}</Table.Td>
                    <Table.Td>{!descriptive && (draft ? <Select size="xs" data={L.vat.filter((v) => v.active).map((v) => ({ value: v.id, label: v.code }))} value={l.vat_rate_id} onChange={(v) => updLine(i, { vat_rate_id: v })} /> : <Text size="xs">{l.vat_nature ?? `${Number(l.vat_rate)}%`}</Text>)}</Table.Td>
                    <Table.Td ta="right">{!descriptive && <><Text fw={600} size="sm">{fmtEuro(lt)}</Text>{m != null && <Text size="10px" c={m < 0 ? 'red' : m < 10 ? 'orange' : 'dimmed'}>margine {pct(m)}</Text>}</>}</Table.Td>
                    {draft && <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => setD((c: any) => ({ ...c, lines: c.lines.filter((_: any, j: number) => j !== i) }))}><IconTrash size={16} /></ActionIcon></Table.Td>}
                  </Table.Tr>
                )
              })}
              {d.lines.length === 0 && <Table.Tr><Table.Td colSpan={8}><Text ta="center" c="dimmed" py="md" size="sm">Leggi il codice a barre o cerca gli articoli da aggiungere</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {draft && (
          <Group p="sm" gap="xs">
            <Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => setD((c: any) => ({ ...c, lines: [...c.lines, { ...EMPTY_LINE, description: 'Servizio / spese', vat_rate_id: party?.vat_rate_id || L.vat.find((v) => v.code === '22')?.id, price_source: 'Prezzo manuale' }] }))}>Riga libera (servizi, spese)</Button>
            <Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => setD((c: any) => ({ ...c, lines: [...c.lines, { ...EMPTY_LINE, description: '', quantity: 0 }] }))}>Riga di testo</Button>
          </Group>
        )}
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Stack>
          {fatturapa && ['FTI', 'FTD', 'NC'].includes(t) && ['confermato', 'evaso'].includes(d.status) && <SdiPanel docId={d.id} number={d.number} year={d.year} onChanged={() => S(`/documenti/${d.id}`).then(setD).catch(() => {})} />}
          <Textarea label="Note sul documento" autosize minRows={2} value={d.notes ?? ''} onChange={(e) => set('notes', e.currentTarget.value)} disabled={!draft} />
          {['PRV', 'ORC', 'DDT', 'FTI'].includes(t) && (
            <Paper withBorder p="md">
              <Group gap={6} mb="xs"><IconFileDescription size={16} /><Text fw={600} size="sm">Stampa</Text></Group>
              <Group gap="lg">
                <Checkbox label="Descrizioni estese" checked={!!d.print_options?.long_descriptions} onChange={(e) => setPO('long_descriptions', e.currentTarget.checked)} disabled={!draft} />
                <Checkbox label="Immagini articoli" checked={!!d.print_options?.images} onChange={(e) => setPO('images', e.currentTarget.checked)} disabled={!draft} />
                {t === 'DDT' && <Checkbox label="Prezzi sul DDT" checked={!!d.print_options?.show_prices} onChange={(e) => setPO('show_prices', e.currentTarget.checked)} disabled={!draft} />}
              </Group>
              {allAtts.length > 0 && ['PRV', 'ORC'].includes(t) && (
                <>
                  <Text size="xs" c="dimmed" mt="sm" mb={4}>Schede tecniche da allegare</Text>
                  <Checkbox.Group value={d.attachment_ids ?? []} onChange={(v) => set('attachment_ids', v)}>
                    <Stack gap={4}>{allAtts.map((a: any) => <Checkbox key={a.id} value={a.id} disabled={!draft} label={<Anchor href={a.url} target="_blank" size="sm">{a.title}</Anchor>} />)}</Stack>
                  </Checkbox.Group>
                </>
              )}
            </Paper>
          )}
          {d.related?.length > 0 && (
            <Paper withBorder p="md">
              <Text fw={600} size="sm" mb="xs">Documenti collegati</Text>
              {d.related.map((r: any) => <Anchor key={r.id} display="block" size="sm" onClick={() => nav(`/vendite/${r.id}`)}>{r.direction === 'origine' ? '← ' : '→ '}{r.label} {r.number ? `n. ${r.number}` : 'bozza'} del {fmtDate(r.date)}{r.status === 'annullato' ? ' · annullato' : ''}</Anchor>)}
            </Paper>
          )}
        </Stack>
        <Paper withBorder p="md">
          <Group justify="space-between"><Text>Imponibile</Text><Text fw={600}>{fmtEuro(taxable)}</Text></Group>
          {Object.entries(groups).sort((a, b) => Number(b[0]) - Number(a[0])).map(([r, v]) => (
            <Group key={r} justify="space-between"><Text size="sm" c="dimmed">IVA {Number(r)}% su {fmtEuro(v)}</Text><Text size="sm">{fmtEuro(Math.round(v * Number(r)) / 100)}</Text></Group>
          ))}
          {stamp > 0 && <Group justify="space-between"><Text size="sm" c="dimmed">Imposta di bollo{stampCharged ? '' : ' (a carico dell\'azienda)'}</Text><Text size="sm">{fmtEuro(stamp)}</Text></Group>}
          <Group justify="space-between" mt="xs" pt="xs" style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}><Text fw={700}>Totale</Text><Text fw={800} fz="xl">{fmtEuro(total)}</Text></Group>
          {showCosts && taxable > 0 && (
            <Group justify="space-between" mt="xs"><Text size="sm" c="dimmed">Costo {fmtEuro(cost)} · margine</Text><Text size="sm" fw={600} c={taxable - cost < 0 ? 'red' : 'green'}>{fmtEuro(taxable - cost)} ({pct(((taxable - cost) / taxable) * 100)})</Text></Group>
          )}
        </Paper>
      </SimpleGrid>

      <PriceDrawer line={infoLine != null ? d.lines[infoLine] : null} partyId={d.party_id} draft={draft} onClose={() => setInfoLine(null)}
        onApply={(patch) => { if (infoLine != null) updLine(infoLine, { ...patch, price_auto: false }); setInfoLine(null) }} nav={nav} />

      <Modal opened={!!previewId} onClose={() => setPreviewId(null)} title={`Anteprima · ${title}`} size="min(1000px, 96vw)" padding="xs">
        {previewId && <iframe src={`/stampa/vendita/${previewId}`} title="Anteprima" style={{ width: '100%', height: '78vh', border: '1px solid var(--mantine-color-default-border)', borderRadius: 6, background: '#fff' }} />}
      </Modal>
      {transformTo && <EvadeModal d={d} to={transformTo} onClose={() => setTransformTo(null)} onConfirm={(q) => transform(transformTo, q)} />}

      <Modal opened={!!creditBlock} onClose={() => setCreditBlock(null)} title="Fido superato">
        <Stack>
          <Alert color="red" icon={<IconAlertTriangle size={18} />}>{creditBlock}</Alert>
          <Text size="sm">Il documento è salvato in bozza. Puoi chiedere un acconto, segnare come incassate le fatture già pagate{isAdmin ? ' oppure confermare comunque (l\'operazione resta registrata).' : ' o chiedere a un amministratore di confermarlo.'}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setCreditBlock(null)}>Chiudi</Button>
            {isAdmin && <Button color="red" onClick={() => save(true, true)} loading={busy}>Conferma comunque</Button>}
          </Group>
        </Stack>
      </Modal>
    </>
  )
}

function EvadeModal({ d, to, onClose, onConfirm }: { d: any; to: string; onClose: () => void; onConfirm: (q: Record<string, number | string>) => void }) {
  const open = d.lines.filter((l: any) => l.item_id && Number(l.residual) > 0)
  const [q, setQ] = useState<Record<string, number | string>>(Object.fromEntries(open.map((l: any) => [l.id, Number(l.residual)])))
  return (
    <Modal opened onClose={onClose} title={`Evadi l'ordine con ${TITLE[to].toLowerCase()}`} size="lg">
      <Text size="sm" c="dimmed" mb="sm">Indica quanto consegni adesso: il resto rimane nell'ordine, ancora impegnato.</Text>
      <Table>
        <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th ta="right">Ordinato</Table.Th><Table.Th ta="right">Da evadere</Table.Th><Table.Th w={120}>Ora</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>
          {open.map((l: any) => (
            <Table.Tr key={l.id}>
              <Table.Td fz="sm">{l.description}</Table.Td>
              <Table.Td ta="right">{Number(l.quantity)}</Table.Td>
              <Table.Td ta="right">{Number(l.residual)}</Table.Td>
              <Table.Td><NumberInput size="xs" value={q[l.id]} onChange={(v) => setQ({ ...q, [l.id]: v })} min={0} max={Number(l.residual)} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group justify="space-between" mt="md">
        <Button variant="subtle" size="xs" onClick={() => setQ(Object.fromEntries(open.map((l: any) => [l.id, 0])))}>Azzera</Button>
        <Button onClick={() => onConfirm(q)}>Crea {TITLE[to].toLowerCase()}</Button>
      </Group>
    </Modal>
  )
}

/** Riquadro prezzi della riga: prezzo proposto, listini, ultimi prezzi al cliente, costi e margine, disponibilità. */
function PriceDrawer({ line, partyId, draft, onClose, onApply, nav }: { line: any; partyId: string | null; draft: boolean; onClose: () => void; onApply: (p: any) => void; nav: (to: string) => void }) {
  const [info, setInfo] = useState<any>(null)
  const key = useRef('')
  useEffect(() => {
    if (!line?.item_id) { setInfo(null); return }
    const p = new URLSearchParams({ item_id: line.item_id, qty: String(Number(line.quantity) || 1) })
    if (partyId) p.set('party_id', partyId)
    if (line.variant_id) p.set('variant_id', line.variant_id)
    key.current = p.toString()
    S('/info-riga?' + p).then((r) => { if (key.current === p.toString()) setInfo(r) }).catch(notifyError)
  }, [line?.item_id, line?.quantity, line?.variant_id, partyId])
  const cur = line ? net(line) : 0
  const cost = info?.costs?.cost != null ? Number(info.costs.cost) : null
  const margin = (price: number) => (cost != null && price ? ((price - cost) / price) * 100 : null)
  const Row = ({ label, value, sub, onClick }: { label: React.ReactNode; value: React.ReactNode; sub?: React.ReactNode; onClick?: () => void }) => (
    <UnstyledButton onClick={draft ? onClick : undefined} style={{ display: 'block', width: '100%', borderRadius: 6, padding: '4px 6px', cursor: draft && onClick ? 'pointer' : 'default' }}
      className={draft && onClick ? 'hover-row' : undefined}>
      <Group justify="space-between" wrap="nowrap"><Text size="sm">{label}</Text><Text size="sm" fw={600}>{value}</Text></Group>
      {sub && <Text size="xs" c="dimmed">{sub}</Text>}
    </UnstyledButton>
  )
  return (
    <Drawer opened={!!line} onClose={onClose} position="right" size="md" title={line ? <Text fw={700}>{line.item_code} · {line.description}</Text> : ''}>
      <style>{'.hover-row:hover{background:var(--mantine-color-default-hover)}'}</style>
      {!info ? <Loading /> : (
        <Stack gap="md">
          <Paper withBorder p="sm" bg="var(--mantine-color-blue-light)">
            <Group justify="space-between"><Text size="sm">Prezzo sulla riga</Text><Text fw={800} fz="lg">{fmtEuro(cur)}</Text></Group>
            {margin(cur) != null && <Text size="sm" c={margin(cur)! < 0 ? 'red' : 'dimmed'}>Margine {pct(margin(cur)!)} · ricarico {cost ? pct(((cur - cost) / cost) * 100) : '—'}</Text>}
          </Paper>
          <div>
            <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={4}>Prezzo proposto</Text>
            <Row label={info.price.source_label} value={info.price.unit_price != null ? fmtEuro(info.price.unit_price) : '—'}
              sub={info.price.list_price && info.price.discounts.length ? `listino ${fmtEuro(info.price.list_price)} − ${info.price.discounts.map((x: string) => Number(x) + '%').join(' − ')}` : undefined}
              onClick={() => onApply({ unit_price: Number(info.price.unit_price), discount1: '', discount2: '', discount3: '', price_source: info.price.source_label })} />
            {info.price.alternatives?.map((a: any, i: number) => <Row key={i} label={a.label} value={fmtEuro(a.unit_price)} />)}
          </div>
          {info.last_sales.length > 0 && (
            <div>
              <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={4}>Ultimi prezzi a questo cliente</Text>
              {info.last_sales.map((s: any, i: number) => (
                <Row key={i} label={`${fmtDate(s.date)} · ${s.label} ${s.number ?? ''}`} value={fmtEuro(s.net_price)}
                  sub={`${Number(s.quantity)} pz a ${fmtEuro(s.unit_price)}${s.discounts.length ? ' − ' + s.discounts.map((x: string) => Number(x) + '%').join(' − ') : ''}${margin(Number(s.net_price)) != null ? ` · margine oggi ${pct(margin(Number(s.net_price))!)}` : ''}`}
                  onClick={() => onApply({ unit_price: Number(s.unit_price), discount1: s.discounts[0] ? Number(s.discounts[0]) : '', discount2: s.discounts[1] ? Number(s.discounts[1]) : '', discount3: s.discounts[2] ? Number(s.discounts[2]) : '', price_source: `Ultimo prezzo (${fmtDate(s.date)})` })} />
              ))}
            </div>
          )}
          {info.lists.length > 0 && (
            <div>
              <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={4}>Listini (IVA esclusa)</Text>
              {info.lists.map((l: any) => <Row key={l.code} label={`${l.name}${l.is_default ? ' · predefinito' : ''}`} value={fmtEuro(l.price)}
                sub={margin(Number(l.price)) != null ? `margine ${pct(margin(Number(l.price))!)}` : undefined}
                onClick={() => onApply({ unit_price: Number(l.price), discount1: '', discount2: '', discount3: '', price_source: `Listino ${l.code}` })} />)}
            </div>
          )}
          {info.costs && (
            <div>
              <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={4}>Costi</Text>
              <Row label="Costo medio ponderato" value={info.costs.avg_cost ? fmtEuro(info.costs.avg_cost) : '—'} />
              <Row label="Ultimo costo" value={info.costs.last_cost ? fmtEuro(info.costs.last_cost) : '—'} />
              {info.last_purchase && <Row label={`Ultimo acquisto · ${info.last_purchase.supplier}`} value={fmtEuro(info.last_purchase.net_price)} sub={`${fmtDate(info.last_purchase.date)} · ${Number(info.last_purchase.quantity)} pz`} />}
              {info.suppliers.filter((s: any) => s.last_cost).map((s: any) => <Row key={s.supplier} label={s.supplier} value={fmtEuro(s.last_cost)} sub={s.code ? `cod. ${s.code}` : undefined} />)}
            </div>
          )}
          {info.item.stock_managed && (
            <div>
              <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={4}>Disponibilità</Text>
              <SimpleGrid cols={4} spacing="xs">
                {[['Giacenza', info.stock.on_hand], ['Impegnata', info.stock.reserved], ['Disponibile', info.stock.available], ['In arrivo', info.stock.ordered]].map(([l, v]) => (
                  <Paper key={l} withBorder p={6} ta="center"><Text size="10px" c="dimmed">{l}</Text><Text fw={700} c={l === 'Disponibile' && Number(v) <= 0 ? 'red' : undefined}>{Number(v)}</Text></Paper>
                ))}
              </SimpleGrid>
            </div>
          )}
          <Divider />
          <Group gap="xs">
            <Button size="xs" variant="light" onClick={() => nav(`/vendite/storico-articolo?item=${line.item_id}`)}>Storico dell'articolo</Button>
            {partyId && <Button size="xs" variant="light" onClick={() => nav(`/vendite/acquistato-cliente?party=${partyId}`)}>Acquistato dal cliente</Button>}
          </Group>
          {draft && <Text size="xs" c="dimmed">Clicca su un prezzo per applicarlo alla riga.</Text>}
        </Stack>
      )}
    </Drawer>
  )
}
