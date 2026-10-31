// Turni e assenze: per ogni operatore e giorno l'orario effettivo (settimana, settimane alterne, ferie, malattia,
// permessi, orari diversi) e le chiusure del salone. Un tocco su una casella segna o modifica un'eccezione.
import { ActionIcon, Alert, Anchor, Badge, Box, Button, Group, Modal, Paper, ScrollArea, Select, SimpleGrid, Stack, Table, Text, TextInput, UnstyledButton } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { IconBrandWhatsapp, IconBuildingStore, IconChevronLeft, IconChevronRight, IconPlus, IconTrash } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { appApi, isoDate } from '../../api'
import { Loading, PageTitle, notifyError, notifyOk } from '../../components'

type Absence = { id: string; staff_id: string | null; kind: string; label: string; date_from: string; date_to: string; hours: string[][]; note: string | null }
type Plan = { hours: string[][]; absence: Absence | null }
type Data = { days: string[]; staff: any[]; plan: Record<string, Record<string, Plan>>; closures: Record<string, Absence | null>; absences: Absence[]; kinds: Record<string, string> }
type Conflict = { id: string; starts_at: string; when: string; client: string; first_name: string; phone: string | null; staff: string; service: string }

const COLORS: Record<string, string> = { ferie: 'teal', malattia: 'red', permesso: 'orange', orario: 'violet', chiusura: 'gray' }
const PERSONAL = [['ferie', 'Ferie'], ['malattia', 'Malattia'], ['permesso', 'Permesso (alcune ore)'], ['orario', 'Orario diverso']]
const DAYS_SHOWN = 14

const monday = (d: Date) => { const x = new Date(d); x.setHours(12, 0, 0, 0); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x }
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x }
const d12 = (s: string) => new Date(s + 'T12:00:00')
const short = (r: string[][]) => r.map(([a, b]) => `${a.replace(/:00$/, '')}–${b.replace(/:00$/, '')}`).join(' · ')
const fmtDay = (s: string) => d12(s).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })
const period = (a: Absence) => a.date_from === a.date_to ? fmtDay(a.date_from) : `dal ${fmtDay(a.date_from)} al ${fmtDay(a.date_to)}`

