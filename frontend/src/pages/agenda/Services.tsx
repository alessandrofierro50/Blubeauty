import { ActionIcon, Badge, Button, Checkbox, ColorInput, Group, Modal, MultiSelect, NumberInput, Paper, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput, Textarea } from '@mantine/core'
import { IconEdit, IconPlus } from '@tabler/icons-react'
import { DateInput } from '@mantine/dates'
import { useEffect, useState } from 'react'

import { appApi, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import { HoursEditor } from './AgendaSettings'
import { TableSelect } from '../anagrafiche/TableSelect'
import type { Service, Staff } from './lib'

export default function Services() {
  const [services, setServices] = useState<Service[] | null>(null)
  const [staff, setStaff] = useState<Staff[]>([])
  const [resources, setResources] = useState<any[]>([])
  const [cats, setCats] = useState<any[]>([])
  const [vats, setVats] = useState<any[]>([])
  const [edit, setEdit] = useState<Partial<Service> | null>(null)
  const [editStaff, setEditStaff] = useState<Partial<Staff> | null>(null)
  const [editRes, setEditRes] = useState<any | null>(null)
  const load = () => Promise.all([appApi('/api/agenda/servizi'), appApi('/api/agenda/operatori'), appApi('/api/agenda/risorse'), appApi('/api/agenda/categorie'),
    appApi('/api/anagrafiche/tabelle/aliquote-iva').catch(() => [])])
    .then(([a, b, c, d, e]) => { setServices(a); setStaff(b); setResources(c); setCats(d); setVats(e) }).catch(notifyError)
  useEffect(() => { load() }, [])
  if (!services) return <Loading />
  const catName = (id: string | null) => cats.find((c) => c.id === id)?.name ?? '—'
  const addCat = async () => {
    const name = window.prompt('Nome della categoria (es. Capelli, Estetica, Unghie)')
    if (name) { await appApi('/api/agenda/categorie', { body: { name } }).catch(notifyError); load() }
  }
  return (
    <>
      <PageTitle title="Servizi, operatori e cabine" subtitle="Listino, durate, tempi di posa e chi esegue ogni servizio" />
      <Tabs defaultValue="servizi">
        <Tabs.List mb="md">
          <Tabs.Tab value="servizi">Servizi ({services.length})</Tabs.Tab>
          <Tabs.Tab value="operatori">Operatori ({staff.length})</Tabs.Tab>
          <Tabs.Tab value="risorse">Cabine e postazioni ({resources.length})</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="servizi">
          <Group mb="sm"><Button leftSection={<IconPlus size={16} />} onClick={() => setEdit({ duration_min: 30, price: '0', staff_ids: staff.map((s) => s.id), resource_ids: [], bookable_online: true, active: true })}>Nuovo servizio</Button>
            <Button variant="default" onClick={addCat}>Nuova categoria</Button></Group>
          <Paper withBorder>
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead><Table.Tr><Table.Th>Servizio</Table.Th><Table.Th>Categoria</Table.Th><Table.Th>Durata</Table.Th><Table.Th>Posa</Table.Th><Table.Th>Operatori</Table.Th><Table.Th>Online</Table.Th><Table.Th ta="right">Prezzo</Table.Th><Table.Th /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {services.map((s) => (
                  <Table.Tr key={s.id} opacity={s.active ? 1 : 0.5}>
                    <Table.Td fw={600}>{s.name}</Table.Td>
                    <Table.Td>{catName(s.category_id)}</Table.Td>
                    <Table.Td>{s.duration_min}'</Table.Td>
                    <Table.Td>{s.processing_min ? `${s.processing_min}' dal ${s.processing_start_min}'` : '—'}</Table.Td>
                    <Table.Td>{s.staff_ids.map((id) => staff.find((x) => x.id === id)?.first_name).join(', ')}</Table.Td>
                    <Table.Td>{s.bookable_online ? <Badge size="sm" color="green">sì</Badge> : <Badge size="sm" color="gray">no</Badge>}</Table.Td>
                    <Table.Td ta="right" fw={600}>{fmtEuro(s.price)}</Table.Td>
                    <Table.Td><ActionIcon variant="subtle" onClick={() => setEdit(s)}><IconEdit size={16} /></ActionIcon></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Paper>
        </Tabs.Panel>
        <Tabs.Panel value="operatori">
          <Button mb="sm" leftSection={<IconPlus size={16} />} onClick={() => setEditStaff({ color: '#2340a8', active: true, bookable_online: true, working_hours: {} })}>Nuovo operatore</Button>
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
            {staff.map((s) => (
              <Paper key={s.id} withBorder p="md" opacity={s.active ? 1 : 0.5}>
                <Group justify="space-between">
                  <Group><div style={{ width: 14, height: 14, borderRadius: '50%', background: s.color }} /><Text fw={700}>{s.first_name} {s.last_name}</Text></Group>
                  <ActionIcon variant="subtle" onClick={() => setEditStaff(s)}><IconEdit size={16} /></ActionIcon>
                </Group>
                <Text size="sm" c="dimmed">{s.bookable_online ? 'Prenotabile online' : 'Solo dal salone'} · {Object.keys(s.working_hours || {}).length ? 'orari personali' : 'orari del salone'}</Text>
              </Paper>
            ))}
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="risorse">
          <Button mb="sm" leftSection={<IconPlus size={16} />} onClick={() => setEditRes({ name: '', kind: 'cabina', active: true })}>Nuova cabina o postazione</Button>
          <Text size="sm" c="dimmed" mb="sm">Un servizio che richiede una cabina (es. pressoterapia, laser) si prenota solo se una cabina è libera per tutta la durata.</Text>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            {resources.map((r) => <Paper key={r.id} withBorder p="md" style={{ cursor: 'pointer' }} onClick={() => setEditRes(r)}><Text fw={700}>{r.name}</Text><Text size="sm" c="dimmed">{r.kind}</Text></Paper>)}
          </SimpleGrid>
        </Tabs.Panel>
      </Tabs>

      {edit && <ServiceModal s={edit} staff={staff} resources={resources} cats={cats} vats={vats} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load() }} />}
      {editStaff && <StaffModal s={editStaff} onClose={() => setEditStaff(null)} onSaved={() => { setEditStaff(null); load() }} />}
      {editRes && <Modal opened onClose={() => setEditRes(null)} title="Cabina o postazione">
        <Stack>
          <TextInput label="Nome" value={editRes.name} onChange={(e) => setEditRes({ ...editRes, name: e.target.value })} />
          <Select label="Tipo" value={editRes.kind} onChange={(v) => setEditRes({ ...editRes, kind: v })} data={['cabina', 'postazione', 'lavatesta', 'macchinario']} />
          <Checkbox label="Attiva" checked={editRes.active} onChange={(e) => setEditRes({ ...editRes, active: e.target.checked })} />
          <Button onClick={async () => {
            try { await appApi(editRes.id ? `/api/agenda/risorse/${editRes.id}` : '/api/agenda/risorse', { method: editRes.id ? 'PUT' : 'POST', body: { name: editRes.name, kind: editRes.kind, active: editRes.active } }); setEditRes(null); load() } catch (e) { notifyError(e) }
          }}>Salva</Button>
        </Stack>
      </Modal>}
    </>
  )
}

function ServiceModal({ s, staff, resources, cats, vats, onClose, onSaved }: { s: Partial<Service>; staff: Staff[]; resources: any[]; cats: any[]; vats: any[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<any>({ ...s, price: Number(s.price ?? 0), posa: !!s.processing_min })
  const save = async () => {
    const body = { name: f.name, category_id: f.category_id || null, description: f.description || null, price: String(f.price ?? 0), vat_rate_id: f.vat_rate_id || null,
      duration_min: f.duration_min, processing_start_min: f.posa ? f.processing_start_min ?? 0 : null, processing_min: f.posa ? f.processing_min : null,
      bookable_online: f.bookable_online, active: f.active, sort_order: f.sort_order ?? 0, recall_days: f.recall_days || null, staff_ids: f.staff_ids ?? [], resource_ids: f.resource_ids ?? [] }
    try { await appApi(s.id ? `/api/agenda/servizi/${s.id}` : '/api/agenda/servizi', { method: s.id ? 'PUT' : 'POST', body }); notifyOk('Servizio salvato'); onSaved() } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} title={s.id ? 'Modifica servizio' : 'Nuovo servizio'} size="lg">
      <Stack>
        <SimpleGrid cols={2}>
          <TextInput label="Nome" value={f.name ?? ''} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <Select label="Categoria" data={cats.map((c) => ({ value: c.id, label: c.name }))} value={f.category_id ?? null} onChange={(v) => setF({ ...f, category_id: v })} clearable />
          <NumberInput label="Prezzo IVA inclusa (€)" value={f.price} onChange={(v) => setF({ ...f, price: v })} min={0} decimalScale={2} decimalSeparator="," />
          <TableSelect kind="aliquote-iva" label="Aliquota IVA" filter={(v) => v.active || v.id === f.vat_rate_id} value={f.vat_rate_id ?? null} onChange={(v) => setF({ ...f, vat_rate_id: v })} clearable placeholder="Predefinita (22%)" />
          <NumberInput label="Durata (minuti)" value={f.duration_min} onChange={(v) => setF({ ...f, duration_min: Number(v) })} min={5} step={5} />
          <NumberInput label="Richiamo dopo (giorni)" description="Es. ritocco colore: 35" value={f.recall_days ?? ''} onChange={(v) => setF({ ...f, recall_days: v === '' ? null : Number(v) })} min={1} />
        </SimpleGrid>
        <Checkbox label="Ha un tempo di posa (l'operatore è libero per un altro cliente)" checked={f.posa} onChange={(e) => setF({ ...f, posa: e.target.checked, processing_start_min: f.processing_start_min ?? 20, processing_min: f.processing_min ?? 30 })} />
        {f.posa && <SimpleGrid cols={2}>
          <NumberInput label="La posa inizia dopo (minuti)" value={f.processing_start_min} onChange={(v) => setF({ ...f, processing_start_min: Number(v) })} min={0} step={5} />
          <NumberInput label="Durata della posa (minuti)" value={f.processing_min} onChange={(v) => setF({ ...f, processing_min: Number(v) })} min={5} step={5} />
        </SimpleGrid>}
        <MultiSelect label="Chi lo esegue" data={staff.map((x) => ({ value: x.id, label: x.first_name }))} value={f.staff_ids ?? []} onChange={(v) => setF({ ...f, staff_ids: v })} />
        <MultiSelect label="Richiede una di queste cabine/postazioni" data={resources.map((x) => ({ value: x.id, label: x.name }))} value={f.resource_ids ?? []} onChange={(v) => setF({ ...f, resource_ids: v })} />
        <Textarea label="Descrizione (mostrata nella prenotazione online)" value={f.description ?? ''} onChange={(e) => setF({ ...f, description: e.target.value })} />
        <Group>
          <Checkbox label="Prenotabile online" checked={f.bookable_online} onChange={(e) => setF({ ...f, bookable_online: e.target.checked })} />
          <Checkbox label="Attivo" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />
        </Group>
        <Button onClick={save} disabled={!f.name}>Salva</Button>
      </Stack>
    </Modal>
  )
}

function StaffModal({ s, onClose, onSaved }: { s: Partial<Staff>; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<any>({ last_name: '', sort_order: 0, ...s })
  const [alt, setAlt] = useState(Object.keys(s.working_hours_b ?? {}).length > 0)
  const save = async () => {
    const body = { first_name: f.first_name, last_name: f.last_name ?? '', color: f.color, active: f.active, bookable_online: f.bookable_online, sort_order: f.sort_order ?? 0, working_hours: f.working_hours ?? {}, working_hours_b: alt ? f.working_hours_b ?? {} : {}, alt_week_a: alt ? f.alt_week_a : null }
    try { await appApi(s.id ? `/api/agenda/operatori/${s.id}` : '/api/agenda/operatori', { method: s.id ? 'PUT' : 'POST', body }); notifyOk('Operatore salvato'); onSaved() } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} title={s.id ? 'Modifica operatore' : 'Nuovo operatore'}>
      <Stack>
        <SimpleGrid cols={2}>
          <TextInput label="Nome" value={f.first_name ?? ''} onChange={(e) => setF({ ...f, first_name: e.target.value })} />
          <TextInput label="Cognome" value={f.last_name ?? ''} onChange={(e) => setF({ ...f, last_name: e.target.value })} />
        </SimpleGrid>
        <ColorInput label="Colore in agenda" value={f.color} onChange={(v) => setF({ ...f, color: v })} swatches={['#2340a8', '#1a3185', '#6ec1e4', '#0b8a6e', '#c2255c', '#f2b413', '#7048e8', '#e8590c']} />
        <Checkbox label="Prenotabile online" checked={f.bookable_online} onChange={(e) => setF({ ...f, bookable_online: e.target.checked })} />
        <Checkbox label="Attivo" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />
        <Checkbox label="Orari personali (turni, giorno libero)" checked={Object.keys(f.working_hours ?? {}).length > 0}
          onChange={(e) => setF({ ...f, working_hours: e.target.checked ? { tue: [['09:00', '19:30']], wed: [['09:00', '19:30']], thu: [['09:00', '19:30']], fri: [['09:00', '19:30']], sat: [['08:30', '18:00']] } : {} })} />
        {Object.keys(f.working_hours ?? {}).length > 0 ? <HoursEditor value={f.working_hours} onChange={(h) => setF({ ...f, working_hours: h })} />
          : <Text size="xs" c="dimmed">Senza orari personali valgono gli orari del salone.</Text>}
        <Checkbox label="Settimane alterne (es. un sabato sì e uno no)" checked={alt}
          onChange={(e) => { setAlt(e.target.checked); if (e.target.checked && !Object.keys(f.working_hours_b ?? {}).length) setF({ ...f, working_hours_b: { ...(Object.keys(f.working_hours ?? {}).length ? f.working_hours : { tue: [['09:00', '19:30']], wed: [['09:00', '19:30']], thu: [['09:00', '19:30']], fri: [['09:00', '19:30']] }) }, alt_week_a: f.alt_week_a ?? new Date().toISOString().slice(0, 10) }) }} />
        {alt && (
          <Paper withBorder p="sm" radius="md">
            <Text size="sm" fw={600}>Orario della settimana B</Text>
            <Text size="xs" c="dimmed" mb="xs">Le settimane si alternano: A (l'orario sopra) e B (questo).</Text>
            <DateInput label="Una data qualsiasi di una settimana A" valueFormat="DD/MM/YYYY" mb="sm" maw={220}
              value={f.alt_week_a ? new Date(f.alt_week_a + 'T12:00') : null} onChange={(d: any) => d && setF({ ...f, alt_week_a: isoDate(new Date(d)) })} />
            <HoursEditor value={f.working_hours_b ?? {}} onChange={(h) => setF({ ...f, working_hours_b: h })} />
          </Paper>
        )}
        <Text size="xs" c="dimmed">Ferie, malattia, permessi e cambi di turno di un giorno si segnano in «Turni e assenze».</Text>
        <Button onClick={save} disabled={!f.first_name}>Salva</Button>
      </Stack>
    </Modal>
  )
}
