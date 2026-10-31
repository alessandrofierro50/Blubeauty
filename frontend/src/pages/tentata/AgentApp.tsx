// App dell'agente (tablet e smartphone), anche senza rete: clienti del giro, documenti con firma del cliente,
// incassi, merce a bordo, rientro. Tutto si salva sul dispositivo e parte appena c'è copertura, senza doppioni
// (ogni invio porta un identificativo generato qui).

import { ActionIcon, Alert, Anchor, Badge, Box, Button, Center, Checkbox, Divider, Group, Loader, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Switch, Text, TextInput, Textarea, Title, UnstyledButton } from '@mantine/core'
import { IconArrowLeft, IconBarcode, IconCash, IconCheck, IconChevronRight, IconCloudOff, IconCloudUpload, IconFileTypePdf, IconMail, IconMapPin, IconMinus, IconPhone, IconPlus, IconPrinter, IconRefresh, IconSearch, IconTrash, IconTruck, IconTruckReturn, IconUsers, IconBrandWhatsapp, IconFileText } from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro, isoDate } from '../../api'
import { Logo, notifyError, notifyOk } from '../../components'
import { CameraScanner, beep } from '../magazzino/MobileCount'
import { isNetworkError, local, uuid4 } from '../pos/shared'
import { DOC_LABEL, SignaturePad, TV, emptySignature, openPdf, qtyFmt, signatureReady, type SignatureValue } from './shared'

type Pending = { kind: 'documento' | 'incasso' | 'visita' | 'invio'; body: any; label: string; at: string; error?: string; doc_uuid?: string }
type Done = {
  client_uuid: string; kind: 'documento' | 'incasso'; doc_type?: string; party_id: string; party_name: string; total: number; at: string
  lines?: { item_id: string; variant_id: string | null; quantity: number }[]; collection?: { method: string; amount: number }
  server_id?: string; label?: string; synced?: boolean; in_pkg?: boolean; sent?: string[]
}
const K = { pkg: (id: string) => `bg_giro_pkg_${id}`, out: (id: string) => `bg_giro_out_${id}`, done: (id: string) => `bg_giro_done_${id}` }
const r2 = (n: number) => Math.round(n * 100) / 100
const skey = (item: string, variant: string | null) => `${item}:${variant ?? ''}`

// ====================================================================================================== elenco dei giri

export default function AgentApp() {
  const { id } = useParams()
  return id ? <TripApp id={id} /> : <MyTrips />
}

function MyTrips() {
  const nav = useNavigate()
  const [vans, setVans] = useState<any[] | null>(null)
  const [trips, setTrips] = useState<any[]>([])
  const [me, setMe] = useState<any>(null)
  const load = () => {
    TV('/furgoni').then(setVans).catch((e) => { if (isNetworkError(e)) setVans([]); else notifyError(e) })
    TV('/giri').then(setTrips).catch(() => {})
  }
  useEffect(() => { load(); appApi('/api/auth/me').then(setMe).catch(() => {}) }, [])
  const today = isoDate(new Date())
  const cached = Object.keys(localStorage).filter((k) => k.startsWith('bg_giro_pkg_')).map((k) => local.get<any>(k, null)).filter(Boolean)
  return (
    <Shell title="I miei giri" subtitle={me?.user.full_name}>
      <Stack p="md">
        {vans === null ? <Center py="xl"><Loader /></Center> : !vans.length && !cached.length ? (
          <Alert color="blue">Non hai un furgone assegnato: chiedi all'ufficio di assegnartelo in «Tentata vendita › Furgoni».</Alert>
        ) : null}
        {vans?.map((v) => {
          const todayTrip = trips.find((t) => t.van_id === v.id && t.trip_date === today)
          const open = trips.filter((t) => t.van_id === v.id && t.status !== 'chiuso')
          return (
            <Paper key={v.id} withBorder p="md" radius="md">
              <Group gap="sm" mb="sm"><IconTruck size={26} color="var(--mantine-color-blue-6)" /><div><Text fw={700}>{v.code} · {v.name}</Text><Text size="sm" c="dimmed">{v.plate}</Text></div></Group>
              {open.map((t) => (
                <Button key={t.id} fullWidth size="lg" mb="xs" variant={t.trip_date === today ? 'filled' : 'light'} rightSection={<IconChevronRight />} onClick={() => nav(`/giro/${t.id}`)}>
                  {t.weekday} {fmtDate(t.trip_date)} · {t.status_label}
                </Button>
              ))}
              {!todayTrip && !open.length && (
                <Button fullWidth size="lg" variant="light" leftSection={<IconPlus />} onClick={async () => {
                  try { const t = await TV('/giri', { body: { van_id: v.id, trip_date: today } }); nav(`/giro/${t.id}`) } catch (e) { notifyError(e) }
                }}>Prepara il giro di oggi</Button>
              )}
            </Paper>
          )
        })}
        {vans !== null && !vans.length && cached.map((p: any) => (
          <Button key={p.trip.id} size="lg" variant="light" onClick={() => nav(`/giro/${p.trip.id}`)}>Giro del {fmtDate(p.trip.trip_date)} (salvato sul dispositivo)</Button>
        ))}
        <Anchor ta="center" size="sm" onClick={() => nav('/')}>Vai al gestionale</Anchor>
      </Stack>
    </Shell>
  )
}

function Shell({ title, subtitle, right, children, onBack }: { title: string; subtitle?: string; right?: React.ReactNode; children: React.ReactNode; onBack?: () => void }) {
  return (
    <Box mih="100vh" bg="var(--mantine-color-gray-0)" style={{ display: 'flex', flexDirection: 'column' }}>
      <Box bg="blue.7" c="white" px="md" py="sm" style={{ position: 'sticky', top: 0, zIndex: 50 }}>
        <Group justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            {onBack ? <ActionIcon variant="subtle" color="white" size="lg" onClick={onBack}><IconArrowLeft /></ActionIcon> : <Logo size={28} withName={false} />}
            <div style={{ minWidth: 0 }}><Text fw={700} truncate>{title}</Text>{subtitle && <Text size="xs" opacity={0.85} truncate>{subtitle}</Text>}</div>
          </Group>
          {right}
        </Group>
      </Box>
      <Box style={{ flex: 1 }}>{children}</Box>
    </Box>
  )
}

// ====================================================================================================== giro

type Screen = { name: 'home' } | { name: 'customer'; pid: string } | { name: 'doc'; pid: string; type: string; fromOrder?: string }
  | { name: 'collect'; pid: string } | { name: 'done'; uuid: string }

