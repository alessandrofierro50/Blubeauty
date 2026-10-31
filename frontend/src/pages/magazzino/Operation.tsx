import { ActionIcon, Badge, Button, Group, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, TagsInput, Text, TextInput, Title } from '@mantine/core'
import { IconBarcode, IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { appApi } from '../../api'
import { Loading, notifyError, notifyOk } from '../../components'
import { VariantGrid, W, useWarehouses } from './shared'

type Line = {
  key: string
  item: any
  qty: number | string
  unit_cost: number | string
  grid: Record<string, number | string>
  lots: { lot_number: string; expiry_date: string; qty: number | string }[]
  serials: string[]
}

const KINDS = [
  { value: 'carico', label: 'Carico', sign: 1 },
  { value: 'scarico', label: 'Scarico', sign: -1 },
  { value: 'rettifica_piu', label: 'Rettifica +', sign: 1 },
  { value: 'rettifica_meno', label: 'Rettifica −', sign: -1 },
  { value: 'scarto', label: 'Scarto', sign: -1 },
]

/** Ricerca articolo da tastiera o lettore: Invio cerca, un solo risultato viene aggiunto subito. */
export function ItemScanner({ onPick, autoFocus = true, all = false }: { onPick: (item: any) => void; autoFocus?: boolean; all?: boolean }) {
  // all: anche servizi e kit (documenti di vendita e acquisto)
  const [code, setCode] = useState('')
  const [results, setResults] = useState<any[]>([])
  const ref = useRef<HTMLInputElement>(null)
  const typed = useRef(0)
  const lookup = (c: string) => W('/cerca?code=' + encodeURIComponent(c) + (all ? '&tutti=true' : ''))
  // suggerimenti mentre si scrive (dalla terza lettera); Invio o lo scanner aggiungono subito se il risultato è uno solo
  useEffect(() => {
    const c = code.trim()
    if (c.length < 3) { setResults([]); return }
    const n = ++typed.current
    const h = setTimeout(() => lookup(c).then((r) => { if (n === typed.current) setResults(r) }).catch(() => {}), 300)
    return () => clearTimeout(h)
  }, [code])
  function pick(r: any) { onPick(r); setResults([]); setCode(''); typed.current++; ref.current?.focus() }
  async function search() {
    const c = code.trim()
    if (!c) return
    try {
      typed.current++
      const r = await lookup(c)
      if (r.length === 1) pick(r[0]); else if (!r.length) notifyError(new Error(`Nessun articolo trovato per «${c}»: controlla che esista in Anagrafiche › Articoli e che sia attivo`)); else setResults(r)
    } catch (e) { notifyError(e) }
    ref.current?.focus()
  }
  return (
    <div>
      <TextInput ref={ref} placeholder="Scrivi codice o descrizione dell'articolo (o leggi il codice a barre) e scegli dall'elenco" leftSection={<IconBarcode size={18} />}
        value={code} onChange={(e) => setCode(e.currentTarget.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); search() } }}
        size="md" autoFocus={autoFocus} rightSection={<ActionIcon variant="filled" onClick={search} aria-label="Aggiungi"><IconPlus size={16} /></ActionIcon>} />
      {results.length > 0 && (
        <Paper withBorder mt={4} p={4} shadow="sm">
          {results.map((r) => (
            <Button key={r.id} variant="subtle" fullWidth justify="flex-start" onClick={() => pick(r)}>
              <Text span ff="monospace" size="xs" c="dimmed" mr={8}>{r.code}</Text>{r.description}
            </Button>
          ))}
        </Paper>
      )}
    </div>
  )
}

