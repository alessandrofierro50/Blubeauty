import { ActionIcon, Alert, Anchor, Badge, Button, Checkbox, Group, Modal, MultiSelect, NumberInput, Paper, Select, SimpleGrid, Stack, Table, Tabs, Text, Textarea, TextInput, Title, Tooltip } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { useDisclosure } from '@mantine/hooks'
import { IconArrowLeft, IconKey, IconLink, IconLogin, IconPencil, IconRefresh, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, adminApi, fmtDate, fmtEuro, isoDate, tokens } from '../../api'
import { Loading, PlanBadge, StatusBadge, notifyError, notifyOk } from '../../components'
import { Credential } from './Tenants'

export default function TenantDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [t, setT] = useState<any>(null)
  const [modules, setModules] = useState<{ code: string; label: string }[]>([])
  const [subOpen, sub] = useDisclosure()
  const [convOpen, conv] = useDisclosure()
  const [editSub, setEditSub] = useState<any>(null)
  const [pwUser, setPwUser] = useState<any>(null)
  const [delOpen, del] = useDisclosure()

  const load = () => adminApi(`/tenants/${id}`).then(setT).catch(notifyError)
  useEffect(() => {
    load()
    adminApi('/modules').then(setModules).catch(() => {})
  }, [id])

  async function action(path: string, okMsg: string) {
    try {
      await adminApi(`/tenants/${id}${path}`, { method: 'POST' })
      notifyOk(okMsg)
      load()
    } catch (e) { notifyError(e) }
  }

  async function impersonate(userId: string) {
    try {
      const r = await adminApi(`/tenants/${id}/impersonate/${userId}`, { method: 'POST' })
      tokens.set('user', r.token)
      window.open('/', '_blank')
    } catch (e) { notifyError(e) }
  }

  async function copyActivation(userId: string) {
    try {
      const r = await adminApi(`/tenants/${id}/users/${userId}/activation-link`, { method: 'POST' })
      await navigator.clipboard?.writeText(r.activation_link).catch(() => {})
      notifyOk('Nuovo link di attivazione copiato negli appunti')
    } catch (e) { notifyError(e) }
  }

  async function deleteSub(subId: string) {
    if (!confirm('Eliminare questo periodo di abbonamento?')) return
    try {
      setT({ ...t, ...(await adminApi(`/subscriptions/${subId}`, { method: 'DELETE' })) })
      notifyOk('Periodo eliminato')
    } catch (e) { notifyError(e) }
  }

  if (!t) return <Loading />
  return (
    <>
      <Anchor size="sm" onClick={() => nav('/admin/aziende')}><Group gap={4}><IconArrowLeft size={14} />Aziende clienti</Group></Anchor>
      <Group justify="space-between" mt="xs" mb="lg" wrap="wrap">
        <div>
          <Group gap="xs"><Title order={2}>{t.name}</Title><PlanBadge code={t.plan_code} /><StatusBadge status={t.status} label={t.status_label} /></Group>
          <Text c="dimmed" size="sm">{t.sector ?? 'Settore non indicato'} · {t.contact_email}</Text>
        </div>
        <Group>
          {canConvert(t)
            ? <Button color="teal" onClick={conv.open}>Converti prova in abbonamento</Button>
            : <Button leftSection={<IconRefresh size={16} />} onClick={() => action('/renew', 'Abbonamento rinnovato')}>Rinnova</Button>}
          <Button variant="light" onClick={sub.open}>Nuovo periodo / cambio pacchetto</Button>
          {t.suspended
            ? <Button color="green" variant="light" onClick={() => action('/reactivate', 'Azienda riattivata')}>Riattiva</Button>
            : <Button color="red" variant="light" onClick={() => confirm('Sospendere l\'accesso a questa azienda?') && action('/suspend', 'Azienda sospesa')}>Sospendi</Button>}
          {t.suspended && <Button color="red" leftSection={<IconTrash size={16} />} onClick={del.open}>Elimina azienda</Button>}
        </Group>
      </Group>

      {t.status === 'sola_lettura' && <Alert color="red" mb="md">Abbonamento scaduto oltre la tolleranza: il cliente è in sola lettura.</Alert>}
      {t.status === 'prova_scaduta' && <Alert color="red" mb="md">Prova gratuita terminata: il cliente vede solo la pagina «Abbonamento». I dati restano per 30 giorni; convertila per farlo ripartire.</Alert>}
      {t.status === 'sospeso' && <Alert color="gray" mb="md">Azienda sospesa: il cliente vede solo la pagina «Abbonamento».</Alert>}

      <SimpleGrid cols={{ base: 1, md: 3 }} mb="lg">
        <Paper withBorder p="md"><Text size="xs" c="dimmed" tt="uppercase" fw={600}>Scadenza</Text><Text fz={22} fw={800}>{fmtDate(t.end_date)}</Text>
          <Text size="xs" c="dimmed">{t.days_left != null ? (t.days_left >= 0 ? `tra ${t.days_left} giorni` : `scaduto da ${-t.days_left} giorni`) : ''}</Text></Paper>
        <Paper withBorder p="md"><Text size="xs" c="dimmed" tt="uppercase" fw={600}>Utenti</Text><Text fz={22} fw={800}>{t.usage.users} / {t.limits.max_users}</Text></Paper>
        <Paper withBorder p="md"><Text size="xs" c="dimmed" tt="uppercase" fw={600}>Magazzini</Text><Text fz={22} fw={800}>{t.usage.warehouses} / {t.limits.max_warehouses}</Text></Paper>
      </SimpleGrid>

      <Tabs defaultValue="abbonamenti">
        <Tabs.List mb="md">
          <Tabs.Tab value="abbonamenti">Abbonamenti</Tabs.Tab>
          <Tabs.Tab value="utenti">Utenti</Tabs.Tab>
          <Tabs.Tab value="moduli">Moduli e limiti</Tabs.Tab>
          <Tabs.Tab value="dati">Dati azienda</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="abbonamenti">
          <Paper withBorder>
            <Table.ScrollContainer minWidth={640}>
              <Table>
                <Table.Thead><Table.Tr><Table.Th>Pacchetto</Table.Th><Table.Th>Dal</Table.Th><Table.Th>Al</Table.Th><Table.Th>Periodicità</Table.Th><Table.Th>Importo</Table.Th><Table.Th>Tolleranza / sola lettura</Table.Th><Table.Th>Note</Table.Th><Table.Th /></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {t.subscriptions.map((s: any) => (
                    <Table.Tr key={s.id}>
                      <Table.Td><Group gap={6}><PlanBadge code={s.plan_code} />{s.is_trial && <Badge variant="outline" color="cyan">prova</Badge>}</Group></Table.Td>
                      <Table.Td>{fmtDate(s.start_date)}</Table.Td>
                      <Table.Td>{fmtDate(s.end_date)}</Table.Td>
                      <Table.Td>{s.period}</Table.Td>
                      <Table.Td>{fmtEuro(s.amount)}</Table.Td>
                      <Table.Td>{s.is_trial ? '—' : `${s.grace_days} + ${s.readonly_days} gg`}</Table.Td>
                      <Table.Td><Text size="xs" c="dimmed" lineClamp={2}>{s.notes ?? ''}</Text></Table.Td>
                      <Table.Td><Group gap={2} wrap="nowrap" justify="flex-end">
                        <Tooltip label="Modifica periodo"><ActionIcon variant="subtle" onClick={() => setEditSub(s)}><IconPencil size={16} /></ActionIcon></Tooltip>
                        <Tooltip label="Elimina periodo"><ActionIcon variant="subtle" color="red" onClick={() => deleteSub(s.id)}><IconTrash size={16} /></ActionIcon></Tooltip>
                      </Group></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Paper>
        </Tabs.Panel>

        <Tabs.Panel value="utenti">
          <Paper withBorder>
            <Table.ScrollContainer minWidth={560}>
              <Table>
                <Table.Thead><Table.Tr><Table.Th>Nome</Table.Th><Table.Th>Email</Table.Th><Table.Th>Ruolo</Table.Th><Table.Th>Stato</Table.Th><Table.Th /></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {t.users.map((u: any) => (
                    <Table.Tr key={u.id}>
                      <Table.Td fw={600}>{u.full_name}</Table.Td>
                      <Table.Td>{u.email}</Table.Td>
                      <Table.Td>{u.role}</Table.Td>
                      <Table.Td>{u.pending_activation ? <Badge color="yellow" variant="light">da attivare</Badge> : u.must_change_password ? <Badge color="cyan" variant="light">password provvisoria</Badge> : u.active ? <Badge color="green" variant="light">attivo</Badge> : <Badge color="gray">disattivato</Badge>}</Table.Td>
                      <Table.Td>
                        <Group gap={4} justify="flex-end" wrap="nowrap">
                          <Tooltip label="Nuova password provvisoria"><ActionIcon variant="subtle" onClick={() => setPwUser(u)}><IconKey size={16} /></ActionIcon></Tooltip>
                          <Tooltip label="Nuovo link di attivazione"><ActionIcon variant="subtle" onClick={() => copyActivation(u.id)}><IconLink size={16} /></ActionIcon></Tooltip>
                          <Tooltip label="Accedi come questo utente (assistenza)"><ActionIcon variant="subtle" onClick={() => impersonate(u.id)}><IconLogin size={16} /></ActionIcon></Tooltip>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Paper>
        </Tabs.Panel>

        <Tabs.Panel value="moduli"><ModulesTab t={t} modules={modules} onSaved={setT} /></Tabs.Panel>
        <Tabs.Panel value="dati"><DataTab t={t} onSaved={setT} /></Tabs.Panel>
      </Tabs>

      {delOpen && <DeleteTenantModal tenant={t} onClose={del.close} onDeleted={() => nav('/admin/aziende')} />}
      {pwUser && <UserPasswordModal tenantId={id!} user={pwUser} onClose={() => { setPwUser(null); load() }} />}
      {convOpen && <ConvertTrialModal tenant={t} onClose={conv.close} onSaved={(d) => { setT({ ...t, ...d }); conv.close() }} />}
      {editSub && <EditPeriodModal sub={editSub} onClose={() => setEditSub(null)} onSaved={(d) => { setT({ ...t, ...d }); setEditSub(null) }} />}
      <NewPeriodModal opened={subOpen} onClose={sub.close} tenant={t} onSaved={(d) => { setT({ ...t, ...d }); sub.close() }} />
    </>
  )
}

function ModulesTab({ t, modules, onSaved }: { t: any; modules: { code: string; label: string }[]; onSaved: (d: any) => void }) {
  const [extra, setExtra] = useState<string[]>(t.extra_modules)
  const [lim, setLim] = useState<Record<string, number | string>>(Object.fromEntries(Object.entries(t.custom_limits as Record<string, number | null>).map(([k, v]) => [k, v ?? ''])))
  async function save() {
    try {
      const body: any = { extra_modules: extra }
      for (const [k, v] of Object.entries(lim)) body[k] = v === '' ? null : v
      const d = await adminApi(`/tenants/${t.id}`, { method: 'PATCH', body })
      onSaved({ ...t, ...d })
      notifyOk('Salvato')
    } catch (e) { notifyError(e) }
  }
  const labels: Record<string, string> = { max_users: 'Utenti', max_companies: 'Ragioni sociali', max_warehouses: 'Magazzini', max_pos: 'Postazioni cassa' }
  return (
    <Paper withBorder p="md">
      <Stack>
        <div>
          <Text fw={600}>Moduli attivi</Text>
          <Group gap={6} mt={6}>{t.modules.map((m: string) => <Badge key={m} variant="light">{modules.find((x) => x.code === m)?.label ?? m}</Badge>)}</Group>
        </div>
        <MultiSelect label="Moduli extra per questo cliente" description="Si aggiungono a quelli del pacchetto"
          data={modules.map((m) => ({ value: m.code, label: m.label }))} value={extra} onChange={setExtra} clearable />
        <Text fw={600}>Limiti personalizzati</Text>
        <Text size="xs" c="dimmed" mt={-12}>Lascia vuoto per usare quelli del pacchetto</Text>
        <SimpleGrid cols={{ base: 2, md: 4 }}>
          {Object.keys(labels).map((k) => (
            <NumberInput key={k} label={labels[k]} placeholder={`pacchetto: ${t.limits[k]}`} value={lim[k]} min={0}
              onChange={(v) => setLim({ ...lim, [k]: v })} />
          ))}
        </SimpleGrid>
        <Group justify="flex-end"><Button onClick={save}>Salva</Button></Group>
      </Stack>
    </Paper>
  )
}

function DataTab({ t, onSaved }: { t: any; onSaved: (d: any) => void }) {
  const fields = ['name', 'vat_number', 'tax_code', 'sector', 'contact_name', 'contact_email', 'phone'] as const
  const labels: Record<string, string> = { name: 'Ragione sociale', vat_number: 'Partita IVA', tax_code: 'Codice fiscale', sector: 'Settore', contact_name: 'Referente', contact_email: 'Email referente', phone: 'Telefono' }
  const [f, setF] = useState<Record<string, string>>(Object.fromEntries([...fields, 'notes'].map((k) => [k, t[k] ?? ''])))
  async function save() {
    try {
      const d = await adminApi(`/tenants/${t.id}`, { method: 'PATCH', body: Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v || null])) })
      onSaved({ ...t, ...d })
      notifyOk('Dati salvati')
    } catch (e) { notifyError(e) }
  }
  return (
    <Paper withBorder p="md">
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {fields.map((k) => <TextInput key={k} label={labels[k]} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.currentTarget.value })} />)}
      </SimpleGrid>
      <Textarea label="Note interne" mt="md" autosize minRows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.currentTarget.value })} />
      <Group justify="flex-end" mt="md"><Button onClick={save}>Salva</Button></Group>
    </Paper>
  )
}