function TripApp({ id }: { id: string }) {
  const nav = useNavigate()
  const [pkg, setPkg] = useState<any>(() => local.get(K.pkg(id), null))
  const [outbox, setOutbox] = useState<Pending[]>(() => local.get(K.out(id), []))
  const [done, setDone] = useState<Done[]>(() => local.get(K.done(id), []))
  const [online, setOnline] = useState(navigator.onLine)
  const [tab, setTab] = useState('clienti')
  const [screen, setScreen] = useState<Screen>({ name: 'home' })
  const [loading, setLoading] = useState(false)
  useEffect(() => { local.set(K.out(id), outbox) }, [outbox])
  useEffect(() => { local.set(K.done(id), done) }, [done])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const p = await TV(`/giri/${id}/pacchetto`)
      setPkg(p)
      local.set(K.pkg(id), p)
      // i documenti già arrivati al server sono compresi nel pacchetto nuovo (merce a bordo, fido, scadenze)
      setDone((d) => d.map((x) => (x.synced ? { ...x, in_pkg: true } : x)))
      setOnline(true)
    } catch (e: any) {
      if (isNetworkError(e)) setOnline(false)
      else notifyError(e)
    } finally { setLoading(false) }
  }, [id])

  // coda: all'avvio, ogni 20 secondi e quando torna la rete
  const flushing = useRef(false)
  const flush = useCallback(async () => {
    if (flushing.current) return
    const queue = local.get<Pending[]>(K.out(id), [])
    if (!queue.some((p) => !p.error)) return
    flushing.current = true
    const keep: Pending[] = []
    let offline = false
    let doneNow = local.get<Done[]>(K.done(id), [])
    const mark = (uuid: string, patch: Partial<Done>) => { doneNow = doneNow.map((d) => (d.client_uuid === uuid ? { ...d, ...patch } : d)) }
    for (const p of queue) {
      if (p.error || offline) { keep.push(p); continue }
      try {
        if (p.kind === 'documento') {
          const r = await TV(`/giri/${id}/documenti`, { body: p.body })
          mark(p.body.client_uuid, { server_id: r.id, label: r.label, synced: true })
        } else if (p.kind === 'incasso') {
          await TV(`/giri/${id}/incassi`, { body: p.body })
          mark(p.body.client_uuid, { synced: true })
        } else if (p.kind === 'visita') {
          await TV(`/giri/${id}/visite`, { body: p.body })
        } else if (p.kind === 'invio') {
          const doc = doneNow.find((d) => d.client_uuid === p.doc_uuid)
          if (!doc?.server_id) { keep.push(p); continue }
          await TV(`/documenti/${doc.server_id}/invia`, { body: p.body })
          mark(doc.client_uuid, { sent: [...(doc.sent ?? []), p.body.channel] })
        }
        setOnline(true)
      } catch (e: any) {
        if (isNetworkError(e)) { offline = true; setOnline(false); keep.push(p) } else keep.push({ ...p, error: e.message })
      }
    }
    local.set(K.done(id), doneNow)
    setDone(doneNow)
    setOutbox(keep)
    flushing.current = false
  }, [id])

  useEffect(() => {
    flush().then(refresh)
    const t = setInterval(flush, 20000)
    const on = () => { setOnline(true); flush() }
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => { clearInterval(t); window.removeEventListener('online', on); window.removeEventListener('offline', off) }
  }, [flush, refresh])

  const enqueue = (p: Omit<Pending, 'at'>) => {
    const q = [...local.get<Pending[]>(K.out(id), []), { ...p, at: new Date().toISOString() }]
    local.set(K.out(id), q)
    setOutbox(q)
    setTimeout(flush, 100)
  }
  const addDone = (d: Done) => { const x = [...local.get<Done[]>(K.done(id), []), d]; local.set(K.done(id), x); setDone(x) }

  // giornata = quello fatto su questo dispositivo + quello già arrivato in ufficio (anche da un altro dispositivo)
  const log = useMemo(() => {
    const mine = new Set(done.map((d) => d.client_uuid))
    const server: Done[] = [
      ...(pkg?.documents ?? []).filter((d: any) => !d.client_uuid || !mine.has(d.client_uuid)).map((d: any) => ({
        client_uuid: d.client_uuid ?? d.id, kind: 'documento' as const, doc_type: d.doc_type, party_id: d.party_id, party_name: d.party, total: Number(d.total),
        at: d.created_at, server_id: d.id, label: d.label, synced: true, in_pkg: true, sent: d.sent.map((x: any) => x.channel) })),
      ...(pkg?.collections ?? []).filter((c: any) => !c.client_uuid || !mine.has(c.client_uuid)).map((c: any) => ({
        client_uuid: c.client_uuid ?? c.id, kind: 'incasso' as const, party_id: c.party_id, party_name: c.party, total: 0, at: c.collected_at,
        collection: { method: c.method, amount: Number(c.amount) }, synced: true, in_pkg: true })),
    ]
    return [...server, ...done].sort((a, b) => a.at.localeCompare(b.at))
  }, [pkg, done])
  // merce a bordo e situazione dei clienti aggiornate con quello fatto sul dispositivo dopo l'ultimo pacchetto
  const fresh = done.filter((d) => !d.in_pkg)
  const stock = useMemo(() => {
    const m: Record<string, number> = {}
    for (const it of pkg?.items ?? []) for (const s of it.stock) m[skey(it.id, s.variant_id)] = (m[skey(it.id, s.variant_id)] ?? 0) + Number(s.quantity)
    for (const d of fresh) {
      if (d.kind !== 'documento' || !d.lines || d.doc_type === 'ORC') continue
      const sign = d.doc_type === 'NC' ? 1 : -1
      for (const l of d.lines) m[skey(l.item_id, l.variant_id)] = (m[skey(l.item_id, l.variant_id)] ?? 0) + sign * l.quantity
    }
    return m
  }, [pkg, done])
  const customers = useMemo(() => (pkg?.customers ?? []).map((c: any) => {
    const mine = fresh.filter((d) => d.party_id === c.id)
    const added = mine.reduce((a, d) => a + (d.kind === 'documento' ? (d.doc_type === 'NC' ? -d.total : d.total) : -(d.collection?.amount ?? 0)), 0)
    const visited = c.visited || mine.length > 0 || log.some((d) => d.party_id === c.id)
    return { ...c, exposure_now: Number(c.credit.exposure) + added, visited, today: log.filter((d) => d.party_id === c.id) }
  }), [pkg, done, log])

  if (!pkg) {
    return <Shell title="Giro" onBack={() => nav('/giro')}><Center py="xl">{loading ? <Loader /> : <Stack align="center"><Text>Dati del giro non ancora scaricati.</Text><Button onClick={refresh}>Scarica</Button></Stack>}</Center></Shell>
  }
  const trip = pkg.trip
  const errors = outbox.filter((p) => p.error).length
  const header = (
    <Group gap={6} wrap="nowrap">
      {outbox.length > 0 && <Badge color={errors ? 'red' : 'yellow'} variant="filled">{outbox.length} da inviare</Badge>}
      {online ? <IconCloudUpload size={20} /> : <IconCloudOff size={20} />}
      <ActionIcon variant="subtle" color="white" onClick={() => flush().then(refresh)} loading={loading}><IconRefresh size={20} /></ActionIcon>
    </Group>
  )
  const back = () => setScreen({ name: 'home' })
  const cust = (pid: string) => customers.find((c: any) => c.id === pid)

  if (screen.name === 'customer') {
    const c = cust(screen.pid)
    return <Shell title={c.name} subtitle={[c.address, c.city].filter(Boolean).join(', ')} right={header} onBack={back}>
      <Customer c={c} pkg={pkg} trip={trip} onDoc={(type, fromOrder) => setScreen({ name: 'doc', pid: c.id, type, fromOrder })}
        onCollect={() => setScreen({ name: 'collect', pid: c.id })} onOpen={(uuid) => setScreen({ name: 'done', uuid })}
        onVisit={(notes) => { enqueue({ kind: 'visita', body: { party_id: c.id, notes }, label: `Visita ${c.name}` }); notifyOk('Visita registrata'); back() }} />
    </Shell>
  }
  if (screen.name === 'doc') {
    const c = cust(screen.pid)
    return <Shell title={`${DOC_LABEL[screen.type]} · ${c.name}`} subtitle={`sezionale /${pkg.van.series}`} right={header} onBack={() => setScreen({ name: 'customer', pid: c.id })}>
      <DocFlow c={c} type={screen.type} fromOrder={screen.fromOrder} pkg={pkg} stock={stock} trip={trip}
        onSave={(body, d) => {
          enqueue({ kind: 'documento', body, label: `${DOC_LABEL[screen.type]} ${c.name}` })
          addDone(d)
          setScreen({ name: 'done', uuid: d.client_uuid })
        }} />
    </Shell>
  }
  if (screen.name === 'collect') {
    const c = cust(screen.pid)
    return <Shell title={`Incasso · ${c.name}`} right={header} onBack={() => setScreen({ name: 'customer', pid: c.id })}>
      <Collect c={c} done={log} onSave={(body, d) => { enqueue({ kind: 'incasso', body, label: `Incasso ${c.name}` }); addDone(d); notifyOk('Incasso registrato'); setScreen({ name: 'customer', pid: c.id }) }} />
    </Shell>
  }
  if (screen.name === 'done') {
    const d = log.find((x) => x.client_uuid === screen.uuid)!
    const c = cust(d.party_id)
    return <Shell title="Documento salvato" right={header} onBack={() => setScreen({ name: 'customer', pid: d.party_id })}>
      <DocDone d={d} c={c} online={online} pending={outbox.some((p) => p.body?.client_uuid === d.client_uuid)}
        onSend={(channel, to) => enqueue({ kind: 'invio', doc_uuid: d.client_uuid, body: { channel, to, client_uuid: uuid4() }, label: `Invio ${channel} ${c?.name ?? ''}` })}
        onNext={back} />
    </Shell>
  }

  return (
    <Shell title={`${pkg.van.code} · ${trip.weekday} ${fmtDate(trip.trip_date)}`} subtitle={`${pkg.agent?.name ?? ''} · ${trip.status_label}`} right={header} onBack={() => nav('/giro')}>
      <Box pb={80}>
        {errors > 0 && <Alert color="red" m="md" title="Invii non riusciti">{outbox.filter((p) => p.error).map((p, i) => <Text key={i} size="sm">{p.label}: {p.error}</Text>)}
          <Group mt="xs"><Button size="xs" variant="light" onClick={() => { setOutbox(outbox.map(({ error: _e, ...p }) => p)); setTimeout(flush, 50) }}>Riprova</Button></Group></Alert>}
        {trip.status === 'preparazione' && <Start id={id} pkg={pkg} onStarted={refresh} />}
        {tab === 'clienti' && <Customers customers={customers} onOpen={(pid) => setScreen({ name: 'customer', pid })} />}
        {tab === 'furgone' && <OnBoard pkg={pkg} stock={stock} />}
        {tab === 'documenti' && <DayLog done={log} outbox={outbox} onOpen={(uuid) => setScreen({ name: 'done', uuid })} />}
        {tab === 'rientro' && <ReturnScreen id={id} pkg={pkg} done={log} outbox={outbox} online={online} onDone={refresh} />}
      </Box>
      <Box pos="fixed" bottom={0} left={0} right={0} bg="white" p={6} style={{ borderTop: '1px solid var(--mantine-color-gray-3)', zIndex: 40 }}>
        <SegmentedControl fullWidth size="md" value={tab} onChange={setTab} data={[
          { value: 'clienti', label: <Group gap={4} justify="center"><IconUsers size={16} />Clienti</Group> },
          { value: 'furgone', label: <Group gap={4} justify="center"><IconTruck size={16} />Furgone</Group> },
          { value: 'documenti', label: <Group gap={4} justify="center"><IconFileText size={16} />Oggi</Group> },
          { value: 'rientro', label: <Group gap={4} justify="center"><IconTruckReturn size={16} />Rientro</Group> },
        ]} />
      </Box>
    </Shell>
  )
}

