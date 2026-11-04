import { ActionIcon, Anchor, Badge, Button, Checkbox, Group, Menu, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Table, Tabs, TagsInput, Text, Textarea, TextInput, Title, Tooltip } from '@mantine/core'
import { IconArrowLeft, IconBarcode, IconCopy, IconDots, IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi, fmtEuro } from '../../api'
import { Loading, notifyError, notifyOk } from '../../components'
import AttachmentsEditor from './AttachmentsEditor'
import ImagesEditor from './ImagesEditor'
import { A, categoryOptions, dec, num, opts, useLookups } from './shared'
import { TableSelect } from './TableSelect'

const EMPTY: any = {
  code: '', description: '', long_description: '', notes: '', item_type: 'articolo', category_id: null, brand_id: null,
  family: '', line: '', season: '', tags: [], unit: 'PZ', weight_net: '', weight_gross: '', volume: '', length: '',
  width: '', height: '', vat_rate_id: null, intrastat_code: '', origin_country: '', last_cost: '', avg_cost: '',
  standard_cost: '', stock_managed: true, lot_managed: false, serial_managed: false, shelf_life_days: '',
  warranty_months: '', min_stock: '', max_stock: '', reorder_point: '', reorder_qty: '', location: '',
  preferred_supplier_id: null, lead_time_days: '', is_kit: false, custom: {}, active: true, plu: '', pos_department_id: null, sold_by_weight: false,
  variants: [], barcodes: [], units: [], suppliers: [], prices: [], components: [],
}

const DECIMALS = ['weight_net', 'weight_gross', 'volume', 'length', 'width', 'height', 'last_cost', 'avg_cost', 'standard_cost', 'min_stock', 'max_stock', 'reorder_point', 'reorder_qty']
const INTS = ['shelf_life_days', 'warranty_months', 'lead_time_days']

