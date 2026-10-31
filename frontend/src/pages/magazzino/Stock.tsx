import { Anchor, Badge, Button, Group, Pagination, Paper, SegmentedControl, Select, SimpleGrid, Table, Tabs, Text, TextInput, Title } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconArrowLeft, IconArrowsExchange, IconPlus, IconSearch } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { fmtDate, fmtEuro } from '../../api'
import { Loading, PageTitle, Stat, notifyError } from '../../components'
import { REASON_COLORS, VariantGrid, W, qty, useWarehouses } from './shared'

export function StockList() {
  const nav = useNavigate()
  const whs = useWarehouses()
  const [q, setQ] = useState('')
  const [dq] = useDebouncedValue(q, 250)
  const [wh, setWh] = useState<string | null>(null)
  const [filtro, setFiltro] = useState('tutti')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<any>(null)
  useEffect(() => {
    const p = new URLSearchParams({ filtro, page: String(page) })
    if (dq) p.set('q', dq)
    if (wh) p.set('warehouse_id', wh)
    W('/giacenze?' + p).then(setData).catch(notifyError)
  }, [dq, wh, filtro, page])
  useEffect(() => setPage(1), [dq, wh, filtro])

  return (
    <>
      <PageTitle title="Giacenze" subtitle={data ? `Valore di magazzino ${fmtEuro(data.stock_value)} (costo medio)` : undefined}
        right={<Group>
          <Button variant="default" leftSection={<IconArrowsExchange size={16} />} onClick={() => nav('/magazzino/trasferimento')}>Trasferimento</Button>
          <Button leftSection={<IconPlus size={16} />} onClick={() => nav('/magazzino/operazione')}>Carico / scarico</Button>
        </Group>} />
      <Group mb="md" wrap="wrap">
        <TextInput placeholder="Cerca o leggi un codice a barre" leftSection={<IconSearch size={16} />} value={q} onChange={(e) => setQ(e.currentTarget.value)} style={{ flex: 1, minWidth: 220 }} autoFocus />
        {whs && whs.length > 1 && <Select placeholder="Tutti i magazzini" data={whs.map((w) => ({ value: w.id, label: w.name }))} value={wh} onChange={setWh} clearable w={220} />}
        <SegmentedControl value={filtro} onChange={setFiltro} data={[{ value: 'tutti', label: 'Tutti' }, { value: 'disponibili', label: 'Disponibili' }, { value: 'sotto_scorta', label: 'Sotto scorta' }, { value: 'esauriti', label: 'Esauriti' }]} />
      </Group>
      {!data ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={760}>
            <Table highlightOnHover verticalSpacing="xs">
              <Table.Thead><Table.Tr><Table.Th>Codice</Table.Th><Table.Th>Descrizione</Table.Th><Table.Th>Ubicazione</Table.Th>
                <Table.Th ta="right">Giacenza</Table.Th><Table.Th ta="right">Impegnata</Table.Th><Table.Th ta="right">Disponibile</Table.Th><Table.Th ta="right">Valore</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {data.rows.map((r: any) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/magazzino/articolo/${r.id}`)}>
                    <Table.Td ff="monospace" fz="sm">{r.code}</Table.Td>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap"><Text size="sm" fw={500}>{r.description}</Text>
                        {r.has_variants && <Badge size="xs" variant="light" color="violet">varianti</Badge>}
                        {r.lot_managed && <Badge size="xs" variant="light" color="orange">lotti</Badge>}
                        {r.serial_managed && <Badge size="xs" variant="light" color="cyan">matricole</Badge>}
                      </Group>
                    </Table.Td>
                    <Table.Td fz="sm" c="dimmed">{r.location ?? ''}</Table.Td>
                    <Table.Td ta="right" fw={600} c={Number(r.on_hand) < 0 ? 'red' : r.under_min ? 'orange' : undefined}>{qty(r.on_hand, r.unit)}</Table.Td>
                    <Table.Td ta="right" c="dimmed">{Number(r.reserved) ? qty(r.reserved) : ''}</Table.Td>
                    <Table.Td ta="right">{qty(r.available)}</Table.Td>
                    <Table.Td ta="right" fz="sm">{fmtEuro(r.value)}</Table.Td>
                  </Table.Tr>
                ))}
                {data.rows.length === 0 && <Table.Tr><Table.Td colSpan={7}><Text ta="center" c="dimmed" py="lg">Nessun articolo</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      {data && data.total > data.page_size && <Group justify="center" mt="md"><Pagination total={Math.ceil(data.total / data.page_size)} value={page} onChange={setPage} /></Group>}
    </>
  )
}

export function StockDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [d, setD] = useState<any>(null)
  const [gridWh, setGridWh] = useState<string>('tutti')
  useEffect(() => { W(`/giacenze/${id}`).then(setD).catch(notifyError) }, [id])
  if (!d) return <Loading />
  const it = d.item
  const total = d.warehouses.reduce((t: number, w: any) => t + Number(w.on_hand), 0)
  const reserved = d.warehouses.reduce((t: number, w: any) => t + Number(w.reserved), 0)
  const gridValues: Record<string, number> = {}
  d.grid?.variants.forEach((v: any) => {
    gridValues[v.id] = gridWh === 'tutti' ? Object.values(v.stock).reduce((t: number, x: any) => t + Number(x), 0) : Number(v.stock[gridWh] ?? 0)
  })
  return (
    <>
      <Anchor size="sm" onClick={() => nav('/magazzino/giacenze')}><Group gap={4}><IconArrowLeft size={14} />Giacenze</Group></Anchor>
      <Group justify="space-between" mt="xs" mb="md" wrap="wrap">
        <div><Title order={2}>{it.description}</Title><Text c="dimmed" size="sm" ff="monospace">{it.code}{it.location ? ` · ubicazione ${it.location}` : ''}</Text></div>
        <Group>
          <Button variant="default" onClick={() => nav(`/articoli/${it.id}`)}>Scheda articolo</Button>
          <Button onClick={() => nav(`/magazzino/operazione?articolo=${it.id}`)}>Carico / scarico</Button>
        </Group>
      </Group>
      <SimpleGrid cols={{ base: 2, md: 4 }} mb="lg">
        <Stat label="Giacenza totale" value={qty(total, it.unit)} />
        <Stat label="Impegnata" value={qty(reserved)} />
        <Stat label="Disponibile" value={qty(total - reserved)} />
        <Stat label="Costo medio" value={it.avg_cost ? fmtEuro(it.avg_cost) : '—'} hint={it.last_cost ? `Ultimo ${fmtEuro(it.last_cost)}` : undefined} />
      </SimpleGrid>

      {d.grid && (
        <Paper withBorder p="md" mb="lg">
          <Group justify="space-between" mb="sm">
            <Text fw={600}>Taglie e colori</Text>
            {d.all_warehouses.length > 1 && (
              <SegmentedControl size="xs" value={gridWh} onChange={setGridWh}
                data={[{ value: 'tutti', label: 'Tutti' }, ...d.all_warehouses.map((w: any) => ({ value: w.id, label: w.name }))]} />
            )}
          </Group>
          <VariantGrid variants={d.grid.variants} values={gridValues} minStock={it.min_stock ? Number(it.min_stock) : null} />
        </Paper>
      )}

      <Tabs defaultValue={d.lots.length ? 'lotti' : d.serials.length ? 'matricole' : 'magazzini'} keepMounted={false}>
        <Tabs.List mb="md">
          <Tabs.Tab value="magazzini">Per magazzino</Tabs.Tab>
          {it.lot_managed && <Tabs.Tab value="lotti">Lotti ({d.lots.length})</Tabs.Tab>}
          {it.serial_managed && <Tabs.Tab value="matricole">Matricole ({d.serials.filter((x: any) => x.status === 'disponibile').length} disponibili)</Tabs.Tab>}
          <Tabs.Tab value="movimenti">Ultimi movimenti</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="magazzini">
          <Paper withBorder><Table>
            <Table.Thead><Table.Tr><Table.Th>Magazzino</Table.Th><Table.Th ta="right">Giacenza</Table.Th><Table.Th ta="right">Impegnata</Table.Th><Table.Th ta="right">In arrivo</Table.Th><Table.Th ta="right">Disponibile</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {d.warehouses.map((w: any) => (
                <Table.Tr key={w.warehouse_id}><Table.Td>{w.name}</Table.Td><Table.Td ta="right" fw={600}>{qty(w.on_hand, it.unit)}</Table.Td>
                  <Table.Td ta="right">{qty(w.reserved)}</Table.Td><Table.Td ta="right">{qty(w.ordered)}</Table.Td><Table.Td ta="right">{qty(w.available)}</Table.Td></Table.Tr>
              ))}
              {d.warehouses.length === 0 && <Table.Tr><Table.Td colSpan={5}><Text c="dimmed" ta="center" py="md" size="sm">Nessuna giacenza</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table></Paper>
        </Tabs.Panel>
        <Tabs.Panel value="lotti">
          <Paper withBorder><Table>
            <Table.Thead><Table.Tr><Table.Th>Lotto</Table.Th><Table.Th>Scadenza</Table.Th><Table.Th>Magazzino</Table.Th><Table.Th ta="right">Quantità</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {d.lots.map((l: any, i: number) => {
                const days = l.expiry_date ? Math.round((new Date(l.expiry_date).getTime() - Date.now()) / 86400000) : null
                return (
                  <Table.Tr key={i}><Table.Td ff="monospace">{l.lot_number}</Table.Td>
                    <Table.Td>{fmtDate(l.expiry_date)} {days !== null && days <= 7 && <Badge size="xs" color={days < 0 ? 'red' : 'orange'}>{days < 0 ? 'scaduto' : `${days} gg`}</Badge>}</Table.Td>
                    <Table.Td>{l.warehouse}</Table.Td><Table.Td ta="right" fw={600}>{qty(l.on_hand, it.unit)}</Table.Td></Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table></Paper>
        </Tabs.Panel>
        <Tabs.Panel value="matricole">
          <Paper withBorder><Table>
            <Table.Thead><Table.Tr><Table.Th>Matricola</Table.Th><Table.Th>Stato</Table.Th><Table.Th>Magazzino</Table.Th><Table.Th>Venduto il</Table.Th><Table.Th>Garanzia fino al</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {d.serials.map((x: any) => (
                <Table.Tr key={x.serial_number}><Table.Td ff="monospace">{x.serial_number}</Table.Td>
                  <Table.Td><Badge variant="light" color={x.status === 'disponibile' ? 'green' : x.status === 'venduto' ? 'blue' : 'gray'}>{x.status}</Badge></Table.Td>
                  <Table.Td>{x.warehouse ?? '—'}</Table.Td><Table.Td>{fmtDate(x.sale_date)}</Table.Td><Table.Td>{fmtDate(x.warranty_until)}</Table.Td></Table.Tr>
              ))}
            </Table.Tbody>
          </Table></Paper>
        </Tabs.Panel>
        <Tabs.Panel value="movimenti"><MovementsTable rows={d.movements} hideItem /></Tabs.Panel>
      </Tabs>
    </>
  )
}

export function MovementsTable({ rows, hideItem }: { rows: any[]; hideItem?: boolean }) {
  return (
    <Paper withBorder>
      <Table.ScrollContainer minWidth={720}>
        <Table verticalSpacing="xs">
          <Table.Thead><Table.Tr><Table.Th>Data</Table.Th><Table.Th>Causale</Table.Th>{!hideItem && <Table.Th>Articolo</Table.Th>}<Table.Th>Dettaglio</Table.Th><Table.Th>Magazzino</Table.Th><Table.Th ta="right">Quantità</Table.Th><Table.Th>Riferimento</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {rows.map((m) => (
              <Table.Tr key={m.id}>
                <Table.Td fz="sm">{new Date(m.moved_at).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}</Table.Td>
                <Table.Td><Badge variant="light" color={REASON_COLORS[m.reason] ?? 'gray'}>{m.reason_label}</Badge></Table.Td>
                {!hideItem && <Table.Td fz="sm"><Text span ff="monospace" size="xs" c="dimmed">{m.code}</Text> {m.description}</Table.Td>}
                <Table.Td fz="xs" c="dimmed">{[m.variant_code, m.lot_number && `lotto ${m.lot_number}`, m.serial_number && `matr. ${m.serial_number}`].filter(Boolean).join(' · ')}</Table.Td>
                <Table.Td fz="sm">{m.warehouse}</Table.Td>
                <Table.Td ta="right" fw={600} c={Number(m.quantity) < 0 ? 'red' : 'green'}>{Number(m.quantity) > 0 ? '+' : ''}{qty(m.quantity)}</Table.Td>
                <Table.Td fz="xs" c="dimmed">{m.party ?? m.reference ?? ''}</Table.Td>
              </Table.Tr>
            ))}
            {rows.length === 0 && <Table.Tr><Table.Td colSpan={7}><Text ta="center" c="dimmed" py="md" size="sm">Nessun movimento</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Paper>
  )
}

export function Movements() {
  const whs = useWarehouses()
  const [wh, setWh] = useState<string | null>(null)
  const [reason, setReason] = useState<string | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<any>(null)
  useEffect(() => {
    const p = new URLSearchParams({ page: String(page) })
    if (wh) p.set('warehouse_id', wh)
    if (reason) p.set('reason', reason)
    if (from) p.set('date_from', from)
    if (to) p.set('date_to', to)
    W('/movimenti?' + p).then(setData).catch(notifyError)
  }, [wh, reason, from, to, page])
  return (
    <>
      <PageTitle title="Movimenti di magazzino" subtitle={data ? `${data.total} movimenti` : undefined} />
      <Group mb="md" wrap="wrap">
        {whs && whs.length > 1 && <Select placeholder="Tutti i magazzini" data={whs.map((w) => ({ value: w.id, label: w.name }))} value={wh} onChange={setWh} clearable w={200} />}
        <Select placeholder="Tutte le causali" value={reason} onChange={setReason} clearable w={200}
          data={[['carico', 'Carico'], ['scarico', 'Scarico'], ['vendita', 'Vendita'], ['acquisto', 'Acquisto'], ['rettifica', 'Rettifica'], ['inventario', 'Inventario'], ['trasferimento', 'Trasferimento'], ['scarto', 'Scarto'], ['omaggio', 'Omaggio']].map(([value, label]) => ({ value, label }))} />
        <TextInput type="date" value={from} onChange={(e) => setFrom(e.currentTarget.value)} aria-label="Dal" />
        <TextInput type="date" value={to} onChange={(e) => setTo(e.currentTarget.value)} aria-label="Al" />
      </Group>
      {!data ? <Loading /> : <MovementsTable rows={data.rows} />}
      {data && data.total > data.page_size && <Group justify="center" mt="md"><Pagination total={Math.ceil(data.total / data.page_size)} value={page} onChange={setPage} /></Group>}
    </>
  )
}