function NewPeriodModal({ opened, onClose, tenant, onSaved }: { opened: boolean; onClose: () => void; tenant: any; onSaved: (d: any) => void }) {
  const [plan, setPlan] = useState<string>(tenant.plan_code ?? 'BASE')
  const [period, setPeriod] = useState('annuale')
  const [start, setStart] = useState<Date | null>(new Date())
  const [end, setEnd] = useState<Date | null>(null)
  const [amount, setAmount] = useState<number | string>('')
  const [grace, setGrace] = useState<number | string>('')
  const [readonly, setReadonly] = useState<number | string>('')
  const [notes, setNotes] = useState('')

  useEffect(() => {
    if (!start) return
    const e = new Date(start)
    if (period === 'mensile') e.setMonth(e.getMonth() + 1)
    else e.setFullYear(e.getFullYear() + 1)
    e.setDate(e.getDate() - 1)
    setEnd(e)
  }, [start, period])

  async function save() {
    if (!start || !end) return
    try {
      const d = await adminApi(`/tenants/${tenant.id}/subscriptions`, {
        body: { plan_code: plan, start_date: isoDate(start), end_date: isoDate(end), period,
          amount: amount === '' ? null : amount, grace_days: grace === '' ? null : grace,
          readonly_days: readonly === '' ? null : readonly, notes: notes || null },
      })
      notifyOk('Periodo salvato')
      onSaved(d)
    } catch (e) { notifyError(e) }
  }

  return (
    <Modal opened={opened} onClose={onClose} title="Nuovo periodo di abbonamento">
      <Stack>
        <Text size="sm" c="dimmed">Se il nuovo periodo inizia mentre ne è in corso un altro, quello in corso viene chiuso il giorno prima (cambio pacchetto).</Text>
        <SimpleGrid cols={2}>
          <Select label="Pacchetto" data={['BASE', 'PLUS', 'PRO']} value={plan} onChange={(v) => setPlan(v ?? 'BASE')} allowDeselect={false} />
          <Select label="Periodicità" data={[{ value: 'annuale', label: 'Annuale' }, { value: 'mensile', label: 'Mensile' }, { value: 'personalizzata', label: 'Personalizzata' }]} value={period} onChange={(v) => setPeriod(v ?? 'annuale')} allowDeselect={false} />
          <DateInput label="Dal" value={start} onChange={setStart} valueFormat="DD/MM/YYYY" />
          <DateInput label="Al" value={end} onChange={setEnd} valueFormat="DD/MM/YYYY" />
          <NumberInput label="Importo (€)" placeholder="listino" value={amount} onChange={setAmount} decimalScale={2} min={0} />
          <NumberInput label="Giorni di tolleranza" placeholder="predefiniti" value={grace} onChange={setGrace} min={0} />
          <NumberInput label="Giorni di sola lettura" placeholder="predefiniti" value={readonly} onChange={setReadonly} min={0} />
        </SimpleGrid>
        <TextInput label="Note" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Annulla</Button><Button onClick={save}>Salva</Button></Group>
      </Stack>
    </Modal>
  )
}

