import { ActionIcon, Badge, Box, Button, Checkbox, Divider, Drawer, Group, Modal, NumberInput, Paper, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput, Textarea, Tooltip } from '@mantine/core'
import { DatePickerInput } from '@mantine/dates'
import { IconCalendarPlus, IconCash, IconChevronLeft, IconChevronRight, IconDeviceMobile, IconExternalLink, IconPlus, IconReceipt, IconTrash, IconUserPlus } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useOutletContext, useSearchParams } from 'react-router-dom'

import { ApiError, appApi, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'
import type { AppCtx } from '../app/AppLayout'
import { type Appointment, CHANNEL, type Service, type Staff, STATUS, dayKey, hhmm, longDay, minutesOf } from './lib'
import { WhatsAppChat } from './WhatsAppChat'
import { PayModal, ReceiptButtons } from '../salone/Pay'

const PX = 1.5 // pixel per minuto

type Laned = { a: Appointment; it: Appointment['items'][0]; lane: number; lanes: number }

/** Affianca gli appuntamenti che si sovrappongono nella stessa colonna (es. una piega durante la posa del colore). */
function lanes(items: { a: Appointment; it: Appointment['items'][0] }[]): Laned[] {
  const out: Laned[] = []
  const sorted = [...items].sort((x, y) => +new Date(x.it.starts_at) - +new Date(y.it.starts_at))
  let cluster: { a: Appointment; it: Appointment['items'][0]; lane: number }[] = []
  let ends: number[] = []
  let clusterEnd = 0
  const flush = () => { cluster.forEach((c) => out.push({ ...c, lanes: ends.length })); cluster = []; ends = [] }
  for (const x of sorted) {
    const s = +new Date(x.it.starts_at), e = +new Date(x.it.ends_at)
    if (cluster.length && s >= clusterEnd) flush()
    let lane = ends.findIndex((v) => v <= s)
    if (lane === -1) lane = ends.push(0) - 1
    ends[lane] = e
    clusterEnd = Math.max(clusterEnd, e)
    cluster.push({ ...x, lane })
  }
  flush()
  return out
}

export default function Agenda() {
  const { status } = useOutletContext<AppCtx>()
  const has = (code: string) => status.menu.some((m: any) => m.code === code && m.enabled)
  const [params, setParams] = useSearchParams()
  const day = params.get('giorno') ? new Date(params.get('giorno') + 'T12:00:00') : new Date()
  const setDay = (d: Date) => setParams({ giorno: isoDate(d) })
  const [settings, setSettings] = useState<any>(null)
  const [staff, setStaff] = useState<Staff[]>([])
  const [services, setServices] = useState<Service[]>([])
  const [appts, setAppts] = useState<Appointment[] | null>(null)
  const [newAt, setNewAt] = useState<{ staffId?: string; time?: string } | null>(null)
  const [openId, setOpenId] = useState<string | null>(params.get('apri'))
  const nav = useNavigate()

  const load = () => appApi(`/api/agenda/appuntamenti?day=${isoDate(day)}`).then(setAppts).catch(notifyError)
  // orario effettivo del giorno (turni, settimane alterne, ferie, permessi, chiusure)
  const [plan, setPlan] = useState<Record<string, { hours: string[][]; absence: any }>>({})
  useEffect(() => {
    Promise.all([appApi('/api/agenda/impostazioni'), appApi('/api/agenda/operatori'), appApi('/api/agenda/servizi')])
      .then(([s, st, sv]) => { setSettings(s); setStaff(st.filter((x: Staff) => x.active)); setServices(sv) }).catch(notifyError)
  }, [])
  useEffect(() => { setAppts(null); load(); appApi(`/api/agenda/orari?giorno=${isoDate(day)}`).then(setPlan).catch(() => setPlan({})) }, [isoDate(day)])

  const hours = settings?.opening_hours?.[dayKey(day)] ?? []
  const [from, to] = useMemo(() => {
    const all = [...hours, ...staff.flatMap((s) => plan[s.id]?.hours ?? s.working_hours?.[dayKey(day)] ?? [])]
    if (!all.length) return [9 * 60, 19 * 60]
    const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3))
    return [Math.floor(Math.min(...all.map((r: string[]) => toMin(r[0]))) / 60) * 60, Math.ceil(Math.max(...all.map((r: string[]) => toMin(r[1]))) / 60) * 60]
  }, [settings, staff, plan, isoDate(day)])

  if (!settings || !appts) return <Loading />
  const shift = (n: number) => { const d = new Date(day); d.setDate(d.getDate() + n); setDay(d) }
  const visible = appts.filter((a) => a.status !== 'disdetto')
  const totalDay = visible.reduce((s, a) => s + Number(a.total), 0)

  return (
    <>
      <PageTitle title="Agenda" subtitle={`${longDay(day)} · ${visible.length} appuntamenti · ${fmtEuro(totalDay)}`}
        right={<Group>
          <ActionIcon variant="default" size="lg" onClick={() => shift(-1)} aria-label="Giorno prima"><IconChevronLeft size={18} /></ActionIcon>
          <Button variant="default" onClick={() => setDay(new Date())}>Oggi</Button>
          <ActionIcon variant="default" size="lg" onClick={() => shift(1)} aria-label="Giorno dopo"><IconChevronRight size={18} /></ActionIcon>
          <DatePickerInput value={day} onChange={(d) => d && setDay(d as Date)} valueFormat="DD/MM/YYYY" w={130} />
          <Button leftSection={<IconCalendarPlus size={16} />} onClick={() => setNewAt({})}>Nuovo appuntamento</Button>
          <Tooltip label="Apri la pagina di prenotazione per i clienti">
            <ActionIcon variant="light" size="lg" component="a" href={`/prenota/${settings.slug}`} target="_blank"><IconExternalLink size={18} /></ActionIcon>
          </Tooltip>
        </Group>} />

      {staff.length === 0 ? (
        <Paper withBorder p="xl" ta="center">
          <Text mb="md">Per iniziare inserisci operatori e servizi.</Text>
          <Button onClick={() => nav('/agenda/servizi')}>Servizi e operatori</Button>
        </Paper>
      ) : (
        <Paper withBorder p={0}>
          <ScrollArea type="auto">
            <Box miw={70 + staff.length * 180}>
              <Group gap={0} wrap="nowrap" style={{ borderBottom: '1px solid var(--mantine-color-gray-3)', position: 'sticky', top: 0, zIndex: 2, background: 'var(--mantine-color-body)' }}>
                <Box w={60} />
                {staff.map((s) => (
                  <Group key={s.id} gap={8} px="sm" py="xs" style={{ flex: 1, minWidth: 180, borderLeft: '1px solid var(--mantine-color-gray-2)' }}>
                    <Box w={12} h={12} bg={s.color} style={{ borderRadius: '50%' }} />
                    <Text fw={700}>{s.first_name}</Text>
                    {plan[s.id]?.absence && <Badge size="sm" variant="light" color={({ ferie: 'teal', malattia: 'red', permesso: 'orange', orario: 'violet', chiusura: 'gray' } as any)[plan[s.id].absence.kind]}>{plan[s.id].absence.kind === 'chiusura' ? 'Salone chiuso' : plan[s.id].absence.label}</Badge>}
                  </Group>
                ))}
              </Group>
              <Group gap={0} wrap="nowrap" align="flex-start" style={{ position: 'relative', height: (to - from) * PX }}>
                <Box w={60} style={{ position: 'relative', height: '100%' }}>
                  {Array.from({ length: (to - from) / 60 }, (_, i) => (
                    <Text key={i} size="xs" c="dimmed" style={{ position: 'absolute', right: 8, top: Math.max(2, i * 60 * PX - 8) }}>{String(from / 60 + i).padStart(2, '0')}:00</Text>
                  ))}
                </Box>
                {staff.map((s) => {
                  const mine = visible.flatMap((a) => a.items.filter((it) => it.staff_id === s.id).map((it) => ({ a, it })))
                  const open = plan[s.id]?.hours ?? s.working_hours?.[dayKey(day)] ?? hours
                  return (
                    <Box key={s.id} style={{ flex: 1, minWidth: 180, position: 'relative', height: '100%', borderLeft: '1px solid var(--mantine-color-gray-2)', background: open.length ? undefined : 'repeating-linear-gradient(45deg, var(--mantine-color-gray-1) 0 8px, transparent 8px 16px)' }}
                      onClick={(e) => {
                        if (e.target !== e.currentTarget) return
                        const y = e.nativeEvent.offsetY / PX + from
                        const m = Math.floor(y / (settings.slot_minutes || 15)) * (settings.slot_minutes || 15)
                        setNewAt({ staffId: s.id, time: `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}` })
                      }}>
                      {Array.from({ length: (to - from) / 60 }, (_, i) => <Box key={i} style={{ position: 'absolute', left: 0, right: 0, top: i * 60 * PX, borderTop: '1px solid var(--mantine-color-gray-2)', pointerEvents: 'none' }} />)}
                      {open.length > 0 && offRanges(open, from, to).map(([a, b]) => <Box key={a} style={{ position: 'absolute', left: 0, right: 0, top: (a - from) * PX, height: (b - a) * PX, pointerEvents: 'none', background: 'repeating-linear-gradient(45deg, var(--mantine-color-gray-light) 0 8px, transparent 8px 16px)' }} />)}
                      {lanes(mine).map(({ a, it, lane, lanes: n }) => {
                        const top = (minutesOf(it.starts_at) - from) * PX
                        const h = (+new Date(it.ends_at) - +new Date(it.starts_at)) / 60000 * PX
                        return (
                          <Box key={it.id} onClick={() => setOpenId(a.id)} data-testid="appt"
                            style={{ position: 'absolute', top, height: h, left: `calc(${(lane / n) * 100}% + 3px)`, width: `calc(${100 / n}% - 6px)`, background: s.color, color: '#fff', borderRadius: 8, padding: '3px 7px', overflow: 'hidden', cursor: 'pointer', boxShadow: '0 0 0 2px var(--mantine-color-body)', opacity: a.status === 'non_presentato' ? 0.45 : 1 }}>
                            {it.processing_min ? <Box style={{ position: 'absolute', left: 0, right: 0, top: (it.processing_start_min ?? 0) * PX, height: it.processing_min * PX, backgroundImage: 'repeating-linear-gradient(135deg, rgba(255,255,255,.5) 0 6px, transparent 6px 12px)' }}><Text size="10px" fw={700} ta="right" pr={6}>posa</Text></Box> : null}
                            <Box style={{ position: 'relative' }}>
                              <Text size="xs" fw={700} lh={1.25}>{hhmm(it.starts_at)} · {a.client ?? 'Cliente occasionale'}</Text>
                              <Text size="xs" lh={1.25} opacity={0.92}>{it.service}</Text>
                              <Text size="10px" lh={1.3} opacity={0.85}>{STATUS[a.status]?.label}{a.channel === 'online' ? ' · 📱 online' : ''}</Text>
                            </Box>
                          </Box>
                        )
                      })}
                    </Box>
                  )
                })}
              </Group>
            </Box>
          </ScrollArea>
        </Paper>
      )}
      <Text size="xs" c="dimmed" mt="xs">Fascia a righe = tempo di posa: l'operatore è libero per un altro cliente. Clic su uno spazio vuoto per prenotare lì.</Text>

      {newAt && <NewAppointment day={day} staff={staff} services={services} preset={newAt} onClose={() => setNewAt(null)}
        onSaved={(a) => { setNewAt(null); load(); setOpenId(a.id) }} />}
      <Drawer opened={!!openId} onClose={() => { setOpenId(null); load() }} position="right" size="lg" title="Appuntamento">
        {openId && <AppointmentDetail id={openId} staff={staff} canCash={has('pos')} onChange={load} />}
      </Drawer>
    </>
  )
}

