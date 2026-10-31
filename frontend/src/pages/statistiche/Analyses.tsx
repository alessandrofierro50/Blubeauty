// Analisi Pro pronte: ABC/Pareto, salute del magazzino (fermi, rotazione, copertura, valore), clienti (frequenza e inattivi), garanzie.

import { BarChart } from '@mantine/charts'
import { Badge, Group, NumberInput, Paper, Progress, SegmentedControl, Select, SimpleGrid, Table, Tabs, Text, TextInput, Title } from '@mantine/core'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { appApi, fmtDate, fmtEuro } from '../../api'
import { Loading, PageTitle, Stat, notifyError } from '../../components'
import { useWarehouses } from '../magazzino/shared'

const BI = (p: string) => appApi('/api/bi' + p)
const n = (v: any, d = 1) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('it-IT', { maximumFractionDigits: d }))
const CLS_COLOR: Record<string, string> = { A: 'teal', B: 'yellow', C: 'gray' }

export default function Analyses() {
  const { tab } = useParams()
  const nav = useNavigate()
  return (
    <>
      <PageTitle title="Analisi avanzate" subtitle="Pareto, magazzino, clienti e garanzie: i numeri che aiutano a decidere" />
      <Tabs value={tab ?? 'abc'} onChange={(v) => nav(`/analisi/${v}`)} mb="md">
        <Tabs.List>
          <Tabs.Tab value="abc">Analisi ABC</Tabs.Tab><Tabs.Tab value="magazzino">Magazzino: rotazione e fermi</Tabs.Tab>
          <Tabs.Tab value="clienti">Clienti: frequenza e inattivi</Tabs.Tab><Tabs.Tab value="garanzie">Garanzie</Tabs.Tab>
        </Tabs.List>
      </Tabs>
      {tab === 'magazzino' ? <Stock /> : tab === 'clienti' ? <Customers /> : tab === 'garanzie' ? <Warranties /> : <Abc />}
    </>
  )
}

