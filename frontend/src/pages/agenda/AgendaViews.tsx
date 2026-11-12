// Viste «Settimana» e «Mese» dell'agenda (la vista «Giorno», una colonna per operatore, resta in Agenda.tsx).
import { Badge, Box, Group, Paper, ScrollArea, SimpleGrid, Stack, Text, UnstyledButton } from '@mantine/core'
import { useMemo } from 'react'

import { fmtEuro, isoDate } from '../../api'
import { type Appointment, type Staff, dayKey, hhmm, minutesOf } from './lib'

const PXW = 1.1 // pixel per minuto nella settimana
const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3))

/** Lunedì della settimana del giorno dato. */
export function monday(d: Date): Date {
  const x = new Date(d); x.setHours(12, 0, 0, 0)
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7))
  return x
}
export function addDays(d: Date, n: number): Date { const x = new Date(d); x.setDate(x.getDate() + n); return x }
export const firstOfMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1, 12)
export const daysInMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()

const sameDay = (iso: string, d: Date) => isoDate(new Date(iso)) === isoDate(d)
const colorOf = (a: Appointment, staff: Staff[]) => staff.find((s) => s.id === a.items[0]?.staff_id)?.color ?? '#2340a8'

/** Appuntamenti che si sovrappongono nello stesso giorno: affiancati. */
function sideBySide(list: Appointment[]): { a: Appointment; lane: number; lanes: number }[] {
  const out: { a: Appointment; lane: number; lanes: number }[] = []
  const sorted = [...list].sort((x, y) => +new Date(x.starts_at) - +new Date(y.starts_at))
  let cluster: { a: Appointment; lane: number }[] = [], ends: number[] = [], clusterEnd = 0
  const flush = () => { cluster.forEach((c) => out.push({ ...c, lanes: ends.length })); cluster = []; ends = [] }
  for (const a of sorted) {
    const s = +new Date(a.starts_at), e = +new Date(a.ends_at)
    if (cluster.length && s >= clusterEnd) flush()
    let lane = ends.findIndex((v) => v <= s)
    if (lane === -1) lane = ends.push(0) - 1
    ends[lane] = e; clusterEnd = Math.max(clusterEnd, e); cluster.push({ a, lane })
  }
  flush()
  return out
}