function UserPasswordModal({ tenantId, user, onClose }: { tenantId: string; user: any; onClose: () => void }) {
  const [password, setPassword] = useState('')
  const [send, setSend] = useState(true)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<any>(null)
  const generate = () => adminApi('/password-provvisoria').then((r) => setPassword(r.password)).catch(notifyError)
  useEffect(() => { generate() }, [])
  async function save() {
    setBusy(true)
    try { setRes(await adminApi(`/tenants/${tenantId}/users/${user.id}/password`, { body: { password, send_email: send } })) } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Modal opened onClose={onClose} title={`Nuova password · ${user.full_name}`}>
      {res ? (
        <Stack>
          <Alert color={res.email_sent ? 'teal' : 'yellow'}>{res.email_sent ? `Credenziali mandate a ${res.username}.` : 'Email non inviata: comunica tu le credenziali.'}</Alert>
          <Credential label="Nome utente" value={res.username} />
          <Credential label="Password provvisoria" value={res.password} mono />
          <Text size="xs" c="dimmed">La vecchia password non vale più. Al primo accesso l'utente sceglie la sua.</Text>
          <Group justify="flex-end"><Button onClick={onClose}>Chiudi</Button></Group>
        </Stack>
      ) : (
        <Stack>
          <Text size="sm" c="dimmed">Le password non si possono rileggere: ne imposti una provvisoria, che l'utente cambierà al primo accesso.</Text>
          <Group align="flex-end" wrap="nowrap">
            <TextInput label="Password provvisoria" value={password} onChange={(e) => setPassword(e.currentTarget.value)} style={{ flex: 1 }} styles={{ input: { fontFamily: 'monospace' } }} />
            <Button variant="default" onClick={generate}>Genera</Button>
          </Group>
          <Checkbox label={`Manda l'email con le credenziali a ${user.email}`} checked={send} onChange={(e) => setSend(e.currentTarget.checked)} />
          <Group justify="flex-end"><Button onClick={save} loading={busy} disabled={password.length < 8}>Imposta password</Button></Group>
        </Stack>
      )}
    </Modal>
  )
}

