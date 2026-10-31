import { Badge, Button, Group, Paper, Progress, SegmentedControl, Select, SimpleGrid, Table, Tabs, Text, Title } from '@mantine/core'
import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext, useParams } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro } from '../../api'
import { Loading, PageTitle, Stat, notifyError } from '../../components'
import { useWarehouses } from '../magazzino/shared'
import type { AppCtx } from '../app/AppLayout'
import BancoStats from './BancoStats'
import SalesBI from './SalesBI'

const ST = (p: string) => appApi('/api/statistiche' + p)
const n = (v: any) => Number(v).toLocaleString('it-IT', { maximumFractionDigits: 2 })

export default function Stats() {
  const { tab } = useParams()
  const nav = useNavigate()
  const [pro, setPro] = useState<boolean | null>(null)
  const ctx = useOutletContext<AppCtx>()
  const hasPos = !!ctx?.status?.menu?.some((m: any) => m.code === 'pos' && m.enabled)
  useEffect(() => { appApi('/api/bi/vendite/modello').then((m) => setPro(m.measures.some((x: any) => x.name === 'margine' && x.available))).catch(() => setPro(false)) }, [])
  return (
    <>
      <PageTitle title="Statistiche" subtitle="Come vanno le vendite e quanto vale il magazzino" />
      <Tabs value={tab ?? 'vendite'} onChange={(v) => nav(v === 'vendite' ? '/statistiche' : `/statistiche/${v}`)} mb="md">
        <Tabs.List><Tabs.Tab value="vendite">Vendite</Tabs.Tab>{hasPos && <Tabs.Tab value="banco">Vendita al banco</Tabs.Tab>}<Tabs.Tab value="magazzino">Magazzino</Tabs.Tab></Tabs.List>
      </Tabs>
      {tab === 'magazzino' ? <StockStats /> : tab === 'banco' ? <BancoStats /> : pro === null ? <Loading /> : <SalesBI pro={pro} />}
    </>
  )
}