// ------------------------------------------------------------------------------------------------------------ settimana
export function WeekView({ start, appts, staff, settings, onOpen, onNew, onDay }: {
  start: Date; appts: Appointment[]; staff: Staff[]; settings: any
  onOpen: (id: string) => void; onNew: (date: Date, time: string) => void; onDay: (d: Date) => void
}) {
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i))
  const today = isoDate(new Date())
  const slot = settings.slot_minutes || 15
  const [from, to] = useMemo(() => {
    const ranges = days.flatMap((d) => [...(settings.opening_hours?.[dayKey(d)] ?? []), ...staff.flatMap((s) => s.working_hours?.[dayKey(d)] ?? [])])
    const mins = [...ranges.flatMap((r: string[]) => [toMin(r[0]), toMin(r[1])]), ...appts.flatMap((a) => [minutesOf(a.starts_at), minutesOf(a.ends_at)])]
    if (!mins.length) return [9 * 60, 19 * 60]
    return [Math.floor(Math.min(...mins) / 60) * 60, Math.ceil(Math.max(...mins) / 60) * 60]
  }, [isoDate(start), appts, staff, settings])
  return (
    <Paper withBorder p={0}>
      <ScrollArea type="auto">
        <Box miw={70 + 7 * 140}>
          <Group gap={0} wrap="nowrap" style={{ borderBottom: '1px solid var(--mantine-color-gray-3)', position: 'sticky', top: 0, zIndex: 2, background: 'var(--mantine-color-body)' }}>
            <Box w={56} />
            {days.map((d) => {
              const list = appts.filter((a) => sameDay(a.starts_at, d))
              const closed = !(settings.opening_hours?.[dayKey(d)] ?? []).length
              return (
                <UnstyledButton key={isoDate(d)} onClick={() => onDay(d)} px="sm" py={6} data-testid="week-day"
                  style={{ flex: 1, minWidth: 140, borderLeft: '1px solid var(--mantine-color-gray-2)', background: isoDate(d) === today ? 'var(--mantine-color-blu-light)' : undefined }}>
                  <Text size="xs" c="dimmed" tt="capitalize">{d.toLocaleDateString('it-IT', { weekday: 'long' })}{closed ? ' · chiuso' : ''}</Text>
                  <Group gap={6} justify="space-between" wrap="nowrap">
                    <Text fw={800} fz="lg">{d.getDate()}</Text>
                    {list.length > 0 && <Text size="xs" c="dimmed">{list.length} · {fmtEuro(list.reduce((s, a) => s + Number(a.total), 0))}</Text>}
                  </Group>
                </UnstyledButton>
              )
            })}
          </Group>
          <Group gap={0} wrap="nowrap" align="flex-start" style={{ position: 'relative', height: (to - from) * PXW }}>
            <Box w={56} style={{ position: 'relative', height: '100%' }}>
              {Array.from({ length: (to - from) / 60 }, (_, i) => (
                <Text key={i} size="xs" c="dimmed" style={{ position: 'absolute', right: 8, top: Math.max(2, i * 60 * PXW - 8) }}>{String(from / 60 + i).padStart(2, '0')}:00</Text>
              ))}
            </Box>
            {days.map((d) => {
              const open = settings.opening_hours?.[dayKey(d)] ?? []
              const list = appts.filter((a) => sameDay(a.starts_at, d))
              return (
                <Box key={isoDate(d)} data-testid="week-col"
                  style={{ flex: 1, minWidth: 140, position: 'relative', height: '100%', borderLeft: '1px solid var(--mantine-color-gray-2)', cursor: 'pointer',
                    background: open.length ? undefined : 'repeating-linear-gradient(45deg, var(--mantine-color-gray-1) 0 8px, transparent 8px 16px)' }}
                  onClick={(e) => {
                    if (e.target !== e.currentTarget) return
                    const m = Math.floor((e.nativeEvent.offsetY / PXW + from) / slot) * slot
                    onNew(d, `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`)
                  }}>
                  {Array.from({ length: (to - from) / 60 }, (_, i) => <Box key={i} style={{ position: 'absolute', left: 0, right: 0, top: i * 60 * PXW, borderTop: '1px solid var(--mantine-color-gray-2)', pointerEvents: 'none' }} />)}
                  {sideBySide(list).map(({ a, lane, lanes }) => {
                    const top = (minutesOf(a.starts_at) - from) * PXW
                    const h = Math.max(18, (+new Date(a.ends_at) - +new Date(a.starts_at)) / 60000 * PXW)
                    return (
                      <Box key={a.id} data-testid="appt" onClick={() => onOpen(a.id)} title={`${hhmm(a.starts_at)} · ${a.client ?? 'Cliente occasionale'} · ${a.items.map((i) => i.service).join(', ')}`}
                        style={{ position: 'absolute', top, height: h, left: `calc(${(lane / lanes) * 100}% + 2px)`, width: `calc(${100 / lanes}% - 4px)`, background: colorOf(a, staff),
                          color: '#fff', borderRadius: 6, padding: '2px 5px', overflow: 'hidden', cursor: 'pointer', boxShadow: '0 0 0 1px var(--mantine-color-body)',
                          opacity: a.status === 'non_presentato' ? 0.45 : 1 }}>
                        <Text size="11px" fw={700} lh={1.2} truncate>{hhmm(a.starts_at)} {a.client ?? 'Cliente occasionale'}</Text>
                        {h > 30 && <Text size="10px" lh={1.2} opacity={0.9} truncate>{a.items.map((i) => i.service).join(', ')}</Text>}
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
  )
}

// ---------------------------------------------------------------------------------------------------------------- mese
export function MonthView({ month, appts, staff, settings, onDay, onOpen }: {
  month: Date; appts: Appointment[]; staff: Staff[]; settings: any; onDay: (d: Date) => void; onOpen: (id: string) => void
}) {
  const first = firstOfMonth(month)
  const start = monday(first)
  const weeks = Math.ceil(((first.getDay() + 6) % 7 + daysInMonth(month)) / 7)
  const cells = Array.from({ length: weeks * 7 }, (_, i) => addDays(start, i))
  const today = isoDate(new Date())
  return (
    <Paper withBorder p={0}>
      <SimpleGrid cols={7} spacing={0}>
        {['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'].map((d) => (
          <Text key={d} size="xs" fw={700} c="dimmed" ta="center" py={6} style={{ borderBottom: '1px solid var(--mantine-color-gray-3)' }}>{d}</Text>
        ))}
        {cells.map((d) => {
          const inMonth = d.getMonth() === month.getMonth()
          const list = inMonth ? appts.filter((a) => sameDay(a.starts_at, d)).sort((x, y) => +new Date(x.starts_at) - +new Date(y.starts_at)) : []
          const closed = !(settings.opening_hours?.[dayKey(d)] ?? []).length
          return (
            <UnstyledButton key={isoDate(d)} onClick={() => onDay(d)} data-testid="month-day" p={6}
              style={{ minHeight: 112, borderRight: '1px solid var(--mantine-color-gray-2)', borderBottom: '1px solid var(--mantine-color-gray-2)', verticalAlign: 'top',
                opacity: inMonth ? 1 : 0.35, display: 'flex', flexDirection: 'column', alignItems: 'stretch', justifyContent: 'flex-start',
                background: isoDate(d) === today ? 'var(--mantine-color-blu-light)' : closed && inMonth ? 'var(--mantine-color-gray-0)' : undefined }}>
              <Group justify="space-between" gap={4} wrap="nowrap">
                <Text fw={800} size="sm">{d.getDate()}</Text>
                {list.length > 0 && <Badge size="xs" variant="light">{list.length}</Badge>}
              </Group>
              {list.length > 0 && <Text size="10px" c="dimmed" mb={2}>{fmtEuro(list.reduce((s, a) => s + Number(a.total), 0))}</Text>}
              {closed && inMonth && !list.length && <Text size="10px" c="dimmed">chiuso</Text>}
              <Stack gap={2}>
                {list.slice(0, 3).map((a) => (
                  <Group key={a.id} gap={4} wrap="nowrap" onClick={(e) => { e.stopPropagation(); onOpen(a.id) }} style={{ cursor: 'pointer' }}>
                    <Box w={6} h={6} bg={colorOf(a, staff)} style={{ borderRadius: '50%', flex: 'none' }} />
                    <Text size="10px" lh={1.25} truncate>{hhmm(a.starts_at)} {a.client ?? 'Cliente occasionale'}</Text>
                  </Group>
                ))}
                {list.length > 3 && <Text size="10px" c="blu" fw={600}>altri {list.length - 3}…</Text>}
              </Stack>
            </UnstyledButton>
          )
        })}
      </SimpleGrid>
    </Paper>
  )
}