function Start({ id, pkg, onStarted }: { id: string; pkg: any; onStarted: () => void }) {
  const [km, setKm] = useState<number | string>('')
  return (
    <Paper withBorder m="md" p="md" radius="md">
      <Text fw={700} mb={4}>Prima di partire</Text>
      <Text size="sm" c="dimmed" mb="sm">Controlla la merce caricata, poi indica i km del furgone e parti: i documenti si possono fare solo a giro iniziato.</Text>
      <Group align="flex-end">
        <NumberInput label="Km alla partenza" size="md" value={km} onChange={setKm} min={0} style={{ flex: 1 }} />
        <Button size="md" onClick={async () => {
          try { await TV(`/giri/${id}/partenza`, { body: { km_start: km === '' ? null : Number(km) } }); notifyOk('Buon giro!'); onStarted() } catch (e) { notifyError(e) }
        }}>Parti</Button>
      </Group>
      {!pkg.items.some((i: any) => i.stock.length) && <Alert color="orange" mt="sm">Il furgone risulta vuoto: chiedi al magazzino di registrare il carico.</Alert>}
    </Paper>
  )
}

// ------------------------------------------------------------------------------------------------------ clienti

function Customers({ customers, onOpen }: { customers: any[]; onOpen: (pid: string) => void }) {
  const [q, setQ] = useState('')
  const list = customers.filter((c) => !q || `${c.name} ${c.city ?? ''}`.toLowerCase().includes(q.toLowerCase()))
  const left = customers.filter((c) => !c.visited).length
  return (
    <Stack p="md" gap="sm">
      <TextInput size="md" leftSection={<IconSearch size={18} />} placeholder="Cerca cliente" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
      <Text size="sm" c="dimmed">{left ? `${left} clienti ancora da visitare su ${customers.length}` : 'Tutti i clienti del giro sono stati visitati'}</Text>
      {list.map((c, i) => {
        const credit = c.credit
        const overLimit = credit.limit !== null && c.exposure_now > Number(credit.limit)
        const overdue = c.installments.filter((x: any) => x.overdue).reduce((a: number, x: any) => a + Number(x.residual), 0)
        return (
          <UnstyledButton key={c.id} onClick={() => onOpen(c.id)}>
            <Paper withBorder p="sm" radius="md" style={{ opacity: c.visited ? 0.7 : 1, borderLeft: `4px solid var(--mantine-color-${c.visited ? 'teal' : 'blue'}-5)` }}>
              <Group justify="space-between" wrap="nowrap">
                <div style={{ minWidth: 0 }}>
                  <Text fw={700} truncate>{i + 1}. {c.name}</Text>
                  <Text size="sm" c="dimmed" truncate>{[c.address, c.city].filter(Boolean).join(', ')}</Text>
                  <Group gap={4} mt={4}>
                    {c.visited && <Badge size="sm" color="teal" leftSection={<IconCheck size={12} />}>visitato</Badge>}
                    {c.orders.length > 0 && <Badge size="sm" color="grape">{c.orders.length} ordini da consegnare</Badge>}
                    {overdue > 0 && <Badge size="sm" color="orange">scaduto {fmtEuro(overdue)}</Badge>}
                    {(overLimit || credit.insolvent) && <Badge size="sm" color="red">{credit.policy === 'blocca' ? 'bloccato' : 'fido'}</Badge>}
                  </Group>
                  {c.stop_notes && <Text size="xs" c="dimmed" mt={4}>{c.stop_notes}</Text>}
                </div>
                <IconChevronRight color="var(--mantine-color-gray-5)" />
              </Group>
            </Paper>
          </UnstyledButton>
        )
      })}
    </Stack>
  )
}

