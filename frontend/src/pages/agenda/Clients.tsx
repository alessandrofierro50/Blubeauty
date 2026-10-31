import { Badge, Button, Checkbox, Grid, Group, Modal, Paper, Select, SimpleGrid, Stack, Table, Text, TextInput, Textarea, Title } from '@mantine/core'
import { DatePickerInput } from '@mantine/dates'
import { IconCalendarPlus, IconPlus, IconSearch } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { NewAppointment } from './Agenda'
import { STATUS, hhmm, longDay } from './lib'
import { WhatsAppChat } from './WhatsAppChat'

export function ClientsList() {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<any[] | null>(null)
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  useEffect(() => {
    const t = setTimeout(() => appApi(`/api/agenda/clienti?q=${encodeURIComponent(q)}`).then(setRows).catch(notifyError), 200)
    return () => clearTimeout(t)
  }, [q])
  return (
    <>
      <PageTitle title="Clienti" subtitle="Schede, consensi, schede tecniche e conversazioni WhatsApp"
        right={<Button leftSection={<IconPlus size={16} />} onClick={() => setOpen(true)}>Nuovo cliente</Button>} />
      <TextInput leftSection={<IconSearch size={16} />} placeholder="Cerca per nome, cellulare o email" value={q} onChange={(e) => setQ(e.target.value)} mb="md" />
      {!rows ? <Loading /> : (
        <Paper withBorder>
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead><Table.Tr><Table.Th>Cliente</Table.Th><Table.Th>Cellulare</Table.Th><Table.Th>Consensi</Table.Th><Table.Th ta="right">Punti</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {rows.map((c) => (
                <Table.Tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/agenda/clienti/${c.id}`)}>
                  <Table.Td fw={600}>{c.name}</Table.Td>
                  <Table.Td>{c.mobile ?? '—'}</Table.Td>
                  <Table.Td><Group gap={4}>
                    <Badge size="sm" variant="light" color={c.privacy ? 'green' : 'orange'}>Privacy</Badge>
                    <Badge size="sm" variant="light" color={c.marketing ? 'green' : 'gray'}>Marketing</Badge>
                  </Group></Table.Td>
                  <Table.Td ta="right">{c.loyalty_points}</Table.Td>
                </Table.Tr>
              ))}
              {rows.length === 0 && <Table.Tr><Table.Td colSpan={4}><Text c="dimmed" ta="center">Nessun cliente</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      {open && <NewClient onClose={() => setOpen(false)} onSaved={(c) => nav(`/agenda/clienti/${c.id}`)} />}
    </>
  )
}

function NewClient({ onClose, onSaved }: { onClose: () => void; onSaved: (c: any) => void }) {
  const [f, setF] = useState({ first_name: '', last_name: '', mobile: '', email: '', privacy: true, marketing: false, birth_date: null as Date | null })
  const save = async () => {
    try { onSaved(await appApi('/api/agenda/clienti', { body: { ...f, birth_date: f.birth_date ? isoDate(f.birth_date) : null } })) } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} title="Nuovo cliente">
      <Stack>
        <SimpleGrid cols={2}>
          <TextInput label="Nome" value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} />
          <TextInput label="Cognome" value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} />
        </SimpleGrid>
        <TextInput label="Cellulare (WhatsApp)" value={f.mobile} onChange={(e) => setF({ ...f, mobile: e.target.value })} />
        <TextInput label="Email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        <DatePickerInput label="Compleanno" value={f.birth_date} onChange={(d) => setF({ ...f, birth_date: d as Date | null })} clearable valueFormat="DD/MM/YYYY" />
        <Checkbox label="Consenso privacy (GDPR)" checked={f.privacy} onChange={(e) => setF({ ...f, privacy: e.target.checked })} />
        <Checkbox label="Consenso marketing (WhatsApp, SMS, email)" checked={f.marketing} onChange={(e) => setF({ ...f, marketing: e.target.checked })} />
        <Button onClick={save} disabled={!f.first_name || !f.last_name}>Salva</Button>
      </Stack>
    </Modal>
  )
}

const CARD_KIND: Record<string, string> = { colore: 'Formula colore', trattamento: 'Trattamento', anamnesi: 'Anamnesi', consenso: 'Consenso informato' }
const CARD_FIELDS: Record<string, string[]> = {
  colore: ['Marca', 'Tonalità', 'Ossidante', 'Posa (min)'],
  trattamento: ['Trattamento', 'Zona', 'Parametri', 'Prodotti'],
  anamnesi: ['Allergie', 'Controindicazioni', 'Farmaci', 'Gravidanza'],
  consenso: ['Trattamento', 'Rischi spiegati', 'Firma'],
}

export function ClientDetail() {
  const { id } = useParams()
  const [c, setC] = useState<any>(null)
  const [staff, setStaff] = useState<any[]>([])
  const [services, setServices] = useState<any[]>([])
  const [cardOpen, setCardOpen] = useState(false)
  const [book, setBook] = useState(false)
  const nav = useNavigate()
  const load = () => appApi(`/api/agenda/clienti/${id}`).then(setC).catch(notifyError)
  useEffect(() => {
    load()
    Promise.all([appApi('/api/agenda/operatori'), appApi('/api/agenda/servizi')]).then(([a, b]) => { setStaff(a.filter((x: any) => x.active)); setServices(b) }).catch(() => {})
  }, [id])
  if (!c) return <Loading />
  const patch = async (body: any) => { try { setC({ ...c, ...(await appApi(`/api/agenda/clienti/${id}`, { method: 'PATCH', body })) }) } catch (e) { notifyError(e) } }
  return (
    <>
      <PageTitle title={c.name} subtitle={[c.mobile, c.email].filter(Boolean).join(' · ') || 'Nessun contatto'}
        right={<Group>
          <Button variant="default" onClick={() => nav(`/soggetti/${c.id}`)}>Dati di fatturazione</Button>
          <Button leftSection={<IconCalendarPlus size={16} />} onClick={() => setBook(true)}>Nuovo appuntamento</Button>
        </Group>} />
      <Grid>
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Stack>
            <Paper withBorder p="md">
              <Group justify="space-between">
                <Group>
                  <Checkbox label="Consenso privacy" checked={c.privacy} onChange={(e) => patch({ privacy: e.target.checked })} />
                  <Checkbox label="Consenso marketing" checked={c.marketing} onChange={(e) => patch({ marketing: e.target.checked })} />
                </Group>
                <Badge size="lg" variant="light">{c.loyalty_points} punti fedeltà</Badge>
              </Group>
              <Group mt="sm" align="flex-end">
                <DatePickerInput label="Compleanno" value={c.birth_date ? new Date(c.birth_date) : null} valueFormat="DD/MM/YYYY" clearable w={180}
                  onChange={(d) => patch({ birth_date: d ? isoDate(d as Date) : null })} />
                <Textarea label="Note" defaultValue={c.notes ?? ''} autosize minRows={1} style={{ flex: 1 }} onBlur={(e) => e.target.value !== (c.notes ?? '') && patch({ notes: e.target.value })} />
              </Group>
            </Paper>
            <Paper withBorder p="md">
              <Group justify="space-between" mb="sm"><Title order={4}>Schede tecniche</Title><Button size="xs" variant="light" onClick={() => setCardOpen(true)}>Aggiungi</Button></Group>
              {c.cards.length === 0 && <Text c="dimmed" size="sm">Nessuna scheda: aggiungi la formula colore o l'anamnesi.</Text>}
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                {c.cards.map((k: any) => (
                  <Paper key={k.id} withBorder p="sm" bg="var(--mantine-color-gray-0)">
                    <Text fw={600} size="sm">{CARD_KIND[k.kind]} — {k.title}</Text>
                    {Object.entries(k.data).map(([f, v]) => <Text key={f} size="sm"><Text span c="dimmed">{f}:</Text> {String(v)}</Text>)}
                    {k.notes && <Text size="sm" mt={4}>{k.notes}</Text>}
                    <Text size="xs" c="dimmed" mt={4}>{new Date(k.created_at).toLocaleDateString('it-IT')}{k.signed_at ? ' · firmato' : ''}</Text>
                  </Paper>
                ))}
              </SimpleGrid>
            </Paper>
            <Paper withBorder p="md">
              <Title order={4} mb="sm">Appuntamenti</Title>
              <Table>
                <Table.Tbody>
                  {c.appointments.map((a: any) => (
                    <Table.Tr key={a.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/agenda?giorno=${a.starts_at.slice(0, 10)}&apri=${a.id}`)}>
                      <Table.Td tt="capitalize">{longDay(a.starts_at)} {hhmm(a.starts_at)}</Table.Td>
                      <Table.Td>{a.items.map((i: any) => i.service).join(', ')}</Table.Td>
                      <Table.Td><Badge size="sm" color={STATUS[a.status]?.color}>{STATUS[a.status]?.label}</Badge></Table.Td>
                      <Table.Td ta="right">{fmtEuro(a.total)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Paper>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Text fw={600} mb="xs">Conversazione WhatsApp</Text>
          <WhatsAppChat title="Il salone" messages={c.messages} />
        </Grid.Col>
      </Grid>
      {cardOpen && <CardModal partyId={c.id} onClose={() => setCardOpen(false)} onSaved={() => { setCardOpen(false); load() }} />}
      {book && <NewAppointment day={new Date()} staff={staff} services={services} preset={{}} partyId={c.id} onClose={() => setBook(false)}
        onSaved={(a) => { setBook(false); nav(`/agenda?giorno=${a.starts_at.slice(0, 10)}&apri=${a.id}`) }} />}
    </>
  )
}

function CardModal({ partyId, onClose, onSaved }: { partyId: string; onClose: () => void; onSaved: () => void }) {
  const [kind, setKind] = useState('colore')
  const [title, setTitle] = useState('Colore abituale')
  const [data, setData] = useState<Record<string, string>>({})
  const [notes, setNotes] = useState('')
  const [signed, setSigned] = useState(false)
  const save = async () => {
    try { await appApi(`/api/agenda/clienti/${partyId}/schede`, { body: { kind, title, data, notes: notes || null, signed } }); notifyOk('Scheda salvata'); onSaved() } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} title="Nuova scheda tecnica">
      <Stack>
        <Select label="Tipo" data={Object.entries(CARD_KIND).map(([value, label]) => ({ value, label }))} value={kind} onChange={(v) => { setKind(v!); setData({}) }} />
        <TextInput label="Titolo" value={title} onChange={(e) => setTitle(e.target.value)} />
        {CARD_FIELDS[kind].map((f) => <TextInput key={f} label={f} value={data[f] ?? ''} onChange={(e) => setData({ ...data, [f]: e.target.value })} />)}
        <Textarea label="Note" value={notes} onChange={(e) => setNotes(e.target.value)} />
        {(kind === 'consenso' || kind === 'anamnesi') && <Checkbox label="Firmato dal cliente" checked={signed} onChange={(e) => setSigned(e.target.checked)} />}
        <Button onClick={save}>Salva</Button>
      </Stack>
    </Modal>
  )
}
