// Furgoni (magazzino viaggiante con agente, targa e sezionale) e giro clienti abituale per giorno della settimana.

import { ActionIcon, Alert, Badge, Button, Checkbox, Chip, Drawer, Group, Modal, NumberInput, Paper, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput, Textarea } from '@mantine/core'
import { IconArrowDown, IconArrowUp, IconPlus, IconRoute, IconTrash, IconTruck } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { StatusBadge, TV, WEEKDAYS, qtyFmt } from './shared'

const EMPTY = { code: '', name: '', vehicle: '', plate: '', series: '', home_warehouse_id: null, agent_id: null, max_discount: 0,
  allowed_docs: ['DDT', 'FTI', 'ORC', 'NC'], cash_account_id: null, blind_count: true, active: true, notes: '' }

export default function Vans() {
  const nav = useNavigate()
  const [vans, setVans] = useState<any[] | null>(null)
  const [opt, setOpt] = useState<any>(null)
  const [edit, setEdit] = useState<any>(null)
  const [route, setRoute] = useState<any>(null)
  const [stock, setStock] = useState<any>(null)
  const load = () => TV('/furgoni').then(setVans).catch(notifyError)
  useEffect(() => { load(); TV('/opzioni').then(setOpt).catch(notifyError) }, [])
  if (!vans || !opt) return <Loading />
  return (
    <>
      <PageTitle title="Furgoni" subtitle="Ogni furgone è un magazzino viaggiante con il suo agente, il sezionale dei documenti e il giro clienti"
        right={<Button leftSection={<IconPlus size={16} />} onClick={() => setEdit({ ...EMPTY })}>Nuovo furgone</Button>} />
      {!vans.length && <Alert color="blue" mb="md">Crea il primo furgone: BluBeauty gli prepara un magazzino dedicato. Poi assegna l'agente e il giro clienti.</Alert>}
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {vans.map((v) => (
          <Paper key={v.id} withBorder p="md" radius="md">
            <Group justify="space-between" align="flex-start">
              <Group gap="sm" wrap="nowrap">
                <IconTruck size={28} color="var(--mantine-color-blue-6)" />
                <div>
                  <Text fw={700}>{v.code} · {v.name}</Text>
                  <Text size="sm" c="dimmed">{[v.vehicle, v.plate].filter(Boolean).join(' · ') || 'Mezzo non indicato'}</Text>
                </div>
              </Group>
              {!v.active && <Badge color="gray">Non attivo</Badge>}
            </Group>
            <Stack gap={4} mt="sm">
              <Text size="sm">Agente: <b>{v.agent ?? 'non assegnato'}</b></Text>
              <Text size="sm">Sezionale documenti: <b>/{v.series}</b> · sconto massimo {qtyFmt(v.max_discount)}%</Text>
              <Text size="sm">Carica da: {v.home_warehouse ?? '—'}</Text>
              <Text size="sm">Giro clienti: {v.route_count} clienti</Text>
              <Text size="sm">Rientro: {v.blind_count ? 'conta alla cieca del magazziniere' : 'conta con quantità attese visibili'}</Text>
              {v.open_trip && <Group gap={6}><Text size="sm">Giro aperto: {v.open_trip.weekday} {new Date(v.open_trip.trip_date).toLocaleDateString('it-IT')}</Text><StatusBadge trip={v.open_trip} /></Group>}
            </Stack>
            <Group mt="md" gap="xs">
              <Button size="xs" variant="light" onClick={() => setEdit({ ...v })}>Modifica</Button>
              <Button size="xs" variant="light" leftSection={<IconRoute size={14} />} onClick={() => setRoute(v)}>Giro clienti</Button>
              <Button size="xs" variant="subtle" onClick={() => TV(`/furgoni/${v.id}`).then(setStock).catch(notifyError)}>Merce a bordo</Button>
              {v.open_trip && <Button size="xs" variant="subtle" onClick={() => nav(`/tentata/giri/${v.open_trip.id}`)}>Apri giro</Button>}
            </Group>
          </Paper>
        ))}
      </SimpleGrid>
      {edit && <VanEditor van={edit} opt={opt} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load() }} />}
      {route && <RouteEditor van={route} onClose={() => { setRoute(null); load() }} />}
      <Modal opened={!!stock} onClose={() => setStock(null)} title={stock ? `Merce a bordo · ${stock.code} ${stock.name}` : ''} size="lg">
        {stock && (stock.stock.length ? (
          <Table striped fz="sm">
            <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th>Lotto</Table.Th><Table.Th ta="right">Quantità</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>{stock.stock.map((r: any, i: number) => (
              <Table.Tr key={i}><Table.Td>{r.code} · {r.description}{r.variant && <Text span c="dimmed"> · {r.variant}</Text>}</Table.Td>
                <Table.Td>{r.lot_number ?? ''}</Table.Td><Table.Td ta="right">{qtyFmt(r.quantity)} {r.unit}</Table.Td></Table.Tr>))}
            </Table.Tbody>
          </Table>) : <Text c="dimmed">Il furgone è vuoto.</Text>)}
      </Modal>
    </>
  )
}