function Customer({ c, pkg, trip, onDoc, onCollect, onOpen, onVisit }: {
  c: any; pkg: any; trip: any; onDoc: (type: string, fromOrder?: string) => void; onCollect: () => void; onOpen: (uuid: string) => void; onVisit: (notes: string) => void
}) {
  const [visitNote, setVisitNote] = useState<string | null>(null)
  const addr = [c.address, c.zip_code, c.city, c.province].filter(Boolean).join(' ')
  const credit = c.credit
  const limit = credit.limit !== null ? Number(credit.limit) : null
  const available = limit !== null ? limit - c.exposure_now : null
  const running = trip.status === 'in_corso' || trip.status === 'rientro'
  const phone = c.mobile || c.phone
  return (
    <Stack p="md" gap="sm">
      <Group gap="xs">
        {addr && <Button variant="light" leftSection={<IconMapPin size={18} />} component="a" href={`https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(addr)}`} target="_blank">Naviga</Button>}
        {phone && <Button variant="light" leftSection={<IconPhone size={18} />} component="a" href={`tel:${phone.replace(/\s/g, '')}`}>Chiama</Button>}
      </Group>
      <Paper withBorder p="sm" radius="md">
        <Group justify="space-between"><Text size="sm" c="dimmed">Esposizione</Text><Text fw={700}>{fmtEuro(c.exposure_now)}</Text></Group>
        {limit !== null && <Group justify="space-between"><Text size="sm" c="dimmed">Fido</Text><Text>{fmtEuro(limit)} · disponibile <b style={{ color: available! < 0 ? 'var(--mantine-color-red-7)' : undefined }}>{fmtEuro(available!)}</b></Text></Group>}
        {credit.insolvent && <Alert color="red" mt="xs" p="xs">Pagamenti in ritardo: {fmtEuro(credit.overdue)} scaduti da {credit.overdue_days} giorni{credit.unpaid ? `, ${credit.unpaid} insoluti` : ''}.
          {credit.policy === 'blocca' ? ' Vendita bloccata: incassa prima lo scaduto.' : ''}</Alert>}
      </Paper>
      {c.installments.length > 0 && (
        <Paper withBorder p="sm" radius="md">
          <Text fw={600} mb={4}>Da incassare</Text>
          {c.installments.map((x: any) => (
            <Group key={x.id} justify="space-between" wrap="nowrap"><Text size="sm" truncate c={x.overdue ? 'red' : undefined}>{x.description} · {fmtDate(x.due_date)}</Text><Text size="sm" fw={600}>{fmtEuro(x.residual)}</Text></Group>
          ))}
        </Paper>
      )}
      {c.orders.map((o: any) => (
        <Paper key={o.id} withBorder p="sm" radius="md" bg="grape.0">
          <Group justify="space-between"><Text fw={600}>{o.label} del {fmtDate(o.date)}</Text>
            {running && pkg.doc_kinds.some((k: any) => k.value === 'DDT') && <Button size="xs" onClick={() => onDoc(pkg.doc_kinds.some((k: any) => k.value === 'DDT') ? 'DDT' : 'FTI', o.id)}>Consegna</Button>}</Group>
          {o.lines.map((l: any) => <Text key={l.id} size="sm">{qtyFmt(l.open)} × {l.description}</Text>)}
        </Paper>
      ))}
      {!running && <Alert color="gray">{trip.status === 'preparazione' ? 'Il giro non è ancora iniziato: parti dalla schermata del giro.' : 'Il giro è chiuso.'}</Alert>}
      {running && (
        <>
          <Text fw={700} mt="xs">Nuovo documento</Text>
          <SimpleGrid cols={2} spacing="xs">
            {pkg.doc_kinds.map((k: any) => <Button key={k.value} size="lg" variant={k.value === 'DDT' ? 'filled' : 'light'} onClick={() => onDoc(k.value)}>{k.value === 'NC' ? 'Reso' : DOC_LABEL[k.value]}</Button>)}
          </SimpleGrid>
          <Group grow>
            <Button size="lg" variant="light" color="teal" leftSection={<IconCash />} onClick={onCollect}>Incassa</Button>
            <Button size="lg" variant="default" onClick={() => setVisitNote('')}>Nessun ordine</Button>
          </Group>
          {visitNote !== null && (
            <Paper withBorder p="sm"><TextInput size="md" placeholder="Nota (es. chiuso, ripassare giovedì)" value={visitNote} onChange={(e) => setVisitNote(e.currentTarget.value)} />
              <Group justify="flex-end" mt="xs"><Button onClick={() => onVisit(visitNote)}>Registra visita</Button></Group></Paper>
          )}
        </>
      )}
      {c.today.length > 0 && (
        <>
          <Text fw={700} mt="xs">Oggi con questo cliente</Text>
          {c.today.map((d: Done) => (
            <UnstyledButton key={d.client_uuid} onClick={() => d.kind === 'documento' && onOpen(d.client_uuid)}>
              <Paper withBorder p="xs"><Group justify="space-between"><Text size="sm">{d.kind === 'documento' ? (d.label ?? DOC_LABEL[d.doc_type!]) : `Incasso ${d.collection?.method}`}</Text>
                <Group gap={6}><Text size="sm" fw={600}>{fmtEuro(d.kind === 'documento' ? d.total : d.collection!.amount)}</Text>{d.synced ? <IconCheck size={16} color="teal" /> : <IconCloudUpload size={16} color="orange" />}</Group></Group></Paper>
            </UnstyledButton>
          ))}
        </>
      )}
    </Stack>
  )
}

// ------------------------------------------------------------------------------------------------------ documento

type Line = { item_id: string; variant_id: string | null; code: string; description: string; unit: string; quantity: number; price: number; discount: number
  vat: number; lot_number: string | null; serials: string; lot_managed: boolean; serial_managed: boolean; origin_line_id?: string; source: string }