export default function Operation({ transfer = false }: { transfer?: boolean }) {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const whs = useWarehouses()
  const [kind, setKind] = useState('carico')
  const [wh, setWh] = useState<string | null>(null)
  const [toWh, setToWh] = useState<string | null>(null)
  const [when, setWhen] = useState('')
  const [reference, setReference] = useState('')
  const [lines, setLines] = useState<Line[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (whs?.length && !wh) setWh(whs[0].id) }, [whs])
  useEffect(() => {
    const art = params.get('articolo')
    if (art) appApi(`/api/anagrafiche/articoli/${art}`).then((it) => W('/cerca?code=' + encodeURIComponent(it.code))).then((r) => r[0] && add(r[0])).catch(() => {})
  }, [])

  const sign = transfer ? -1 : KINDS.find((k) => k.value === kind)!.sign
  const inflow = sign > 0

  function add(item: any) {
    const existing = lines.find((l) => l.item.id === item.id)
    if (existing) {
      if (item.variant_id) setLines(lines.map((l) => l === existing ? { ...l, grid: { ...l.grid, [item.variant_id]: Number(l.grid[item.variant_id] || 0) + 1 } } : l))
      else if (!item.serial_managed && !item.lot_managed && !item.variants.length) setLines(lines.map((l) => l === existing ? { ...l, qty: Number(l.qty || 0) + 1 } : l))
      return
    }
    setLines([{ key: crypto.randomUUID(), item, qty: item.serial_managed ? 0 : 1, unit_cost: '', grid: item.variant_id ? { [item.variant_id]: 1 } : {},
      lots: item.lot_managed ? [{ lot_number: '', expiry_date: '', qty: '' }] : [], serials: [] }, ...lines])
  }
  const upd = (key: string, patch: Partial<Line>) => setLines(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)))

  function payloadLines() {
    const out: any[] = []
    for (const l of lines) {
      const cost = l.unit_cost === '' ? null : String(l.unit_cost)
      if (l.item.variants.length) {
        for (const [vid, q] of Object.entries(l.grid)) if (Number(q) > 0) out.push({ item_id: l.item.id, variant_id: vid, quantity: String(q), unit_cost: cost })
      } else if (l.item.serial_managed) {
        if (l.serials.length) out.push({ item_id: l.item.id, quantity: String(l.serials.length), serials: l.serials, unit_cost: cost })
      } else if (l.item.lot_managed && (inflow || l.lots.some((x) => x.lot_number))) {
        for (const lot of l.lots) if (Number(lot.qty) > 0) out.push({ item_id: l.item.id, quantity: String(lot.qty), lot_number: lot.lot_number || null, expiry_date: lot.expiry_date || null, unit_cost: cost })
      } else if (Number(l.qty) > 0) out.push({ item_id: l.item.id, quantity: String(l.qty), unit_cost: cost })
    }
    return out
  }

  async function save() {
    const pl = payloadLines()
    if (!pl.length) return notifyError(new Error('Nessuna quantità inserita'))
    setBusy(true)
    try {
      if (transfer) {
        await W('/trasferimenti', { body: { from_warehouse_id: wh, to_warehouse_id: toWh, when: when || null, reference: reference || null, lines: pl } })
        notifyOk('Trasferimento registrato')
      } else {
        await W('/movimenti', { body: { kind, warehouse_id: wh, when: when || null, reference: reference || null, lines: pl } })
        notifyOk('Operazione registrata')
      }
      setLines([])
      nav('/magazzino/movimenti')
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  if (!whs) return <Loading />
  const whOpts = whs.map((w) => ({ value: w.id, label: w.name }))
  return (
    <>
      <Group justify="space-between" mb="md" wrap="wrap">
        <Title order={2}>{transfer ? 'Trasferimento tra magazzini' : 'Carico e scarico'}</Title>
        <Button onClick={save} loading={busy} disabled={!lines.length || (transfer && (!toWh || toWh === wh))}>Registra</Button>
      </Group>
      <Paper withBorder p="md" mb="md">
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
          {!transfer && <div><Text size="sm" fw={500} mb={4}>Operazione</Text><SegmentedControl fullWidth value={kind} onChange={setKind} data={KINDS} size="xs" /></div>}
          <Select label={transfer ? 'Da magazzino' : 'Magazzino'} data={whOpts} value={wh} onChange={setWh} allowDeselect={false} />
          {transfer && <Select label="A magazzino" data={whOpts.filter((o) => o.value !== wh)} value={toWh} onChange={setToWh} placeholder="Scegli" />}
          <TextInput type="date" label="Data" description="vuota = oggi" value={when} onChange={(e) => setWhen(e.currentTarget.value)} />
          <TextInput label="Riferimento / note" placeholder="es. DDT 123 del fornitore" value={reference} onChange={(e) => setReference(e.currentTarget.value)} />
        </SimpleGrid>
      </Paper>
      <ItemScanner onPick={add} />
      <Stack mt="md">
        {lines.map((l) => (
          <Paper key={l.key} withBorder p="md">
            <Group justify="space-between" mb="sm" wrap="nowrap">
              <div><Text fw={600}>{l.item.description}</Text><Text size="xs" c="dimmed" ff="monospace">{l.item.code} · {l.item.unit}</Text></div>
              <Group gap="xs">
                {l.item.lot_managed && <Badge variant="light" color="orange">lotti</Badge>}
                {l.item.serial_managed && <Badge variant="light" color="cyan">matricole</Badge>}
                <ActionIcon variant="subtle" color="red" onClick={() => setLines(lines.filter((x) => x.key !== l.key))}><IconTrash size={16} /></ActionIcon>
              </Group>
            </Group>
            {l.item.variants.length > 0 ? (
              <VariantGrid variants={l.item.variants} values={l.grid} onChange={(vid, v) => upd(l.key, { grid: { ...l.grid, [vid]: v } })} compact />
            ) : l.item.serial_managed ? (
              <TagsInput label={`Matricole (${l.serials.length} pezzi)`} placeholder="Leggi o scrivi ogni matricola e premi Invio" value={l.serials}
                onChange={(v) => upd(l.key, { serials: v.map((x) => x.trim().toUpperCase()) })} splitChars={[',', ' ']} />
            ) : l.item.lot_managed ? (
              <Stack gap="xs">
                {l.lots.map((lot, i) => (
                  <Group key={i} align="flex-end" wrap="wrap">
                    <TextInput label="Lotto" placeholder={inflow ? 'obbligatorio' : 'vuoto = primo in scadenza (FEFO)'} value={lot.lot_number} w={200}
                      onChange={(e) => upd(l.key, { lots: l.lots.map((x, j) => j === i ? { ...x, lot_number: e.currentTarget.value } : x) })} />
                    {inflow && <TextInput type="date" label="Scadenza" description={l.item.shelf_life_days ? `vuota = +${l.item.shelf_life_days} gg` : undefined} value={lot.expiry_date}
                      onChange={(e) => upd(l.key, { lots: l.lots.map((x, j) => j === i ? { ...x, expiry_date: e.currentTarget.value } : x) })} />}
                    <NumberInput label={`Quantità (${l.item.unit})`} value={lot.qty} min={0} w={130}
                      onChange={(v) => upd(l.key, { lots: l.lots.map((x, j) => j === i ? { ...x, qty: v } : x) })} />
                    {l.lots.length > 1 && <ActionIcon variant="subtle" color="red" mb={6} onClick={() => upd(l.key, { lots: l.lots.filter((_, j) => j !== i) })}><IconTrash size={14} /></ActionIcon>}
                  </Group>
                ))}
                {inflow && <Button variant="subtle" size="xs" w="fit-content" leftSection={<IconPlus size={14} />} onClick={() => upd(l.key, { lots: [...l.lots, { lot_number: '', expiry_date: '', qty: '' }] })}>Altro lotto</Button>}
              </Stack>
            ) : (
              <NumberInput label={`Quantità (${l.item.unit})`} value={l.qty} min={0} w={160} onChange={(v) => upd(l.key, { qty: v })} />
            )}
            {inflow && !transfer && (
              <NumberInput mt="sm" label="Costo unitario €" description="Aggiorna costo ultimo e medio" value={l.unit_cost} min={0} decimalScale={4} w={200}
                onChange={(v) => upd(l.key, { unit_cost: v })} />
            )}
          </Paper>
        ))}
        {lines.length === 0 && <Text c="dimmed" ta="center" py="xl">Leggi o cerca un articolo per iniziare.</Text>}
      </Stack>
    </>
  )
}