export default function ItemEditor() {
  const { id } = useParams()
  const isNew = id === 'nuovo'
  const nav = useNavigate()
  const L = useLookups()
  const [it, setIt] = useState<any>(isNew ? null : undefined)
  const [suppliers, setSuppliers] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  const [posDeps, setPosDeps] = useState<any[] | null>(null)  // null = vendita al banco non inclusa
  useEffect(() => { appApi('/api/pos/reparti').then(setPosDeps).catch(() => setPosDeps(null)) }, [])

  useEffect(() => {
    A('/soggetti?tipo=fornitori&page_size=200').then((r) => setSuppliers(r.rows)).catch(() => {})
    if (isNew) {
      A('/articoli/nuovo-codice').then((r) => setIt({ ...EMPTY, code: r.code })).catch(notifyError)
    } else {
      A(`/articoli/${id}`).then(setIt).catch(notifyError)
    }
  }, [id])

  useEffect(() => {
    if (isNew && it && L && !it.vat_rate_id) {
      const v22 = L.vat.find((v) => v.code === '22')
      if (v22) setIt((x: any) => ({ ...x, vat_rate_id: v22.id }))
    }
  }, [L, it?.code])

  if (!it || !L) return <Loading />
  const fg = L.settings.field_groups
  const set = (k: string, v: any) => setIt({ ...it, [k]: v })
  const field = (k: string) => ({ value: it[k] ?? '', onChange: (e: any) => set(k, e.currentTarget.value) })
  const numf = (k: string) => ({ value: num(it[k]), onChange: (v: any) => set(k, v) })
  const vatRate = Number(L.vat.find((v) => v.id === it.vat_rate_id)?.rate ?? 0)
  const cost = Number(it.last_cost || it.avg_cost || it.standard_cost || 0)

  function payload() {
    const { images: _images, prices_customers: _pc, ...rest } = it
    const p: any = { ...rest }
    for (const k of DECIMALS) p[k] = dec(p[k])
    for (const k of INTS) p[k] = p[k] === '' || p[k] === null ? null : Number(p[k])
    for (const k of ['long_description', 'notes', 'family', 'line', 'season', 'intrastat_code', 'origin_country', 'location', 'plu']) p[k] = p[k] || null
    p.code = p.code || null
    p.prices = p.prices.map((r: any) => ({ price_list_id: r.price_list_id, min_qty: dec(r.min_qty) ?? '0', price: dec(r.price) ?? '0', discount1: dec(r.discount1), discount2: dec(r.discount2), discount3: dec(r.discount3) }))
    p.suppliers = p.suppliers.filter((r: any) => r.supplier_id).map((r: any) => ({ supplier_id: r.supplier_id, supplier_code: r.supplier_code || null, last_cost: dec(r.last_cost), discount: dec(r.discount), min_order_qty: dec(r.min_order_qty) }))
    p.units = p.units.filter((r: any) => r.unit && r.factor).map((r: any) => ({ unit: r.unit, factor: String(r.factor) }))
    p.barcodes = p.barcodes.filter((r: any) => r.barcode).map((r: any) => ({ barcode: r.barcode, barcode_type: r.barcode_type || 'EAN13', variant_code: r.variant_code || null, unit: r.unit || null, quantity: dec(r.quantity) ?? '1' }))
    p.variants = p.variants.filter((r: any) => r.code).map((r: any) => ({ code: r.code, size: r.size || null, color: r.color || null, format: r.format || null, price_delta: dec(r.price_delta), active: r.active !== false }))
    p.components = p.components.filter((r: any) => r.component_id).map((r: any) => ({ component_id: r.component_id, quantity: String(r.quantity || 1) }))
    return p
  }

  async function save() {
    setBusy(true)
    try {
      const r = isNew ? await A('/articoli', { body: payload() }) : await A(`/articoli/${id}`, { method: 'PUT', body: payload() })
      notifyOk('Articolo salvato')
      setIt(r)
      if (isNew) nav(`/articoli/${r.id}`, { replace: true })
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  async function duplicate() {
    try {
      const r = await A(`/articoli/${id}/duplica`, { method: 'POST' })
      notifyOk('Articolo duplicato')
      nav(`/articoli/${r.id}`)
    } catch (e) { notifyError(e) }
  }

  async function deactivate() {
    if (!confirm('Disattivare l\'articolo? Resterà nello storico dei documenti.')) return
    try {
      await A(`/articoli/${id}`, { method: 'DELETE' })
      notifyOk('Articolo disattivato')
      nav('/articoli')
    } catch (e) { notifyError(e) }
  }

  return (
    <>
      <Anchor size="sm" onClick={() => nav('/articoli')}><Group gap={4}><IconArrowLeft size={14} />Articoli</Group></Anchor>
      <Group justify="space-between" mt="xs" mb="md" wrap="wrap">
        <Group gap="sm">
          {it.images?.[0] && <img src={it.images[0].thumb_url} alt="" style={{ width: 48, height: 48, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--mantine-color-gray-3)' }} />}
          <Title order={2}>{isNew ? 'Nuovo articolo' : it.description}</Title>
          {!isNew && <Badge variant="outline" ff="monospace">{it.code}</Badge>}
          {!it.active && <Badge color="gray">disattivato</Badge>}
        </Group>
        <Group>
          {!isNew && (
            <Menu position="bottom-end">
              <Menu.Target><ActionIcon variant="default" size="lg"><IconDots size={18} /></ActionIcon></Menu.Target>
              <Menu.Dropdown>
                <Menu.Item leftSection={<IconCopy size={14} />} onClick={duplicate}>Duplica</Menu.Item>
                <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={deactivate}>Disattiva</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          )}
          <Button onClick={save} loading={busy}>Salva</Button>
        </Group>
      </Group>

      <Tabs defaultValue="generale" keepMounted={false}>
        <Tabs.List mb="md" style={{ flexWrap: 'wrap' }}>
          <Tabs.Tab value="generale">Generale</Tabs.Tab>
          <Tabs.Tab value="immagini">Immagini {it.images?.length > 0 && <Badge size="xs" ml={4}>{it.images.length}</Badge>}</Tabs.Tab>
          <Tabs.Tab value="prezzi">Prezzi e costi</Tabs.Tab>
          <Tabs.Tab value="allegati">Schede tecniche</Tabs.Tab>
          {it.item_type === 'articolo' && <Tabs.Tab value="magazzino">Magazzino</Tabs.Tab>}
          {fg.varianti && <Tabs.Tab value="varianti">Varianti {it.variants.length > 0 && <Badge size="xs" ml={4}>{it.variants.length}</Badge>}</Tabs.Tab>}
          <Tabs.Tab value="codici">Codici a barre e UM</Tabs.Tab>
          <Tabs.Tab value="fornitori">Fornitori</Tabs.Tab>
          {fg.distinta_base && <Tabs.Tab value="kit">Distinta base</Tabs.Tab>}
          {L.settings.custom_fields.some((c) => c.entity === 'item') && <Tabs.Tab value="extra">Campi personalizzati</Tabs.Tab>}
        </Tabs.List>

        <Tabs.Panel value="generale">
          <Paper withBorder p="md">
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
              <TextInput label="Codice" {...field('code')} styles={{ input: { fontFamily: 'monospace' } }} />
              <TextInput label="Descrizione" required {...field('description')} style={{ gridColumn: 'span 2' }} />
              <Select label="Tipo" data={[{ value: 'articolo', label: 'Articolo' }, { value: 'servizio', label: 'Servizio' }]} value={it.item_type}
                onChange={(v) => setIt({ ...it, item_type: v, stock_managed: v === 'articolo' ? it.stock_managed : false })} allowDeselect={false} />
              <TableSelect kind="categorie" label="Categoria" value={it.category_id} onChange={(v) => set('category_id', v)} clearable />
              <TableSelect kind="marche" label="Marca" value={it.brand_id} onChange={(v) => set('brand_id', v)} clearable />
              <TableSelect kind="unita-misura" valueKey="code" label="Unità di misura" value={it.unit} onChange={(v) => v && set('unit', v)} />
              <TableSelect kind="aliquote-iva" label="Aliquota IVA" filter={(v) => v.active} value={it.vat_rate_id} onChange={(v) => set('vat_rate_id', v)} />
              <TextInput label="Famiglia" {...field('family')} />
              <TextInput label="Linea" {...field('line')} />
              <TextInput label="Stagione" placeholder="es. Primavera-Estate 2027" {...field('season')} />
              <TagsInput label="Etichette" value={it.tags} onChange={(v) => set('tags', v)} placeholder="Invio per aggiungere" />
            </SimpleGrid>
            <SimpleGrid cols={{ base: 1, md: 2 }} mt="md">
              <Textarea label="Descrizione estesa (stampata nei documenti)" autosize minRows={3} {...field('long_description')} />
              <Textarea label="Note interne" autosize minRows={3} {...field('notes')} />
            </SimpleGrid>
            {fg.intrastat && (
              <SimpleGrid cols={{ base: 1, sm: 3 }} mt="md">
                <TextInput label="Nomenclatura combinata (Intrastat)" {...field('intrastat_code')} maxLength={8} />
                <TextInput label="Paese di origine" placeholder="IT" {...field('origin_country')} maxLength={2} />
              </SimpleGrid>
            )}
            <Switch mt="md" label="Articolo attivo" checked={it.active} onChange={(e) => set('active', e.currentTarget.checked)} />
          </Paper>
        </Tabs.Panel>

        <Tabs.Panel value="immagini">
          <Paper withBorder p="md"><ImagesEditor itemId={isNew ? undefined : it.id} images={it.images ?? []} onChange={(imgs) => setIt({ ...it, images: imgs, image_url: imgs[0]?.url ?? null })} /></Paper>
        </Tabs.Panel>

        <Tabs.Panel value="allegati"><AttachmentsEditor itemId={isNew ? undefined : it.id} /></Tabs.Panel>

        <Tabs.Panel value="prezzi">
          <Paper withBorder p="md" mb="md">
            <SimpleGrid cols={{ base: 1, sm: 3 }}>
              <NumberInput label="Costo ultimo (€)" decimalScale={4} min={0} {...numf('last_cost')} />
              <NumberInput label="Costo medio ponderato (€)" decimalScale={4} min={0} {...numf('avg_cost')} description="Aggiornato dai carichi di magazzino" />
              <NumberInput label="Costo standard (€)" decimalScale={4} min={0} {...numf('standard_cost')} />
            </SimpleGrid>
          </Paper>
          <PricesTable it={it} set={set} lists={L.lists} vatRate={vatRate} cost={cost} />
        </Tabs.Panel>

        <Tabs.Panel value="magazzino">
          <Paper withBorder p="md">
            <Group mb="md">
              <Switch label="Gestito a magazzino" checked={it.stock_managed} onChange={(e) => set('stock_managed', e.currentTarget.checked)} />
              {fg.lotti && <Switch label="Gestione lotti e scadenze" checked={it.lot_managed} onChange={(e) => setIt({ ...it, lot_managed: e.currentTarget.checked, serial_managed: e.currentTarget.checked ? false : it.serial_managed })} />}
              {fg.matricole && <Switch label="Gestione matricole" checked={it.serial_managed} onChange={(e) => setIt({ ...it, serial_managed: e.currentTarget.checked, lot_managed: e.currentTarget.checked ? false : it.lot_managed })} />}
            </Group>
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
              {it.lot_managed && <NumberInput label="Durata standard (giorni)" description="Propone la scadenza del lotto" min={0} {...numf('shelf_life_days')} />}
              {it.serial_managed && <NumberInput label="Garanzia (mesi)" min={0} {...numf('warranty_months')} />}
              <NumberInput label="Scorta minima" min={0} {...numf('min_stock')} />
              <NumberInput label="Scorta massima" min={0} {...numf('max_stock')} />
              <NumberInput label="Punto di riordino" min={0} {...numf('reorder_point')} />
              <NumberInput label="Quantità da riordinare" min={0} {...numf('reorder_qty')} />
              <TextInput label="Ubicazione" placeholder="es. A-03" {...field('location')} />
              <Select label="Fornitore preferito" data={opts(suppliers, (s) => s.name)} value={it.preferred_supplier_id} onChange={(v) => set('preferred_supplier_id', v)} clearable searchable />
              <NumberInput label="Tempo di consegna (giorni)" min={0} {...numf('lead_time_days')} />
            </SimpleGrid>
            {posDeps && (
              <>
                <Text fw={600} mt="lg" mb="xs">Vendita al banco</Text>
                <SimpleGrid cols={{ base: 1, sm: 3 }}>
                  <TextInput label="PLU" description="Codice breve per la cassa e la bilancia" maxLength={10} {...field('plu')} />
                  <Select label="Reparto" description="Raggruppa i corrispettivi" data={posDeps.filter((d) => d.active).map((d) => ({ value: d.id, label: `${d.code} · ${d.name}` }))}
                    value={it.pos_department_id} onChange={(v) => set('pos_department_id', v)} clearable />
                  <Switch mt="xl" label="Venduto a peso" description="La cassa chiede il peso (o lo legge dal codice della bilancia)" checked={!!it.sold_by_weight} onChange={(e) => set('sold_by_weight', e.currentTarget.checked)} />
                </SimpleGrid>
              </>
            )}
            {fg.dimensioni && (
              <>
                <Text fw={600} mt="lg" mb="xs">Pesi e dimensioni</Text>
                <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }}>
                  <NumberInput label="Peso netto (kg)" decimalScale={3} min={0} {...numf('weight_net')} />
                  <NumberInput label="Peso lordo (kg)" decimalScale={3} min={0} {...numf('weight_gross')} />
                  <NumberInput label="Volume (m³)" decimalScale={4} min={0} {...numf('volume')} />
                  <NumberInput label="Lunghezza (cm)" decimalScale={1} min={0} {...numf('length')} />
                  <NumberInput label="Larghezza (cm)" decimalScale={1} min={0} {...numf('width')} />
                  <NumberInput label="Altezza (cm)" decimalScale={1} min={0} {...numf('height')} />
                </SimpleGrid>
              </>
            )}
          </Paper>
        </Tabs.Panel>

        <Tabs.Panel value="varianti"><VariantsEditor it={it} set={set} /></Tabs.Panel>
        <Tabs.Panel value="codici"><CodesEditor it={it} set={set} units={L.units} /></Tabs.Panel>
        <Tabs.Panel value="fornitori"><SuppliersEditor it={it} set={set} suppliers={suppliers} /></Tabs.Panel>
        <Tabs.Panel value="kit"><KitEditor it={it} set={set} /></Tabs.Panel>
        <Tabs.Panel value="extra">
          <Paper withBorder p="md">
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
              {L.settings.custom_fields.filter((c) => c.entity === 'item').map((c) => (
                <CustomField key={c.key} def={c} value={it.custom?.[c.key]} onChange={(v) => set('custom', { ...it.custom, [c.key]: v })} />
              ))}
            </SimpleGrid>
          </Paper>
        </Tabs.Panel>
      </Tabs>
    </>
  )
}

export function CustomField({ def, value, onChange }: { def: any; value: any; onChange: (v: any) => void }) {
  if (def.field_type === 'number') return <NumberInput label={def.label} value={num(value)} onChange={onChange} />
  if (def.field_type === 'bool') return <Checkbox mt={28} label={def.label} checked={!!value} onChange={(e) => onChange(e.currentTarget.checked)} />
  if (def.field_type === 'list') return <Select label={def.label} data={def.options} value={value ?? null} onChange={onChange} clearable />
  if (def.field_type === 'date') return <TextInput type="date" label={def.label} value={value ?? ''} onChange={(e) => onChange(e.currentTarget.value)} />
  return <TextInput label={def.label} value={value ?? ''} onChange={(e) => onChange(e.currentTarget.value)} />
}

function PricesTable({ it, set, lists, vatRate, cost }: { it: any; set: (k: string, v: any) => void; lists: any[]; vatRate: number; cost: number }) {
  const rows = it.prices
  const upd = (i: number, k: string, v: any) => set('prices', rows.map((r: any, j: number) => (j === i ? { ...r, [k]: v } : r)))
  const add = () => set('prices', [...rows, { price_list_id: lists.find((l) => l.is_default)?.id ?? lists[0]?.id, min_qty: 0, price: '' }])
  const calc = (r: any) => {
    const list = lists.find((l) => l.id === r.price_list_id)
    let net = Number(r.price || 0)
    for (const d of [r.discount1, r.discount2, r.discount3]) if (d) net = (net * (100 - Number(d))) / 100
    const ex = list?.vat_included && vatRate ? (net * 100) / (100 + vatRate) : net
    const markup = cost && ex ? ((ex - cost) / cost) * 100 : null
    return { net, ex, markup }
  }
  return (
    <Paper withBorder>
      <Table.ScrollContainer minWidth={820}>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>Listino</Table.Th><Table.Th>Da quantità</Table.Th><Table.Th>Prezzo</Table.Th><Table.Th>Sc.1 %</Table.Th><Table.Th>Sc.2 %</Table.Th><Table.Th>Sc.3 %</Table.Th><Table.Th>Netto IVA esclusa</Table.Th><Table.Th>Ricarico</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r: any, i: number) => {
              const c = calc(r)
              return (
                <Table.Tr key={i}>
                  <Table.Td><Select data={lists.map((l) => ({ value: l.id, label: `${l.code}${l.vat_included ? ' (IVA incl.)' : ''}` }))} value={r.price_list_id} onChange={(v) => upd(i, 'price_list_id', v)} allowDeselect={false} w={190} /></Table.Td>
                  <Table.Td><NumberInput value={num(r.min_qty)} onChange={(v) => upd(i, 'min_qty', v)} min={0} w={90} /></Table.Td>
                  <Table.Td><NumberInput value={num(r.price)} onChange={(v) => upd(i, 'price', v)} decimalScale={4} min={0} w={110} prefix="€ " /></Table.Td>
                  {['discount1', 'discount2', 'discount3'].map((d) => <Table.Td key={d}><NumberInput value={num(r[d])} onChange={(v) => upd(i, d, v)} min={0} max={100} w={70} /></Table.Td>)}
                  <Table.Td>{fmtEuro(c.ex)}</Table.Td>
                  <Table.Td>{c.markup != null ? <Badge color={c.markup < 0 ? 'red' : c.markup < 20 ? 'yellow' : 'green'} variant="light">{c.markup.toFixed(1)}%</Badge> : '—'}</Table.Td>
                  <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => set('prices', rows.filter((_: any, j: number) => j !== i))}><IconTrash size={16} /></ActionIcon></Table.Td>
                </Table.Tr>
              )
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Group p="sm"><Button variant="light" size="xs" leftSection={<IconPlus size={14} />} onClick={add}>Aggiungi prezzo</Button>
        <Text size="xs" c="dimmed">Più righe sullo stesso listino con quantità diverse = prezzi a scaglioni.</Text></Group>
    </Paper>
  )
}

function VariantsEditor({ it, set }: { it: any; set: (k: string, v: any) => void }) {
  const [sizes, setSizes] = useState<string[]>([])
  const [colors, setColors] = useState<string[]>([])
  const rows = it.variants
  const upd = (i: number, k: string, v: any) => set('variants', rows.map((r: any, j: number) => (j === i ? { ...r, [k]: v } : r)))
  function generate() {
    const existing = new Set(rows.map((r: any) => r.code))
    const add: any[] = []
    const cs = colors.length ? colors : [null]
    for (const c of cs) for (const s of sizes.length ? sizes : [null]) {
      const code = [it.code, c ? c.slice(0, 3).toUpperCase() : null, s].filter(Boolean).join('-')
      if (!existing.has(code)) add.push({ code, size: s, color: c, format: null, price_delta: '', active: true })
    }
    set('variants', [...rows, ...add])
  }
  return (
    <Stack>
      <Paper withBorder p="md">
        <Text fw={600} mb="xs">Genera la griglia taglie × colori</Text>
        <Group align="flex-end" wrap="wrap">
          <TagsInput label="Taglie" value={sizes} onChange={setSizes} placeholder="S, M, L…" w={260} />
          <TagsInput label="Colori" value={colors} onChange={setColors} placeholder="Bianco, Nero…" w={260} />
          <Button variant="light" onClick={generate} disabled={!sizes.length && !colors.length}>Genera varianti</Button>
        </Group>
      </Paper>
      <Paper withBorder>
        <Table.ScrollContainer minWidth={640}>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Codice variante</Table.Th><Table.Th>Taglia</Table.Th><Table.Th>Colore</Table.Th><Table.Th>Formato</Table.Th><Table.Th>Maggiorazione €</Table.Th><Table.Th>Attiva</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {rows.map((r: any, i: number) => (
                <Table.Tr key={i}>
                  <Table.Td><TextInput value={r.code} onChange={(e) => upd(i, 'code', e.currentTarget.value)} ff="monospace" /></Table.Td>
                  <Table.Td><TextInput value={r.size ?? ''} onChange={(e) => upd(i, 'size', e.currentTarget.value)} w={80} /></Table.Td>
                  <Table.Td><TextInput value={r.color ?? ''} onChange={(e) => upd(i, 'color', e.currentTarget.value)} w={110} /></Table.Td>
                  <Table.Td><TextInput value={r.format ?? ''} onChange={(e) => upd(i, 'format', e.currentTarget.value)} w={100} /></Table.Td>
                  <Table.Td><NumberInput value={num(r.price_delta)} onChange={(v) => upd(i, 'price_delta', v)} decimalScale={2} w={100} /></Table.Td>
                  <Table.Td><Checkbox checked={r.active !== false} onChange={(e) => upd(i, 'active', e.currentTarget.checked)} /></Table.Td>
                  <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => set('variants', rows.filter((_: any, j: number) => j !== i))}><IconTrash size={16} /></ActionIcon></Table.Td>
                </Table.Tr>
              ))}
              {rows.length === 0 && <Table.Tr><Table.Td colSpan={7}><Text c="dimmed" ta="center" py="md" size="sm">Nessuna variante: l'articolo è unico.</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
    </Stack>
  )
}

function CodesEditor({ it, set, units }: { it: any; set: (k: string, v: any) => void; units: any[] }) {
  const bcs = it.barcodes
  const ums = it.units
  const updB = (i: number, k: string, v: any) => set('barcodes', bcs.map((r: any, j: number) => (j === i ? { ...r, [k]: v } : r)))
  const updU = (i: number, k: string, v: any) => set('units', ums.map((r: any, j: number) => (j === i ? { ...r, [k]: v } : r)))
  const variantOpts = it.variants.map((v: any) => v.code)
  async function genBarcode() {
    try {
      const used = new Set(bcs.map((b: any) => b.barcode))
      let r = await A('/articoli/genera-barcode')
      // il server non conosce ancora i codici non salvati: incrementa finché libero
      while (used.has(r.barcode)) r = { barcode: String(Number(r.barcode.slice(0, 12)) + 1) }
      set('barcodes', [...bcs, { barcode: r.barcode, barcode_type: 'EAN13', variant_code: null, unit: null, quantity: 1 }])
    } catch (e) { notifyError(e) }
  }
  return (
    <Stack>
      <Paper withBorder>
        <Group justify="space-between" p="sm"><Text fw={600}>Codici a barre</Text>
          <Group gap="xs">
            <Button size="xs" variant="light" leftSection={<IconBarcode size={14} />} onClick={genBarcode}>Genera EAN interno</Button>
            <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => set('barcodes', [...bcs, { barcode: '', barcode_type: 'EAN13', quantity: 1 }])}>Aggiungi</Button>
          </Group></Group>
        <Table.ScrollContainer minWidth={620}>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Codice</Table.Th><Table.Th>Tipo</Table.Th>{variantOpts.length > 0 && <Table.Th>Variante</Table.Th>}<Table.Th>Confezione</Table.Th><Table.Th>Quantità</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {bcs.map((r: any, i: number) => (
                <Table.Tr key={i}>
                  <Table.Td><TextInput value={r.barcode} onChange={(e) => updB(i, 'barcode', e.currentTarget.value)} ff="monospace" placeholder="Leggi con lo scanner" /></Table.Td>
                  <Table.Td><Select data={['EAN13', 'EAN8', 'UPC', 'CODE128', 'QR']} value={r.barcode_type} onChange={(v) => updB(i, 'barcode_type', v)} w={110} allowDeselect={false} /></Table.Td>
                  {variantOpts.length > 0 && <Table.Td><Select data={variantOpts} value={r.variant_code ?? null} onChange={(v) => updB(i, 'variant_code', v)} clearable w={170} /></Table.Td>}
                  <Table.Td><Select data={units.map((u) => u.code)} value={r.unit ?? null} onChange={(v) => updB(i, 'unit', v)} clearable w={90} /></Table.Td>
                  <Table.Td><NumberInput value={num(r.quantity)} onChange={(v) => updB(i, 'quantity', v)} min={0} w={80} /></Table.Td>
                  <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => set('barcodes', bcs.filter((_: any, j: number) => j !== i))}><IconTrash size={16} /></ActionIcon></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
      <Paper withBorder>
        <Group justify="space-between" p="sm"><Text fw={600}>Unità di misura secondarie</Text>
          <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => set('units', [...ums, { unit: null, factor: '' }])}>Aggiungi</Button></Group>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>Unità</Table.Th><Table.Th>Contiene ({it.unit})</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {ums.map((r: any, i: number) => (
              <Table.Tr key={i}>
                <Table.Td><Select data={units.filter((u) => u.code !== it.unit).map((u) => ({ value: u.code, label: `${u.code} — ${u.description}` }))} value={r.unit} onChange={(v) => updU(i, 'unit', v)} w={200} /></Table.Td>
                <Table.Td><NumberInput value={num(r.factor)} onChange={(v) => updU(i, 'factor', v)} min={0} decimalScale={4} w={120} /></Table.Td>
                <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => set('units', ums.filter((_: any, j: number) => j !== i))}><IconTrash size={16} /></ActionIcon></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Paper>
    </Stack>
  )
}

function SuppliersEditor({ it, set, suppliers }: { it: any; set: (k: string, v: any) => void; suppliers: any[] }) {
  const rows = it.suppliers
  const upd = (i: number, k: string, v: any) => set('suppliers', rows.map((r: any, j: number) => (j === i ? { ...r, [k]: v } : r)))
  return (
    <Paper withBorder>
      <Group justify="space-between" p="sm"><Text fw={600}>Codici e costi per fornitore</Text>
        <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => set('suppliers', [...rows, { supplier_id: null }])}>Aggiungi</Button></Group>
      <Table.ScrollContainer minWidth={640}>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>Fornitore</Table.Th><Table.Th>Codice fornitore</Table.Th><Table.Th>Ultimo costo</Table.Th><Table.Th>Sconto %</Table.Th><Table.Th>Ordine minimo</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((r: any, i: number) => (
              <Table.Tr key={i}>
                <Table.Td><Select data={opts(suppliers, (s) => s.name)} value={r.supplier_id} onChange={(v) => upd(i, 'supplier_id', v)} searchable w={220} /></Table.Td>
                <Table.Td><TextInput value={r.supplier_code ?? ''} onChange={(e) => upd(i, 'supplier_code', e.currentTarget.value)} /></Table.Td>
                <Table.Td><NumberInput value={num(r.last_cost)} onChange={(v) => upd(i, 'last_cost', v)} decimalScale={4} w={110} /></Table.Td>
                <Table.Td><NumberInput value={num(r.discount)} onChange={(v) => upd(i, 'discount', v)} w={80} /></Table.Td>
                <Table.Td><NumberInput value={num(r.min_order_qty)} onChange={(v) => upd(i, 'min_order_qty', v)} w={90} /></Table.Td>
                <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => set('suppliers', rows.filter((_: any, j: number) => j !== i))}><IconTrash size={16} /></ActionIcon></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Text size="xs" c="dimmed" p="sm">Il codice fornitore serve a riconoscere l'articolo quando importi le sue fatture elettroniche.</Text>
    </Paper>
  )
}

function KitEditor({ it, set }: { it: any; set: (k: string, v: any) => void }) {
  const [q, setQ] = useState('')
  const [found, setFound] = useState<any[]>([])
  useEffect(() => {
    if (q.length < 2) return setFound([])
    const t = setTimeout(() => A('/articoli?page_size=20&q=' + encodeURIComponent(q)).then((r) => setFound(r.rows.filter((x: any) => x.id !== it.id))).catch(() => {}), 250)
    return () => clearTimeout(t)
  }, [q])
  const rows = it.components
  const options = useMemo(() => found.map((f) => ({ value: f.id, label: `${f.code} — ${f.description}` })), [found])
  return (
    <Paper withBorder p="md">
      <Text size="sm" c="dimmed" mb="sm">Quando vendi un kit, il magazzino scarica i componenti nelle quantità indicate.</Text>
      <Select placeholder="Cerca un componente da aggiungere" searchable searchValue={q} onSearchChange={setQ} data={options} value={null}
        onChange={(v) => { const f = found.find((x) => x.id === v); if (f && !rows.some((r: any) => r.component_id === v)) set('components', [...rows, { component_id: f.id, code: f.code, description: f.description, quantity: 1 }]); setQ('') }}
        nothingFoundMessage={q.length >= 2 ? 'Nessun articolo' : 'Scrivi almeno 2 caratteri'} mb="md" />
      <Table>
        <Table.Thead><Table.Tr><Table.Th>Componente</Table.Th><Table.Th>Quantità</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {rows.map((r: any, i: number) => (
            <Table.Tr key={r.component_id}>
              <Table.Td><Text size="sm"><Text span ff="monospace" size="xs" c="dimmed">{r.code}</Text> {r.description}</Text></Table.Td>
              <Table.Td><NumberInput value={num(r.quantity)} onChange={(v) => set('components', rows.map((x: any, j: number) => (j === i ? { ...x, quantity: v } : x)))} decimalScale={4} min={0} w={110} /></Table.Td>
              <Table.Td><Tooltip label="Rimuovi"><ActionIcon variant="subtle" color="red" onClick={() => set('components', rows.filter((_: any, j: number) => j !== i))}><IconTrash size={16} /></ActionIcon></Tooltip></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Paper>
  )
}
