import { ActionIcon, Alert, Anchor, Badge, Button, Group, Modal, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput, Textarea } from '@mantine/core'
import { IconPlus, IconRepeat, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fmtDate, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { dec, num, useLookups } from '../anagrafiche/shared'
import { CustomerPicker, S, StatusBadge } from './shared'

const FREQ = [{ value: '1', label: 'Mensile' }, { value: '2', label: 'Bimestrale' }, { value: '3', label: 'Trimestrale' }, { value: '4', label: 'Quadrimestrale' }, { value: '6', label: 'Semestrale' }, { value: '12', label: 'Annuale' }]

export default function Contracts() {
  const nav = useNavigate()
  const [data, setData] = useState<any>(null)
  const [filter, setFilter] = useState('attivi')
  const [edit, setEdit] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const load = () => S(`/contratti${filter === 'tutti' ? '' : `?attivi=${filter === 'attivi'}`}`).then(setData).catch(notifyError)
  useEffect(() => { load() }, [filter])

  async function generate() {
    setBusy(true)
    try {
      const r = await S('/contratti/genera', { body: {} })
      notifyOk(r.documents.length ? `${r.documents.length} fatture create` : 'Nessun canone da fatturare oggi')
      load()
      if (r.documents.length === 1) nav(`/vendite/${r.documents[0].id}`)
      else if (r.documents.length) nav('/vendite?tipo=FTI')
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function openContract(id: string) {
    try { setEdit(await S(`/contratti/${id}`)) } catch (e) { notifyError(e) }
  }

  if (!data) return <Loading />
  const yearly = data.rows.filter((r: any) => r.active).reduce((s: number, r: any) => s + Number(r.yearly), 0)
  return (
    <>
      <PageTitle title="Contratti e canoni" subtitle="Abbonamenti, assistenze, noleggi: le fatture si emettono da sole alla scadenza di ogni periodo"
        right={<Group>
          <Button variant="default" leftSection={<IconRepeat size={16} />} onClick={generate} loading={busy} disabled={!data.due}>Fattura i canoni scaduti{data.due ? ` (${data.due})` : ''}</Button>
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEdit({ party_id: null, description: '', start_date: isoDate(new Date()), end_date: '', frequency_months: 1, billing: 'anticipata', auto_confirm: true, payment_term_id: null, active: true, notes: '', lines: [{ description: '', quantity: 1, unit_price: '', vat_rate_id: null }] })}>Nuovo contratto</Button>
        </Group>} />
      <Group mb="md" justify="space-between">
        <SegmentedControl value={filter} onChange={setFilter} data={[{ value: 'attivi', label: 'Attivi' }, { value: 'conclusi', label: 'Conclusi' }, { value: 'tutti', label: 'Tutti' }]} />
        <Text size="sm" c="dimmed">Valore annuo dei contratti attivi <b>{fmtEuro(yearly)}</b> + IVA</Text>
      </Group>
      <Paper withBorder>
        <Table.ScrollContainer minWidth={760}>
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead><Table.Tr><Table.Th>Contratto</Table.Th><Table.Th>Cliente</Table.Th><Table.Th>Periodicità</Table.Th><Table.Th>Prossima fattura</Table.Th><Table.Th ta="right">Importo</Table.Th><Table.Th>Ultima fattura</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {data.rows.map((c: any) => {
                const due = c.active && c.next_invoice_date <= isoDate(new Date())
                return (
                  <Table.Tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => openContract(c.id)}>
                    <Table.Td><Text size="xs" ff="monospace" c="dimmed">{c.code}</Text><Text size="sm" fw={600}>{c.description}</Text></Table.Td>
                    <Table.Td fz="sm">{c.party_name}</Table.Td>
                    <Table.Td fz="sm">{c.frequency_label}{c.billing === 'posticipata' ? ' · posticipata' : ''}{!c.auto_confirm && <Badge ml={6} size="xs" variant="outline">da controllare</Badge>}</Table.Td>
                    <Table.Td fz="sm">{c.active ? <Text size="sm" c={due ? 'red' : undefined} fw={due ? 700 : undefined}>{fmtDate(c.next_invoice_date)}</Text> : <Badge color="gray" variant="light">concluso</Badge>}</Table.Td>
                    <Table.Td ta="right" fw={600}>{fmtEuro(c.taxable)}</Table.Td>
                    <Table.Td fz="sm">{c.last_invoice ? `n. ${c.last_invoice.number ?? 'bozza'} del ${fmtDate(c.last_invoice.date)}` : '—'}</Table.Td>
                  </Table.Tr>
                )
              })}
              {data.rows.length === 0 && <Table.Tr><Table.Td colSpan={6}><Text ta="center" c="dimmed" py="lg">Nessun contratto. Crea il primo: canoni di assistenza, abbonamenti, noleggi…</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
      {edit && <ContractModal c={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load() }} />}
    </>
  )
}

function ContractModal({ c: initial, onClose, onSaved }: { c: any; onClose: () => void; onSaved: () => void }) {
  const nav = useNavigate()
  const L = useLookups()
  const [c, setC] = useState<any>({ ...initial, lines: initial.lines.map((l: any) => ({ ...l, quantity: Number(l.quantity), unit_price: l.unit_price === '' ? '' : Number(l.unit_price) })) })
  const set = (k: string, v: any) => setC((x: any) => ({ ...x, [k]: v }))
  const updLine = (i: number, k: string, v: any) => setC((x: any) => ({ ...x, lines: x.lines.map((l: any, j: number) => (j === i ? { ...l, [k]: v } : l)) }))
  if (!L) return null
  const vat22 = L.vat.find((v) => v.code === '22')?.id
  const taxable = c.lines.reduce((s: number, l: any) => s + Number(l.quantity || 0) * Number(l.unit_price || 0) * (1 - Number(l.discount1 || 0) / 100), 0)

  async function save() {
    try {
      const body = {
        party_id: c.party_id, description: c.description, start_date: c.start_date, end_date: c.end_date || null,
        frequency_months: Number(c.frequency_months), billing: c.billing, next_invoice_date: c.id ? c.next_invoice_date : null,
        auto_confirm: c.auto_confirm, payment_term_id: c.payment_term_id, active: c.active, notes: c.notes || null,
        lines: c.lines.map((l: any) => ({ item_id: l.item_id ?? null, description: l.description, quantity: String(l.quantity || 1), unit_price: String(l.unit_price || 0), discount1: dec(l.discount1), vat_rate_id: l.vat_rate_id || vat22 })),
      }
      if (c.id) await S(`/contratti/${c.id}`, { method: 'PUT', body })
      else await S('/contratti', { body })
      notifyOk('Contratto salvato')
      onSaved()
    } catch (e) { notifyError(e) }
  }
  async function remove() {
    if (!confirm('Eliminare il contratto? Se ha già emesso fatture verrà solo disattivato.')) return
    try { await S(`/contratti/${c.id}`, { method: 'DELETE' }); onSaved() } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} size="xl" title={c.id ? `Contratto ${c.code}` : 'Nuovo contratto'}>
      <Stack>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <CustomerPicker label="Cliente" value={c.party_id} onChange={(v) => set('party_id', v)} required />
          <TextInput label="Descrizione" placeholder="es. Assistenza software annuale" value={c.description} onChange={(e) => set('description', e.currentTarget.value)} required />
          <Select label="Periodicità" data={FREQ} value={String(c.frequency_months)} onChange={(v) => set('frequency_months', Number(v))} allowDeselect={false} />
          <div>
            <Text size="sm" fw={500} mb={4}>Fatturazione</Text>
            <SegmentedControl fullWidth value={c.billing} onChange={(v) => set('billing', v)} data={[{ value: 'anticipata', label: 'Anticipata (inizio periodo)' }, { value: 'posticipata', label: 'Posticipata (fine periodo)' }]} />
          </div>
          <TextInput type="date" label="Inizio contratto" value={c.start_date} onChange={(e) => set('start_date', e.currentTarget.value)} />
          <TextInput type="date" label="Fine contratto (vuoto = a tempo indeterminato)" value={c.end_date ?? ''} onChange={(e) => set('end_date', e.currentTarget.value)} />
          {c.id && <TextInput type="date" label="Prossima fattura" value={c.next_invoice_date} onChange={(e) => set('next_invoice_date', e.currentTarget.value)} />}
          <Select label="Pagamento" data={L.payments.map((p) => ({ value: p.id, label: p.description }))} value={c.payment_term_id} onChange={(v) => set('payment_term_id', v)} clearable placeholder="quello del cliente" />
        </SimpleGrid>
        <Paper withBorder>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Voce in fattura</Table.Th><Table.Th w={80}>Q.tà</Table.Th><Table.Th w={120}>Prezzo</Table.Th><Table.Th w={80}>Sconto %</Table.Th><Table.Th w={100}>IVA</Table.Th><Table.Th w={40} /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {c.lines.map((l: any, i: number) => (
                <Table.Tr key={i}>
                  <Table.Td><TextInput size="xs" placeholder="es. Canone assistenza" value={l.description} onChange={(e) => updLine(i, 'description', e.currentTarget.value)} /></Table.Td>
                  <Table.Td><NumberInput size="xs" hideControls value={num(l.quantity)} onChange={(v) => updLine(i, 'quantity', v)} min={0} /></Table.Td>
                  <Table.Td><NumberInput size="xs" hideControls value={num(l.unit_price)} onChange={(v) => updLine(i, 'unit_price', v)} min={0} decimalScale={2} prefix="€ " /></Table.Td>
                  <Table.Td><NumberInput size="xs" hideControls value={num(l.discount1)} onChange={(v) => updLine(i, 'discount1', v)} min={0} max={100} /></Table.Td>
                  <Table.Td><Select size="xs" data={L.vat.filter((v) => v.active).map((v) => ({ value: v.id, label: v.code }))} value={l.vat_rate_id ?? vat22} onChange={(v) => updLine(i, 'vat_rate_id', v)} /></Table.Td>
                  <Table.Td><ActionIcon variant="subtle" color="red" disabled={c.lines.length === 1} onClick={() => set('lines', c.lines.filter((_: any, j: number) => j !== i))}><IconTrash size={16} /></ActionIcon></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Group justify="space-between" p="xs">
            <Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => set('lines', [...c.lines, { description: '', quantity: 1, unit_price: '', vat_rate_id: vat22 }])}>Aggiungi voce</Button>
            <Text size="sm">Ogni fattura <b>{fmtEuro(taxable)}</b> + IVA · all'anno <b>{fmtEuro((taxable * 12) / Number(c.frequency_months))}</b></Text>
          </Group>
        </Paper>
        <Text size="xs" c="dimmed">Nella fattura ogni voce riporta il periodo, es. «Canone assistenza – periodo 01/11/2026 – 30/11/2026».</Text>
        <Group>
          <Switch label="Emetti la fattura in automatico (altrimenti resta in bozza da controllare)" checked={c.auto_confirm} onChange={(e) => set('auto_confirm', e.currentTarget.checked)} />
          {c.id && <Switch label="Contratto attivo" checked={c.active} onChange={(e) => set('active', e.currentTarget.checked)} />}
        </Group>
        <Textarea label="Note interne" autosize minRows={1} value={c.notes ?? ''} onChange={(e) => set('notes', e.currentTarget.value)} />
        {c.invoices?.length > 0 && (
          <Alert variant="light" title="Fatture emesse">
            {c.invoices.map((d: any) => <Group key={d.id} gap="xs"><Anchor size="sm" onClick={() => nav(`/vendite/${d.id}`)}>n. {d.number ?? 'bozza'} del {fmtDate(d.doc_date)} · {fmtEuro(d.total)}</Anchor><StatusBadge d={d} /></Group>)}
          </Alert>
        )}
        <Group justify="space-between">
          {c.id ? <Button variant="subtle" color="red" onClick={remove}>Elimina</Button> : <span />}
          <Button onClick={save} disabled={!c.party_id || !c.description || c.lines.some((l: any) => !l.description)}>Salva contratto</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