function DocFlow({ c, type, fromOrder, pkg, stock, trip, onSave }: { c: any; type: string; fromOrder?: string; pkg: any; stock: Record<string, number>; trip: any; onSave: (body: any, d: Done) => void }) {
  const items: any[] = pkg.items
  const byId = useMemo(() => new Map(items.map((i) => [i.id, i])), [items])
  const maxDisc = Number(pkg.van.max_discount)
  const priceOf = (it: any, variant: string | null) => {
    const k = `${it.id}:${variant ?? ''}`
    const p = pkg.prices[c.id]?.[k] ?? pkg.prices._?.[k]
    return { price: p ? Number(p.price) : 0, source: p?.source ?? 'Nessun prezzo' }
  }
  const vatOf = (it: any) => Number(c.vat_rate ?? it.vat_rate ?? 22)
  const [lines, setLines] = useState<Line[]>(() => {
    if (!fromOrder) return []
    const o = c.orders.find((x: any) => x.id === fromOrder)
    return (o?.lines ?? []).filter((l: any) => l.item_id && byId.has(l.item_id)).map((l: any) => {
      const it = byId.get(l.item_id)
      return { item_id: it.id, variant_id: l.variant_id, code: it.code, description: l.description, unit: it.unit, quantity: Number(l.open), price: Number(l.unit_price),
        discount: Number(l.discount ?? 0), vat: vatOf(it), lot_number: null, serials: '', lot_managed: it.lot_managed, serial_managed: it.serial_managed, origin_line_id: l.id, source: o.label }
    })
  })
  const [step, setStep] = useState<'righe' | 'firma'>('righe')
  const [q, setQ] = useState('')
  const [camera, setCamera] = useState(false)
  const [sig, setSig] = useState<SignatureValue>(emptySignature())
  const [gps, setGps] = useState(true)
  const [term, setTerm] = useState<string | null>(c.payment_term_id)
  const [paid, setPaid] = useState(type === 'FTI')
  const [method, setMethod] = useState('contanti')
  const [amount, setAmount] = useState<number | string>('')
  const [checkInfo, setCheckInfo] = useState('')
  const [notes, setNotes] = useState('')
  const [pickVariant, setPickVariant] = useState<any>(null)
  const anyItem = type === 'ORC' || type === 'NC'

  const add = (it: any, variant: string | null = null) => {
    if (it.has_variants && !variant) { setPickVariant(it); return }
    const { price, source } = priceOf(it, variant)
    setLines((ls) => {
      const i = ls.findIndex((l) => l.item_id === it.id && l.variant_id === variant && !l.origin_line_id && !l.lot_number)
      if (i >= 0) return ls.map((l, n) => (n === i ? { ...l, quantity: l.quantity + 1 } : l))
      const vname = variant ? it.variants.find((v: any) => v.id === variant)?.label : null
      return [...ls, { item_id: it.id, variant_id: variant, code: it.code, description: it.description + (vname ? ` · ${vname}` : ''), unit: it.unit, quantity: 1, price,
        discount: 0, vat: vatOf(it), lot_number: null, serials: '', lot_managed: it.lot_managed, serial_managed: it.serial_managed, source }]
    })
    setQ('')
  }
  const onCode = (code: string) => {
    for (const it of items) {
      const b = it.barcodes.find((x: any) => x.barcode === code)
      if (b || it.code === code) { beep(true); add(it, b?.variant_id ?? null); setCamera(false); return }
    }
    beep(false)
  }
  const upd = (i: number, patch: Partial<Line>) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, ...patch } : l)))
  const net = (l: Line) => l.price * (1 - (l.discount || 0) / 100)
  const groups: Record<string, number> = {}
  lines.forEach((l) => { groups[l.vat] = (groups[l.vat] ?? 0) + r2(net(l) * l.quantity) })
  const taxable = r2(Object.values(groups).reduce((a, b) => a + b, 0))
  const vat = r2(Object.entries(groups).reduce((a, [r, v]) => a + r2((v * Number(r)) / 100), 0))
  const total = r2(taxable + vat)
  // controlli sul dispositivo: giacenza a bordo, sconto massimo, fido
  const shortage = type === 'ORC' || type === 'NC' ? [] : lines.filter((l) => {
    const used = lines.filter((x) => x.item_id === l.item_id && x.variant_id === l.variant_id).reduce((a, x) => a + x.quantity, 0)
    return byId.get(l.item_id)?.stock_managed && used > (stock[skey(l.item_id, l.variant_id)] ?? 0)
  })
  const discOver = type !== 'NC' && lines.some((l) => l.discount > maxDisc)
  const credit = c.credit
  const limit = credit.limit !== null ? Number(credit.limit) : null
  const adds = type === 'NC' ? 0 : total
  const over = ['DDT', 'FTI', 'ORC'].includes(type) && ((limit !== null && c.exposure_now + adds > limit) || credit.insolvent)
  const blocked = over && credit.policy === 'blocca' && !(paid && type === 'FTI' && Number(amount || total) >= total && !credit.insolvent)
  const warn = over ? (credit.insolvent ? `${c.name} ha pagamenti in ritardo (${fmtEuro(credit.overdue)} scaduti)` : `Fido superato: esposizione ${fmtEuro(c.exposure_now + adds)} su ${fmtEuro(limit!)}`) : null
  const serialsOk = lines.every((l) => !l.serial_managed || l.serials.split(/[\s,;]+/).filter(Boolean).length === l.quantity)
  const found = q.length >= 1 ? items.filter((i) => `${i.code} ${i.description}`.toLowerCase().includes(q.toLowerCase())).slice(0, 30) : []
  const onVan = items.filter((i) => i.stock.length || anyItem)

  async function confirm() {
    const uuid = uuid4()
    let pos: any = {}
    if (gps && 'geolocation' in navigator) {
      pos = await new Promise((res) => navigator.geolocation.getCurrentPosition((p) => res({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy }), () => res({}), { timeout: 6000, maximumAge: 120000 }))
    }
    const collected = paid ? r2(Number(amount === '' ? total : amount)) : 0
    const body = {
      client_uuid: uuid, doc_type: type, party_id: c.id, doc_date: trip.trip_date, payment_term_id: term, notes: notes || null,
      lines: lines.map((l) => ({ item_id: l.item_id, variant_id: l.variant_id, description: l.description, quantity: String(l.quantity), unit_price: l.price.toFixed(4),
        discount: l.discount ? String(l.discount) : null, lot_number: l.lot_number, serials: l.serial_managed ? l.serials.split(/[\s,;]+/).filter(Boolean) : null,
        origin_line_id: l.origin_line_id ?? null, price_source: l.source })),
      delivery: sig.signature_png ? { signer_name: sig.signer_name, signature_png: sig.signature_png, signed_at: sig.signed_at ?? new Date().toISOString(), ...pos } : null,
      collection: collected > 0 ? { method, amount: collected.toFixed(2), check_info: method === 'assegno' ? checkInfo || null : null } : null,
      credit_warning: warn,
    }
    onSave(body, { client_uuid: uuid, kind: 'documento', doc_type: type, party_id: c.id, party_name: c.name, total, at: new Date().toISOString(),
      lines: lines.map((l) => ({ item_id: l.item_id, variant_id: l.variant_id, quantity: l.quantity })), collection: collected > 0 ? { method, amount: collected } : undefined })
  }

  if (camera) return <CameraScanner onCode={onCode} onClose={() => setCamera(false)} />
  if (pickVariant) {
    return (
      <Stack p="md">
        <Text fw={700}>{pickVariant.code} · {pickVariant.description}</Text>
        {pickVariant.variants.map((v: any) => (
          <Button key={v.id} size="lg" variant="light" justify="space-between" rightSection={!anyItem && <Badge>{qtyFmt(stock[skey(pickVariant.id, v.id)] ?? 0)}</Badge>}
            onClick={() => { const it = pickVariant; setPickVariant(null); add(it, v.id) }}>{v.label}</Button>
        ))}
        <Button variant="subtle" onClick={() => setPickVariant(null)}>Annulla</Button>
      </Stack>
    )
  }
  if (step === 'firma') {
    return (
      <Stack px="md" pt="md" pb={100}>
        <Paper withBorder p="sm" radius="md">
          <Group justify="space-between"><Text>{lines.length} righe</Text><Text fw={800} size="xl">{fmtEuro(type === 'NC' ? -total : total)}</Text></Group>
          <Text size="xs" c="dimmed">Imponibile {fmtEuro(taxable)} · IVA {fmtEuro(vat)}</Text>
        </Paper>
        {type !== 'NC' && <Select size="md" label="Pagamento" data={pkg.payment_terms.map((t: any) => ({ value: t.id, label: t.description }))} value={term} onChange={setTerm} />}
        {type !== 'NC' && type !== 'ORC' && (
          <Paper withBorder p="sm" radius="md">
            <Switch size="md" label={type === 'FTI' ? 'Incassato adesso' : 'Acconto incassato adesso'} checked={paid} onChange={(e) => setPaid(e.currentTarget.checked)} />
            {paid && (
              <Stack gap="xs" mt="sm">
                <SegmentedControl fullWidth value={method} onChange={setMethod} data={pkg.methods} />
                <NumberInput size="md" label="Importo" value={amount === '' ? total : amount} onChange={setAmount} decimalScale={2} decimalSeparator="," thousandSeparator="." min={0} suffix=" €" />
                {method === 'assegno' && <TextInput size="md" label="Banca e numero dell'assegno" value={checkInfo} onChange={(e) => setCheckInfo(e.currentTarget.value)} />}
              </Stack>
            )}
          </Paper>
        )}
        <Paper withBorder p="sm" radius="md">
          <SignaturePad label={type === 'NC' ? 'Firma di chi consegna il reso' : 'Firma del cliente per ricevuta'} value={sig} onChange={setSig} />
          <Checkbox mt="sm" label="Registra la posizione della consegna" checked={gps} onChange={(e) => setGps(e.currentTarget.checked)} />
        </Paper>
        <Textarea label="Note" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} autosize minRows={1} />
        {warn && <Alert color={blocked ? 'red' : 'orange'}>{warn}{blocked ? '. Il cliente è bloccato: incassa il totale o chiama l\'ufficio.' : ''}</Alert>}
        <Box pos="fixed" bottom={0} left={0} right={0} p="sm" bg="white" style={{ borderTop: '1px solid var(--mantine-color-gray-3)' }}>
          <Group grow>
            <Button size="lg" variant="default" onClick={() => setStep('righe')}>Indietro</Button>
            <Button size="lg" leftSection={<IconCheck />} disabled={blocked || (type !== 'ORC' && !signatureReady(sig))} onClick={confirm}>Conferma</Button>
          </Group>
          {type !== 'ORC' && !signatureReady(sig) && <Text size="xs" c="dimmed" ta="center" mt={4}>Serve la firma e il nome di chi firma</Text>}
        </Box>
      </Stack>
    )
  }
  return (
    <Stack px="md" pt="md" pb={110} gap="sm">
      <Group gap="xs" wrap="nowrap">
        <TextInput size="md" style={{ flex: 1 }} leftSection={<IconSearch size={18} />} placeholder={anyItem ? 'Cerca articolo' : 'Cerca tra la merce a bordo'} value={q} onChange={(e) => setQ(e.currentTarget.value)} />
        <ActionIcon size={42} variant="light" onClick={() => setCamera(true)}><IconBarcode /></ActionIcon>
      </Group>
      {(q ? found : lines.length ? [] : onVan.slice(0, 40)).map((it) => {
        const avail = it.has_variants ? null : stock[skey(it.id, null)] ?? 0
        return (
          <UnstyledButton key={it.id} onClick={() => add(it)}>
            <Paper withBorder p="xs" radius="md">
              <Group justify="space-between" wrap="nowrap">
                <div style={{ minWidth: 0 }}><Text size="sm" fw={600} truncate>{it.description}</Text><Text size="xs" c="dimmed">{it.code} · {fmtEuro(priceOf(it, null).price)}</Text></div>
                {!anyItem && avail !== null && <Badge color={avail > 0 ? 'blue' : 'red'} variant="light">{qtyFmt(avail)} {it.unit}</Badge>}
                <IconPlus size={18} />
              </Group>
            </Paper>
          </UnstyledButton>
        )
      })}
      {lines.length > 0 && <Divider label="Righe del documento" labelPosition="left" />}
      {lines.map((l, i) => {
        const it = byId.get(l.item_id)
        const short = shortage.some((s) => s === l)
        return (
          <Paper key={i} withBorder p="sm" radius="md" style={short ? { borderColor: 'var(--mantine-color-red-5)' } : undefined}>
            <Group justify="space-between" wrap="nowrap" align="flex-start">
              <div style={{ minWidth: 0 }}><Text fw={600} size="sm">{l.description}</Text>
                <Text size="xs" c="dimmed">{l.code} · {l.source}{l.origin_line_id ? ' · da ordine' : ''}</Text></div>
              <ActionIcon variant="subtle" color="red" onClick={() => setLines(lines.filter((_, n) => n !== i))}><IconTrash size={18} /></ActionIcon>
            </Group>
            <Group mt="xs" gap="xs" wrap="nowrap">
              <ActionIcon size={40} variant="light" onClick={() => upd(i, { quantity: Math.max(1, l.quantity - 1) })}><IconMinus /></ActionIcon>
              <NumberInput size="md" w={90} min={0} value={l.quantity} onChange={(v) => upd(i, { quantity: Number(v) || 0 })} hideControls styles={{ input: { textAlign: 'center' } }} />
              <ActionIcon size={40} variant="light" onClick={() => upd(i, { quantity: l.quantity + 1 })}><IconPlus /></ActionIcon>
              <NumberInput size="md" w={86} label={undefined} placeholder="sc. %" min={0} max={type === 'NC' ? 100 : maxDisc} value={l.discount || ''} onChange={(v) => upd(i, { discount: Number(v) || 0 })}
                suffix="%" hideControls error={type !== 'NC' && l.discount > maxDisc} />
              <Text fw={700} style={{ marginLeft: 'auto' }}>{fmtEuro(r2(net(l) * l.quantity))}</Text>
            </Group>
            {l.lot_managed && type !== 'ORC' && (
              <Select mt="xs" size="sm" placeholder={type === 'NC' ? 'Lotto reso' : 'Lotto: automatico (prima quelli che scadono prima)'} clearable searchable
                data={(it?.stock ?? []).filter((s: any) => s.lot_number).map((s: any) => ({ value: s.lot_number, label: `${s.lot_number}${s.expiry_date ? ' · scad. ' + fmtDate(s.expiry_date) : ''} · ${qtyFmt(s.quantity)}` }))}
                value={l.lot_number} onChange={(v) => upd(i, { lot_number: v })} />
            )}
            {l.serial_managed && type !== 'ORC' && <TextInput mt="xs" size="sm" placeholder={`${l.quantity} matricole separate da spazio`} value={l.serials} onChange={(e) => upd(i, { serials: e.currentTarget.value.toUpperCase() })} />}
            {short && <Text size="xs" c="red" mt={4}>A bordo ne risultano {qtyFmt(stock[skey(l.item_id, l.variant_id)] ?? 0)}</Text>}
          </Paper>
        )
      })}
      <Box pos="fixed" bottom={0} left={0} right={0} p="sm" bg="white" style={{ borderTop: '1px solid var(--mantine-color-gray-3)' }}>
        <Group justify="space-between" mb={6}><Text size="sm" c="dimmed">Totale IVA inclusa</Text><Text fw={800} size="lg">{fmtEuro(total)}</Text></Group>
        {discOver && <Text size="xs" c="red">Sconto massimo consentito: {qtyFmt(maxDisc)}%</Text>}
        {!serialsOk && <Text size="xs" c="red">Indica una matricola per ogni pezzo</Text>}
        <Button fullWidth size="lg" disabled={!lines.length || discOver || shortage.length > 0 || !serialsOk || lines.some((l) => l.quantity <= 0)} onClick={() => setStep('firma')}>
          {type === 'ORC' ? 'Avanti' : 'Avanti: firma del cliente'}
        </Button>
      </Box>
    </Stack>
  )
}

