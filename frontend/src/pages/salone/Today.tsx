// «Oggi»: la schermata principale in modalità semplice. Tutto quello che serve in salone, con pulsanti grandi.
import { ActionIcon, Badge, Box, Button, Group, Menu, Modal, Paper, SimpleGrid, Stack, Text, ThemeIcon, Title, UnstyledButton } from '@mantine/core'
import { IconCalendarEvent, IconCalendarPlus, IconCash, IconCheck, IconDots, IconPrinter, IconUserSearch, IconUsers } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'

import { appApi, fmtEuro, isoDate } from '../../api'
import { Loading, notifyError } from '../../components'
import type { AppCtx } from '../app/AppLayout'
import { type Appointment, STATUS, type Staff, hhmm, longDay } from '../agenda/lib'
import { PayModal, ReceiptButtons } from './Pay'

export default function Today() {
  const { me, status } = useOutletContext<AppCtx>()
  const has = (code: string) => status.menu.some((m: any) => m.code === code && m.enabled)
  const nav = useNavigate()
  const [appts, setAppts] = useState<Appointment[] | null>(null)
  const [staff, setStaff] = useState<Staff[]>([])
  const [paying, setPaying] = useState<Appointment | null>(null)
  const [receipt, setReceipt] = useState<string | null>(null)
  const load = () => appApi(`/api/agenda/appuntamenti?day=${isoDate(new Date())}`).then(setAppts).catch(notifyError)
  useEffect(() => { load(); appApi('/api/agenda/operatori').then(setStaff).catch(() => {}) }, [])
  if (!appts) return <Loading />
  const live = appts.filter((a) => !['disdetto', 'non_presentato'].includes(a.status))
  const cashed = live.filter((a) => a.status === 'pagato').reduce((s, a) => s + Number(a.total), 0)
  const now = Date.now()
  const hour = new Date().getHours()
  const act = async (a: Appointment, path: string, body: any = {}) => {
    try { await appApi(`/api/agenda/appuntamenti/${a.id}/${path}`, { body }); load() } catch (e) { notifyError(e) }
  }

  return (
    <Stack gap="lg" maw={980}>
      <div>
        <Title order={1} fz={{ base: 28, sm: 34 }}>{hour < 13 ? 'Buongiorno' : hour < 18 ? 'Buon pomeriggio' : 'Buonasera'}, {me.user.full_name.split(' ')[0]} 👋</Title>
        <Text c="dimmed" fz="lg" tt="capitalize">{longDay(new Date())}</Text>
      </div>

      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <BigTile color="blu" icon={<IconCalendarPlus size={34} />} label="Nuovo appuntamento" onClick={() => nav('/nuovo')} filled />
        <BigTile color="teal" icon={<IconCalendarEvent size={34} />} label="Agenda" onClick={() => nav('/agenda')} />
        <BigTile color="grape" icon={<IconUserSearch size={34} />} label="Cerca cliente" onClick={() => nav('/agenda/clienti')} />
        {has('pos') ? <BigTile color="green" icon={<IconCash size={34} />} label={`Incassato oggi ${fmtEuro(cashed)}`} onClick={() => nav('/agenda')} />
          : <BigTile color="green" icon={<IconUsers size={34} />} label={`${live.length} clienti oggi`} onClick={() => nav('/agenda')} />}
      </SimpleGrid>

      <div>
        <Group justify="space-between" mb="sm">
          <Title order={2} fz={24}>Oggi in salone · {live.length}</Title>
        </Group>
        {live.length === 0 ? (
          <Paper withBorder radius="lg" p="xl" ta="center">
            <Text fz="lg" mb="md">Nessun appuntamento per oggi.</Text>
            <Button size="lg" radius="xl" leftSection={<IconCalendarPlus />} onClick={() => nav('/nuovo')}>Prendi un appuntamento</Button>
          </Paper>
        ) : (
          <Stack gap="sm">
            {live.map((a) => {
              const st = STATUS[a.status]
              const who = staff.find((s) => s.id === a.items[0]?.staff_id)
              const past = new Date(a.starts_at).getTime() < now
              return (
                <Paper key={a.id} withBorder radius="lg" p="md" data-testid="today-appt"
                  style={{ borderLeft: `8px solid ${who?.color ?? '#2340a8'}`, opacity: a.status === 'pagato' ? 0.75 : 1 }}>
                  <Group justify="space-between" wrap="nowrap" align="center">
                    <Group wrap="nowrap" gap="lg">
                      <Box ta="center" miw={70}>
                        <Text fz={28} fw={800} lh={1}>{hhmm(a.starts_at)}</Text>
                        <Text size="sm" c={past && ['prenotato', 'confermato'].includes(a.status) ? 'orange' : 'dimmed'}>{who?.first_name ?? ''}</Text>
                      </Box>
                      <div>
                        <Text fz={22} fw={700} lh={1.2}>{a.client ?? 'Cliente occasionale'}</Text>
                        <Text fz="md" c="dimmed">{a.items.map((i) => i.service).join(' + ')} · {fmtEuro(a.total)}{a.channel === 'online' ? ' · 📱 prenotato dal telefono' : ''}</Text>
                        <Badge mt={4} color={st?.color} variant="light" size="lg">{st?.label}</Badge>
                      </div>
                    </Group>
                    <Group gap="xs" wrap="nowrap">
                      {['prenotato', 'confermato'].includes(a.status) && <Button size="lg" radius="xl" variant="light" leftSection={<IconCheck />} onClick={() => act(a, 'stato', { status: 'arrivato' })}>È arrivata</Button>}
                      {has('pos') && ['arrivato', 'concluso', 'prenotato', 'confermato'].includes(a.status) && <Button size="lg" radius="xl" color="green" leftSection={<IconCash />} onClick={() => setPaying(a)}>Incassa</Button>}
                      {a.status === 'pagato' && has('periferiche') && <Button size="lg" radius="xl" variant="default" leftSection={<IconPrinter />} onClick={() => setReceipt(a.id)}>Ricevuta</Button>}
                      <Menu position="bottom-end">
                        <Menu.Target><ActionIcon size={48} radius="xl" variant="subtle" aria-label="Altro"><IconDots /></ActionIcon></Menu.Target>
                        <Menu.Dropdown>
                          <Menu.Item onClick={() => nav(`/agenda?giorno=${a.starts_at.slice(0, 10)}&apri=${a.id}`)}>Apri i dettagli</Menu.Item>
                          {a.party_id && <Menu.Item onClick={() => nav(`/agenda/clienti/${a.party_id}`)}>Scheda della cliente</Menu.Item>}
                          {['prenotato', 'confermato'].includes(a.status) && <Menu.Item color="red" onClick={() => act(a, 'stato', { status: 'non_presentato' })}>Non è venuta</Menu.Item>}
                          {['prenotato', 'confermato', 'arrivato'].includes(a.status) && <Menu.Item color="red" onClick={() => act(a, 'disdici')}>Disdici l'appuntamento</Menu.Item>}
                        </Menu.Dropdown>
                      </Menu>
                    </Group>
                  </Group>
                </Paper>
              )
            })}
          </Stack>
        )}
      </div>
      {paying && <PayModal appt={paying} onClose={() => setPaying(null)} onDone={() => { setPaying(null); load() }} />}
      {receipt && <ReceiptModal id={receipt} onClose={() => setReceipt(null)} />}
    </Stack>
  )
}

function BigTile({ icon, label, onClick, color, filled }: { icon: React.ReactNode; label: string; onClick: () => void; color: string; filled?: boolean }) {
  return (
    <UnstyledButton onClick={onClick}>
      <Paper radius="lg" p="lg" h={130} withBorder={!filled} bg={filled ? `var(--mantine-color-${color}-6)` : undefined} c={filled ? 'white' : undefined}
        style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', boxShadow: filled ? '0 10px 24px rgba(35,64,168,.3)' : undefined }}>
        <ThemeIcon size={52} radius="md" color={color} variant={filled ? 'white' : 'light'}>{icon}</ThemeIcon>
        <Text fz={18} fw={700} lh={1.2}>{label}</Text>
      </Paper>
    </UnstyledButton>
  )
}

function ReceiptModal({ id, onClose }: { id: string; onClose: () => void }) {
  return <Modal opened onClose={onClose} title="Stampa la ricevuta" radius="lg" centered><ReceiptButtons apptId={id} /></Modal>
}