function Abc() {
  const [what, setWhat] = useState('articolo')
  const [measure, setMeasure] = useState('fatturato')
  const [period, setPeriod] = useState('ultimi_12_mesi')
  const [d, setD] = useState<any>(null)
  useEffect(() => {
    setD(null)
    const m = what === 'fornitore' ? (measure === 'quantita' ? 'quantita' : 'spesa') : measure
    BI(`/analisi/abc?oggetto=${what}&misura=${m}&periodo=${period}`).then(setD).catch(notifyError)
  }, [what, measure, period])
  const chart = useMemo(() => (d?.rows ?? []).slice(0, 40).map((r: any) => ({ label: r.label.split(' · ').pop(), Valore: Number(r.value), Cumulata: Number(r.cumulative), cls: r.class })), [d])
  return (
    <>
      <Group mb="md">
        <SegmentedControl value={what} onChange={setWhat} data={[{ value: 'articolo', label: 'Articoli' }, { value: 'cliente', label: 'Clienti' }, { value: 'fornitore', label: 'Fornitori' }]} />
        <SegmentedControl value={what === 'fornitore' && measure === 'margine' ? 'fatturato' : measure} onChange={setMeasure}
          data={what === 'fornitore' ? [{ value: 'fatturato', label: 'Spesa' }, { value: 'quantita', label: 'Quantità' }]
            : [{ value: 'fatturato', label: 'Fatturato' }, { value: 'margine', label: 'Margine' }, { value: 'quantita', label: 'Quantità' }]} />
        <Select value={period} onChange={(v) => setPeriod(v ?? 'ultimi_12_mesi')} allowDeselect={false} w={200}
          data={[{ value: 'ultimi_12_mesi', label: 'Ultimi 12 mesi' }, { value: 'anno_corrente', label: "Quest'anno" }, { value: 'anno_precedente', label: 'Anno scorso' },
            { value: 'trimestre_corrente', label: 'Questo trimestre' }, { value: 'mese_precedente', label: 'Mese scorso' }]} />
      </Group>
      {!d ? <Loading /> : (
        <>
          <SimpleGrid cols={{ base: 1, sm: 3 }} mb="md">
            {d.summary.map((s: any) => (
              <Paper key={s.class} withBorder p="md">
                <Group justify="space-between"><Badge size="lg" color={CLS_COLOR[s.class]}>Classe {s.class}</Badge><Text fw={700}>{n(s.value_share)}% del totale</Text></Group>
                <Text size="sm" mt="xs">{s.count} {what === 'articolo' ? 'articoli' : what === 'cliente' ? 'clienti' : 'fornitori'} ({n(s.count_share)}%) · {d.measure === 'quantita' ? n(s.value, 3) : fmtEuro(s.value)}</Text>
                <Progress value={Number(s.value_share)} color={CLS_COLOR[s.class]} mt={6} />
              </Paper>
            ))}
          </SimpleGrid>
          <Text size="sm" c="dimmed" mb="sm">Classe A: chi fa insieme il primo {d.thresholds[0]}% di {d.measure_label.toLowerCase()} · B fino al {d.thresholds[1]}% · C il resto.
            {d.excluded ? ` ${d.excluded} esclusi perché a zero o in negativo.` : ''}</Text>
          {chart.length > 0 && (
            <Paper withBorder p="md" mb="md">
              <BarChart h={260} dataKey="label" data={chart} series={[{ name: 'Valore', color: 'blue.6' }]} valueFormatter={(v) => (d.measure === 'quantita' ? n(v) : fmtEuro(v))}
                xAxisProps={{ interval: 'preserveStartEnd' }} />
            </Paper>
          )}
          <Paper withBorder>
            <Table striped fz="sm">
              <Table.Thead><Table.Tr><Table.Th>#</Table.Th><Table.Th>{what === 'articolo' ? 'Articolo' : what === 'cliente' ? 'Cliente' : 'Fornitore'}</Table.Th><Table.Th ta="right">{d.measure_label}</Table.Th>
                <Table.Th ta="right">Quota</Table.Th><Table.Th ta="right">Cumulata</Table.Th><Table.Th>Classe</Table.Th>
                {d.rows[0]?.values.margine_pct !== undefined && d.measure !== 'margine' && <Table.Th ta="right">Margine %</Table.Th>}</Table.Tr></Table.Thead>
              <Table.Tbody>
                {d.rows.slice(0, 500).map((r: any) => (
                  <Table.Tr key={r.key}>
                    <Table.Td c="dimmed">{r.rank}</Table.Td><Table.Td>{r.label}</Table.Td>
                    <Table.Td ta="right" fw={600}>{d.measure === 'quantita' ? n(r.value, 3) : fmtEuro(r.value)}</Table.Td>
                    <Table.Td ta="right">{n(r.share)}%</Table.Td><Table.Td ta="right">{n(r.cumulative)}%</Table.Td>
                    <Table.Td><Badge color={CLS_COLOR[r.class]} variant="light">{r.class}</Badge></Table.Td>
                    {r.values.margine_pct !== undefined && d.measure !== 'margine' && <Table.Td ta="right">{r.values.margine_pct !== null ? `${n(r.values.margine_pct)}%` : '—'}</Table.Td>}
                  </Table.Tr>
                ))}
                {!d.rows.length && <Table.Tr><Table.Td colSpan={7}><Text c="dimmed" ta="center" py="lg">Nessun dato nel periodo</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
        </>
      )}
    </>
  )
}

function Stock() {
  const nav = useNavigate()
  const whs = useWarehouses()
  const [wh, setWh] = useState<string | null>(null)
  const [days, setDays] = useState<string | number>(90)
  const [view, setView] = useState('tutti')
  const [d, setD] = useState<any>(null)
  useEffect(() => { setD(null); BI(`/analisi/magazzino?giorni=${days || 90}${wh ? `&magazzino=${wh}` : ''}`).then(setD).catch(notifyError) }, [wh, days])
  const rows = (d?.rows ?? []).filter((r: any) => view === 'tutti' || (view === 'fermi' ? r.idle : view === 'eccesso' ? (r.coverage_days ?? 0) > 180 : view === 'esaurimento' ? r.coverage_days !== null && r.coverage_days <= 15 : r.negative))
  return (
    <>
      <Group mb="md" align="flex-end">
        {whs && whs.length > 1 && <Select label="Magazzino" placeholder="Tutti" data={whs.map((w) => ({ value: w.id, label: w.name }))} value={wh} onChange={setWh} clearable />}
        <NumberInput label="Periodo di osservazione (giorni)" value={days} onChange={setDays} min={7} max={730} w={220} />
        <SegmentedControl value={view} onChange={setView} data={[{ value: 'tutti', label: 'Tutti' }, { value: 'fermi', label: 'Fermi' }, { value: 'eccesso', label: 'Scorte in eccesso' },
          { value: 'esaurimento', label: 'In esaurimento' }, { value: 'negativi', label: 'Negativi' }]} />
      </Group>
      {!d ? <Loading /> : (
        <>
          <SimpleGrid cols={{ base: 2, md: 5 }} mb="md">
            <Stat label="Valore al costo medio" value={fmtEuro(d.summary.value_avg)} hint={`${d.summary.items} articoli in giacenza`} />
            <Stat label="Valore all'ultimo costo" value={fmtEuro(d.summary.value_last)} />
            <Stat label="Valore FIFO" value={fmtEuro(d.summary.value_fifo)} hint="ai costi degli ultimi carichi" />
            <Stat label="Articoli fermi" value={<Text span fw={700} fz="inherit" c={d.summary.idle_count ? 'orange' : undefined}>{d.summary.idle_count}</Text>} hint={`${fmtEuro(d.summary.idle_value)} immobilizzati`} />
            <Stat label="Scorte oltre 6 mesi" value={d.summary.overstock_count} hint="copertura > 180 giorni" />
          </SimpleGrid>
          <Paper withBorder>
            <Table striped highlightOnHover fz="sm">
              <Table.Thead><Table.Tr><Table.Th>Articolo</Table.Th><Table.Th ta="right">Giacenza</Table.Th><Table.Th ta="right">Valore (medio)</Table.Th><Table.Th ta="right">FIFO</Table.Th>
                <Table.Th ta="right">Uscite {d.days} gg</Table.Th><Table.Th ta="right">Rotazione annua</Table.Th><Table.Th ta="right">Copertura</Table.Th><Table.Th>Ultima uscita</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.slice(0, 500).map((r: any) => (
                  <Table.Tr key={r.item_id} style={{ cursor: 'pointer' }} onClick={() => nav(`/magazzino/articolo/${r.item_id}`)}>
                    <Table.Td><Text span size="xs" ff="monospace" c="dimmed">{r.code} </Text>{r.description}{r.idle && <Badge ml={6} size="xs" color="orange" variant="light">fermo</Badge>}</Table.Td>
                    <Table.Td ta="right" c={r.negative ? 'red' : undefined}>{n(r.on_hand, 3)} {r.unit}</Table.Td>
                    <Table.Td ta="right">{fmtEuro(r.value_avg)}</Table.Td><Table.Td ta="right">{fmtEuro(r.value_fifo)}</Table.Td>
                    <Table.Td ta="right">{n(r.out_period, 3)}</Table.Td><Table.Td ta="right">{r.rotation !== null ? n(r.rotation) : '—'}</Table.Td>
                    <Table.Td ta="right">{r.coverage_days !== null ? `${n(r.coverage_days, 0)} gg` : r.idle ? '∞' : '—'}</Table.Td>
                    <Table.Td>{r.last_out ? `${fmtDate(r.last_out)} (${r.idle_days} gg fa)` : 'mai'}</Table.Td>
                  </Table.Tr>
                ))}
                {!rows.length && <Table.Tr><Table.Td colSpan={8}><Text c="dimmed" ta="center" py="lg">Nessun articolo</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
          <Text size="xs" c="dimmed" mt="xs">Rotazione: uscite degli ultimi 12 mesi divise per la giacenza attuale. Copertura: giorni per esaurire la giacenza al ritmo di uscita del periodo.</Text>
        </>
      )}
    </>
  )
}

function Customers() {
  const nav = useNavigate()
  const [days, setDays] = useState<string | number>(90)
  const [st, setSt] = useState('tutti')
  const [q, setQ] = useState('')
  const [d, setD] = useState<any>(null)
  useEffect(() => { setD(null); BI(`/analisi/clienti?giorni_inattivo=${days || 90}`).then(setD).catch(notifyError) }, [days])
  const rows = (d?.rows ?? []).filter((r: any) => (st === 'tutti' || r.status === st) && (!q || r.name.toLowerCase().includes(q.toLowerCase())))
  const LABEL: Record<string, [string, string]> = { attivo: ['attivo', 'green'], a_rischio: ['a rischio', 'orange'], inattivo: ['inattivo', 'red'] }
  return (
    <>
      <Group mb="md" align="flex-end">
        <NumberInput label="Inattivo dopo (giorni)" value={days} onChange={setDays} min={15} max={1095} w={180} />
        <SegmentedControl value={st} onChange={setSt} data={[{ value: 'tutti', label: 'Tutti' }, { value: 'attivo', label: 'Attivi' }, { value: 'a_rischio', label: 'A rischio' }, { value: 'inattivo', label: 'Inattivi' }]} />
        <TextInput placeholder="Cerca cliente" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
      </Group>
      {!d ? <Loading /> : (
        <>
          <SimpleGrid cols={{ base: 1, sm: 3 }} mb="md">
            <Stat label="Clienti attivi" value={d.summary.attivo} />
            <Stat label="A rischio" value={<Text span fw={700} fz="inherit" c="orange">{d.summary.a_rischio}</Text>} hint="comprano più di rado del solito" />
            <Stat label="Inattivi" value={<Text span fw={700} fz="inherit" c="red">{d.summary.inattivo}</Text>} hint={`nessun acquisto da oltre ${d.inactive_days} giorni`} />
          </SimpleGrid>
          <Paper withBorder>
            <Table striped highlightOnHover fz="sm">
              <Table.Thead><Table.Tr><Table.Th>Cliente</Table.Th><Table.Th>Stato</Table.Th><Table.Th>Ultimo acquisto</Table.Th><Table.Th ta="right">Acquisti 12 mesi</Table.Th>
                <Table.Th ta="right">Fatturato 12 mesi</Table.Th><Table.Th ta="right">Medio</Table.Th><Table.Th ta="right">Ogni quanto</Table.Th><Table.Th>Contatti</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.slice(0, 500).map((r: any) => (
                  <Table.Tr key={r.party_id} style={{ cursor: 'pointer' }} onClick={() => nav(`/soggetti/${r.party_id}`)}>
                    <Table.Td fw={500}>{r.name}<Text span size="xs" c="dimmed"> {r.city ?? ''}</Text></Table.Td>
                    <Table.Td><Badge variant="light" color={LABEL[r.status][1]}>{LABEL[r.status][0]}</Badge></Table.Td>
                    <Table.Td>{fmtDate(r.last)} <Text span size="xs" c="dimmed">({r.days_since} gg)</Text></Table.Td>
                    <Table.Td ta="right">{r.docs_12m}</Table.Td><Table.Td ta="right" fw={600}>{fmtEuro(r.revenue_12m)}</Table.Td>
                    <Table.Td ta="right">{r.avg_ticket ? fmtEuro(r.avg_ticket) : '—'}</Table.Td>
                    <Table.Td ta="right">{r.avg_gap_days ? `${r.avg_gap_days} gg` : '—'}</Table.Td>
                    <Table.Td><Text size="xs">{[r.email, r.mobile].filter(Boolean).join(' · ')}</Text></Table.Td>
                  </Table.Tr>
                ))}
                {!rows.length && <Table.Tr><Table.Td colSpan={8}><Text c="dimmed" ta="center" py="lg">Nessun cliente</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
        </>
      )}
    </>
  )
}

function Warranties() {
  const [days, setDays] = useState<string | number>(60)
  const [d, setD] = useState<any>(null)
  useEffect(() => { setD(null); BI(`/analisi/garanzie?giorni=${days || 60}`).then(setD).catch(notifyError) }, [days])
  return (
    <>
      <Group mb="md"><NumberInput label="In scadenza entro (giorni)" value={days} onChange={setDays} min={0} max={730} w={200} /></Group>
      {!d ? <Loading /> : (
        <>
          <SimpleGrid cols={{ base: 1, sm: 2 }} mb="md">
            <Stat label="Prodotti in garanzia" value={d.active} hint="matricole vendute con garanzia ancora valida" />
            <Stat label="Garanzie in scadenza" value={d.expiring} hint={`nei prossimi ${d.days} giorni`} />
          </SimpleGrid>
          <Paper withBorder>
            <Title order={5} p="sm">Matricole vendute</Title>
            <Table fz="sm" striped>
              <Table.Thead><Table.Tr><Table.Th>Matricola</Table.Th><Table.Th>Articolo</Table.Th><Table.Th>Cliente</Table.Th><Table.Th>Venduta</Table.Th><Table.Th>Garanzia fino al</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {d.rows.map((r: any) => (
                  <Table.Tr key={r.serial}>
                    <Table.Td ff="monospace">{r.serial}</Table.Td><Table.Td>{r.item_code} · {r.description}</Table.Td><Table.Td>{r.customer ?? '—'}</Table.Td>
                    <Table.Td>{fmtDate(r.sale_date)}</Table.Td>
                    <Table.Td><Badge variant="light" color={r.days_left < 0 ? 'gray' : r.days_left <= d.days ? 'orange' : 'green'}>{fmtDate(r.warranty_until)} · {r.days_left < 0 ? 'scaduta' : `${r.days_left} gg`}</Badge></Table.Td>
                  </Table.Tr>
                ))}
                {!d.rows.length && <Table.Tr><Table.Td colSpan={5}><Text c="dimmed" ta="center" py="lg">Nessuna matricola venduta con garanzia</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
        </>
      )}
    </>
  )
}