function DocDone({ d, c, online, pending, onSend, onNext }: { d: Done; c: any; online: boolean; pending: boolean; onSend: (channel: string, to: string | null) => void; onNext: () => void }) {
  const [email, setEmail] = useState<string>(c?.email ?? '')
  const [busy, setBusy] = useState(false)
  async function whatsapp() {
    if (!d.server_id) return
    setBusy(true)
    try {
      const r = await TV(`/documenti/${d.server_id}/invia`, { body: { channel: 'whatsapp', to: c?.mobile || c?.phone || null } })
      window.open(r.url, '_blank')
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  return (
    <Stack p="md">
      <Center><IconCheck size={56} color="var(--mantine-color-teal-6)" /></Center>
      <Title order={3} ta="center">{d.label ?? DOC_LABEL[d.doc_type!]} · {fmtEuro(d.total)}</Title>
      <Text ta="center" c="dimmed">{d.party_name}</Text>
      <Text ta="center" size="sm">{d.synced ? 'Registrato in ufficio' : pending ? (online ? 'Invio in corso…' : 'Salvato sul dispositivo: parte appena torna la rete') : 'In attesa'}</Text>
      {d.collection && <Alert color="teal">Incassati {fmtEuro(d.collection.amount)} ({d.collection.method})</Alert>}
      <Paper withBorder p="md" radius="md">
        <Text fw={700} mb="xs">Manda il documento firmato al cliente</Text>
        <Group align="flex-end" wrap="nowrap">
          <TextInput size="md" style={{ flex: 1 }} label="Email" value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
          <Button size="md" leftSection={<IconMail size={18} />} disabled={!email.includes('@')} onClick={() => { onSend('email', email); notifyOk(online ? 'Email in invio' : 'Email in coda: parte appena torna la rete') }}>Invia</Button>
        </Group>
        <Button mt="sm" fullWidth size="md" color="green" leftSection={<IconBrandWhatsapp />} disabled={!d.server_id || !online} loading={busy} onClick={whatsapp}>WhatsApp</Button>
        {(!d.server_id || !online) && <Text size="xs" c="dimmed" mt={4}>WhatsApp e PDF sono disponibili quando il documento è arrivato in ufficio.</Text>}
        {d.sent?.length ? <Text size="xs" c="teal" mt={4}>Già inviato: {d.sent.join(', ')}</Text> : null}
      </Paper>
      <Group grow>
        <Button size="md" variant="light" leftSection={<IconFileTypePdf />} disabled={!d.server_id || !online} onClick={() => openPdf(d.server_id!).catch(notifyError)}>PDF / stampa</Button>
        <Button size="md" onClick={onNext}>Prossimo cliente</Button>
      </Group>
    </Stack>
  )
}

// ------------------------------------------------------------------------------------------------------ incasso

function Collect({ c, done, onSave }: { c: any; done: Done[]; onSave: (body: any, d: Done) => void }) {
  const already = done.filter((d) => d.party_id === c.id && d.kind === 'incasso').reduce((a, d) => a + (d.collection?.amount ?? 0), 0)
  const [sel, setSel] = useState<string[]>(c.installments.filter((x: any) => x.overdue).map((x: any) => x.id))
  const selTotal = c.installments.filter((x: any) => sel.includes(x.id)).reduce((a: number, x: any) => a + Number(x.residual), 0)
  const [amount, setAmount] = useState<number | string>('')
  const [method, setMethod] = useState('contanti')
  const [checkInfo, setCheckInfo] = useState('')
  const [sig, setSig] = useState<SignatureValue>(emptySignature())
  const value = Number(amount === '' ? selTotal : amount)
  return (
    <Stack px="md" pt="md" pb={90}>
      {already > 0 && <Alert color="gray">Già incassati oggi da questo cliente: {fmtEuro(already)}</Alert>}
      {c.installments.length ? (
        <Paper withBorder p="sm" radius="md">
          <Text fw={600} mb="xs">Scadenze da incassare</Text>
          <Checkbox.Group value={sel} onChange={setSel}>
            <Stack gap={6}>{c.installments.map((x: any) => (
              <Checkbox key={x.id} value={x.id} size="md" label={<Group justify="space-between" w="100%" wrap="nowrap" gap="xs"><Text size="sm" c={x.overdue ? 'red' : undefined}>{x.description} · {fmtDate(x.due_date)}</Text><Text size="sm" fw={600}>{fmtEuro(x.residual)}</Text></Group>}
                styles={{ body: { width: '100%' }, labelWrapper: { width: '100%' } }} />))}</Stack>
          </Checkbox.Group>
        </Paper>
      ) : <Alert color="gray">Nessuna scadenza aperta: l'importo resta come acconto da abbinare in ufficio.</Alert>}
      <SegmentedControl fullWidth size="md" value={method} onChange={setMethod} data={[{ value: 'contanti', label: 'Contanti' }, { value: 'assegno', label: 'Assegno' }, { value: 'pos', label: 'POS' }]} />
      <NumberInput size="lg" label="Importo incassato" value={amount === '' ? (selTotal ? r2(selTotal) : '') : amount} onChange={setAmount} decimalScale={2} decimalSeparator="," thousandSeparator="." min={0} suffix=" €" />
      {method === 'assegno' && <TextInput size="md" label="Banca e numero dell'assegno" value={checkInfo} onChange={(e) => setCheckInfo(e.currentTarget.value)} />}
      <Paper withBorder p="sm"><SignaturePad label="Firma del cliente (facoltativa, per la ricevuta)" value={sig} onChange={setSig} height={140} /></Paper>
      <Box pos="fixed" bottom={0} left={0} right={0} p="sm" bg="white" style={{ borderTop: '1px solid var(--mantine-color-gray-3)' }}>
        <Button fullWidth size="lg" color="teal" disabled={!(value > 0)} onClick={() => {
          const uuid = uuid4()
          onSave({ client_uuid: uuid, party_id: c.id, method, amount: r2(value).toFixed(2), installment_ids: sel.length ? sel : null, check_info: method === 'assegno' ? checkInfo || null : null,
            signature: sig.signature_png ? { ...sig, signed_at: sig.signed_at ?? new Date().toISOString() } : null },
          { client_uuid: uuid, kind: 'incasso', party_id: c.id, party_name: c.name, total: 0, at: new Date().toISOString(), collection: { method, amount: r2(value) } })
        }}>Registra incasso di {fmtEuro(value || 0)}</Button>
      </Box>
    </Stack>
  )
}

// ------------------------------------------------------------------------------------------------------ furgone, giornata, rientro

function OnBoard({ pkg, stock }: { pkg: any; stock: Record<string, number> }) {
  const [q, setQ] = useState('')
  const rows = pkg.items.flatMap((it: any) => (it.has_variants ? it.variants.map((v: any) => ({ it, v })) : [{ it, v: null }]))
    .map((r: any) => ({ ...r, qty: stock[skey(r.it.id, r.v?.id ?? null)] ?? 0 }))
    .filter((r: any) => r.qty !== 0 || r.it.stock.length)
    .filter((r: any) => !q || `${r.it.code} ${r.it.description}`.toLowerCase().includes(q.toLowerCase()))
  return (
    <Stack p="md" gap="xs">
      <TextInput size="md" leftSection={<IconSearch size={18} />} placeholder="Cerca" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
      <Text size="sm" c="dimmed">Merce a bordo, aggiornata con le vendite e i resi di oggi</Text>
      {rows.map((r: any, i: number) => (
        <Paper key={i} withBorder p="xs">
          <Group justify="space-between" wrap="nowrap">
            <div style={{ minWidth: 0 }}><Text size="sm" fw={600} truncate>{r.it.description}{r.v ? ` · ${r.v.label}` : ''}</Text>
              <Text size="xs" c="dimmed">{r.it.code}{r.it.stock.filter((s: any) => s.lot_number && (s.variant_id ?? null) === (r.v?.id ?? null)).map((s: any) => ` · ${s.lot_number}${s.expiry_date ? ' ' + fmtDate(s.expiry_date) : ''}`).join('')}</Text></div>
            <Badge size="lg" color={r.qty > 0 ? 'blue' : 'red'} variant="light">{qtyFmt(r.qty)} {r.it.unit}</Badge>
          </Group>
        </Paper>
      ))}
      {!rows.length && <Text c="dimmed" ta="center" py="lg">Furgone vuoto</Text>}
    </Stack>
  )
}

function DayLog({ done, outbox, onOpen }: { done: Done[]; outbox: Pending[]; onOpen: (uuid: string) => void }) {
  const byMethod: Record<string, number> = {}
  done.forEach((d) => { if (d.collection) byMethod[d.collection.method] = (byMethod[d.collection.method] ?? 0) + d.collection.amount })
  const sold = done.filter((d) => d.kind === 'documento' && ['DDT', 'FTI'].includes(d.doc_type!)).reduce((a, d) => a + d.total, 0)
  return (
    <Stack p="md" gap="xs">
      <Group grow>
        <Paper withBorder p="sm"><Text size="xs" c="dimmed">Venduto (IVA incl.)</Text><Text fw={800}>{fmtEuro(sold)}</Text></Paper>
        <Paper withBorder p="sm"><Text size="xs" c="dimmed">Incassato</Text><Text fw={800}>{fmtEuro(Object.values(byMethod).reduce((a, b) => a + b, 0))}</Text>
          <Text size="xs" c="dimmed">{Object.entries(byMethod).map(([m, v]) => `${m} ${fmtEuro(v)}`).join(' · ')}</Text></Paper>
      </Group>
      {[...done].reverse().map((d) => (
        <UnstyledButton key={d.client_uuid} onClick={() => d.kind === 'documento' && onOpen(d.client_uuid)}>
          <Paper withBorder p="xs">
            <Group justify="space-between" wrap="nowrap">
              <div style={{ minWidth: 0 }}><Text size="sm" fw={600} truncate>{d.kind === 'documento' ? (d.label ?? DOC_LABEL[d.doc_type!]) : `Incasso (${d.collection?.method})`} · {d.party_name}</Text>
                <Text size="xs" c="dimmed">{new Date(d.at).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}{d.sent?.length ? ` · inviato ${d.sent.join(', ')}` : ''}</Text></div>
              <Group gap={6} wrap="nowrap"><Text size="sm" fw={700}>{fmtEuro(d.kind === 'documento' ? (d.doc_type === 'NC' ? -d.total : d.total) : d.collection!.amount)}</Text>
                {d.synced ? <IconCheck size={16} color="var(--mantine-color-teal-6)" /> : outbox.some((p) => p.body?.client_uuid === d.client_uuid && p.error) ? <Badge color="red" size="xs">errore</Badge> : <IconCloudUpload size={16} color="var(--mantine-color-orange-6)" />}</Group>
            </Group>
          </Paper>
        </UnstyledButton>
      ))}
      {!done.length && <Text c="dimmed" ta="center" py="lg">Ancora nessun documento oggi</Text>}
    </Stack>
  )
}

function ReturnScreen({ id, pkg, done, outbox, online, onDone }: { id: string; pkg: any; done: Done[]; outbox: Pending[]; online: boolean; onDone: () => void }) {
  const trip = pkg.trip
  const byMethod: Record<string, number> = {}
  done.forEach((d) => { if (d.collection) byMethod[d.collection.method] = (byMethod[d.collection.method] ?? 0) + d.collection.amount })
  const [km, setKm] = useState<number | string>('')
  const [cash, setCash] = useState<Record<string, number | string>>({ contanti: r2(byMethod.contanti ?? 0), assegno: r2(byMethod.assegno ?? 0) })
  const [notes, setNotes] = useState('')
  const [sig, setSig] = useState<SignatureValue>(emptySignature(pkg.agent?.name ?? ''))
  const [busy, setBusy] = useState(false)
  if (trip.status === 'rientro' || trip.status === 'chiuso') {
    return (
      <Stack p="md">
        <Alert color={trip.status === 'chiuso' ? 'teal' : 'orange'} title={trip.status === 'chiuso' ? 'Giro chiuso' : 'Rientro dichiarato'}>
          {trip.status === 'chiuso' ? 'Il magazziniere ha verificato la merce.' : 'Ora il magazziniere conta la merce sul furgone.'}</Alert>
        <Button size="lg" leftSection={<IconPrinter />} onClick={() => window.open(`/stampa/giro/${id}/merce`, '_blank')}>Stampa merce rimasta</Button>
        {trip.status === 'chiuso' && <Button size="lg" variant="light" leftSection={<IconPrinter />} onClick={() => window.open(`/stampa/giro/${id}/rientro`, '_blank')}>Documento di rientro firmato</Button>}
      </Stack>
    )
  }
  if (trip.status !== 'in_corso') return <Alert m="md" color="gray">Il giro non è ancora iniziato.</Alert>
  const blocked = outbox.length > 0 || !online
  return (
    <Stack px="md" pt="md" pb={170}>
      <Text size="sm" c="dimmed">A fine giro dichiara km e soldi da consegnare. Poi stampa la merce rimasta sul mezzo: il magazziniere la conta e firma.</Text>
      {outbox.length > 0 && <Alert color="orange">Ci sono {outbox.length} invii in coda: aspetta che partano (serve la rete) prima di rientrare.</Alert>}
      {!online && <Alert color="orange">Senza rete: il rientro si dichiara quando torna la copertura.</Alert>}
      <NumberInput size="md" label="Km al rientro" value={km} onChange={setKm} min={trip.km_start ?? 0} description={trip.km_start ? `Partito con ${trip.km_start} km` : undefined} />
      <Group grow>
        <NumberInput size="md" label="Contanti da consegnare" value={cash.contanti} onChange={(v) => setCash({ ...cash, contanti: v })} decimalScale={2} decimalSeparator="," thousandSeparator="." min={0} suffix=" €" description={`incassati ${fmtEuro(byMethod.contanti ?? 0)}`} />
        <NumberInput size="md" label="Assegni da consegnare" value={cash.assegno} onChange={(v) => setCash({ ...cash, assegno: v })} decimalScale={2} decimalSeparator="," thousandSeparator="." min={0} suffix=" €" description={`incassati ${fmtEuro(byMethod.assegno ?? 0)}`} />
      </Group>
      <Textarea label="Note per l'ufficio" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} autosize minRows={2} />
      <Paper withBorder p="sm"><SignaturePad label="La tua firma" nameLabel="Nome" value={sig} onChange={setSig} height={140} /></Paper>
      <Box pos="fixed" bottom={64} left={0} right={0} p="sm" bg="white" style={{ borderTop: '1px solid var(--mantine-color-gray-3)', zIndex: 41 }}>
        <Button fullWidth size="lg" color="orange" leftSection={<IconTruckReturn />} loading={busy} disabled={blocked || !signatureReady(sig)} onClick={async () => {
          setBusy(true)
          try {
            await TV(`/giri/${id}/rientro`, { body: { km_end: km === '' ? null : Number(km), notes: notes || null,
              cash: Object.fromEntries(Object.entries(cash).filter(([, v]) => v !== '').map(([k, v]) => [k, String(v)])),
              signature: { ...sig, signed_at: new Date().toISOString() } } })
            notifyOk('Rientro dichiarato')
            onDone()
            window.open(`/stampa/giro/${id}/merce`, '_blank')
          } catch (e) { notifyError(e) } finally { setBusy(false) }
        }}>Dichiara il rientro</Button>
      </Box>
    </Stack>
  )
}