function StockStats() {
  const nav = useNavigate()
  const whs = useWarehouses()
  const [wh, setWh] = useState<string | null>(null)
  const [days, setDays] = useState('60')
  const [d, setD] = useState<any>(null)
  useEffect(() => { setD(null); ST(`/magazzino?days=${days}${wh ? `&warehouse_id=${wh}` : ''}`).then(setD).catch(notifyError) }, [wh, days])
  return (
    <>
      <Group mb="md">
        {whs && whs.length > 1 && <Select placeholder="Tutti i magazzini" data={whs.map((w) => ({ value: w.id, label: w.name }))} value={wh} onChange={setWh} clearable />}
      </Group>
      {!d ? <Loading /> : (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
            <Stat label="Valore di magazzino" value={fmtEuro(d.value)} hint="al costo medio (o ultimo costo)" />
            <Stat label="Sotto scorta minima" value={d.under_min.length} hint="articoli da riordinare" />
            <Stat label="Giacenza negativa" value={<Text span fw={700} fz="inherit" c={d.negative.length ? 'red' : undefined}>{d.negative.length}</Text>} hint="da verificare" />
            <Stat label="Lotti in scadenza" value={d.expiring_lots.length} hint={d.expired_count ? `${d.expired_count} già scaduti` : `nei prossimi ${days} giorni`} />
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, lg: 2 }} mb="md">
            <Paper withBorder p="md">
              <Title order={5} mb="sm">Valore per categoria</Title>
              {d.by_category.map((c: any) => (
                <div key={c.name} style={{ marginBottom: 8 }}>
                  <Group justify="space-between"><Text size="sm">{c.name}</Text><Text size="sm" fw={600}>{fmtEuro(c.value)}</Text></Group>
                  <Progress value={Number(c.share)} size={5} />
                </div>
              ))}
              {d.by_warehouse.length > 1 && (
                <>
                  <Title order={6} mt="md" mb={4}>Per magazzino</Title>
                  {d.by_warehouse.map((w: any) => <Group key={w.name} justify="space-between"><Text size="sm">{w.name}</Text><Text size="sm" fw={600}>{fmtEuro(w.value)}</Text></Group>)}
                </>
              )}
            </Paper>
            <Paper withBorder p="md">
              <Group justify="space-between" mb="sm">
                <Title order={5}>Lotti in scadenza</Title>
                <SegmentedControl size="xs" value={days} onChange={setDays} data={[{ value: '15', label: '15 gg' }, { value: '30', label: '30 gg' }, { value: '60', label: '60 gg' }, { value: '120', label: '120 gg' }]} />
              </Group>
              <Table verticalSpacing={4} fz="sm">
                <Table.Tbody>
                  {d.expiring_lots.slice(0, 30).map((l: any) => (
                    <Table.Tr key={l.item_id + l.lot_number}>
                      <Table.Td><Text size="sm">{l.description}</Text><Text size="xs" c="dimmed">lotto {l.lot_number}</Text></Table.Td>
                      <Table.Td ta="right">{n(l.on_hand)} {l.unit}</Table.Td>
                      <Table.Td ta="right"><Badge size="sm" color={l.days < 0 ? 'red' : l.days <= 7 ? 'orange' : 'yellow'} variant="light">{l.days < 0 ? `scaduto da ${-l.days} gg` : `${fmtDate(l.expiry_date)} · ${l.days} gg`}</Badge></Table.Td>
                    </Table.Tr>
                  ))}
                  {!d.expiring_lots.length && <Table.Tr><Table.Td><Text c="dimmed" ta="center" py="md">Nessun lotto in scadenza</Text></Table.Td></Table.Tr>}
                </Table.Tbody>
              </Table>
            </Paper>
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, lg: 2 }}>
            <Paper withBorder p="md">
              <Group justify="space-between" mb="sm"><Title order={5}>Sotto scorta minima</Title>{d.under_min.length > 0 && <Button size="xs" variant="light" onClick={() => nav('/acquisti/riordino')}>Proposta di riordino</Button>}</Group>
              <Table verticalSpacing={4} fz="sm">
                <Table.Tbody>
                  {d.under_min.slice(0, 30).map((r: any) => (
                    <Table.Tr key={r.item_id} style={{ cursor: 'pointer' }} onClick={() => nav(`/magazzino/articolo/${r.item_id}`)}>
                      <Table.Td><Text span size="xs" ff="monospace" c="dimmed">{r.code} </Text>{r.description}</Table.Td>
                      <Table.Td ta="right">{n(r.on_hand)} / {n(r.min_stock)} {r.unit}</Table.Td>
                    </Table.Tr>
                  ))}
                  {!d.under_min.length && <Table.Tr><Table.Td><Text c="dimmed" ta="center" py="md">Tutto sopra la scorta minima</Text></Table.Td></Table.Tr>}
                </Table.Tbody>
              </Table>
            </Paper>
            <Paper withBorder p="md">
              <Title order={5} mb="sm">Giacenze negative</Title>
              <Table verticalSpacing={4} fz="sm">
                <Table.Tbody>
                  {d.negative.slice(0, 30).map((r: any) => (
                    <Table.Tr key={r.item_id} style={{ cursor: 'pointer' }} onClick={() => nav(`/magazzino/articolo/${r.item_id}`)}>
                      <Table.Td><Text span size="xs" ff="monospace" c="dimmed">{r.code} </Text>{r.description}</Table.Td>
                      <Table.Td ta="right" c="red" fw={600}>{n(r.on_hand)} {r.unit}</Table.Td>
                    </Table.Tr>
                  ))}
                  {!d.negative.length && <Table.Tr><Table.Td><Text c="dimmed" ta="center" py="md">Nessuna giacenza negativa</Text></Table.Td></Table.Tr>}
                </Table.Tbody>
              </Table>
            </Paper>
          </SimpleGrid>
        </>
      )}
    </>
  )
}
