import { ActionIcon, Alert, Button, Checkbox, CopyButton, Group, Modal, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Table, Text, TextInput, Tooltip } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { useDisclosure } from '@mantine/hooks'
import { IconCheck, IconCopy, IconDownload, IconPlus, IconSearch } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { adminApi, downloadFile, fmtDate, isoDate } from '../../api'
import { Loading, PageTitle, PlanBadge, StatusBadge, notifyError, notifyOk } from '../../components'

export default function Tenants() {
  const [rows, setRows] = useState<any[] | null>(null)
  const [q, setQ] = useState('')
  const [opened, { open, close }] = useDisclosure()
  const nav = useNavigate()

  const load = () => adminApi('/tenants').then(setRows).catch(notifyError)
  useEffect(() => { load() }, [])
  const exportTenants = (format: 'csv' | 'xlsx') =>
    downloadFile('admin', `/api/admin/tenants/export?format=${format}`, `aziende-${isoDate(new Date())}.${format}`).catch(notifyError)

  const filtered = useMemo(
    () => (rows ?? []).filter((r) => (r.name + ' ' + (r.sector ?? '') + ' ' + r.contact_email).toLowerCase().includes(q.toLowerCase())),
    [rows, q],
  )

  return (
    <>
      <PageTitle title="Aziende clienti" subtitle="Clienti, pacchetti e scadenze"
        right={<Group gap="xs">
          <Button variant="default" leftSection={<IconDownload size={16} />} onClick={() => exportTenants('xlsx')}>Excel</Button>
          <Button variant="default" leftSection={<IconDownload size={16} />} onClick={() => exportTenants('csv')}>CSV</Button>
          <Button leftSection={<IconPlus size={16} />} onClick={open}>Nuova azienda</Button>
        </Group>} />
      <TextInput placeholder="Cerca per nome, settore o email" leftSection={<IconSearch size={16} />} mb="md"
        value={q} onChange={(e) => setQ(e.currentTarget.value)} />
      {!rows ? <Loading /> : (
        <Paper withBorder>
          <Table.ScrollContainer minWidth={720}>
            <Table highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr><Table.Th>Azienda</Table.Th><Table.Th>Settore</Table.Th><Table.Th>Pacchetto</Table.Th><Table.Th>Stato</Table.Th><Table.Th>Scadenza</Table.Th></Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {filtered.map((r) => (
                  <Table.Tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/admin/aziende/${r.id}`)}>
                    <Table.Td><Text fw={600}>{r.name}</Text><Text size="xs" c="dimmed">{r.contact_email}</Text></Table.Td>
                    <Table.Td>{r.sector ?? '—'}</Table.Td>
                    <Table.Td><PlanBadge code={r.plan_code} /></Table.Td>
                    <Table.Td><StatusBadge status={r.status} label={r.status_label} /></Table.Td>
                    <Table.Td>{fmtDate(r.end_date)}{r.days_left != null && r.days_left >= 0 && <Text span size="xs" c="dimmed"> · {r.days_left} gg</Text>}</Table.Td>
                  </Table.Tr>
                ))}
                {filtered.length === 0 && (
                  <Table.Tr><Table.Td colSpan={5}><Text c="dimmed" ta="center" py="md">Nessuna azienda</Text></Table.Td></Table.Tr>
                )}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      )}
      <NewTenantModal opened={opened} onClose={close} onCreated={(id) => { close(); nav(`/admin/aziende/${id}`) }} />
    </>
  )
}

function NewTenantModal({ opened, onClose, onCreated }: { opened: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const empty = { name: '', vat_number: '', sector: '', contact_name: '', contact_email: '', phone: '', admin_name: '', admin_email: '' }
  const [f, setF] = useState(empty)
  const [plan, setPlan] = useState('BASE')
  const [period, setPeriod] = useState('annuale')
  const [trial, setTrial] = useState(false)
  const [start, setStart] = useState<Date | null>(new Date())
  const [end, setEnd] = useState<Date | null>(null)
  const [amount, setAmount] = useState<number | string>('')
  const [busy, setBusy] = useState(false)
  const [access, setAccess] = useState<'password' | 'link'>('password')
  const [password, setPassword] = useState('')
  const [sendMail, setSendMail] = useState(true)
  const [created, setCreated] = useState<any>(null)
  const generate = () => adminApi('/password-provvisoria').then((r) => setPassword(r.password)).catch(notifyError)
  useEffect(() => { if (opened && !password) generate() }, [opened])
  const set = (k: keyof typeof empty) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.currentTarget.value })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await adminApi('/tenants', {
        body: {
          ...Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v || null])),
          admin_email: f.admin_email || f.contact_email,
          plan_code: plan, period, is_trial: trial,
          start_date: start ? isoDate(start) : null,
          end_date: end ? isoDate(end) : null,
          amount: amount === '' ? null : amount,
          admin_password: access === 'password' ? password : null, send_activation: sendMail,
        },
      })
      setF(empty)
      setPassword('')
      setCreated(r)
    } catch (err) { notifyError(err) } finally { setBusy(false) }
  }

  return (
    <Modal opened={opened} onClose={() => { if (created) { onCreated(created.id); setCreated(null) } else onClose() }} title={created ? 'Azienda creata' : 'Nuova azienda cliente'} size="lg">
      {created ? (
        <Stack>
          <Alert color={created.email_sent ? 'teal' : 'yellow'}>{created.email_sent ? `Email mandata a ${created.username}.` : 'Email non inviata: comunica tu le credenziali al cliente.'}</Alert>
          <Credential label="Indirizzo" value={`${window.location.origin}/login`} />
          <Credential label="Nome utente" value={created.username} />
          {created.temp_password ? <Credential label="Password provvisoria" value={created.temp_password} mono />
            : <Credential label="Link di attivazione" value={created.activation_link} />}
          {created.temp_password && <Text size="xs" c="dimmed">La password si vede solo adesso: poi resta salvata in modo non leggibile. Se serve, ne generi una nuova dalla scheda dell'azienda.</Text>}
          <Group justify="flex-end"><Button onClick={() => { onCreated(created.id); setCreated(null) }}>Apri l'azienda</Button></Group>
        </Stack>
      ) : (
      <form onSubmit={submit}>
        <Stack>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Ragione sociale" required value={f.name} onChange={set('name')} />
            <TextInput label="Partita IVA" value={f.vat_number} onChange={set('vat_number')} />
            <TextInput label="Settore" placeholder="es. Panetteria" value={f.sector} onChange={set('sector')} />
            <TextInput label="Telefono" value={f.phone} onChange={set('phone')} />
            <TextInput label="Referente" value={f.contact_name} onChange={set('contact_name')} />
            <TextInput label="Email referente" description="Riceve gli avvisi di scadenza" type="email" required value={f.contact_email} onChange={set('contact_email')} />
          </SimpleGrid>
          <Text fw={600} mt="xs">Primo amministratore dell'azienda</Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Nome e cognome" required value={f.admin_name} onChange={set('admin_name')} />
            <TextInput label="Email di accesso" placeholder="uguale al referente" type="email" value={f.admin_email} onChange={set('admin_email')} />
          </SimpleGrid>
          <Text fw={600} mt="xs">Accesso</Text>
          <SegmentedControl value={access} onChange={(v) => setAccess(v as any)} data={[
            { value: 'password', label: 'Password provvisoria' }, { value: 'link', label: 'Link per sceglierla' }]} />
          {access === 'password' ? (
            <Group align="flex-end" wrap="nowrap">
              <TextInput label="Password provvisoria" description="Il cliente la cambia al primo accesso" value={password} required minLength={8}
                onChange={(e) => setPassword(e.currentTarget.value)} style={{ flex: 1 }} styles={{ input: { fontFamily: 'monospace' } }} />
              <Button variant="default" onClick={generate}>Genera</Button>
            </Group>
          ) : <Text size="sm" c="dimmed">L'email contiene un link valido una volta per scegliere la password.</Text>}
          <Checkbox label={access === 'password' ? 'Manda al cliente l\'email con nome utente e password' : 'Manda al cliente l\'email con il link'} checked={sendMail}
            onChange={(e) => setSendMail(e.currentTarget.checked)} />
          <Text fw={600} mt="xs">Abbonamento</Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select label="Pacchetto" data={['BASE', 'PLUS', 'PRO']} value={plan} onChange={(v) => setPlan(v ?? 'BASE')} allowDeselect={false} />
            <Select label="Periodicità" data={[{ value: 'annuale', label: 'Annuale' }, { value: 'mensile', label: 'Mensile' }]}
              value={period} onChange={(v) => setPeriod(v ?? 'annuale')} disabled={trial} allowDeselect={false} />
            <DateInput label="Dal" value={start} onChange={setStart} valueFormat="DD/MM/YYYY" />
            <DateInput label="Al" placeholder="calcolata in automatico" value={end} onChange={setEnd} valueFormat="DD/MM/YYYY" clearable />
            <NumberInput label="Importo (€)" placeholder="prezzo di listino" value={amount} onChange={setAmount} decimalScale={2} min={0} />
            <Checkbox label="Periodo di prova gratuito" checked={trial} onChange={(e) => setTrial(e.currentTarget.checked)} mt={30} />
          </SimpleGrid>
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose}>Annulla</Button>
            <Button type="submit" loading={busy} disabled={access === 'password' && password.length < 8}>Crea azienda</Button>
          </Group>
        </Stack>
      </form>
      )}
    </Modal>
  )
}

export function Credential({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <Group justify="space-between" wrap="nowrap">
      <div style={{ minWidth: 0 }}><Text size="xs" c="dimmed">{label}</Text><Text fw={600} ff={mono ? 'monospace' : undefined} size={mono ? 'lg' : 'sm'} style={{ wordBreak: 'break-all' }}>{value}</Text></div>
      <CopyButton value={value}>{({ copied, copy }) => <Tooltip label={copied ? 'Copiato' : 'Copia'}><ActionIcon variant="light" color={copied ? 'teal' : 'blue'} onClick={copy}>{copied ? <IconCheck size={16} /> : <IconCopy size={16} />}</ActionIcon></Tooltip>}</CopyButton>
    </Group>
  )
}
