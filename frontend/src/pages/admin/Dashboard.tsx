import { Button, Paper, SimpleGrid, Table, Text, Title } from '@mantine/core'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { adminApi, fmtDate, fmtEuro } from '../../api'
import { Loading, PageTitle, Stat, StatusBadge, notifyError, notifyOk } from '../../components'

export default function Dashboard() {
  const [d, setD] = useState<any>(null)
  const nav = useNavigate()

  const load = () => adminApi('/dashboard').then(setD).catch(notifyError)
  useEffect(() => { load() }, [])

  async function runReminders() {
    try {
      const r = await adminApi('/reminders/run', { method: 'POST' })
      notifyOk(r.sent.length ? `Inviati ${r.sent.length} avvisi` : 'Nessun avviso da inviare oggi')
    } catch (e) { notifyError(e) }
  }

  if (!d) return <Loading />
  const c = d.status_counts
  return (
    <>
      <PageTitle title="Panoramica" subtitle="Lo stato dei tuoi clienti e degli abbonamenti"
        right={<Button variant="light" onClick={runReminders}>Controlla scadenze ora</Button>} />
      <SimpleGrid cols={{ base: 2, md: 4 }} mb="lg">
        <Stat label="Aziende clienti" value={d.tenants_total} />
        <Stat label="Ricavo mensile ricorrente" value={fmtEuro(d.mrr)} hint="Stima sugli abbonamenti attivi" />
        <Stat label="Attivi" value={c.attivo + c.in_scadenza + c.prova} hint={`di cui ${c.prova} in prova`} />
        <Stat label="Da seguire" value={c.in_scadenza + c.tolleranza + c.sola_lettura} hint="In scadenza o scaduti" />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, md: 3 }} mb="lg">
        {['BASE', 'PLUS', 'PRO'].map((p) => <Stat key={p} label={`Pacchetto ${p}`} value={d.by_plan[p] ?? 0} />)}
      </SimpleGrid>
      <Paper withBorder p="md">
        <Title order={4} mb="sm">Da seguire</Title>
        {d.attention.length === 0 ? (
          <Text c="dimmed" size="sm">Nessun abbonamento in scadenza nei prossimi 30 giorni.</Text>
        ) : (
          <Table.ScrollContainer minWidth={500}>
            <Table highlightOnHover>
              <Table.Thead><Table.Tr><Table.Th>Azienda</Table.Th><Table.Th>Stato</Table.Th><Table.Th>Scadenza</Table.Th><Table.Th>Giorni</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {d.attention.map((a: any) => (
                  <Table.Tr key={a.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/admin/aziende/${a.id}`)}>
                    <Table.Td fw={600}>{a.name}</Table.Td>
                    <Table.Td><StatusBadge status={a.status} label={a.status_label} /></Table.Td>
                    <Table.Td>{fmtDate(a.end_date)}</Table.Td>
                    <Table.Td>{a.days_left}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Paper>
    </>
  )
}
