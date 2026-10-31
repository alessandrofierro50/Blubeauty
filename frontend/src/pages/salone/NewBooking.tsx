// Nuovo appuntamento a passi guidati (modalità semplice): Per chi? → Cosa? → Con chi? → Quando? → Conferma.
import { Badge, Box, Button, Checkbox, Group, Paper, SimpleGrid, Stack, Stepper, Text, TextInput, ThemeIcon, Title, UnstyledButton } from '@mantine/core'
import { IconArrowLeft, IconBrandWhatsapp, IconCheck, IconSearch, IconUserPlus } from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { appApi, fmtEuro, isoDate } from '../../api'
import { notifyError } from '../../components'
import type { Service, Staff } from '../agenda/lib'

const choice = { radius: 'lg' as const, p: 'md' as const, withBorder: true }

export default function NewBooking() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [step, setStep] = useState(params.get('cliente') ? 1 : 0)
  const [q, setQ] = useState('')
  const [clients, setClients] = useState<any[]>([])
  const [client, setClient] = useState<any>(params.get('cliente') ? { id: params.get('cliente') } : null)
  const [creating, setCreating] = useState(false)
  const [nc, setNc] = useState({ first_name: '', last_name: '', mobile: '', marketing: true })
  const [services, setServices] = useState<Service[]>([])
  const [staff, setStaff] = useState<Staff[]>([])
  const [cats, setCats] = useState<any[]>([])
  const [service, setService] = useState<Service | null>(null)
  const [who, setWho] = useState<string | null>(null)
  const [day, setDay] = useState(isoDate(new Date()))
  const [slots, setSlots] = useState<any[] | null>(null)
  const [time, setTime] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<any>(null)

  useEffect(() => {
    Promise.all([appApi('/api/agenda/servizi'), appApi('/api/agenda/operatori'), appApi('/api/agenda/categorie')])
      .then(([a, b, c]) => { setServices(a.filter((x: Service) => x.active)); setStaff(b.filter((x: Staff) => x.active)); setCats(c) }).catch(notifyError)
    if (params.get('cliente')) appApi(`/api/agenda/clienti/${params.get('cliente')}`).then(setClient).catch(() => {})
  }, [])
  useEffect(() => {
    const t = setTimeout(() => appApi(`/api/agenda/clienti?limit=12&q=${encodeURIComponent(q)}`).then(setClients).catch(() => {}), 200)
    return () => clearTimeout(t)
  }, [q])
  useEffect(() => {
    if (step !== 3 || !service) return
    setSlots(null)
    appApi(`/api/agenda/disponibilita?service_id=${service.id}&day=${day}${who ? `&staff_id=${who}` : ''}`).then(setSlots).catch(notifyError)
  }, [step, day, who, service?.id])
  const days = useMemo(() => Array.from({ length: 14 }, (_, i) => { const d = new Date(); d.setDate(d.getDate() + i); return d }), [])
  const grouped = useMemo(() => {
    const m = new Map<string, Service[]>()
    services.forEach((s) => { const c = cats.find((x) => x.id === s.category_id)?.name ?? 'Altri servizi'; m.set(c, [...(m.get(c) ?? []), s]) })
    return [...m.entries()]
  }, [services, cats])

  const confirm = async () => {
    setBusy(true)
    try {
      let pid = client?.id
      if (!pid) pid = (await appApi('/api/agenda/clienti', { body: { ...nc, privacy: true } })).id
      const a = await appApi('/api/agenda/appuntamenti', { body: { party_id: pid, day, time, channel: 'telefono', items: [{ service_id: service!.id, staff_id: who }] } })
      setDone(a)
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }

  if (done) {
    return (
      <Stack align="center" ta="center" maw={560} mx="auto" mt="xl" gap="lg">
        <ThemeIcon size={96} radius={96} color="green" variant="light"><IconCheck size={56} /></ThemeIcon>
        <Title order={1}>Fatto!</Title>
        <Text fz="xl"><b>{done.client}</b><br />{service?.name} · {new Date(done.starts_at).toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' })} alle {time}</Text>
        {done.messages?.length > 0 && <Badge size="xl" color="green" variant="light" leftSection={<IconBrandWhatsapp size={18} />}>Conferma inviata su WhatsApp</Badge>}
        <Group>
          <Button size="xl" radius="xl" onClick={() => { setDone(null); setStep(0); setClient(null); setService(null); setTime(null); setNc({ first_name: '', last_name: '', mobile: '', marketing: true }) }}>Un altro appuntamento</Button>
          <Button size="xl" radius="xl" variant="default" onClick={() => nav('/')}>Torna a Oggi</Button>
        </Group>
      </Stack>
    )
  }

  const back = () => (step === 0 ? nav('/') : setStep(step - 1))
  const clientName = client ? (client.name ?? '') : `${nc.last_name} ${nc.first_name}`.trim()
  return (
    <Stack maw={900} gap="lg">
      <Group>
        <Button variant="subtle" size="lg" leftSection={<IconArrowLeft />} onClick={back}>{step === 0 ? 'Annulla' : 'Indietro'}</Button>
        <Title order={1} fz={30}>Nuovo appuntamento</Title>
      </Group>
      <Stepper active={step} size="lg" allowNextStepsSelect={false}>
        <Stepper.Step label="Per chi?" description={clientName || undefined} />
        <Stepper.Step label="Cosa?" description={service?.name} />
        <Stepper.Step label="Con chi?" description={who ? staff.find((s) => s.id === who)?.first_name : step > 2 ? 'La prima libera' : undefined} />
        <Stepper.Step label="Quando?" description={time ?? undefined} />
      </Stepper>

      {step === 0 && (
        <Stack>
          {!creating ? <>
            <TextInput size="xl" radius="xl" placeholder="Scrivi il nome o il cellulare" leftSection={<IconSearch />} value={q} onChange={(e) => setQ(e.target.value)} autoFocus data-testid="cerca-cliente" />
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              {clients.map((c) => (
                <UnstyledButton key={c.id} onClick={() => { setClient(c); setStep(1) }}>
                  <Paper {...choice}><Text fz="xl" fw={700}>{c.name}</Text><Text c="dimmed">{c.mobile ?? 'senza cellulare'}{c.loyalty_points ? ` · ${c.loyalty_points} punti` : ''}</Text></Paper>
                </UnstyledButton>
              ))}
            </SimpleGrid>
            <Button size="xl" radius="xl" variant="light" leftSection={<IconUserPlus />} onClick={() => setCreating(true)}>È una cliente nuova</Button>
          </> : (
            <Paper {...choice} p="lg">
              <Stack>
                <Title order={3}>Cliente nuova</Title>
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <TextInput size="xl" label="Nome" value={nc.first_name} onChange={(e) => setNc({ ...nc, first_name: e.target.value })} />
                  <TextInput size="xl" label="Cognome" value={nc.last_name} onChange={(e) => setNc({ ...nc, last_name: e.target.value })} />
                </SimpleGrid>
                <TextInput size="xl" label="Cellulare (per la conferma su WhatsApp)" inputMode="tel" value={nc.mobile} onChange={(e) => setNc({ ...nc, mobile: e.target.value })} />
                <Checkbox size="lg" label="Vuole ricevere offerte su WhatsApp" checked={nc.marketing} onChange={(e) => setNc({ ...nc, marketing: e.target.checked })} />
                <Button size="xl" radius="xl" disabled={!nc.first_name || !nc.last_name} onClick={() => { setClient(null); setStep(1) }}>Avanti</Button>
              </Stack>
            </Paper>
          )}
        </Stack>
      )}

      {step === 1 && (
        <Stack>
          {grouped.map(([cat, list]) => (
            <div key={cat}>
              <Text fw={700} c="dimmed" tt="uppercase" mb={6}>{cat}</Text>
              <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
                {list.map((s) => (
                  <UnstyledButton key={s.id} onClick={() => { setService(s); setWho(null); setTime(null); setStep(2) }} data-testid="servizio">
                    <Paper {...choice}><Text fz="xl" fw={700}>{s.name}</Text><Text c="dimmed" fz="lg">{s.duration_min} minuti · {fmtEuro(s.price)}</Text></Paper>
                  </UnstyledButton>
                ))}
              </SimpleGrid>
            </div>
          ))}
        </Stack>
      )}

      {step === 2 && service && (
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <UnstyledButton onClick={() => { setWho(null); setStep(3) }}>
            <Paper {...choice} ta="center" p="lg"><Box mx="auto" w={64} h={64} bg="#2340a8" c="white" style={{ borderRadius: '50%', display: 'grid', placeItems: 'center', fontSize: 28 }}>★</Box>
              <Text fz="lg" fw={700} mt="sm">La prima libera</Text></Paper>
          </UnstyledButton>
          {staff.filter((s) => service.staff_ids.includes(s.id)).map((s) => (
            <UnstyledButton key={s.id} onClick={() => { setWho(s.id); setStep(3) }} data-testid="operatore">
              <Paper {...choice} ta="center" p="lg"><Box mx="auto" w={64} h={64} bg={s.color} c="white" style={{ borderRadius: '50%', display: 'grid', placeItems: 'center', fontSize: 28, fontWeight: 700 }}>{s.first_name[0]}</Box>
                <Text fz="lg" fw={700} mt="sm">{s.first_name}</Text></Paper>
            </UnstyledButton>
          ))}
        </SimpleGrid>
      )}

      {step === 3 && service && (
        <Stack>
          <Group gap="xs" wrap="nowrap" style={{ overflowX: 'auto' }} pb={4}>
            {days.map((d, i) => (
              <Button key={i} size="lg" radius="lg" h={74} miw={84} variant={isoDate(d) === day ? 'filled' : 'default'} onClick={() => { setDay(isoDate(d)); setTime(null) }}>
                <Stack gap={0} align="center"><Text size="xs" tt="uppercase">{i === 0 ? 'Oggi' : i === 1 ? 'Domani' : d.toLocaleDateString('it-IT', { weekday: 'short' })}</Text>
                  <Text fz={22} fw={800}>{d.getDate()}</Text><Text size="xs">{d.toLocaleDateString('it-IT', { month: 'short' })}</Text></Stack>
              </Button>
            ))}
          </Group>
          {slots === null ? <Text fz="lg" c="dimmed">Cerco gli orari liberi…</Text> : slots.length === 0 ? <Paper {...choice} bg="var(--mantine-color-yellow-0)"><Text fz="lg">Nessun orario libero questo giorno: prova il giorno dopo.</Text></Paper> : (
            <SimpleGrid cols={{ base: 3, sm: 5, md: 6 }}>
              {slots.map((s) => <Button key={s.time} size="xl" radius="lg" variant={time === s.time ? 'filled' : 'light'} onClick={() => setTime(s.time)} data-testid="orario">{s.time}</Button>)}
            </SimpleGrid>
          )}
          {time && (
            <Paper {...choice} p="lg" bg="var(--mantine-color-blu-0)">
              <Group justify="space-between">
                <div>
                  <Text fz="xl" fw={700}>{clientName}</Text>
                  <Text fz="lg">{service.name} · {new Date(day + 'T12:00').toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' })} alle {time}</Text>
                </div>
                <Button size="xl" radius="xl" color="green" loading={busy} onClick={confirm} leftSection={<IconCheck />}>Conferma</Button>
              </Group>
            </Paper>
          )}
        </Stack>
      )}
    </Stack>
  )
}
