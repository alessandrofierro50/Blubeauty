import { ActionIcon, Anchor, Badge, Button, Checkbox, Group, Menu, Modal, NumberInput, Pagination, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, TagsInput, Text, TextInput, Textarea, Title } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconArrowLeft, IconChevronDown, IconFileImport, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { dec, num, opts, useLookups } from '../anagrafiche/shared'
import { ItemScanner } from '../magazzino/Operation'
import { useWarehouses } from '../magazzino/shared'

export const P = (path: string, opts?: { method?: string; body?: unknown }) => appApi('/api/acquisti' + path, opts)

export const TYPE_LABEL: Record<string, string> = { ORF: 'Ordine', DDTF: 'DDT', FTF: 'Fattura', NCF: 'Nota di credito' }
export const STATUS_COLOR: Record<string, string> = { bozza: 'gray', confermato: 'blue', evaso: 'green', annullato: 'red' }

export function useSuppliers() {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => { appApi('/api/anagrafiche/soggetti?tipo=fornitori&page_size=200').then((r) => setRows(r.rows)).catch(() => {}) }, [])
  return rows
}

export function PurchaseList() {
  const nav = useNavigate()
  const [tipo, setTipo] = useState('tutti')
  const [q, setQ] = useState('')
  const [dq] = useDebouncedValue(q, 250)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<any>(null)
  const [sel, setSel] = useState<string[]>([])
  const [invoiceOpen, setInvoiceOpen] = useState(false)
  const [invNumber, setInvNumber] = useState('')
  const [invDate, setInvDate] = useState('')

  const load = () => {
    const p = new URLSearchParams({ page: String(page) })
    if (tipo === 'da_fatturare') p.set('da_fatturare', 'true')
    else if (tipo !== 'tutti') p.set('tipo', tipo)
    if (dq) p.set('q', dq)
    P('/documenti?' + p).then(setData).catch(notifyError)
  }
  useEffect(load, [tipo, dq, page])
  useEffect(() => { setPage(1); setSel([]) }, [tipo, dq])

  async function createInvoice() {
    try {
      const d = await P('/fattura-da-ddt', { body: { ddt_ids: sel, external_number: invNumber, external_date: invDate || null } })
      notifyOk('Fattura creata in bozza: controlla e conferma')
      nav(`/acquisti/${d.id}`)
    } catch (e) { notifyError(e) }
  }

  return (
    <>
      <PageTitle title="Acquisti" subtitle="Ordini, DDT e fatture dei fornitori"
        right={<Group>
          <Button variant="default" leftSection={<IconFileImport size={16} />} onClick={() => nav('/acquisti/import-xml')}>Importa fatture XML</Button>
          <Menu position="bottom-end">
            <Menu.Target><Button leftSection={<IconPlus size={16} />} rightSection={<IconChevronDown size={14} />}>Nuovo</Button></Menu.Target>
            <Menu.Dropdown>
              <Menu.Item onClick={() => nav('/acquisti/nuovo?tipo=ORF')}>Ordine a fornitore</Menu.Item>
              <Menu.Item onClick={() => nav('/acquisti/nuovo?tipo=DDTF')}>DDT fornitore (carico merce)</Menu.Item>
              <Menu.Item onClick={() => nav('/acquisti/nuovo?tipo=FTF')}>Fattura fornitore</Menu.Item>
              <Menu.Item onClick={() => nav('/acquisti/nuovo?tipo=NCF')}>Nota di credito fornitore</Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>} />
      <Group mb="md" wrap="wrap">
        <SegmentedControl value={tipo} onChange={setTipo} data={[{ value: 'tutti', label: 'Tutti' }, { value: 'ORF', label: 'Ordini' }, { value: 'DDTF', label: 'DDT' },
          { value: 'FTF', label: 'Fatture' }, { value: 'NCF', label: 'Note credito' }, { value: 'da_fatturare', label: 'DDT da fatturare' }]} />
        <TextInput placeholder="Fornitore o numero" leftSection={<IconSearch size={16} />} value={q} onChange={(e) => setQ(e.currentTarget.value)} style={{ flex: 1, minWidth: 200 }} />
        {tipo === 'da_fatturare' && <Button disabled={!sel.length} onClick={() => setInvoiceOpen(true)}>Registra fattura ({sel.length} DDT)</Button>}
      </Group>
      {!data ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={760}>
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead><Table.Tr>{tipo === 'da_fatturare' && <Table.Th w={36} />}<Table.Th>Documento</Table.Th><Table.Th>Data</Table.Th><Table.Th>Fornitore</Table.Th><Table.Th>N. fornitore</Table.Th><Table.Th ta="right">Totale</Table.Th><Table.Th>Stato</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {data.rows.map((d: any) => (
                  <Table.Tr key={d.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/acquisti/${d.id}`)}>
                    {tipo === 'da_fatturare' && <Table.Td onClick={(e) => e.stopPropagation()}><Checkbox checked={sel.includes(d.id)} onChange={(e) => setSel(e.currentTarget.checked ? [...sel, d.id] : sel.filter((x) => x !== d.id))} /></Table.Td>}
                    <Table.Td><Group gap={6}><Badge variant="light">{TYPE_LABEL[d.doc_type]}</Badge><Text size="sm" fw={600}>{d.number ? `n. ${d.number}/${d.year}` : 'bozza'}</Text>{d.source === 'xml' && <Badge size="xs" variant="outline">XML</Badge>}</Group></Table.Td>
                    <Table.Td fz="sm">{fmtDate(d.doc_date)}</Table.Td>
                    <Table.Td fz="sm" fw={500}>{d.party_name}</Table.Td>
                    <Table.Td fz="sm">{d.external_number ?? ''}</Table.Td>
                    <Table.Td ta="right" fw={600}>{fmtEuro(d.total)}</Table.Td>
                    <Table.Td><Badge color={STATUS_COLOR[d.status]} variant="dot">{d.status}</Badge></Table.Td>
                  </Table.Tr>
                ))}
                {data.rows.length === 0 && <Table.Tr><Table.Td colSpan={7}><Text ta="center" c="dimmed" py="lg">Nessun documento</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {data && data.total > data.page_size && <Group justify="center" mt="md"><Pagination total={Math.ceil(data.total / data.page_size)} value={page} onChange={setPage} /></Group>}
      <Modal opened={invoiceOpen} onClose={() => setInvoiceOpen(false)} title="Fattura dei DDT selezionati">
        <Stack>
          <Text size="sm" c="dimmed">La merce è già stata caricata con i DDT: la fattura non muove il magazzino ma può aggiornare i costi.</Text>
          <TextInput label="Numero fattura del fornitore" value={invNumber} onChange={(e) => setInvNumber(e.currentTarget.value)} />
          <TextInput type="date" label="Data fattura" value={invDate} onChange={(e) => setInvDate(e.currentTarget.value)} />
          <Group justify="flex-end"><Button onClick={createInvoice} disabled={!invNumber}>Crea fattura</Button></Group>
        </Stack>
      </Modal>
    </>
  )
}

const EMPTY_LINE = { item_id: null, variant_id: null, description: '', unit: '', quantity: 1, unit_price: '', discount1: '', discount2: '', discount3: '', vat_rate_id: null, lot_number: '', expiry_date: '', serials: [] as string[] }

export function PurchaseEditor() {
  const { id } = useParams()
  const isNew = id === 'nuovo'
  const [params] = useSearchParams()
  const nav = useNavigate()
  const L = useLookups()
  const whs = useWarehouses()
  const suppliers = useSuppliers()
  const [d, setD] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [transformOpen, setTransformOpen] = useState<string | null>(null)
  const [extNum, setExtNum] = useState('')

  useEffect(() => {
    if (isNew) {
      const t = params.get('tipo') || 'DDTF'
      setD({ doc_type: t, party_id: null, doc_date: '', external_number: '', external_date: '', warehouse_id: null, payment_term_id: null,
        moves_stock: t !== 'ORF', reference: '', notes: '', status: 'bozza', lines: [], vat_summary: [], related: [] })
    } else P(`/documenti/${id}`).then(setD).catch(notifyError)
  }, [id])
  useEffect(() => { if (isNew && d && !d.warehouse_id && whs?.length) setD({ ...d, warehouse_id: whs[0].id }) }, [whs, d?.doc_type])

  if (!d || !L || !whs) return <Loading />
  const draft = d.status === 'bozza'
  const set = (k: string, v: any) => setD({ ...d, [k]: v })
  const updLine = (i: number, k: string, v: any) => set('lines', d.lines.map((l: any, j: number) => (j === i ? { ...l, [k]: v } : l)))
  const lineTotal = (l: any) => {
    let p = Number(l.unit_price || 0)
    for (const x of [l.discount1, l.discount2, l.discount3]) if (x) p = (p * (100 - Number(x))) / 100
    return Math.round(p * Number(l.quantity || 0) * 100) / 100
  }
  const vatRate = (l: any) => Number(L.vat.find((v) => v.id === l.vat_rate_id)?.rate ?? 0)
  const taxable = d.lines.reduce((t: number, l: any) => t + lineTotal(l), 0)
  const groups: Record<string, number> = {}
  d.lines.forEach((l: any) => { const r = vatRate(l); groups[r] = (groups[r] ?? 0) + lineTotal(l) })
  const vat = Object.entries(groups).reduce((t, [r, v]) => t + Math.round(v * Number(r)) / 100, 0)

  function addItem(it: any) {
    const full = it
    appApi(`/api/anagrafiche/articoli/${it.id}`).then((a) => {
      const sup = a.suppliers.find((s: any) => s.supplier_id === d.party_id)
      setD((cur: any) => ({ ...cur, lines: [...cur.lines, { ...EMPTY_LINE, item_id: a.id, item_code: a.code, description: a.description, unit: a.unit,
        variant_id: full.variant_id ?? null, variants: full.variants, lot_managed: a.lot_managed, serial_managed: a.serial_managed,
        unit_price: Number(sup?.last_cost ?? a.last_cost ?? 0) || '', vat_rate_id: a.vat_rate_id, quantity: a.serial_managed ? 0 : 1 }] }))
    }).catch(notifyError)
  }

  function payload() {
    return {
      doc_type: d.doc_type, party_id: d.party_id, doc_date: d.doc_date || null, external_number: d.external_number || null,
      external_date: d.external_date || null, warehouse_id: d.warehouse_id, payment_term_id: d.payment_term_id, moves_stock: d.moves_stock,
      reference: d.reference || null, notes: d.notes || null,
      lines: d.lines.map((l: any) => ({ item_id: l.item_id, variant_id: l.variant_id, description: l.description, unit: l.unit || null,
        quantity: String(l.serial_managed ? (l.serials?.length ?? 0) : l.quantity || 0), unit_price: String(l.unit_price || 0),
        discount1: dec(l.discount1), discount2: dec(l.discount2), discount3: dec(l.discount3), vat_rate_id: l.vat_rate_id,
        lot_number: l.lot_number || null, expiry_date: l.expiry_date || null, serials: l.serials ?? [], origin_line_id: l.origin_line_id ?? null,
        supplier_code: l.supplier_code ?? null })),
    }
  }

  async function save(andConfirm = false) {
    if (!d.party_id) return notifyError(new Error('Scegli il fornitore'))
    setBusy(true)
    try {
      let r = isNew ? await P('/documenti', { body: payload() }) : await P(`/documenti/${id}`, { method: 'PUT', body: payload() })
      if (andConfirm) r = await P(`/documenti/${r.id}/conferma`, { method: 'POST' })
      notifyOk(andConfirm ? 'Documento confermato' : 'Bozza salvata')
      if (isNew) nav(`/acquisti/${r.id}`, { replace: true })
      setD(r)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function action(path: string, msg: string) {
    try { setD(await P(`/documenti/${id}/${path}`, { method: 'POST' })); notifyOk(msg) } catch (e) { notifyError(e) }
  }
  async function remove() {
    if (!confirm('Eliminare la bozza?')) return
    try { await P(`/documenti/${id}`, { method: 'DELETE' }); nav('/acquisti') } catch (e) { notifyError(e) }
  }
  async function transform() {
    try {
      const r = await P(`/documenti/${id}/trasforma`, { body: { to: transformOpen, external_number: extNum || null } })
      setTransformOpen(null)
      nav(`/acquisti/${r.id}`)
    } catch (e) { notifyError(e) }
  }

  const title = `${({ ORF: 'Ordine a fornitore', DDTF: 'DDT fornitore', FTF: 'Fattura fornitore', NCF: 'Nota di credito fornitore' } as any)[d.doc_type]}${d.number ? ` n. ${d.number}/${d.year}` : ''}`
  return (
    <>
      <Anchor size="sm" onClick={() => nav('/acquisti')}><Group gap={4}><IconArrowLeft size={14} />Acquisti</Group></Anchor>
      <Group justify="space-between" mt="xs" mb="md" wrap="wrap">
        <Group gap="xs"><Title order={2}>{title}</Title><Badge color={STATUS_COLOR[d.status]} variant="light">{d.status}</Badge>{d.source === 'xml' && <Badge variant="outline">da fattura elettronica</Badge>}</Group>
        <Group>
          {draft && !isNew && <Button variant="subtle" color="red" onClick={remove}>Elimina</Button>}
          {draft && <Button variant="default" onClick={() => save(false)} loading={busy}>Salva bozza</Button>}
          {draft && <Button onClick={() => save(true)} loading={busy}>Conferma</Button>}
          {d.doc_type === 'ORF' && d.status === 'confermato' && (
            <Menu><Menu.Target><Button rightSection={<IconChevronDown size={14} />}>Evadi ordine</Button></Menu.Target>
              <Menu.Dropdown><Menu.Item onClick={() => setTransformOpen('DDTF')}>Ricevuto con DDT</Menu.Item><Menu.Item onClick={() => setTransformOpen('FTF')}>Ricevuto con fattura</Menu.Item></Menu.Dropdown></Menu>
          )}
          {!draft && d.status !== 'annullato' && <Button variant="subtle" color="red" onClick={() => confirm('Annullare il documento? I movimenti di magazzino verranno stornati.') && action('annulla', 'Documento annullato')}>Annulla documento</Button>}
          {d.xml_url && <Button variant="default" component="a" href={d.xml_url} target="_blank">XML originale</Button>}
          {!draft && d.status !== 'annullato' && ['DDTF', 'FTF'].includes(d.doc_type) && <Button variant="default" onClick={() => nav(`/etichette?doc=${d.id}`)}>Stampa etichette</Button>}
        </Group>
      </Group>

      <Paper withBorder p="md" mb="md">
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
          <Select label="Fornitore" data={opts(suppliers, (s) => s.name)} value={d.party_id} onChange={(v) => set('party_id', v)} searchable disabled={!draft} />
          {d.doc_type !== 'ORF' && <TextInput label={`Numero ${d.doc_type === 'DDTF' ? 'DDT' : 'fattura'} del fornitore`} value={d.external_number ?? ''} onChange={(e) => set('external_number', e.currentTarget.value)} disabled={!draft} />}
          <TextInput type="date" label={d.doc_type === 'ORF' ? 'Data ordine' : 'Data documento'} value={d.doc_date ?? ''} onChange={(e) => set('doc_date', e.currentTarget.value)} disabled={!draft} />
          <Select label="Magazzino" data={whs.map((w) => ({ value: w.id, label: w.name }))} value={d.warehouse_id} onChange={(v) => set('warehouse_id', v)} disabled={!draft} allowDeselect={false} />
          <Select label="Pagamento" data={opts(L.payments)} value={d.payment_term_id} onChange={(v) => set('payment_term_id', v)} clearable disabled={!draft} />
          <TextInput label="Riferimento" value={d.reference ?? ''} onChange={(e) => set('reference', e.currentTarget.value)} disabled={!draft} />
          {d.doc_type !== 'ORF' && <Switch mt={28} label={d.doc_type === 'NCF' ? 'Scarica il magazzino (reso)' : 'Carica il magazzino'} checked={d.moves_stock} onChange={(e) => set('moves_stock', e.currentTarget.checked)} disabled={!draft} />}
        </SimpleGrid>
      </Paper>

      {draft && <div style={{ marginBottom: 12 }}><ItemScanner onPick={addItem} autoFocus={false} all /></div>}

      <Paper withBorder mb="md">
        <Table.ScrollContainer minWidth={980}>
          <Table verticalSpacing={6}>
            <Table.Thead><Table.Tr><Table.Th>Articolo / descrizione</Table.Th><Table.Th w={150}>Lotto · variante · matricole</Table.Th><Table.Th w={90}>Q.tà</Table.Th><Table.Th w={110}>Prezzo</Table.Th><Table.Th w={150}>Sconti %</Table.Th><Table.Th w={110}>IVA</Table.Th><Table.Th w={100} ta="right">Importo</Table.Th>{draft && <Table.Th w={40} />}</Table.Tr></Table.Thead>
            <Table.Tbody>
              {d.lines.map((l: any, i: number) => (
                <Table.Tr key={i}>
                  <Table.Td>
                    {l.item_code && <Text size="xs" ff="monospace" c="dimmed">{l.item_code}{l.supplier_code ? ` · forn. ${l.supplier_code}` : ''}</Text>}
                    {draft ? <Textarea size="xs" autosize minRows={1} value={l.description} onChange={(e) => updLine(i, 'description', e.currentTarget.value)} /> : <Text size="sm">{l.description}</Text>}
                  </Table.Td>
                  <Table.Td>
                    {l.variants?.length > 0 && <Select size="xs" placeholder="variante" data={l.variants.map((v: any) => ({ value: v.id, label: [v.color, v.size].filter(Boolean).join(' ') || v.code }))} value={l.variant_id} onChange={(v) => updLine(i, 'variant_id', v)} disabled={!draft} />}
                    {!l.variants?.length && l.variant_code && <Text size="xs">{l.variant_code}</Text>}
                    {l.lot_managed && (draft ? <Group gap={4} wrap="nowrap"><TextInput size="xs" placeholder="lotto" value={l.lot_number ?? ''} onChange={(e) => updLine(i, 'lot_number', e.currentTarget.value)} /><TextInput size="xs" type="date" value={l.expiry_date ?? ''} onChange={(e) => updLine(i, 'expiry_date', e.currentTarget.value)} /></Group> : <Text size="xs">lotto {l.lot_number}</Text>)}
                    {l.serial_managed && (draft ? <TagsInput size="xs" placeholder="matricole" value={l.serials ?? []} onChange={(v) => updLine(i, 'serials', v)} /> : <Text size="xs">{(l.serials ?? []).join(', ')}</Text>)}
                  </Table.Td>
                  <Table.Td>{draft && !l.serial_managed ? <NumberInput size="xs" hideControls value={num(l.quantity)} onChange={(v) => updLine(i, 'quantity', v)} min={0} /> : <Text size="sm">{Number(l.serial_managed ? (l.serials?.length ?? l.quantity) : l.quantity)} {l.unit}</Text>}</Table.Td>
                  <Table.Td>{draft ? <NumberInput size="xs" hideControls value={num(l.unit_price)} onChange={(v) => updLine(i, 'unit_price', v)} decimalScale={4} min={0} /> : <Text size="sm">{fmtEuro(l.unit_price)}</Text>}</Table.Td>
                  <Table.Td>
                    <Group gap={2} wrap="nowrap">{['discount1', 'discount2', 'discount3'].map((k) => draft ? <NumberInput key={k} size="xs" hideControls value={num(l[k])} onChange={(v) => updLine(i, k, v)} min={0} max={100} w={46} /> : l[k] ? <Text key={k} size="xs">{Number(l[k])}%</Text> : null)}</Group>
                  </Table.Td>
                  <Table.Td>{draft ? <Select size="xs" data={L.vat.filter((v) => v.active).map((v) => ({ value: v.id, label: v.code }))} value={l.vat_rate_id} onChange={(v) => updLine(i, 'vat_rate_id', v)} /> : <Text size="xs">{l.vat_nature ?? `${Number(l.vat_rate)}%`}</Text>}</Table.Td>
                  <Table.Td ta="right" fw={600}>{fmtEuro(lineTotal(l))}</Table.Td>
                  {draft && <Table.Td><ActionIcon variant="subtle" color="red" onClick={() => set('lines', d.lines.filter((_: any, j: number) => j !== i))}><IconTrash size={16} /></ActionIcon></Table.Td>}
                </Table.Tr>
              ))}
              {d.lines.length === 0 && <Table.Tr><Table.Td colSpan={8}><Text ta="center" c="dimmed" py="md" size="sm">Leggi o cerca gli articoli da aggiungere</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {draft && <Group p="sm"><Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => set('lines', [...d.lines, { ...EMPTY_LINE, description: 'Spese di trasporto', vat_rate_id: L.vat.find((v) => v.code === '22')?.id }])}>Riga descrittiva / spese</Button></Group>}
      </Paper>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Stack>
          {d.related?.length > 0 && (
            <Paper withBorder p="md">
              <Text fw={600} mb="xs">Documenti collegati</Text>
              {d.related.map((r: any) => <Anchor key={r.id} display="block" size="sm" onClick={() => nav(`/acquisti/${r.id}`)}>{r.direction === 'origine' ? '← ' : '→ '}{r.label} {r.external_number ?? (r.number ? `n. ${r.number}` : 'bozza')} del {fmtDate(r.date)} · {r.status}</Anchor>)}
            </Paper>
          )}
          {d.payment_schedule?.length > 0 && (
            <Paper withBorder p="md">
              <Text fw={600} mb="xs">Scadenze di pagamento</Text>
              {d.payment_schedule.map((p: any, i: number) => <Text key={i} size="sm">{fmtDate(p.due_date)} · {fmtEuro(p.amount)}{p.iban ? ` · IBAN ${p.iban}` : ''}</Text>)}
            </Paper>
          )}
        </Stack>
        <Paper withBorder p="md">
          <Group justify="space-between"><Text>Imponibile</Text><Text fw={600}>{fmtEuro(taxable)}</Text></Group>
          {Object.entries(groups).sort((a, b) => Number(b[0]) - Number(a[0])).map(([r, v]) => (
            <Group key={r} justify="space-between"><Text size="sm" c="dimmed">IVA {Number(r)}% su {fmtEuro(v)}</Text><Text size="sm">{fmtEuro(Math.round(v * Number(r)) / 100)}</Text></Group>
          ))}
          {Number(d.stamp_duty) > 0 && <Group justify="space-between"><Text size="sm" c="dimmed">Bollo</Text><Text size="sm">{fmtEuro(d.stamp_duty)}</Text></Group>}
          <Group justify="space-between" mt="xs" pt="xs" style={{ borderTop: '1px solid var(--mantine-color-gray-3)' }}><Text fw={700}>Totale</Text><Text fw={800} fz="xl">{fmtEuro(taxable + vat + Number(d.stamp_duty || 0))}</Text></Group>
        </Paper>
      </SimpleGrid>

      <Modal opened={!!transformOpen} onClose={() => setTransformOpen(null)} title={transformOpen === 'DDTF' ? 'Merce ricevuta con DDT' : 'Merce ricevuta con fattura'}>
        <Stack>
          <Text size="sm" c="dimmed">Viene creato il documento con le quantità ancora da ricevere: modificale se la consegna è parziale, poi conferma per caricare il magazzino.</Text>
          <TextInput label={`Numero ${transformOpen === 'DDTF' ? 'DDT' : 'fattura'} del fornitore`} value={extNum} onChange={(e) => setExtNum(e.currentTarget.value)} />
          <Group justify="flex-end"><Button onClick={transform}>Crea</Button></Group>
        </Stack>
      </Modal>
    </>
  )
}