export default function Shifts() {
  const [start, setStart] = useState(() => monday(new Date()))
  const [data, setData] = useState<Data | null>(null)
  const [salon, setSalon] = useState('')
  const [edit, setEdit] = useState<Partial<Absence> | null>(null)
  const load = () => appApi(`/api/agenda/turni?dal=${isoDate(start)}&giorni=${DAYS_SHOWN}`).then(setData).catch(notifyError)
  useEffect(() => { load() }, [isoDate(start)])
  useEffect(() => { appApi('/api/agenda/impostazioni').then((s) => setSalon(s.display_name || s.salon_name || '')).catch(() => {}) }, [])
  if (!data) return <Loading />
  const today = isoDate(new Date())
  const names = Object.fromEntries(data.staff.map((s) => [s.id, s.first_name]))

  return (
    <>
      <PageTitle title="Turni e assenze" subtitle={`Dal ${fmtDay(data.days[0])} al ${fmtDay(data.days[data.days.length - 1])} · tocca una casella per segnare ferie, malattia, permessi o un orario diverso`}
        right={<Group>
          <ActionIcon variant="default" size="lg" onClick={() => setStart(addDays(start, -7))} aria-label="Settimana prima"><IconChevronLeft size={18} /></ActionIcon>
          <Button variant="default" onClick={() => setStart(monday(new Date()))}>Oggi</Button>
          <ActionIcon variant="default" size="lg" onClick={() => setStart(addDays(start, 7))} aria-label="Settimana dopo"><IconChevronRight size={18} /></ActionIcon>
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEdit({ staff_id: data.staff[0]?.id ?? null, kind: 'ferie', date_from: today, date_to: today })}>Segna un'assenza</Button>
          <Button variant="light" color="gray" leftSection={<IconBuildingStore size={16} />} onClick={() => setEdit({ staff_id: null, kind: 'chiusura', date_from: today, date_to: today })}>Chiudi il salone</Button>
        </Group>} />

      <Paper withBorder p={0}>
        <ScrollArea type="auto">
          <Table withColumnBorders style={{ minWidth: 140 + data.days.length * 92 }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={140} />
                {data.days.map((d) => (
                  <Table.Th key={d} ta="center" bg={d === today ? 'var(--mantine-color-blu-light)' : undefined} style={{ fontWeight: d === today ? 800 : 600 }}>
                    <Text size="xs" tt="uppercase" c="dimmed">{d12(d).toLocaleDateString('it-IT', { weekday: 'short' })}</Text>
                    <Text size="sm" fw={700}>{fmtDay(d)}</Text>
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.staff.map((s) => (
                <Table.Tr key={s.id}>
                  <Table.Td><Group gap={8} wrap="nowrap"><Box w={12} h={12} bg={s.color} style={{ borderRadius: '50%', flexShrink: 0 }} /><Text fw={700}>{s.first_name}</Text></Group></Table.Td>
                  {data.days.map((d) => {
                    const p = data.plan[s.id][d]
                    const a = p.absence
                    return (
                      <Table.Td key={d} p={4} bg={d === today ? 'var(--mantine-color-blu-light)' : undefined}>
                        <UnstyledButton w="100%" mih={52} p={4} style={{ borderRadius: 8 }} data-testid="turno"
                          onClick={() => setEdit(a ? a : { staff_id: s.id, kind: 'ferie', date_from: d, date_to: d })}>
                          <Stack gap={2} align="center">
                            {a && <Badge size="sm" color={COLORS[a.kind]} variant={a.kind === 'chiusura' || a.kind === 'ferie' || a.kind === 'malattia' ? 'filled' : 'light'}>{a.kind === 'chiusura' ? 'Chiuso' : a.label}</Badge>}
                            {p.hours.length ? <Text size="xs" ta="center">{short(p.hours)}</Text> : !a && <Text size="xs" c="dimmed">Libero</Text>}
                          </Stack>
                        </UnstyledButton>
                      </Table.Td>
                    )
                  })}
                </Table.Tr>
              ))}
              <Table.Tr>
                <Table.Td><Group gap={8} wrap="nowrap"><IconBuildingStore size={16} /><Text fw={700}>Salone</Text></Group></Table.Td>
                {data.days.map((d) => {
                  const c = data.closures[d]
                  return (
                    <Table.Td key={d} p={4}>
                      <UnstyledButton w="100%" mih={36} style={{ borderRadius: 8 }} onClick={() => setEdit(c ? c : { staff_id: null, kind: 'chiusura', date_from: d, date_to: d })}>
                        <Stack align="center">{c ? <Badge size="sm" color="gray" variant="filled">Chiuso</Badge> : <Text size="xs" c="dimmed">aperto</Text>}</Stack>
                      </UnstyledButton>
                    </Table.Td>
                  )
                })}
              </Table.Tr>
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Paper>

      <Paper withBorder p="md" mt="lg">
        <Text fw={700} mb="xs">Assenze e chiusure in questo periodo</Text>
        {data.absences.length === 0 ? <Text c="dimmed" size="sm">Nessuna: tutti lavorano con il loro orario solito.</Text> : (
          <Stack gap={6}>
            {data.absences.map((a) => (
              <Group key={a.id} justify="space-between" wrap="nowrap">
                <UnstyledButton onClick={() => setEdit(a)}>
                  <Group gap="xs" wrap="nowrap">
                    <Badge color={COLORS[a.kind]}>{a.label}</Badge>
                    <Text fw={600}>{a.staff_id ? names[a.staff_id] ?? '' : 'Tutto il salone'}</Text>
                    <Text size="sm">{period(a)}{a.hours.length ? ` · ${short(a.hours)}` : ''}{a.note ? ` · ${a.note}` : ''}</Text>
                  </Group>
                </UnstyledButton>
                <ActionIcon variant="subtle" color="red" aria-label="Elimina" onClick={() => remove(a)}><IconTrash size={16} /></ActionIcon>
              </Group>
            ))}
          </Stack>
        )}
      </Paper>

      {edit && <AbsenceModal value={edit} staff={data.staff} salon={salon} onClose={() => setEdit(null)} onSaved={() => load()} />}
    </>
  )

  async function remove(a: Absence) {
    if (!window.confirm(`Eliminare «${a.label}» ${period(a)}?`)) return
    try { await appApi(`/api/agenda/turni/assenze/${a.id}`, { method: 'DELETE' }); notifyOk('Eliminata'); load() } catch (e) { notifyError(e) }
  }
}

function AbsenceModal({ value, staff, salon, onClose, onSaved }: { value: Partial<Absence>; staff: any[]; salon: string; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<any>({ hours: [], note: '', ...value })
  const [busy, setBusy] = useState(false)
  const [conflicts, setConflicts] = useState<Conflict[] | null>(null)
  const nav = useNavigate()
  const closure = f.staff_id === null
  const needsHours = f.kind === 'permesso' || f.kind === 'orario'

  const setWho = (v: string | null) => {
    const isSalon = v === 'salone'
    setF({ ...f, staff_id: isSalon ? null : v, kind: isSalon ? 'chiusura' : f.kind === 'chiusura' ? 'ferie' : f.kind })
  }
  const setKind = (k: string) => setF({ ...f, kind: k, hours: (k === 'permesso' || k === 'orario') && !f.hours?.length ? [k === 'permesso' ? ['15:00', '19:30'] : ['09:00', '13:00']] : f.hours })

  async function save() {
    setBusy(true)
    try {
      const body = { staff_id: f.staff_id, kind: f.kind, date_from: f.date_from, date_to: f.date_to, hours: needsHours ? f.hours : [], note: f.note || null }
      const r = await appApi(f.id ? `/api/agenda/turni/assenze/${f.id}` : '/api/agenda/turni/assenze', { method: f.id ? 'PUT' : 'POST', body })
      onSaved()
      if (r.conflicts.length) setConflicts(r.conflicts)
      else { notifyOk('Salvato'); onClose() }
    } catch (e) { notifyError(e) } finally { setBusy(false) }
  }
  async function remove() {
    try { await appApi(`/api/agenda/turni/assenze/${f.id}`, { method: 'DELETE' }); notifyOk('Eliminata'); onSaved(); onClose() } catch (e) { notifyError(e) }
  }

  if (conflicts) return (
    <Modal opened onClose={onClose} title="Appuntamenti da spostare" size="lg">
      <Alert color="orange" mb="md">Salvato. Questi appuntamenti erano già presi e ora cadono fuori dall'orario: spostali o avvisa la cliente.</Alert>
      <Stack gap="xs">
        {conflicts.map((c) => {
          const text = `Ciao ${c.first_name}, ti scriviamo da ${salon || 'il salone'}: purtroppo dobbiamo spostare il tuo appuntamento di ${c.when}. Ci scrivi o ci chiami per scegliere un nuovo orario? Grazie e scusa per il disagio!`
          return (
            <Paper key={c.id} withBorder p="sm" radius="md">
              <Group justify="space-between" wrap="nowrap">
                <div>
                  <Text fw={700}>{c.client || 'Cliente senza nome'}</Text>
                  <Text size="sm">{c.when} · {c.service}{c.staff ? ` con ${c.staff}` : ''}</Text>
                </div>
                <Group gap="xs" wrap="nowrap">
                  {c.phone && <Button size="xs" color="green" leftSection={<IconBrandWhatsapp size={16} />} component="a" target="_blank"
                    href={`https://wa.me/${c.phone.replace(/\D/g, '')}?text=${encodeURIComponent(text)}`}>Avvisa</Button>}
                  <Button size="xs" variant="light" onClick={() => nav(`/agenda?giorno=${c.starts_at.slice(0, 10)}&apri=${c.id}`)}>Apri</Button>
                </Group>
              </Group>
            </Paper>
          )
        })}
      </Stack>
      <Button fullWidth mt="md" variant="default" onClick={onClose}>Fatto</Button>
    </Modal>
  )

  return (
    <Modal opened onClose={onClose} title={f.id ? 'Modifica' : closure ? 'Chiusura del salone' : 'Segna un\'assenza o un cambio di turno'} size="md">
      <Stack>
        <Select label="Chi" allowDeselect={false} value={f.staff_id ?? 'salone'} onChange={setWho}
          data={[...staff.map((s) => ({ value: s.id, label: s.first_name })), { value: 'salone', label: 'Tutto il salone (chiusura)' }]} />
        {!closure && (
          <SimpleGrid cols={2} spacing="xs">
            {PERSONAL.map(([k, label]) => (
              <Button key={k} size="md" color={COLORS[k]} variant={f.kind === k ? 'filled' : 'light'} onClick={() => setKind(k)}>{label}</Button>
            ))}
          </SimpleGrid>
        )}
        <SimpleGrid cols={2}>
          <DateInput label="Dal" valueFormat="DD/MM/YYYY" value={f.date_from ? d12(f.date_from) : null}
            onChange={(d: any) => { if (!d) return; const v = isoDate(new Date(d)); setF({ ...f, date_from: v, date_to: f.date_to < v ? v : f.date_to }) }} />
          <DateInput label="Al" valueFormat="DD/MM/YYYY" value={f.date_to ? d12(f.date_to) : null} minDate={f.date_from ? d12(f.date_from) : undefined}
            onChange={(d: any) => d && setF({ ...f, date_to: isoDate(new Date(d)) })} />
        </SimpleGrid>
        {needsHours && (
          <div>
            <Text size="sm" fw={500}>{f.kind === 'permesso' ? 'Ore di assenza' : 'Ore di lavoro in quei giorni'}</Text>
            <Stack gap={6} mt={4}>
              {(f.hours as string[][]).map((r, i) => (
                <Group key={i} gap={6} wrap="nowrap">
                  <TextInput w={80} value={r[0]} onChange={(e) => setF({ ...f, hours: f.hours.map((x: string[], j: number) => (j === i ? [e.target.value, x[1]] : x)) })} />
                  <Text>–</Text>
                  <TextInput w={80} value={r[1]} onChange={(e) => setF({ ...f, hours: f.hours.map((x: string[], j: number) => (j === i ? [x[0], e.target.value] : x)) })} />
                  {f.hours.length > 1 && <ActionIcon variant="subtle" color="red" onClick={() => setF({ ...f, hours: f.hours.filter((_: any, j: number) => j !== i) })}><IconTrash size={14} /></ActionIcon>}
                </Group>
              ))}
              {f.kind === 'orario' && f.hours.length < 3 && <Anchor size="sm" onClick={() => setF({ ...f, hours: [...f.hours, ['15:00', '19:30']] })}>+ aggiungi una fascia (es. pomeriggio)</Anchor>}
            </Stack>
          </div>
        )}
        <TextInput label="Nota (facoltativa)" placeholder={closure ? 'es. Ferragosto, inventario' : 'es. visita medica'} value={f.note ?? ''} onChange={(e) => setF({ ...f, note: e.target.value })} />
        <Group justify="space-between">
          {f.id ? <Button variant="subtle" color="red" leftSection={<IconTrash size={16} />} onClick={remove}>Elimina</Button> : <span />}
          <Group><Button variant="default" onClick={onClose}>Annulla</Button><Button loading={busy} onClick={save} data-testid="salva-assenza">Salva</Button></Group>
        </Group>
      </Stack>
    </Modal>
  )
}