/** La prova si può convertire se è l'ultimo periodo (nessun abbonamento pagato dopo di lei). */
function canConvert(t: any) {
  const trials = t.subscriptions.filter((s: any) => s.is_trial)
  if (!trials.length) return false
  const last = trials.reduce((a: any, b: any) => (a.start_date > b.start_date ? a : b))
  return !t.subscriptions.some((s: any) => !s.is_trial && s.start_date >= last.start_date)
}

function ConvertTrialModal({ tenant, onClose, onSaved }: { tenant: any; onClose: () => void; onSaved: (d: any) => void }) {
  const [plan, setPlan] = useState<string>(tenant.plan_code ?? 'BASE')
  const [period, setPeriod] = useState('annuale')
  const [start, setStart] = useState(tenant.status === 'prova' ? 'fine_prova' : 'oggi')
  const [amount, setAmount] = useState<number | string>('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    try {
      const d = await adminApi(`/tenants/${tenant.id}/convert-trial`, {
        body: { plan_code: plan, period, start, amount: amount === '' ? null : amount, notes: notes || null } })
      notifyOk('Prova convertita in abbonamento')
      onSaved(d)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Modal opened onClose={onClose} title="Converti prova in abbonamento">
      <Stack>
        <Text size="sm" c="dimmed">L'azienda riparte con tutti i suoi dati. La prova resta nello storico dei periodi.</Text>
        <SimpleGrid cols={2}>
          <Select label="Pacchetto" data={['BASE', 'PLUS', 'PRO']} value={plan} onChange={(v) => setPlan(v ?? 'BASE')} allowDeselect={false} />
          <Select label="Periodicità" data={[{ value: 'annuale', label: 'Annuale' }, { value: 'mensile', label: 'Mensile' }]} value={period} onChange={(v) => setPeriod(v ?? 'annuale')} allowDeselect={false} />
        </SimpleGrid>
        <Select label="Inizio dell'abbonamento" value={start} onChange={(v) => setStart(v ?? 'oggi')} allowDeselect={false}
          data={[{ value: 'oggi', label: 'Da oggi (la prova si chiude ieri)' }, { value: 'fine_prova', label: `Dal giorno dopo la fine della prova (${fmtDate(tenant.end_date)})` }]} />
        <NumberInput label="Importo (€)" placeholder="listino" value={amount} onChange={setAmount} decimalScale={2} min={0} />
        <TextInput label="Note" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Annulla</Button><Button color="teal" onClick={save} loading={busy}>Converti</Button></Group>
      </Stack>
    </Modal>
  )
}