function VanEditor({ van, opt, onClose, onSaved }: { van: any; opt: any; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState<any>({ ...van, max_discount: Number(van.max_discount ?? 0) })
  const [busy, setBusy] = useState(false)
  const set = (k: string, x: any) => setV((o: any) => ({ ...o, [k]: x }))
  async function save() {
    setBusy(true)
    try {
      const body = { ...v, max_discount: String(v.max_discount ?? 0) }
      if (v.id) await TV(`/furgoni/${v.id}`, { method: 'PUT', body })
      else await TV('/furgoni', { body })
      notifyOk('Furgone salvato')
      onSaved()
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Modal opened onClose={onClose} title={v.id ? `Furgone ${v.code}` : 'Nuovo furgone'} size="lg">
      <Stack>
        <SimpleGrid cols={3}>
          <TextInput label="Codice" required value={v.code} onChange={(e) => set('code', e.currentTarget.value.toUpperCase())} disabled={!!v.id} maxLength={10} />
          <TextInput label="Nome" required value={v.name} onChange={(e) => set('name', e.currentTarget.value)} style={{ gridColumn: 'span 2' }} />
          <TextInput label="Mezzo" placeholder="es. Fiat Ducato" value={v.vehicle ?? ''} onChange={(e) => set('vehicle', e.currentTarget.value)} />
          <TextInput label="Targa" value={v.plate ?? ''} onChange={(e) => set('plate', e.currentTarget.value.toUpperCase())} />
          <TextInput label="Sezionale documenti" required description="es. A1: DDT 12/A1" value={v.series} disabled={!!v.id}
            onChange={(e) => set('series', e.currentTarget.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))} maxLength={10} />
        </SimpleGrid>
        <SimpleGrid cols={2}>
          <Select label="Agente" data={opt.agents} value={v.agent_id} onChange={(x) => set('agent_id', x)} clearable searchable
            description="Utente con ruolo «agente»: vede solo questo furgone" />
          <Select label="Carica dal magazzino" data={opt.warehouses.filter((w: any) => w.value !== v.warehouse_id)} value={v.home_warehouse_id}
            onChange={(x) => set('home_warehouse_id', x)} />
          <NumberInput label="Sconto massimo dell'agente (%)" min={0} max={100} decimalScale={2} value={v.max_discount} onChange={(x) => set('max_discount', x)} />
          <Select label="Contanti e assegni in" data={opt.accounts.filter((a: any) => a.kind === 'cassa')} value={v.cash_account_id}
            onChange={(x) => set('cash_account_id', x)} clearable description="Conto cassa dell'agente" />
        </SimpleGrid>
        <Checkbox.Group label="Documenti che l'agente può emettere" value={v.allowed_docs} onChange={(x) => set('allowed_docs', x)}>
          <Group mt={6}>{opt.doc_kinds.map((d: any) => <Checkbox key={d.value} value={d.value} label={d.label} />)}</Group>
        </Checkbox.Group>
        <Switch label="Conta alla cieca al rientro" description="Il magazziniere conta senza vedere le quantità attese: le differenze emergono alla conferma"
          checked={v.blind_count} onChange={(e) => set('blind_count', e.currentTarget.checked)} />
        {v.id && <Switch label="Furgone attivo" checked={v.active} onChange={(e) => set('active', e.currentTarget.checked)} />}
        <Textarea label="Note" value={v.notes ?? ''} onChange={(e) => set('notes', e.currentTarget.value)} autosize minRows={2} />
        {!v.id && <Text size="xs" c="dimmed">BluBeauty crea un magazzino «Furgone {v.name || '…'}» dedicato: la merce a bordo è la sua giacenza.</Text>}
        <Group justify="flex-end"><Button onClick={save} loading={busy} disabled={!v.code || !v.name || !v.series}>Salva</Button></Group>
      </Stack>
    </Modal>
  )
}

function RouteEditor({ van, onClose }: { van: any; onClose: () => void }) {
  const [rows, setRows] = useState<any[] | null>(null)
  const [q, setQ] = useState('')
  const [found, setFound] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => { TV(`/furgoni/${van.id}/giro-clienti`).then(setRows).catch(notifyError) }, [van.id])
  useEffect(() => {
    if (q.length < 2) { setFound([]); return }
    const t = setTimeout(() => TV(`/clienti?q=${encodeURIComponent(q)}`).then(setFound).catch(() => {}), 250)
    return () => clearTimeout(t)
  }, [q])
  const move = (i: number, d: number) => setRows((r) => { const x = [...r!]; const [a] = x.splice(i, 1); x.splice(i + d, 0, a); return x })
  async function save() {
    setBusy(true)
    try {
      setRows(await TV(`/furgoni/${van.id}/giro-clienti`, { method: 'PUT', body: rows!.map((r) => ({ party_id: r.party_id, weekdays: r.weekdays, notes: r.notes })) }))
      notifyOk('Giro clienti salvato')
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Drawer opened onClose={onClose} position="right" size="xl" title={`Giro clienti · ${van.code} ${van.name}`}>
      {!rows ? <Loading /> : (
        <Stack>
          <Text size="sm" c="dimmed">I clienti nell'ordine di visita e i giorni in cui passa il furgone: il giro di ogni giorno parte da qui,
            più i clienti con ordini da consegnare.</Text>
          <Select placeholder="Aggiungi un cliente (nome, città, P.IVA)" searchable searchValue={q} onSearchChange={setQ} value={null}
            data={found.filter((f) => !rows.some((r) => r.party_id === f.id)).map((f) => ({ value: f.id, label: `${f.name}${f.city ? ' · ' + f.city : ''}` }))}
            nothingFoundMessage={q.length < 2 ? 'Scrivi almeno 2 lettere' : 'Nessun cliente'}
            onChange={(id) => { const f = found.find((x) => x.id === id); if (f) setRows([...rows, { party_id: f.id, name: f.name, city: f.city, weekdays: [0, 1, 2, 3, 4], notes: '' }]); setQ('') }} />
          {rows.map((r, i) => (
            <Paper key={r.party_id} withBorder p="sm">
              <Group justify="space-between" wrap="nowrap">
                <div style={{ minWidth: 0 }}>
                  <Text fw={600} truncate>{i + 1}. {r.name}</Text>
                  <Text size="xs" c="dimmed">{[r.address, r.city].filter(Boolean).join(', ')}</Text>
                </div>
                <Group gap={2} wrap="nowrap">
                  <ActionIcon variant="subtle" disabled={i === 0} onClick={() => move(i, -1)}><IconArrowUp size={16} /></ActionIcon>
                  <ActionIcon variant="subtle" disabled={i === rows.length - 1} onClick={() => move(i, 1)}><IconArrowDown size={16} /></ActionIcon>
                  <ActionIcon variant="subtle" color="red" onClick={() => setRows(rows.filter((_, n) => n !== i))}><IconTrash size={16} /></ActionIcon>
                </Group>
              </Group>
              <Chip.Group multiple value={r.weekdays.map(String)} onChange={(v) => setRows(rows.map((x, n) => (n === i ? { ...x, weekdays: v.map(Number).sort() } : x)))}>
                <Group gap={4} mt="xs">{WEEKDAYS.map((d, n) => <Chip key={n} value={String(n)} size="xs">{d}</Chip>)}</Group>
              </Chip.Group>
              <TextInput mt="xs" size="xs" placeholder="Note per l'agente (orari, scarico merce…)" value={r.notes ?? ''}
                onChange={(e) => { const val = e.currentTarget.value; setRows(rows.map((x, n) => (n === i ? { ...x, notes: val } : x))) }} />
            </Paper>
          ))}
          {!rows.length && <Text c="dimmed" ta="center" py="lg">Nessun cliente nel giro</Text>}
          <Group justify="flex-end"><Button onClick={save} loading={busy}>Salva giro clienti</Button></Group>
        </Stack>
      )}
    </Drawer>
  )
}
