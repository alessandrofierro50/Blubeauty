// Giri dei furgoni: situazione del giorno per agente (documenti arrivati, venduto, incassi, visite, km) e storico.

import { Alert, Badge, Button, Group, Modal, Paper, Progress, Select, SimpleGrid, Stack, Table, Text } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { IconPlus, IconTruck } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fmtDate, fmtEuro, isoDate } from '../../api'
import { Loading, PageTitle, notifyError } from '../../components'
import { StatusBadge, TV } from './shared'

export default function Trips() {
  const nav = useNavigate()
  const [day, setDay] = useState<Date>(new Date())
  const [today, setToday] = useState<any[] | null>(null)
  const [history, setHistory] = useState<any[] | null>(null)
  const [vans, setVans] = useState<any[]>([])
  const [creating, setCreating] = useState<{ van_id: string | null; date: Date } | null>(null)
  useEffect(() => { TV('/furgoni').then(setVans).catch(notifyError); TV('/giri').then(setHistory).catch(notifyError) }, [])
  useEffect(() => { setToday(null); TV(`/giri?day=${isoDate(day)}`).then(setToday).catch(notifyError) }, [day])

  async function create() {
    try {
      const t = await TV('/giri', { body: { van_id: creating!.van_id, trip_date: isoDate(creating!.date) } })
      nav(`/tentata/giri/${t.id}`)
    } catch (e) { notifyError(e) }
  }
  return (
    <>
      <PageTitle title="Giri dei furgoni" subtitle="Preparazione e carico, documenti e incassi arrivati dagli agenti, rientri da verificare"
        right={<Group>
          <DateInput value={day} onChange={(d) => d && setDay(d)} valueFormat="dddd DD/MM/YYYY" locale="it" w={220} />
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating({ van_id: vans[0]?.id ?? null, date: day })} disabled={!vans.length}>Nuovo giro</Button>
        </Group>} />
      {!vans.length && <Alert color="blue" mb="md">Prima crea un furgone in «Furgoni».</Alert>}
      {!today ? <Loading /> : !today.length ? <Text c="dimmed" mb="lg">Nessun giro il {fmtDate(isoDate(day))}.</Text> : (
        <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} mb="xl">
          {today.map((t) => {
            const s = t.summary
            const cash = s.cash.reduce((a: number, c: any) => a + Number(c.collected), 0)
            return (
              <Paper key={t.id} withBorder p="md" radius="md" style={{ cursor: 'pointer' }} onClick={() => nav(`/tentata/giri/${t.id}`)}>
                <Group justify="space-between" mb="xs">
                  <Group gap="xs"><IconTruck size={20} /><Text fw={700}>{t.van}</Text></Group>
                  <StatusBadge trip={t} />
                </Group>
                <Text size="sm" c="dimmed" mb="sm">{t.agent ?? 'Agente non assegnato'}</Text>
                <SimpleGrid cols={3} spacing="xs">
                  <Kpi label="Venduto" value={fmtEuro(s.sold_taxable)} />
                  <Kpi label="Incassato" value={fmtEuro(cash)} />
                  <Kpi label="Km" value={s.km ?? '—'} />
                </SimpleGrid>
                <Text size="xs" mt="sm">Visite {s.visits.visited} di {s.visits.planned}</Text>
                <Progress value={s.visits.planned ? (100 * s.visits.visited) / s.visits.planned : 0} size="sm" mt={4} />
                <Group gap={4} mt="sm">{Object.entries(s.documents).map(([k, v]: any) => <Badge key={k} variant="light" color="gray">{v.count} {v.label}</Badge>)}</Group>
                {t.status === 'rientro' && <Alert color="orange" mt="sm" p="xs">Rientrato: il magazziniere deve verificare la merce</Alert>}
              </Paper>
            )
          })}
        </SimpleGrid>
      )}
      <Text fw={700} mb="xs">Ultimi giri</Text>
      {!history ? <Loading /> : (
        <Paper withBorder>
          <Table highlightOnHover fz="sm">
            <Table.Thead><Table.Tr><Table.Th>Data</Table.Th><Table.Th>Furgone</Table.Th><Table.Th>Agente</Table.Th><Table.Th>Stato</Table.Th>
              <Table.Th ta="right">Venduto</Table.Th><Table.Th ta="right">Visite</Table.Th><Table.Th ta="right">Km</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {history.map((t) => (
                <Table.Tr key={t.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/tentata/giri/${t.id}`)}>
                  <Table.Td>{t.weekday} {fmtDate(t.trip_date)}</Table.Td><Table.Td>{t.van}</Table.Td><Table.Td>{t.agent ?? '—'}</Table.Td>
                  <Table.Td><StatusBadge trip={t} /></Table.Td><Table.Td ta="right">{fmtEuro(t.summary.sold_taxable)}</Table.Td>
                  <Table.Td ta="right">{t.summary.visits.visited}/{t.summary.visits.planned}</Table.Td><Table.Td ta="right">{t.summary.km ?? '—'}</Table.Td>
                </Table.Tr>
              ))}
              {!history.length && <Table.Tr><Table.Td colSpan={7}><Text c="dimmed" ta="center" py="md">Nessun giro negli ultimi 60 giorni</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      <Modal opened={!!creating} onClose={() => setCreating(null)} title="Nuovo giro">
        {creating && (
          <Stack>
            <Select label="Furgone" data={vans.map((v) => ({ value: v.id, label: `${v.code} · ${v.name}${v.agent ? ' — ' + v.agent : ''}` }))}
              value={creating.van_id} onChange={(v) => setCreating({ ...creating, van_id: v })} allowDeselect={false} />
            <DateInput label="Giorno" value={creating.date} onChange={(d) => d && setCreating({ ...creating, date: d })} valueFormat="dddd DD/MM/YYYY" />
            <Text size="sm" c="dimmed">Il giro parte con i clienti del giro abituale per quel giorno della settimana e con quelli che hanno ordini da consegnare.</Text>
            <Group justify="flex-end"><Button onClick={create} disabled={!creating.van_id}>Crea il giro</Button></Group>
          </Stack>
        )}
      </Modal>
    </>
  )
}

function Kpi({ label, value }: { label: string; value: any }) {
  return <div><Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text><Text fw={700}>{value}</Text></div>
}
