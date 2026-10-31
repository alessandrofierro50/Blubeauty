// Statistiche della vendita al banco, sul modello BI delle vendite filtrato sul canale "banco":
// fasce orarie, giorni della settimana, reparti, cassieri e casse, sconti delle promozioni.

import { BarChart } from '@mantine/charts'
import { Group, Paper, Progress, SegmentedControl, SimpleGrid, Table, Text, TextInput, Title } from '@mantine/core'
import { useEffect, useState } from 'react'

import { appApi, fmtEuro, isoDate } from '../../api'
import { Loading, Stat, notifyError } from '../../components'

const Q = (body: any) => appApi('/api/bi/vendite/query', { body })
const eur0 = (v: number) => v.toLocaleString('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const n = (v: any) => Number(v).toLocaleString('it-IT', { maximumFractionDigits: 1 })

function range(p: string): [string, string] {
  const to = new Date()
  const from = new Date()
  if (p === '7') from.setDate(to.getDate() - 6)
  else if (p === '30') from.setDate(to.getDate() - 29)
  else if (p === '90') from.setDate(to.getDate() - 89)
  else if (p === 'mese') from.setDate(1)
  else if (p === 'anno') { from.setMonth(0); from.setDate(1) }
  return [isoDate(from), isoDate(to)]
}

export default function BancoStats() {
  const [period, setPeriod] = useState('30')
  const [custom, setCustom] = useState<[string, string]>(range('30'))
  const [data, setData] = useState<any>(null)
  const [from, to] = period === 'altro' ? custom : range(period)
  useEffect(() => {
    setData(null)
    const base = { date_from: from, date_to: to, filters: { canale: ['banco'] } }
    const m = ['fatturato', 'documenti', 'note_credito', 'quantita']
    Promise.all([
      Q({ ...base, measures: [...m, 'fattura_media', 'sconti_promo'], dimensions: [], compare: 'periodo_precedente' }),
      Q({ ...base, measures: ['fatturato', 'documenti'], dimensions: ['fascia_oraria'], sort: 'fascia_oraria', desc: false }),
      Q({ ...base, measures: ['fatturato', 'documenti'], dimensions: ['giorno_settimana'], sort: 'giorno_settimana', desc: false }),
      Q({ ...base, measures: ['fatturato', 'quantita'], dimensions: ['reparto'], sort: 'fatturato' }),
      Q({ ...base, measures: ['fatturato', 'documenti', 'fattura_media', 'note_credito'], dimensions: ['cassiere'], sort: 'fatturato' }),
      Q({ ...base, measures: ['fatturato', 'documenti', 'fattura_media'], dimensions: ['cassa'], sort: 'fatturato' }),
      Q({ ...base, measures: ['fatturato', 'quantita'], dimensions: ['articolo'], sort: 'fatturato', limit: 11 }),
    ]).then(([tot, hours, days, deps, cashiers, regs, items]) => setData({ tot, hours, days, deps, cashiers, regs, items })).catch(notifyError)
  }, [from, to])

  return (
    <>
      <Group mb="md" align="flex-end">
        <SegmentedControl value={period} onChange={setPeriod} data={[{ value: '7', label: '7 giorni' }, { value: '30', label: '30 giorni' }, { value: 'mese', label: 'Questo mese' },
          { value: '90', label: '90 giorni' }, { value: 'anno', label: "Quest'anno" }, { value: 'altro', label: 'Altro' }]} />
        {period === 'altro' && (
          <>
            <TextInput type="date" label="Dal" value={custom[0]} onChange={(e) => setCustom([e.currentTarget.value, custom[1]])} />
            <TextInput type="date" label="Al" value={custom[1]} onChange={(e) => setCustom([custom[0], e.currentTarget.value])} />
          </>
        )}
      </Group>
      {!data ? <Loading /> : <Dashboard d={data} />}
    </>
  )
}

function Delta({ v }: { v: any }) {
  if (v === null || v === undefined) return null
  const x = Number(v)
  return <Text span size="xs" c={x >= 0 ? 'teal' : 'red'} fw={600}>{x >= 0 ? '+' : ''}{n(x)}%</Text>
}

function Dashboard({ d }: { d: any }) {
  const t = d.tot.totals, dl = d.tot.totals_delta || {}
  if (!t.documenti && !t.note_credito) return <Paper withBorder p="xl"><Text c="dimmed" ta="center">Nessuna vendita al banco nel periodo.</Text></Paper>
  const pieces = Number(t.quantita) / Math.max(1, t.documenti)
  const hours = Array.from({ length: 24 }, (_, h) => d.hours.rows.find((r: any) => r.dims.fascia_oraria.key === h))
  const first = hours.findIndex(Boolean), last = 23 - [...hours].reverse().findIndex(Boolean)
  const hourData = first < 0 ? [] : hours.slice(first, last + 1).map((r, i) => ({ label: `${String(first + i).padStart(2, '0')}`, Incasso: Number(r?.values.fatturato ?? 0), Scontrini: r?.values.documenti ?? 0 }))
  const dayNames = ['', 'lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom']
  const dayData = [1, 2, 3, 4, 5, 6, 7].map((k) => { const r = d.days.rows.find((x: any) => x.dims.giorno_settimana.key === k); return { label: dayNames[k], Incasso: Number(r?.values.fatturato ?? 0), Scontrini: r?.values.documenti ?? 0 } })
  const peak = hourData.reduce((a: any, b: any) => (b.Scontrini > (a?.Scontrini ?? -1) ? b : a), null)
  return (
    <>
      <SimpleGrid cols={{ base: 2, md: 3, lg: 6 }} mb="md">
        <Stat label="Incassato (imponibile)" value={fmtEuro(t.fatturato)} hint={dl.fatturato !== undefined ? undefined : 'al netto dei resi'} />
        <Stat label="Scontrini" value={<>{t.documenti} <Delta v={dl.documenti} /></>} hint={t.note_credito ? `${t.note_credito} resi` : 'nessun reso'} />
        <Stat label="Scontrino medio" value={<>{fmtEuro(t.fattura_media ?? 0)} <Delta v={dl.fattura_media} /></>} hint="imponibile per scontrino" />
        <Stat label="Pezzi per scontrino" value={n(pieces)} />
        <Stat label="Ora di punta" value={peak ? `${peak.label}–${String(Number(peak.label) + 1).padStart(2, '0')}` : '—'} hint={peak ? `${peak.Scontrini} scontrini` : undefined} />
        <Stat label="Sconti promozioni" value={fmtEuro(t.sconti_promo ?? 0)} hint="3x2, N-esimo pezzo, soglie" />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 2 }} mb="md">
        <Paper withBorder p="md">
          <Title order={5} mb="sm">Fasce orarie</Title>
          <BarChart h={240} dataKey="label" data={hourData} series={[{ name: 'Incasso', color: 'blue.6' }]} valueFormatter={eur0} maxBarWidth={28}
            tooltipProps={{ content: ({ payload }: any) => payload?.[0] ? <Paper withBorder p={6} shadow="sm"><Text size="sm" fw={600}>ore {payload[0].payload.label}</Text><Text size="sm">{eur0(payload[0].payload.Incasso)} · {payload[0].payload.Scontrini} scontrini</Text></Paper> : null }} />
        </Paper>
        <Paper withBorder p="md">
          <Title order={5} mb="sm">Giorni della settimana</Title>
          <BarChart h={240} dataKey="label" data={dayData} series={[{ name: 'Incasso', color: 'teal.6' }]} valueFormatter={eur0} maxBarWidth={36} />
        </Paper>
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 3 }}>
        <Paper withBorder p="md">
          <Title order={5} mb="sm">Reparti</Title>
          <Shares rows={d.deps.rows.filter((r: any) => r.dims.reparto.key !== null || Number(r.values.fatturato) > 0)} dim="reparto" total={Number(t.fatturato)} />
          <Text size="xs" c="dimmed">Gli sconti delle promozioni di cassa sono nel riquadro in alto.</Text>
        </Paper>
        <Paper withBorder p="md">
          <Title order={5} mb="sm">Cassieri</Title>
          <Table fz="sm" verticalSpacing={4}>
            <Table.Thead><Table.Tr><Table.Th>Cassiere</Table.Th><Table.Th ta="right">Scontrini</Table.Th><Table.Th ta="right">Medio</Table.Th><Table.Th ta="right">Incasso</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {d.cashiers.rows.map((r: any) => (
                <Table.Tr key={String(r.dims.cassiere.key)}>
                  <Table.Td>{r.dims.cassiere.label}{r.values.note_credito ? <Text span size="xs" c="dimmed"> · {r.values.note_credito} resi</Text> : null}</Table.Td>
                  <Table.Td ta="right">{r.values.documenti}</Table.Td><Table.Td ta="right">{fmtEuro(r.values.fattura_media ?? 0)}</Table.Td>
                  <Table.Td ta="right" fw={600}>{fmtEuro(r.values.fatturato)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {d.regs.rows.length > 1 && (
            <>
              <Title order={6} mt="md" mb={4}>Casse</Title>
              {d.regs.rows.map((r: any) => <Group key={String(r.dims.cassa.key)} justify="space-between"><Text size="sm">{r.dims.cassa.label} · {r.values.documenti} scontrini</Text><Text size="sm" fw={600}>{fmtEuro(r.values.fatturato)}</Text></Group>)}
            </>
          )}
        </Paper>
        <Paper withBorder p="md">
          <Title order={5} mb="sm">Articoli più venduti al banco</Title>
          <Shares rows={d.items.rows.filter((r: any) => r.dims.articolo.key !== null)} dim="articolo" total={Number(t.fatturato)} qty />
        </Paper>
      </SimpleGrid>
    </>
  )
}

function Shares({ rows, dim, total, qty }: { rows: any[]; dim: string; total: number; qty?: boolean }) {
  if (!rows.length) return <Text c="dimmed" size="sm">Nessun dato</Text>
  return (
    <>
      {rows.map((r) => {
        const share = total ? (Number(r.values.fatturato) / total) * 100 : 0
        return (
          <div key={String(r.dims[dim].key)} style={{ marginBottom: 8 }}>
            <Group justify="space-between" wrap="nowrap" gap="xs">
              <Text size="sm" truncate style={{ flex: 1 }}>{r.dims[dim].label}</Text>
              {qty && <Text size="xs" c="dimmed">{n(r.values.quantita)} pz</Text>}
              <Text size="sm" fw={600}>{fmtEuro(r.values.fatturato)}</Text>
            </Group>
            <Progress value={Math.max(0, share)} size={4} mt={2} />
          </div>
        )
      })}
    </>
  )
}