// ---------------------------------------------------------------------------------------------------- nuovo appuntamento
export function NewAppointment({ day, staff, services, preset, partyId, onClose, onSaved }: {
  day: Date; staff: Staff[]; services: Service[]; preset: { staffId?: string; time?: string }; partyId?: string
  onClose: () => void; onSaved: (a: Appointment) => void
}) {
  const [date, setDate] = useState<Date>(day)
  const [clients, setClients] = useState<{ value: string; label: string }[]>([])
  const [party, setParty] = useState<string | null>(partyId ?? null)
  const [q, setQ] = useState('')
  const [newClient, setNewClient] = useState(false)
  const [nc, setNc] = useState({ first_name: '', last_name: '', mobile: '', marketing: false })
  const [serviceId, setServiceId] = useState<string | null>(null)
  const [staffId, setStaffId] = useState<string | null>(preset.staffId ?? null)
  const [slots, setSlots] = useState<{ time: string; staff_ids: string[] }[] | null>(null)
  const [time, setTime] = useState<string | null>(preset.time ?? null)
  const [notes, setNotes] = useState('')
  const [channel, setChannel] = useState('telefono')
  const [busy, setBusy] = useState(false)
  const svc = services.find((s) => s.id === serviceId)
  const eligible = staff.filter((s) => svc?.staff_ids.includes(s.id))

  useEffect(() => {
    const t = setTimeout(() => appApi(`/api/agenda/clienti?limit=30&q=${encodeURIComponent(q)}`)
      .then((r) => setClients(r.map((c: any) => ({ value: c.id, label: `${c.name}${c.mobile ? ' · ' + c.mobile : ''}` })))).catch(() => {}), 200)
    return () => clearTimeout(t)
  }, [q])
  useEffect(() => {
    if (!serviceId) return
    setSlots(null)
    appApi(`/api/agenda/disponibilita?service_id=${serviceId}&day=${isoDate(date)}${staffId ? `&staff_id=${staffId}` : ''}`).then(setSlots).catch(notifyError)
  }, [serviceId, staffId, isoDate(date)])

  const save = async () => {
    setBusy(true)
    try {
      let pid = party
      if (newClient) {
        const c = await appApi('/api/agenda/clienti', { body: { ...nc, privacy: true } })
        pid = c.id
      }
      const a = await appApi('/api/agenda/appuntamenti', { body: { party_id: pid, day: isoDate(date), time, channel, notes: notes || null, items: [{ service_id: serviceId, staff_id: staffId }] } })
      notifyOk(a.messages?.length ? 'Appuntamento salvato: conferma inviata su WhatsApp' : 'Appuntamento salvato')
      onSaved(a)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  return (
    <Modal opened onClose={onClose} title="Nuovo appuntamento" size="lg">
      <Stack>
        {!newClient ? (
          <Group align="flex-end" wrap="nowrap">
            <Select label="Cliente" placeholder="Cerca per nome o cellulare" searchable data={clients} value={party} onChange={setParty}
              onSearchChange={setQ} nothingFoundMessage="Nessun cliente" style={{ flex: 1 }} data-testid="client-select" />
            <Button variant="default" leftSection={<IconUserPlus size={16} />} onClick={() => setNewClient(true)}>Nuovo</Button>
          </Group>
        ) : (
          <Paper withBorder p="sm">
            <SimpleGrid cols={3}>
              <TextInput label="Nome" value={nc.first_name} onChange={(e) => setNc({ ...nc, first_name: e.target.value })} />
              <TextInput label="Cognome" value={nc.last_name} onChange={(e) => setNc({ ...nc, last_name: e.target.value })} />
              <TextInput label="Cellulare" value={nc.mobile} onChange={(e) => setNc({ ...nc, mobile: e.target.value })} />
            </SimpleGrid>
            <Checkbox mt="xs" label="Consenso a ricevere offerte su WhatsApp" checked={nc.marketing} onChange={(e) => setNc({ ...nc, marketing: e.target.checked })} />
          </Paper>
        )}
        <Select label="Servizio" data={services.filter((s) => s.active).map((s) => ({ value: s.id, label: `${s.name} · ${s.duration_min} min · ${fmtEuro(s.price)}` }))}
          value={serviceId} onChange={(v) => { setServiceId(v); setTime(null) }} searchable data-testid="service-select" />
        {svc && (
          <Group gap="xs">
            <Text size="sm" fw={500}>Operatore</Text>
            <Button size="xs" variant={staffId === null ? 'filled' : 'default'} onClick={() => setStaffId(null)}>Primo libero</Button>
            {eligible.map((s) => <Button key={s.id} size="xs" variant={staffId === s.id ? 'filled' : 'default'} onClick={() => setStaffId(s.id)}
              leftSection={<Box w={8} h={8} bg={s.color} style={{ borderRadius: '50%' }} />}>{s.first_name}</Button>)}
          </Group>
        )}
        <DatePickerInput label="Giorno" value={date} onChange={(d) => d && setDate(d as Date)} valueFormat="dddd DD MMMM YYYY" />
        {svc && (
          <div>
            <Text size="sm" fw={500} mb={4}>Orari liberi</Text>
            {slots === null ? <Text size="sm" c="dimmed">Calcolo…</Text> : slots.length === 0 ? <Text size="sm" c="orange">Nessun orario libero: cambia giorno o operatore.</Text> : (
              <Group gap={6}>{slots.map((s) => <Button key={s.time} size="xs" variant={time === s.time ? 'filled' : 'light'} onClick={() => setTime(s.time)}>{s.time}</Button>)}</Group>
            )}
          </div>
        )}
        <SegmentedControl value={channel} onChange={setChannel} data={[{ value: 'telefono', label: 'Telefono' }, { value: 'salone', label: 'In salone' }, { value: 'whatsapp', label: 'WhatsApp' }]} />
        <Textarea label="Note" value={notes} onChange={(e) => setNotes(e.target.value)} autosize minRows={1} />
        <Group justify="space-between">
          <Text size="xs" c="dimmed">Con il cellulare del cliente parte la conferma su WhatsApp.</Text>
          <Button onClick={save} loading={busy} disabled={!serviceId || !time || (newClient && (!nc.first_name || !nc.last_name))}>Salva appuntamento</Button>
        </Group>
      </Stack>
    </Modal>
  )
}

// ---------------------------------------------------------------------------------------------------- dettaglio
export function AppointmentDetail({ id, staff, canCash, onChange }: { id: string; staff: Staff[]; canCash: boolean; onChange: () => void }) {
  const [a, setA] = useState<Appointment | null>(null)
  const [cashOpen, setCashOpen] = useState(false)
  const nav = useNavigate()
  const load = () => appApi(`/api/agenda/appuntamenti/${id}`).then(setA).catch(notifyError)
  useEffect(() => { load() }, [id])
  if (!a) return <Loading />
  const st = STATUS[a.status]
  const act = async (path: string, body?: any) => {
    try { setA(await appApi(`/api/agenda/appuntamenti/${a.id}/${path}`, { body: body ?? {} })); onChange() } catch (e) { notifyError(e) }
  }
  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <div>
          <Text c="dimmed" size="sm" tt="capitalize">{longDay(a.starts_at)}</Text>
          <Text fz={28} fw={800}>{hhmm(a.starts_at)} – {hhmm(a.ends_at)}</Text>
          <Text size="sm" c="dimmed">{CHANNEL[a.channel]}</Text>
        </div>
        <Badge size="lg" color={st?.color} data-testid="status">{st?.label}</Badge>
      </Group>
      {a.party_id && (
        <Paper withBorder p="sm" style={{ cursor: 'pointer' }} onClick={() => nav(`/agenda/clienti/${a.party_id}`)}>
          <Text fw={700}>{a.client}</Text>
          <Text size="sm" c="dimmed">{a.client_mobile}</Text>
        </Paper>
      )}
      <Stack gap={4}>
        {a.items.map((it) => (
          <Group key={it.id} justify="space-between">
            <Text size="sm"><b>{it.service}</b> · {staff.find((s) => s.id === it.staff_id)?.first_name ?? '—'}</Text>
            <Text size="sm" fw={600}>{fmtEuro(it.price)}</Text>
          </Group>
        ))}
        <Divider />
        <Group justify="space-between"><Text fw={700}>Totale</Text><Text fw={800}>{fmtEuro(a.total)}</Text></Group>
      </Stack>
      {a.notes && <Text size="sm">📝 {a.notes}</Text>}
      {a.document && (
        <Paper withBorder p="sm" bg="var(--mantine-color-green-0)">
          <Group gap="xs"><IconReceipt size={18} />
            <Text size="sm" fw={600}>{a.document.doc_type === 'FTI' ? 'Fattura' : 'Scontrino'} n. {a.document.number} · {fmtEuro(a.document.total)}</Text>
          </Group>
          {a.document.doc_type === 'SCO' && <Text size="xs" c="dimmed">Registratore telematico: {a.document.rt?.status ?? 'non collegato'}{a.document.rt?.number ? ` · documento ${a.document.rt.number}` : ''}</Text>}
          {a.document.doc_type === 'FTI' && <Button size="xs" variant="subtle" onClick={() => nav(`/vendite/${a.document.id}`)}>Apri la fattura (invio allo SDI)</Button>}
        </Paper>
      )}
      <Group gap="xs">
        {['prenotato'].includes(a.status) && <Button variant="default" onClick={() => act('stato', { status: 'confermato' })}>Confermato</Button>}
        {['prenotato', 'confermato'].includes(a.status) && <Button variant="default" onClick={() => act('stato', { status: 'arrivato' })}>✓ Cliente arrivato</Button>}
        {a.status === 'arrivato' && <Button variant="default" onClick={() => act('stato', { status: 'concluso' })}>✓ Servizio concluso</Button>}
        {canCash && !['pagato', 'disdetto', 'non_presentato'].includes(a.status) && <Button leftSection={<IconCash size={16} />} onClick={() => setCashOpen(true)}>Incassa</Button>}
        {['prenotato', 'confermato'].includes(a.status) && <Button variant="default" color="red" onClick={() => act('stato', { status: 'non_presentato' })}>Non presentato</Button>}
        {['prenotato', 'confermato', 'arrivato'].includes(a.status) && <Button variant="light" color="red" leftSection={<IconTrash size={14} />} onClick={() => act('disdici')}>Disdici</Button>}
      </Group>
      <Text size="sm" fw={600} mt="sm">Messaggi WhatsApp al cliente</Text>
      <WhatsAppChat title="Il salone" messages={a.messages ?? []} height={300} />
      {a.public_url && <Text size="xs" c="dimmed" ta="center">Link personale del cliente: <a href={a.public_url} target="_blank" rel="noreferrer">apri</a></Text>}
      {a.status === 'pagato' && <ReceiptButtons apptId={a.id} />}
      {cashOpen && <PayModal appt={a} onClose={() => setCashOpen(false)} onDone={(x) => { setCashOpen(false); setA(x); onChange() }} />}
    </Stack>
  )
}

/** Fasce della giornata in cui l'operatore non lavora (pausa, permesso), in minuti dalla mezzanotte. */
function offRanges(open: string[][], from: number, to: number): [number, number][] {
  const m = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3))
  const sorted = open.map(([a, b]) => [m(a), m(b)]).sort((x, y) => x[0] - y[0])
  const out: [number, number][] = []
  let t = from
  for (const [a, b] of sorted) { if (a > t) out.push([t, a]); t = Math.max(t, b) }
  if (t < to) out.push([t, to])
  return out
}