function EditPeriodModal({ sub, onClose, onSaved }: { sub: any; onClose: () => void; onSaved: (d: any) => void }) {
  const d0 = (iso: string) => new Date(iso + 'T00:00:00')
  const [start, setStart] = useState<Date | null>(d0(sub.start_date))
  const [end, setEnd] = useState<Date | null>(d0(sub.end_date))
  const [amount, setAmount] = useState<number | string>(Number(sub.amount))
  const [grace, setGrace] = useState<number | string>(sub.grace_days)
  const [readonly, setReadonly] = useState<number | string>(sub.readonly_days)
  const [notes, setNotes] = useState(sub.notes ?? '')
  async function save() {
    if (!start || !end) return
    try {
      const d = await adminApi(`/subscriptions/${sub.id}`, { method: 'PATCH', body: {
        start_date: isoDate(start), end_date: isoDate(end), amount, grace_days: Number(grace) || 0,
        readonly_days: Number(readonly) || 0, notes: notes || null } })
      notifyOk('Periodo modificato')
      onSaved(d)
    } catch (e) { notifyError(e) }
  }
  return (
    <Modal opened onClose={onClose} title={`Modifica periodo · ${sub.plan_name}${sub.is_trial ? ' (prova)' : ''}`}>
      <Stack>
        <SimpleGrid cols={2}>
          <DateInput label="Dal" value={start} onChange={setStart} valueFormat="DD/MM/YYYY" />
          <DateInput label="Al" value={end} onChange={setEnd} valueFormat="DD/MM/YYYY" />
          <NumberInput label="Importo (€)" value={amount} onChange={setAmount} decimalScale={2} min={0} />
          <div />
          <NumberInput label="Giorni di tolleranza" value={grace} onChange={setGrace} min={0} disabled={sub.is_trial} />
          <NumberInput label="Giorni di sola lettura" value={readonly} onChange={setReadonly} min={0} disabled={sub.is_trial} />
        </SimpleGrid>
        <TextInput label="Note" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Annulla</Button><Button onClick={save}>Salva</Button></Group>
      </Stack>
    </Modal>
  )
}

/** Eliminazione definitiva: archivio ZIP (copia sul server + download sul computer), poi nome e parola ELIMINA. */
function DeleteTenantModal({ tenant, onClose, onDeleted }: { tenant: any; onClose: () => void; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false)
  const [arc, setArc] = useState<{ file: string; sha256: string; size: number; rows: number; media: number } | null>(null)
  const [localSha, setLocalSha] = useState('')
  const [name, setName] = useState('')
  const [word, setWord] = useState('')

  async function makeArchive() {
    setBusy(true)
    try {
      const a = await adminApi(`/tenants/${tenant.id}/archivio`, { method: 'POST' })
      const res = await fetch(`/api/admin/tenants/${tenant.id}/archivio/${a.file}`, { headers: { Authorization: `Bearer ${tokens.get('admin')}` } })
      if (!res.ok) throw new ApiError(res.status, 'Scaricamento dell\'archivio non riuscito')
      const blob = await res.blob()
      // l'impronta si calcola sui byte ricevuti dal browser: se coincide con quella del server il file è intero
      const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
      const hex = Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('')
      if (hex !== a.sha256) throw new Error('Il file scaricato è diverso da quello sul server: riprova.')
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = a.file
      link.click()
      URL.revokeObjectURL(url)
      setArc(a)
      setLocalSha(hex)
      notifyOk('Archivio creato sul server e scaricato sul computer')
    } catch (e) { notifyError(e) }
    setBusy(false)
  }

  async function remove() {
    if (!arc) return
    setBusy(true)
    try {
      await adminApi(`/tenants/${tenant.id}/elimina`, { method: 'POST', body: { file: arc.file, sha256: localSha, name, confirm: word } })
      notifyOk('Azienda eliminata')
      onDeleted()
    } catch (e) { notifyError(e) }
    setBusy(false)
  }

  const ready = !!arc && name.trim() === tenant.name && word.trim() === 'ELIMINA'
  return (
    <Modal opened onClose={onClose} title={`Elimina ${tenant.name}`} size="lg">
      <Stack>
        <Alert color="red">L'eliminazione è definitiva: spariscono utenti, anagrafiche, documenti, magazzino e file. Prima si crea un archivio completo, che resta sul server e viene scaricato sul tuo computer.</Alert>
        <Text fw={600}>1. Archivio</Text>
        {arc
          ? <Alert color="green">Archivio <b>{arc.file}</b>: {arc.rows} righe, {arc.media} file caricati, {(arc.size / 1024).toFixed(0)} KB. Copia sul server e sul computer verificate (SHA-256 {arc.sha256.slice(0, 12)}…).</Alert>
          : <Button onClick={makeArchive} loading={busy}>Crea l'archivio e scaricalo</Button>}
        <Text fw={600}>2. Conferma</Text>
        <TextInput label={`Scrivi il nome dell'azienda: ${tenant.name}`} value={name} onChange={(e) => setName(e.currentTarget.value)} disabled={!arc} />
        <TextInput label="Scrivi la parola ELIMINA" value={word} onChange={(e) => setWord(e.currentTarget.value)} disabled={!arc} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Annulla</Button>
          <Button color="red" disabled={!ready} loading={busy} onClick={remove}>Elimina definitivamente</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
